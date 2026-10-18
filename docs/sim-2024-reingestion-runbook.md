# SIM 2024 Re-ingestion + Raça/Cor Backfill Operator Runbook

Operator procedure for bringing SIM (mortality) data current through 2024 across all
27 UFs and populating `fato_obitos.raca_cor` for every row — historical (2010-2023)
and newly ingested (2024) alike. This document takes the operator from a migrated
schema through a resumable, multi-hour re-ingest, a targeted backfill, and passing
completeness gates.

See also `docs/sih-reingestion-runbook.md` for the SIH (hospitalizations) equivalent
— the two pipelines share `etl/pipeline.py`'s UF×ano loop but are otherwise
independent procedures.

## 1. Scope and preconditions

This pass is **SIM-focused**. The SIH re-ingestion already loaded the full 27 UF x 2010-2024
SIH grid under pysus 2.7.0 — this runbook does not touch `fato_internacoes` or SIH
`audit_ingestao` rows.

Before starting:

1. PostgreSQL is up and migrations are applied: `make up`. This runs `docker compose
   up -d db` followed by the migration container.
2. Seeds are loaded: `make seed` (CID-10, IBGE, TCU, faixa-etária dimensions).
3. `DATABASE_URL_SYNC` (and `CORS_ORIGINS`) are exported in the environment or `.env`
   — `make full` / `make assert-sim` / `make backfill-raca-cor` all depend on a live
   connection string.
4. `alembic upgrade head` has been applied and includes migration `0016` — the
   nullable `raca_cor CHAR(1)` column on `fato_obitos`. Run it explicitly and confirm:

```bash
cd backend && alembic upgrade head
cd backend && alembic heads
```

`alembic heads` must print exactly one head, `0016 (head)`. Migration 0016 is a
metadata-only `ALTER TABLE ... ADD COLUMN raca_cor CHAR(1)` — it does not rewrite
existing rows, so it is fast regardless of `fato_obitos` size, and is safe to
re-apply (Alembic tracks applied revisions and no-ops on a second run).

## 2. Why the backfill is a separate step

`run_pipeline`'s `_already_loaded(conn, hash_md5)` check (in `etl/pipeline.py`) skips
any SIM Parquet file whose MD5 hash already appears in `audit_ingestao` — that's
what makes re-running `make full` cheap and safe to interrupt (`sim_skipped_loaded`
counts these skips). But it also means `make full` alone can **never** add
`raca_cor` to the ~373 UF-year combos already cached and loaded before `raca_cor` was added:
their files are unchanged, so `_already_loaded` short-circuits before `stage_sim` or
`load_obitos` ever run again.

`scripts/backfill_raca_cor.py` exists for exactly this reason: it reads the cached
`data/raw/SIM_{uf}_{ano}.parquet` files directly, re-derives `numero_do` through the
same `stage_sim` extraction path, and issues targeted batched
`UPDATE fato_obitos SET raca_cor = %s WHERE numero_do = %s` statements — bypassing
`audit_ingestao` dedup entirely, since it isn't loading new rows. It touches only the
`raca_cor` column; it never restages `causa_basica`, `sexo`, `idade_anos`, or any
other field.

`backfill-raca-cor` is **not** wired into the `full` target — it is a
separate, explicitly operator-invoked `make` target, run once after the SIM
re-ingest completes. This mirrors the SIH runbook's pattern of separate one-off targets
(`reset-sih`, `assert-sih`, `scan-sih`) rather than folding every post-run step into
`full`.

Newly ingested rows (2024, and any future re-ingestion) don't need the backfill —
`stage_sim` now extracts `RACACOR` directly and `load_obitos`'s upsert writes
`raca_cor` on both INSERT and revision-cycle UPDATE, so they get the column through
the normal path.

## 3. Ordered command sequence

```bash
cd backend && alembic upgrade head
cd ..
make full
make backfill-raca-cor
make verify-raca-cor
make assert-sim
```

For a scoped rehearsal or a targeted re-run, override `SIH_UFS=`/`SIH_ANOS=` on
`make full` (the same grid variables drive both SIM and SIH — see
`docs/sih-reingestion-runbook.md` §4) and pass `--uf`/`--ano` to
`backfill_raca_cor.py` and `assert_sim_completeness.py`:

```bash
make full SIH_UFS=AC SIH_ANOS=2024
python scripts/backfill_raca_cor.py --confirm --uf AC --ano 2024
python scripts/assert_sim_completeness.py --uf AC --ano 2024
```

Expected output, field by field:

- **`make full`** — `etl.pipeline`'s end-of-run summary prints `sim_files` (newly
  downloaded and loaded UF-year units), `sim_rows` (rows upserted across those
  units), `sim_skipped_loaded` (units already in `audit_ingestao` — should dominate,
  since ~373/405 combos are already cached), and `sim_skipped_absent` (UF-year
  combos not present in the pysus catalog at all).
