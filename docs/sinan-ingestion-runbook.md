# SINAN Ingestion Operator Runbook

Operator procedure for the full 3-agravo (`DENG`, `CHIK`, `ANIM`) x `SINAN_ANOS` SINAN
(notificações) ingestion under pysus 2.7.0. This document takes the operator from a clean
environment through a resumable, multi-hour run to a passing completeness assertion.

Unlike the SIH (`docs/sih-reingestion-runbook.md`) and SIM runbooks, there is no reset step
here: SINAN has no prior ingestion in this project, so the first run is naturally clean.
The two runbooks otherwise share the same shape — scope, prerequisites, procedure,
interruption/resume, the completeness gate, and troubleshooting.

## 1. Scope and grain

The full grid is **3 agravos x the `SINAN_ANOS` year range** (default `2015,...,2024` = 10
years) = **30 national download units**. This is deliberately `(agravo, ano)`, never
`(agravo, UF)`: `pysus.sinan()` has no `state` parameter (live-verified,
`docs/pysus-270-sinan-spike-findings.md`, check 2/3) — every download is already one
**national** file covering all 27 UFs. There is therefore no `SINAN_UFS` Makefile variable
and UF is not a checkpoint dimension: scoping a rehearsal means fewer agravos or fewer
years, never fewer UFs. UF completeness is instead verified **after** loading, as distinct
`dim_local.sigla_uf` coverage within already-loaded `fato_notificacoes` rows — this is
`assert_sinan_completeness.py`'s check 3, not a re-fetchable grid dimension.

## 2. Prerequisites

1. `pip install -r backend/requirements.txt` — installs the pinned `pysus==2.7.0` /
   `pyreaddbc>=2.0.4` versions this runbook depends on.
2. PostgreSQL running with migrations through `0019` applied (`make up`) —
   `0019_alter_audit_ingestao_for_sinan.py` is what makes `audit_ingestao.uf=NULL` and
   `fonte='SINAN'` legal; without it every SINAN audit write fails a CHECK/NOT NULL
   constraint.
3. `make seed` — loads `dim_local`, `dim_populacao` (TCU) and `dim_faixa_etaria`.
   `taxa_por_100k` is silently `NULL` for any município/ano missing a TCU population
   estimate, so a missing seed does not fail the run, it just produces unusable rates.
4. `DATABASE_URL_SYNC` and `CORS_ORIGINS` exported (or set in `.env`) — `make ingest-sinan`
   / `make assert-sinan` both fail fast via `scripts/validate_env.py` or
   `scripts/assert_sinan_completeness.py`'s own `DATABASE_URL_SYNC` guard if these are
   missing.
5. `make spike-pysus-sinan` must exit 0. Re-run this whenever more than two weeks have
   passed since `docs/pysus-270-sinan-spike-findings.md` was written — the DuckLake catalog
   is a third-party-hosted service and DataSUS's own DADOS/PRELIM vs DADOS/FINAIS layout
   has already produced one documented anomaly (see "Expected volume" below). Do not assume
   the API contract or the catalog's file layout is stable indefinitely.
6. Budget disk space for `data/raw/` — a full run caches up to 30 `SINAN_<AGRAVO>_<ano>.parquet`
   files, several of which (DENG in particular) are multi-million-row national files, in
   addition to existing SIM/SIH Parquet caches.

## 3. Expected volume

Real per-agravo, per-year row counts observed in `docs/pysus-270-sinan-spike-findings.md`
(run date 2026-08-01, year 2023):

| Agravo | Year | Row count |
|--------|------|-----------|
| DENG | 2023 | 3,291,912 |
| CHIK | 2023 | 532,884 |
| ANIM | 2023 | 10,000 |

ANIM 2023's 10,000-row count is not an ingestion bug — DataSUS's most recent SINAN years
live under `DADOS/PRELIM` (preliminary, still-updating files) rather than `DADOS/FINAIS`
(closed annual files), and a small PRELIM snapshot is a documented, real data-lifecycle
characteristic (see `docs/pysus-270-sinan-spike-findings.md`'s "Data-lifecycle caveat"
section). Do not treat a low recent-year count as evidence of a broken fetch before
checking whether it is already recorded under `known_partial` in
`scripts/sinan_agravo_allowlist.yaml`.

