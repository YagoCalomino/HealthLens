# SIH Re-ingestion Operator Runbook

Operator procedure for the full 27 UF x 2010-2024 SIH (SIHSUS/AIH) re-ingestion under
pysus 2.7.0. This document takes the operator from a clean reset through a resumable,
multi-hour run to a passing completeness assertion.

For the SIM (mortality) equivalent — re-ingesting SIM through 2024 and backfilling
`raca_cor` — see `docs/sim-2024-reingestion-runbook.md`.

## 1. What this does and why

`pysus` was upgraded `2.2.0` -> `2.7.0`. Under the old version, the
convenience call `sih(..., group="RD")` silently returned zero rows against the current
DuckLake catalog — a broken filter, not a data-availability problem. The fix
(`backend/etl/ingestor.py::_fetch_sih_rd`) replaces that call with a low-level
`PySUS()` client fetch that filters the catalog's file list by `RD` filename prefix
before downloading, with `IDENT=1` retained as a second, defense-in-depth filter in
`backend/etl/staging/sih_staging.py`.

**All 27 UFs are re-downloaded from scratch** — including the 5 UFs that
already held data loaded under the old, broken pysus 2.2.0 path — to avoid mixed
provenance between rows loaded under the broken filter and rows loaded under the
fixed one. There is no partial-migration path: the reset in Step 1 clears all prior
SIH state before the new run begins.

## 2. Preflight

1. `pip install -r backend/requirements.txt` — installs the pinned `pysus==2.7.0` /
   `pyreaddbc>=2.0.4` versions this runbook depends on.
2. `make spike-pysus` must exit 0. Re-run this whenever more than two weeks have
   passed since `docs/pysus-270-spike-findings.md` was written — the DuckLake catalog
   is a third-party-hosted service and has already shipped one undocumented breaking
   change (the `group="RD"` regression this re-ingestion exists to fix). Do not assume the
   API contract is stable indefinitely.
3. `make up` — starts PostgreSQL and runs Alembic migrations.
4. `make seed` — loads CID-10, IBGE, TCU and faixa-etária dimension seeds.
5. Confirm `DATABASE_URL_SYNC` and `CORS_ORIGINS` are set in the environment (or
   `.env`) — `make full`/`make reset-sih`/`make assert-sih` all fail fast via
   `scripts/validate_env.py` or their own `DATABASE_URL_SYNC` guard if these are
   missing.
6. Budget disk space for `data/raw/` — a full run caches up to 405 yearly SIH Parquet
   files (`data/raw/SIH_{UF}_{ANO}.parquet`), one per (UF, ano) unit, in addition to
   existing SIM Parquet files.

## 3. Step 1 — Reset (one-time, destructive)

Preview first, then execute:

```bash
python scripts/reset_sih_data.py --dry-run
make reset-sih
```

`make reset-sih` runs `python scripts/reset_sih_data.py --confirm`, which deletes, in
this order:

- **All rows from `fato_internacoes`** (the entire SIH fact table).
- **Rows from `audit_ingestao` WHERE `fonte = 'SIH'`** (SIH ingestion history only).
- **All `data/raw/SIH_*.parquet` cache files.**

It **preserves**: all SIM `audit_ingestao` rows (`fonte = 'SIM'`), all
`fato_obitos` rows, and all `data/raw/SIM_*.parquet` cache files. `reset_sih_data.py`
never touches SIM state.

Skipping this step means the existing hash-based dedup in `etl/pipeline.py`
(`_already_loaded`, keyed off `audit_ingestao.hash_md5`) and the local-Parquet-cache
short-circuit in `etl/ingestor.py::get_or_download_sih` would silently retain rows and
cache files loaded under the pysus 2.2.0-era broken filter — exactly the mixed-
provenance failure the reset step exists to prevent. Always reset before the first pysus 2.7.0
full re-ingestion.

## 4. Step 2 — Run

```bash
make full
```

This is a **multi-hour** operation: it iterates `SIH_UFS x SIH_ANOS` (default: all 27
UFs x 2010-2024 = 405 UF-year units) through `python -m etl.pipeline`. `pysus` caps its
own download concurrency internally — this runbook does not add parallelism on top of
it. Progress is readable from the per-unit `N/405`-style positional log lines emitted
by the pipeline as each (UF, ano) unit is processed.