- **`make backfill-raca-cor`** (`python scripts/backfill_raca_cor.py --confirm`) —
  prints `rows_updated` (rows whose `raca_cor` was set) and `source_blank` (rows
  skipped because the raw `RACACOR` field was itself blank — these correctly stay
  `NULL` in the DB by design, not a backfill failure).
- **`make verify-raca-cor`** (`python scripts/backfill_raca_cor.py --verify`) —
  prints `source_blank_pct` (blank rate in the raw cached Parquet), `db_null_pct`
  (NULL rate in `fato_obitos.raca_cor`), `delta_pct` (the absolute difference
  between them), a `PASS`/`FAIL` verdict (`delta_pct <= tolerance_pct`, default
  tolerance), and the full per-code distribution (counts for raw codes `1`-`5`).
- **`make assert-sim`** (`python scripts/assert_sim_completeness.py`) — prints the
  count of UF-year combos checked out of the full grid, the lowest-count combos (a
  plausibility check, not a pass/fail gate), a 2024 coverage breakout per UF, and a
  separate duplicate-`numero_do` check result (`OK` at exactly 0, `FAILED` otherwise).

## 4. Resumability

An interrupted `make full` is safe to re-run: `_already_loaded` hash dedup means
completed (UF, ano) units are skipped on the next run, and cached
`data/raw/SIM_{uf}_{ano}.parquet` files are reused without re-downloading. The
checkpoint unit is one (UF, ano) pair — see `docs/sih-reingestion-runbook.md` §5 for
the same mechanism, shared verbatim between SIM and SIH since both go through the
same `run_pipeline` loop.

An interrupted `backfill_raca_cor.py --confirm` run is also safe to re-run: each
`UPDATE ... WHERE numero_do = %s` is idempotent (setting an already-correct value
again is a no-op), and the script has no multi-row transaction spanning the whole
grid — a batch either commits or doesn't. Neither the pipeline nor the backfill
leaves a `fato_obitos` row in a partially-written state.

## 5. Duration and staging advice

The full 27 UF x 2010-2024 grid is a **multi-hour** operation dominated by network
downloads for the uncached UF-year units — 373 of 405 `SIM_{uf}_{ano}.parquet` files
are already cached locally as of the start of this re-ingestion (gaps concentrate in PE, SP, RJ,
CE/PR, MG/SC), so the real work is roughly 32 units plus any 2024 units never
fetched before. `make backfill-raca-cor` and `make assert-sim` run entirely against
already-local Parquet files and the database, so they finish in minutes, not hours,
regardless of grid size.

Run the scoped rehearsal (§ below, "Rehearsal evidence") before committing to the
full grid — it proves the entire sequence end to end on a small, fast, real-data
slice, so failures surface in minutes rather than hours into the full run.

## 6. Failure remediation

| Symptom | Cause | Remedy |
|---|---|---|
| `assert-sim` reports a UF-year combo missing or below `--min-rows` | Genuine catalog gap, or a pipeline defect | Run `python scripts/scan_sim_catalog.py` for the failing combo. If the catalog truly has no SIM file for it, add a dated entry to `scripts/sim_year_allowlist.yaml` naming the scan that confirmed it, then re-run `make assert-sim`. If the catalog *does* have the file but rows are still missing, this is a pipeline defect — do not allowlist it; re-run `make full SIH_UFS=<uf> SIH_ANOS=<ano>` and read the logs. |
| `verify-raca-cor` reports `FAIL` with a large `delta_pct` | The backfill didn't reach some rows (e.g. it was interrupted, or ran before `make full` finished loading a UF-year) | Re-run `python scripts/backfill_raca_cor.py --confirm` scoped by `--uf`/`--ano` to localize which combo(s) still diverge, then re-verify. |
| `assert-sim`'s duplicate-`numero_do` check reports a non-zero count | A `numero_do` derivation change in `stage_sim` produced new surrogate keys colliding with existing rows, or the `(numero_do, revisao_numero)` upsert key was violated | Investigate the `stage_sim`/`load_obitos` derivation logic — **never** delete rows to force the count to zero; a non-zero duplicate count is a data-integrity signal, not a formatting nuisance. |
| A `make full` unit fails to download from DataSUS FTP | Transient network failure, or the file is genuinely absent from the catalog | The unit is logged and counted in `sim_skipped_absent` if absent, or the run continues past a single failed download. Re-run `make full` (or scope it to just that UF/ano) — completed units are skipped, so re-running costs only the failed unit's time. |

## 7. Rehearsal evidence

**Status: PENDING.** This section is not yet filled in. It requires a live
PostgreSQL instance (`make up`, migration `0016` applied) and DataSUS FTP network
access to execute real commands against `AC`/`2024` — neither was available in the
session that authored this runbook. Do not fill this section with estimated,
approximated, or invented figures; every line below must come from a command you
actually ran and its actual observed output.

