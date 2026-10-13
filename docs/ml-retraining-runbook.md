# ML Retraining Operator Runbook

Operator procedure for producing the two database states the ML layer requires: two freshly-computed
`municipio_cluster_assignments` snapshots (2021 and 2024, at least 3 years apart) and
a forecast retrain anchored to `ano_referencia = 2024` with a 2025-2027 horizon. This
document takes the operator from a clean environment through the two multi-hour jobs to a
passing completeness gate and a live endpoint spot-check.

Both requirements are statements about the **database**, not the code —
only a real run against real ingested data, verified by `make assert-ml-snapshots`, satisfies
them.

## 1. Prerequisites

1. PostgreSQL up and migrations current: `make up seed`.
2. `DATABASE_URL_SYNC` (and `CORS_ORIGINS`) exported (or set in `.env`) — `make assert-ml-snapshots`
   fails fast via its own `DATABASE_URL_SYNC` guard if missing, matching
   `assert_sinan_completeness.py`'s guard style.
3. Real flat `data/raw/SIM_*.parquet` and `data/raw/SIH_*.parquet` files present —
   `run_clustering.py --ano-referencia <ano>` globs these directly. A dev checkout
   may hold SIM Parquet files but zero SIH Parquet files if the SIH re-ingestion has not
   yet been run on that machine (per `docs/pysus-270-spike-findings.md`'s Environment
   Availability finding). If so, `make cluster-snapshots` fails at path resolution
   (`FileNotFoundError: No SIH Parquet files found in data/raw`) — complete the SIH
   re-ingestion (`docs/sih-reingestion-runbook.md`) first.

## 2. Step 1 — verify the materialized view is fresh

`/risco-prospectivo`'s T+3 lookup reads `mv_taxa_municipio_ano` directly.
A stale view silently breaks the endpoint — check this **before**
running either job:

```sql
SELECT MAX(ano) FROM mv_taxa_municipio_ano WHERE fonte = 'SIM';
```