## 4. Procedure

Always rehearse scoped before running the full grid.

### Step 1 — Scoped rehearsal

```bash
make ingest-sinan SINAN_AGRAVOS=ANIM SINAN_ANOS=2023
python scripts/assert_sinan_completeness.py --agravo ANIM --ano 2023 --min-ufs 1
```

The scoped `assert_sinan_completeness.py` call uses `--min-ufs 1` rather than the default
27 for a rehearsal, since a single-unit rehearsal is about confirming the pipeline runs end
to end, not confirming full national UF coverage.

### Step 2 — Full run

```bash
make ingest-sinan
```

This is a **multi-hour** operation (DENG alone is a multi-million-row national file per
year). It runs `cd backend && python -m etl.pipeline --sinan-only --agravo $(SINAN_AGRAVOS)
--ano $(SINAN_ANOS)`, iterating `SINAN_AGRAVOS x SINAN_ANOS` (default: 3 agravos x
2015-2024 = 30 units). `pysus` caps its own download concurrency internally — this runbook
does not add parallelism on top of it.

`--sinan-only` skips the SIM/SIH loops entirely, so this target never touches
`fato_obitos` or `fato_internacoes`. To run SINAN as part of the full DataSUS pipeline
instead, use `make full`, which wires `ingest-sinan` in after the SIH pass and before
`make ml`, with its own independent `SINAN_AGRAVOS`/`SINAN_ANOS` scope (not coupled to
`SIH_UFS`/`SIH_ANOS`).

### Step 3 — Full gate

```bash
make assert-sinan
```

## 5. Interruption and resume

Ctrl-C is safe at any point during `make ingest-sinan`. On re-run:

- Units already recorded in `audit_ingestao` (matched by `hash_md5`, `fonte='SINAN'`) are
  skipped — the pipeline's `_already_loaded` check short-circuits before any network call.
- Cached `data/raw/SINAN_<AGRAVO>_<ano>.parquet` files are reused without re-downloading.

**The checkpoint unit is one `(agravo, ano)` pair.** There is no finer-grained (e.g.
per-UF) checkpoint, because there is no UF dimension to checkpoint at download time — a
half-downloaded `(agravo, ano)` unit simply re-downloads that unit from scratch on the next
run; it never rolls back or invalidates a unit that had already completed and been
recorded.

The end-of-run summary printed by `etl.pipeline` reports SINAN files processed, rows
upserted (labelled "SINAN notificações upserted" — never "casos", since each row is a
notification, not a confirmed diagnosis), already-loaded (resumed) units and
catalog-absent units, mirroring the existing SIM/SIH summary lines.

## 6. Interpreting the completeness gate

`make assert-sinan` runs `python scripts/assert_sinan_completeness.py`, a three-check gate:

1. **Presence** — every `(agravo, ano)` in the grid not listed in `known_absent` must have
   at least `--min-rows` (default 1) `fato_notificacoes` rows.
2. **Cliff** — for each agravo, a non-allowlisted year's count must not fall below
   `cliff_ratio` (default 0.10) of the median of that agravo's other checked years, unless
   the combo is listed in `known_partial`. This is the check the PRELIM-vs-FINAL
   data-lifecycle pattern above is designed to pass without masking a real gap.
3. **UF coverage** — every agravo with any loaded rows must
   show at least `--min-ufs` (default 27) distinct `dim_local.sigla_uf` values.

Exit code `0` means every checked combo passed or was allowlisted; exit code `1` prints the
failing combos with remediation instructions. On failure:

1. Re-run just the failing unit: `make ingest-sinan SINAN_AGRAVOS=<agravo> SINAN_ANOS=<ano>`.
2. Re-run `make spike-pysus-sinan` to confirm what the pysus DuckLake catalog actually
   holds for that unit. There is no `scan-sinan` catalog-scanning script (see "Known
   limitations" below) — the spike script's real data fetch is the reliable evidence path.
3. **Only after confirming the real catalog state**, add a dated entry to the appropriate
   key (`known_absent` for a genuinely missing file, `known_partial` for a real-but-small
   PRELIM file) in `scripts/sinan_agravo_allowlist.yaml`, naming the confirming method and
   the observed row count in an inline comment. An entry is **never** added merely to make
   the check pass — an unexplained entry defeats the purpose of the completeness assertion
   by masking a real ingestion gap instead of surfacing it.

## 7. Terminology

Every row in `fato_notificacoes` is one **notificação** (notification) — a report to the
surveillance system — not an asserted confirmed diagnosis. Confirmation status lives in the
raw `classi_fin` code, which is `NULL` for `ANIM` (the animais peçonhentos agravo has no
such column at all — it was never part of ANIM's SINAN form). Any downstream consumer that
wants confirmed-only counts must filter on `classi_fin` explicitly (excluding both the
empty-string and literal `"None"`-string missing-value encodings — see
`docs/pysus-270-sinan-spike-findings.md`'s "Missing-value encoding" section) and label its
own output accordingly. This project's API and this runbook always say "notificações", never
"casos", for `fato_notificacoes` counts.

## 8. Known limitations

- **No `reset-sinan` target.** Unlike SIH — which had cached data loaded under an older,
  broken pysus 2.2.0 code path that needed clearing before re-ingestion — SINAN
  has no prior ingestion in this project at all. The first run is naturally clean, so there
  is nothing to reset.
- **No `scan-sinan` catalog scanner.** pysus's `list_files()` helper crashed the
  interpreter when called repeatedly in a loop on Windows during development.
  `make spike-pysus-sinan` is the reliable catalog-evidence path instead — it performs a
  real, bounded data fetch rather than an unbounded catalog listing.
- **PRELIM-vs-FINAL duplicate-notification caveat.** `stage_sinan`'s deterministic key does
  not currently distinguish a notification that appears in both a PRELIM snapshot and a
  later FINAL file under different row identities; this is an accepted limitation of the
  current staging design, not something this runbook's procedure works around.

## 9. Troubleshooting

- **Every row for a unit is skipped with an unresolvable `dim_local` join.** Symptom of
  7-digit `ID_MN_RESI`/`ID_MUNICIP` codes reaching staging instead of 6-digit ones — a
  regression of the `add_dv=False` contract that every SINAN fetch call site must pass
  explicitly (`docs/pysus-270-sinan-spike-findings.md`'s "`add_dv` contract" section).
  Check `backend/etl/ingestor.py`'s SINAN fetch call for a missing or flipped `add_dv`
  argument.
- **`taxa_por_100k` is `NULL` across the board.** The `dim_populacao` (TCU) seed is
  missing or incomplete for the loaded município/ano combinations — re-run `make seed`.
- **A `fonte`/`uf` constraint violation on the `audit_ingestao` write.** Migration `0019`
  (`0019_alter_audit_ingestao_for_sinan.py`) has not been applied — confirm with
  `make migrate` and check the applied revision.
- **A rehearsal or full run appears to hang with no progress lines.** DENG in particular is
  a multi-million-row national file; the per-unit "SINAN: fetching N/30 ..." progress line
  only advances once the whole unit's download, staging and load complete — there is no
  finer-grained progress within a single unit.

## 10. After a successful run

- Re-run `make ml` if downstream forecasts should reflect newly-loaded SINAN coverage
  (only relevant once a SINAN-driven ML runner consumes `fato_notificacoes`; as of the
  current version, `make ml` does not).
- Record any populated `scripts/sinan_agravo_allowlist.yaml` entries (with their dated,
  spike-confirmed comments) so later runs inherit the documented gaps instead of
  re-discovering them.

## 11. Rehearsal evidence

**Run date:** 2026-08-01. **Unit:** `ANIM`, `2023` — the smallest of the three agravos'
frames, chosen as a small real sample (10,000 raw rows against a live
DataSUS fetch, per `docs/pysus-270-sinan-spike-findings.md`'s "Expected volume" table).
Executed against PostgreSQL 16 at `127.0.0.1:5433` (local `docker-compose.override.yml`
port remap; untracked), migrations at head `0019`, seeds loaded (`dim_local`=5571 rows,
`dim_populacao`=83550 rows, `dim_faixa_etaria`=10 rows, `dim_agravo`=3 rows). `make` is
not installed on this Windows host, so each `make <target>` command below was run as its
underlying Makefile command directly (shown), with identical effect.

### Preparation

```
cd backend && alembic current
```
```
0019 (head)
```

```
python scripts/spike_pysus_270_sinan.py   # underlying command for `make spike-pysus-sinan`
```
Exited 0, all 8 checks PASSED, reproducing `docs/pysus-270-sinan-spike-findings.md`'s
figures exactly (ANIM 2023 = 10,000 rows/75 cols, `TRA_CLASSI`/`TP_ACIDENT` present,
`CLASSI_FIN` absent) — the catalog has not drifted since that spike was written.

### Deviation found and fixed during this rehearsal

The first rehearsal attempt (`python -m etl.pipeline --sinan-only --agravo ANIM --ano
2023`, underlying command for `make ingest-sinan SINAN_AGRAVOS=ANIM SINAN_ANOS=2023`)
downloaded the real 10,000-row ANIM 2023 file successfully, but staging dropped **100%**
of rows:

```
INFO SINAN ANIM 2023: 10000 rows saved to data\raw\SINAN_ANIM_2023.parquet
INFO stage_sinan: dropped 2 rows with null/blank ID_MN_RESI
INFO stage_sinan: dropped 9998 rows with unparseable DT_NOTIFIC
INFO stage_sinan: total rows dropped: 10000 of 10000 (100.0%)
INFO load_notificacoes complete: 0 upserted, 0 skipped (local=0, agravo=0)
```

**Diagnosis:** `stage_sinan._parse_dt_notific`
assumed every 8-digit `DT_NOTIFIC` string is `DDMMYYYY`, matching `sim_staging.py`'s
real, live-verified SIM convention — but this assumption was never live-verified
against real SINAN data before this rehearsal. Inspecting the real downloaded Parquet
directly showed `DT_NOTIFIC` values like `'20230101'`, `'20230628'`, `'20230911'` — all
`YYYYMMDD`, not `DDMMYYYY`. Parsing `'20230101'` as `%d%m%Y` computes month=`23`, which
`pd.to_datetime(..., errors="coerce")` silently turns into `NaT` rather than raising —
exactly the SIH `group="RD"`-class silent-wrong-result failure (a filter that
quietly returns the wrong subset instead of raising), just at the staging layer instead of the fetch layer.

**Fix:** `backend/etl/staging/sinan_staging.py::_parse_dt_notific` now tries both
`%d%m%Y` and `%Y%m%d` against the batch's 8-digit values and counts how many each
actually parses to a valid calendar date, defaulting to `%d%m%Y` (the established SIM
convention, matching the existing unit fixtures) unless `%Y%m%d` strictly out-parses it
on that batch — which is what real YYYYMMDD-shaped data (ANIM 2023) does. A regression
test (`test_stage_sinan_ano_mes_from_yyyymmdd_string`) was added to
`backend/tests/test_etl_staging_sinan.py` asserting a `YYYYMMDD` batch parses correctly;
all 34 tests in that file pass, plus the full `test_etl_pipeline_sinan.py` and
`test_scripts_assert_sinan_completeness.py` suites (53 tests total across the three
files). The stale `audit_ingestao` row and cached Parquet file from the failed first
attempt were deleted before re-running, so every number below comes from a genuinely
fresh re-run against the fixed code.

### Rehearsal run

```
cd backend && python -m etl.pipeline --sinan-only --agravo ANIM --ano 2023
```
```
INFO SINAN ANIM 2023: 10000 rows saved to data\raw\SINAN_ANIM_2023.parquet
INFO stage_sinan: dropped 2 rows with null/blank ID_MN_RESI
INFO stage_sinan: total rows dropped: 2 of 10000 (0.0%)
INFO load_notificacoes complete: 9998 upserted, 0 skipped (local=0, agravo=0)
INFO SINAN ANIM 2023: 9998 rows upserted

Pipeline complete:
  SINAN files processed       : 1
  SINAN notificações upserted : 9998
  SINAN already loaded (resumed): 0
  SINAN absent from catalog   : 0
```

### Verification queries (real observed output)

**1. Total rows and per-`tipo_agravo` breakdown**
```sql
SELECT COUNT(*) FROM fato_notificacoes;                          -- 9998
SELECT tipo_agravo, COUNT(*) FROM fato_notificacoes GROUP BY tipo_agravo;
```
```
 tipo_agravo | count
-------------+-------
 ANIM        |  9998
```
Rows exist only for `ANIM`, as expected for a scoped single-agravo load.

**2. Distinct UF coverage from one national file**
```sql
SELECT COUNT(DISTINCT dl.sigla_uf)
FROM fato_notificacoes fn JOIN dim_local dl ON fn.dim_local_id = dl.id;   -- 27
```
All 27 UFs present, none absent:
`AC,AL,AM,AP,BA,CE,DF,ES,GO,MA,MG,MS,MT,PA,PB,PE,PI,PR,RJ,RN,RO,RR,RS,SC,SE,SP,TO`.
This is the live evidence for UF coverage: a single national `sinan()` call
(no `state=`/UF parameter at all) yields rows spanning every UF.

**3. Per-agravo null pattern**
```sql
SELECT COUNT(*) FILTER (WHERE classi_fin IS NOT NULL) AS classi_fin_nn,
       COUNT(*) FILTER (WHERE gravidade_grave IS NOT NULL) AS grav_nn
FROM fato_notificacoes;                                            -- 0, 0

SELECT COUNT(*) FILTER (WHERE tra_classi IS NOT NULL) AS tra_nn,
       COUNT(*) FILTER (WHERE tp_acidente IS NOT NULL) AS tp_nn
FROM fato_notificacoes;                                            -- 9960, 9998

SELECT tra_classi, COUNT(*) FROM fato_notificacoes GROUP BY tra_classi ORDER BY 2 DESC;
```
```
 tra_classi | count
------------+-------
          1 |  9159
          2 |   556
          3 |   197
          9 |    48
  (blank)   |    38
```
`classi_fin`/`gravidade_grave` are 0/0 non-NULL — confirmed absent for `ANIM`, matching
the migration's documented per-agravo nullability. `tp_acidente` is fully populated
(9998/9998); `tra_classi` is 9960/9998 non-NULL (38 blank-string source rows staged to
NULL, per the empty-string/`"None"`-string missing-value handling in `stage_sinan`).
The `tra_classi` distribution (`1`:9159, `2`:556, `3`:197, `9`:48, blank:38) matches
`docs/pysus-270-sinan-spike-findings.md`'s raw distribution (`1`:9159, `2`:557, `3`:197,
`9`:49, blank:38) to within the 2 rows dropped for null `ID_MN_RESI` in this run — they
agree.

**4. `taxa_por_100k` coverage**
```sql
SELECT COUNT(*) FILTER (WHERE taxa_por_100k IS NOT NULL) AS taxa_nn,
       COUNT(*) FILTER (WHERE taxa_por_100k IS NULL) AS taxa_null,
       COUNT(*) AS total
FROM fato_notificacoes;
```
```
 taxa_nn | taxa_null | total
---------+-----------+-------
    9998 |         0 |  9998
```
0% NULL rate: every município/ano pair this rehearsal loaded has a matching TCU
population estimate in `dim_populacao`. A non-zero NULL rate would mean the loaded
município/ano combination has no TCU estimate — not observed here.

**5. Residence attribution spot-check**
```sql
SELECT fn.id, fn.numero_notificacao, dl.codigo_ibge_6, dl.sigla_uf, dl.nome_municipio
FROM fato_notificacoes fn JOIN dim_local dl ON fn.dim_local_id = dl.id
ORDER BY fn.id LIMIT 5;
```
```
 id | numero_notificacao   | codigo_ibge_6 | sigla_uf | nome_municipio
----+-----------------------+---------------+----------+----------------
  1 | 2023202301320100-0    | 320100        | ES       | Boa Esperança
  2 | 2023202301320405-0    | 320405        | ES       | Pedro Canário
  3 | 2023202301292200-0    | 292200        | BA       | Mucuri
  4 | 2023202301320300-0    | 320300        | ES       | Iúna
  5 | 2023202301320210-0    | 320210        | ES       | Ecoporanga
```
The raw source Parquet's first 5 rows: `ID_MN_RESI` = `320100, 320405, 292200, 320300,
320210`; `ID_MUNICIP` = `320100, 320405, 320405, 320300, 320210`. All five
`codigo_ibge_6` values match `ID_MN_RESI` exactly. Row 3 is the discriminating case:
`ID_MN_RESI=292200` (Mucuri, BA) differs from `ID_MUNICIP=320405` (the notifying unit's
municipality, ES) on that same source row, and the database attributes it to `292200` —
proving residence attribution reads `ID_MN_RESI`, not `ID_MUNICIP`.

**6. Audit row**
```sql
SELECT arquivo, uf, ano, fonte FROM audit_ingestao WHERE fonte = 'SINAN';
```
```
             arquivo              | uf | ano  | fonte
-----------------------------------+----+------+-------
 data\raw\SINAN_ANIM_2023.parquet |    | 2023 | SINAN
```
`uf` is NULL, `ano` is the real rehearsal year `2023` — confirmed.

### Resume proof

```
cd backend && python -m etl.pipeline --sinan-only --agravo ANIM --ano 2023
```
```
INFO SINAN ANIM 2023: using local file data\raw\SINAN_ANIM_2023.parquet
INFO SINAN ANIM 2023 already loaded (hash=095c3ec5d97cbb7298a4bef1dcc0c6ba) — skipping

Pipeline complete:
  SINAN files processed       : 0
  SINAN notificações upserted : 0
  SINAN already loaded (resumed): 1
  SINAN absent from catalog   : 0
```
`fato_notificacoes` row count unchanged at 9998 after the re-run — no re-download
(reused the cached Parquet), no re-load (`already loaded` short-circuit).

### Scoped completeness gate

```
python scripts/assert_sinan_completeness.py --agravo ANIM --ano 2023 --min-ufs 27
```
```
SINAN completeness OK: 1 combos checked, 0 allowlisted absences, 4 allowlisted
partials, 9998 total notificações, 0 unexplained gaps.

Per-agravo UF coverage:
  ANIM: 27 distinct UFs

Lowest-count combos (plausibility check):
  ANIM/2023: 9998 notificações
```
Exit code `0`. `--min-ufs 27` was used rather than a relaxed value because this
rehearsal's single unit happened to observe the full 27-UF count already (query 2
above); had the observed count been lower, the value observed in query 2 would have
been used instead. The 4 "allowlisted partials"
are the pre-populated `known_partial` entries in
`scripts/sinan_agravo_allowlist.yaml` (DENG/CHIK/ANIM 2024 + ANIM 2023 itself) —
none are new; no entry was added by this rehearsal. **This scoped run does not exercise
the unrelaxed default 27-agravo x 10-year grid presence/cliff checks across all three
agravos** — confirming the full grid's completeness against `scripts/sinan_agravo_allowlist.yaml`
without new unexplained entries is the operator's responsibility after the full-grid run.

### Summary

All acceptance criteria for SINAN ingestion are demonstrated against real,
freshly-fetched DataSUS data: notifications are attributed to município of residence
(§5), span all 27 UFs from a single national file with no UF parameter at fetch time
(§2), carry the correct per-agravo nullable classification columns (§3), are labelled
`notificações` throughout (never `casos`), and the resume path re-downloads and re-loads
nothing (§ Resume proof). One real staging bug (`DT_NOTIFIC` digit-order assumption) was
found and fixed as a direct result of running this rehearsal against real data instead
of fixtures — exactly the failure mode this rehearsal exists to catch before the multi-hour
full-grid run.