For a scoped rehearsal or a targeted re-run of specific UFs/years, override
`SIH_UFS=`/`SIH_ANOS=` on the command line:

```bash
make full SIH_UFS=AC,SE SIH_ANOS=2023
```

## 5. Step 3 — Interrupt and resume

Ctrl-C is safe at any point during `make full`. On re-run:

- Units already recorded in `audit_ingestao` (matched by `hash_md5`) are skipped —
  `_already_loaded` short-circuits before any network call.
- Cached `data/raw/SIH_{UF}_{ANO}.parquet` files are reused without re-downloading.

**The checkpoint unit is one (UF, ano) pair.** A unit interrupted mid-download loses
only that unit's own partial work — it never rolls back or invalidates a unit that had
already completed and been recorded. There is no finer-grained (e.g. per-month)
checkpoint; a half-downloaded UF-year simply re-downloads that UF-year from scratch on
the next run.

The end-of-run summary printed by `etl.pipeline` reports, for both SIM and SIH:
loaded-file counts, row counts, already-loaded skip counts, and absent-from-catalog
skip counts (`sim_files`, `sih_files`, `sim_rows`, `sih_rows`, `sim_skipped_loaded`,
`sih_skipped_loaded`, `sim_skipped_absent`, `sih_skipped_absent`).

## 6. Step 4 — Verify

```bash
make assert-sih
```

Runs `python scripts/assert_sih_completeness.py`, which asserts every (UF, ano) combo
in the 405-combo grid has at least `--min-rows` (default 1) `fato_internacoes` rows,
unless the combo is listed in `scripts/sih_year_allowlist.yaml`. Exit code `0` means
every checked combo passed or was allowlisted; exit code `1` means at least one combo
is missing or below the row-count threshold, with the failing combos printed.

The printed "lowest-count combos" list (up to 10) is a plausibility check, not a
pass/fail gate — it exists to catch surprisingly low but technically non-zero row
counts that would otherwise pass the assertion silently.

## 7. Step 5 — Handling failures

When `make assert-sih` reports failing combos, follow this decision tree:

1. `python scripts/scan_sih_catalog.py --uf <failing UFs> --ano <failing years>` —
   check whether the pysus DuckLake catalog actually has RD files for the failing
   combo(s).
2. **If the catalog has no RD files** for a combo, this is a genuine upstream data
   gap, not a bug. Add the combo to `scripts/sih_year_allowlist.yaml` with a dated
   comment naming the scan that confirmed it, then re-run
   `make assert-sih`.
3. **If the catalog DOES have RD files but rows are still missing** from
   `fato_internacoes`, this is a pipeline defect, **not** an allowlist candidate. Do
   not allowlist it. Re-run just that unit —
   `make full SIH_UFS=<uf> SIH_ANOS=<ano>` — and read the logs to diagnose.
4. If `scan_sih_catalog.py` shows the pysus catalog cannot serve a file that the
   DataSUS FTP mirror still has, follow `docs/s3-mirror-runbook.md` for the manual
   fallback fetch-and-convert procedure.

## 8. Known upstream reality

DataSUS catalog coverage is genuinely partial, independent of anything this pipeline
does: month coverage within a UF-year is frequently fewer than 12 months (e.g.
SE/2023 has RD files for only 5 of 12 months, confirmed live
by `scripts/scan_sih_catalog.py`), and some UF-years are absent from the catalog
entirely. `assert_sih_completeness.py`'s "at least one row per UF-year" threshold is
deliberate — **do not tighten it to require 12 months of coverage**; doing so would
turn a normal, well-understood upstream gap into a constant false-failure.

## 9. After a successful run

- Re-run `make ml` if downstream forecasts should reflect the newly-loaded SIH
  coverage.
- Record any populated `scripts/sih_year_allowlist.yaml` entries (with their dated,
  scan-confirmed comments) so later runs inherit the documented gaps instead of
  re-discovering them.