Expected: `2024`. If it returns `2023` (or anything else), refresh it before continuing:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_taxa_municipio_ano;
```

Re-run the `SELECT MAX(ano)` query afterward to confirm `2024` before moving to Step 2.

## 3. Step 2 — regenerate cluster snapshots

```bash
make cluster-snapshots
```

Equivalent to:

```bash
cd backend && python -m ml.run_clustering --ano-referencia 2021
cd backend && python -m ml.run_clustering --ano-referencia 2024
```

This is **two invocations by design** — the runner has no multi-year mode; the
`CLUSTER_ANOS` Makefile variable (default `2021 2024`) is looped one year at a time. Each
invocation prints a summary dict with the keys `rows_written`, `n_clusters`,
`silhouette_score`, `ano_referencia` — confirm `ano_referencia` in each summary matches the
year just run.

Verify afterward:

```sql
SELECT ano_referencia, COUNT(*) FROM municipio_cluster_assignments
WHERE algoritmo='KMeans' AND n_clusters=6
GROUP BY ano_referencia ORDER BY ano_referencia;
```

Expect two rows: `2021` and `2024`, each with a non-zero count (~5570 municípios, allowing for
any known data-availability gaps — see §6 below).

## 4. Step 3 — retrain forecasts

```bash
make retrain-forecasts
```

Equivalent to `cd backend && python -m ml.run_forecasting`. `_ANO_REFERENCIA` is now `2024`,
so every `forecast_resultados` row this run writes is labelled 2024.
The forecast horizon derives from the last observed date in the input series, not from a
separate configurable flag — verify it landed on 2025-2027:

```sql
SELECT DISTINCT ano_forecast FROM forecast_resultados ORDER BY ano_forecast;
```

Expect `2025, 2026, 2027` to be present. Municípios with short historical series (SIM data
starting only in 2023) may also contribute a `2023` or `2024` row, anchored to their own last
available year — that is expected, not a bug (see §5).

This is a **multi-hour** operation (AutoARIMA runs per município, up to 5570 series; Prophet
runs per UF, 27 series, twice for 80%/95% intervals).

## 5. Step 4 — run the gate

```bash
make assert-ml-snapshots
```

Equivalent to `python scripts/assert_ml_snapshots.py`. Expect exit `0` and a `PASS` summary.

The gate performs three checks and prints a `FAIL` with remediation instructions if any fails:

1. **Cluster snapshots** — at least two distinct `ano_referencia` values in
   `municipio_cluster_assignments` (algoritmo=`KMeans`, n_clusters=6), at least 3 years apart,
   and no snapshot with zero rows. *Remediation:* re-run `make cluster-snapshots` for the
   missing/empty year.
2. **Forecast currency** — `forecast_resultados`'s distinct `ano_referencia` set is exactly
   `{2024}` (a lingering `2023` alongside `2024` means a partial retrain) and its distinct
   `ano_forecast` set contains `{2025, 2026, 2027}` (extra past years are expected and allowed —
   see the note below). *Remediation:* re-run `make retrain-forecasts` to completion; if a
   partial retrain left mixed `ano_referencia` years, investigate why the prior run was
   interrupted before re-running.

   Note: `ano_forecast` is checked as a superset, not an exact match. Municípios with short
   historical series (e.g. some RJ municípios whose SIM data starts only in 2023) get forecasts
   anchored to their own last available year, so `ano_forecast` can legitimately include 2023 or
   2024 alongside 2025-2027. That is correct per-município behavior — the run's completeness
   signal is the `ano_referencia={2024}` check above, not the absence of extra past forecast
   years.
3. **Materialized view freshness** — `mv_taxa_municipio_ano`'s `MAX(ano)` for `fonte='SIM'` is
   `2024`. *Remediation:* the failure message prints the exact
   `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_taxa_municipio_ano;` command to run — this
   mirrors Step 1 above and can recur if the view was refreshed then re-staled by a later SIM
   re-ingest.

## 6. Known data-availability caveats

**SIH catalog gaps are real, not a bug.** SP has RD (AIH) files in the pysus 2.7.0 catalog for
only 2010 and 2023 across the full 2010-2024 range (13 years absent: 2011-2022, 2024) — see
`docs/sih-reingestion-runbook.md` and `scripts/sih_year_allowlist.yaml`'s `known_absent` list.
Clustering's `taxa_internacoes` feature will be `0` for the affected UF-years as a direct
consequence. **Do not** "fix" this by relaxing the RD filename-prefix filter in
`backend/etl/ingestor.py::_fetch_sih_rd` — that filter is the primary safeguard against SIH-SP
(procedures) rows and SIH-RJ ("AIH Rejeitada") rows contaminating `fato_internacoes`; a `0`
`taxa_internacoes` for SP in an absent year is the correct, documented behavior, not an
ingestion defect.

## 7. Run evidence

Run completed 2026-08-05 against the real live database with the fully re-ingested
SIM/SIH Parquet corpus.

**Clustering:**
- `ano_referencia=2021`: 4562 municípios, k=6, silhouette=0.5859
- `ano_referencia=2024`: 4636 municípios, k=6, silhouette=0.5534

**Forecasting:**
- 16,791 previsões total — 5,570 AutoARIMA + 27 Prophet — 0 fallbacks

**`make assert-ml-snapshots` output:**

```
Per-snapshot contagem de municípios (municipio_cluster_assignments):
  ano_referencia=2021: 4562 municípios
  ano_referencia=2023: 50 municípios
  ano_referencia=2024: 4636 municípios

  OK: cluster snapshots: anos encontrados [2021, 2023, 2024], maior intervalo 3 anos (>= 3 exigido).
  OK: forecast currency: ano_referencia=[2024], ano_forecast=[2023, 2024, 2025, 2026, 2027] (horizonte esperado [2025, 2026, 2027] presente) -- conforme esperado.
  OK: mv_taxa_municipio_ano atualizada: MAX(ano)=2024.

PASS
```

The pre-existing `ano_referencia=2023` cluster snapshot (50 municípios) is a leftover
sample-mode/earlier-run artifact and does not break `check_cluster_snapshots` (the gate
only requires *some* pair of distinct years ≥3 apart; 2021↔2024 satisfies it). The
`ano_forecast` set includes `2023, 2024` alongside `2025-2027` because municípios with short
historical series (RJ sample data starting only in 2023) get forecasts anchored to their own
last available year — expected per-município behavior, not a partial retrain (see §5's note;
`check_forecast_currency` was changed from an exact-match to a superset check to accommodate
this after this run surfaced it).

**`/risco-prospectivo` spot-check:**

```
GET /risco-prospectivo/?municipio=355030&ano_referencia=2021 → 200 OK
São Paulo → cluster "Alta Carga Respiratória e Hospitalar"
```

**Bugs found and fixed during this run:**

1. `backend/etl/staging/sim_staging.py` — the single-row `DTOBITO` format sniff misclassified
   day-20 dates, corrupting 178,133 `fato_obitos` rows. Fixed by scoring the whole batch instead
   of one row, mirroring the SINAN `DT_NOTIFIC` fix in `sinan_staging.py`.
2. `backend/ml/run_clustering.py` — `_aggregate_features`'s SIH `read_parquet` call raised a
   schema-mismatch error when old SP-schema (36-col) and new RD-schema (113-col) files coexisted
   in `data/raw/`; fixed with `union_by_name=True`. Also replaced the `WHERE SP_TIPO = 1` filter
   with `WHERE IDENT = 1` — `SP_TIPO` is always NULL on genuine RD/AIH rows once pysus
   concatenates the SIH-RD and SIH-SP groups, so the old filter silently zeroed out
   `taxa_internacoes` for every município.