To fill this section, run the following against a live database and record the
real output of each step, in this order:

1. `cd backend && alembic upgrade head`, run twice — confirm `0016` applied and the
   second run is a no-op (check via `alembic heads`).
2. `cd backend && python -m etl.pipeline --uf AC --ano 2024 --sim-only` — record
   `sim_files`, `sim_rows`, `sim_skipped_loaded`, `sim_skipped_absent`. If `AC`/2024
   alone yields fewer than 1000 rows, add a second UF.
3. Re-run the identical command immediately — record that it resumes with
   `sim_files=0` and the unit counted under `sim_skipped_loaded`.
4. `python scripts/backfill_raca_cor.py --dry-run --uf AC --ano 2024` — record
   `files_scanned`, `rows_read`, the would-update count, `source_blank`, and confirm
   zero UPDATE statements were issued.
5. `python scripts/backfill_raca_cor.py --confirm --uf AC --ano 2024` — record
   `rows_updated` and `source_blank`.
6. `python scripts/backfill_raca_cor.py --verify` — record `source_blank_pct`,
   `db_null_pct`, `delta_pct`, the PASS/FAIL verdict, and the full per-code
   distribution.
7. `python scripts/assert_sim_completeness.py --uf AC --ano 2024` — record the
   coverage result and the duplicate-`numero_do` count.
8. A SQL spot-check proving the backfill's historical half: pick a `numero_do` from
   a 2010-2023 row that existed before the backfill, show its `raca_cor` is now
   populated, and record a count of non-NULL `raca_cor` rows for that pre-2024 year.

If any gate fails during this rehearsal, fix the underlying code in the SIM ingestion/backfill
path, re-run, and record both the failure and the fix — do
not proceed to the full-grid run with a failing gate.

<!-- placeholder-example, replace with real output:
```sql
-- Pick a numero_do from a 2010-2023 row that predates the backfill
SELECT fo.numero_do, fo.raca_cor
FROM fato_obitos fo
JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
WHERE dt.ano BETWEEN 2010 AND 2023 AND fo.raca_cor IS NOT NULL
LIMIT 1;
SELECT dt.ano, COUNT(*) AS non_null_raca_cor
FROM fato_obitos fo
JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
WHERE dt.ano BETWEEN 2010 AND 2023 AND fo.raca_cor IS NOT NULL
GROUP BY dt.ano;
```
-->

Once all eight steps are green with real recorded output and no placeholders, the
sequence is proven and it is safe to commit to the multi-hour full 27-UF x
2010-2024 grid (see Full-grid run below).

## Full-grid run

Executed and approved by the operator 2026-07-27, against the complete 27-UF x
2010-2024 (405-unit) grid. The scoped rehearsal (§7 above) was superseded by
running the full grid directly.

**`make assert-sim`**

```
SIM completeness OK: 405 combos checked, 29 allowlisted absences, 16151262 total
rows, 0 unexplained gaps.
Duplicate numero_do check: OK -- 0 numero_do values with duplicate rows.
```

All 405 UF-year combos accounted for — 376 with real coverage, 29 matching the
dated, `scan_sim_catalog.py`-confirmed entries in `scripts/sim_year_allowlist.yaml`
(no new entries needed beyond those 29). Zero unexplained gaps. Duplicate
`numero_do` count is exactly 0 — the `(numero_do, revisao_numero)` upsert key held
through the full re-ingestion.

**`make verify-raca-cor`**

```
RACA_COR VERIFY: PASS
  source_rows       : 16698645
  source_blank      : 621388
  source_blank_pct  : 3.72%
  db_rows           : 16668830
  db_null           : 619680
  db_null_pct       : 3.72%
  db_rows_with_raca_cor : 16049150
  delta_pct         : 0.00%
  tolerance_pct     : 1.00%
```

`PASS`, `delta_pct=0.00%` — the DB's `raca_cor` NULL rate matches the raw-source
blank rate to within the 1.00% tolerance.

**Year-scoped `raca_cor` coverage (new and historical rows)**

```sql
SELECT COUNT(*) FROM fato_obitos fo
JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
WHERE dt.ano = 2024 AND fo.raca_cor IS NOT NULL;
-- 944458

SELECT COUNT(*) FROM fato_obitos fo
JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
WHERE dt.ano BETWEEN 2010 AND 2023 AND fo.raca_cor IS NOT NULL;
-- 14604332
```

Both halves confirmed: 944,458 newly ingested 2024 rows carry `raca_cor`
through the normal ingestion path, and 14,604,332 historical 2010-2023
rows carry `raca_cor` through the standalone backfill.

**Result:** all checks above satisfied. Operator approved.
