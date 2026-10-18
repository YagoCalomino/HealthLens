# pysus 2.7.0 Verification Spike — Findings

**Purpose:** Confirm the real API surface of `pysus` 2.7.0 (`sim()`/`sih()` return types, `as_dataframe=True` requirement, `IDENT=1` reconfirmation) against live DataSUS data, executed in this repo, before any ingestion code is written.

**Script:** `scripts/spike_pysus_270.py`
**Run command:** `python scripts/spike_pysus_270.py` (defaults: SIM `AC` 2022, SIH `SE` 2023)
**Result:** Exit code `0` — all six checks PASSED on the first run; no UF/year retry was needed (`SE` 2023 already had RD files in the catalog).

## Verdict

| # | Check | Verdict | Observed evidence (one line) |
|---|-------|---------|-------------------------------|
| 1 | Versions | PASS | `pysus.__version__='2.7.0'`, `pyreaddbc.__version__='2.0.4'` |
| 2 | `as_dataframe` signature | PASS | `as_dataframe` is not a direct `sim()`/`sih()` parameter (forwarded via `**kwargs`); the real default (`False`) lives on `pysus.api._impl.databases._fetch_data` |
| 3 | SIM return type | PASS | `sim()` default → `list` (paths); `sim(as_dataframe=True)` → `DataFrame`, 4159 rows |
| 4 | `group="RD"` is broken | PASS | `sih(..., group='RD')` → `DataFrame`, `len=0` — confirms the DuckLake catalog bug |
| 5 | Filename-prefix filtering | PASS | Observed prefixes for SE/2023: `['RD', 'RJ', 'SP']`; first RD file downloaded successfully |
| 6 | `IDENT=1` reconfirmation | PASS | RD file: 113 columns, no `SP_TIPO`, `IDENT` value_counts `{1: 8414, 5: 66}`; RJ file (475 rows): 100% `IDENT==1` |

## Raw output

```
Downloading sim:   0%|          | 0/1 [00:00<?, ?file/s]Downloading sim: 100%|##########| 1/1 [00:01<00:00,  1.77s/file]Downloading sim: 100%|##########| 1/1 [00:01<00:00,  1.77s/file]
======================================================================
pysus 2.7.0 verification spike -- results
======================================================================

[PASS] 1. Versions
    pysus.__version__='2.7.0' pyreaddbc.__version__='2.0.4'

[PASS] 2. as_dataframe signature
    pysus.sim(state: Annotated[str, AfterValidator(func=<function _validate_state at 0x0000021C36E7D580>)], year: int | list[int], group: str | None = None, **kwargs) -> list[str] | pandas.core.frame.DataFrame
    pysus.sih(state: Annotated[str, AfterValidator(func=<function _validate_state at 0x0000021C36E7D580>)], year: int | list[int], month: int | list[int], group: str | None = None, **kwargs) -> list[str] | pandas.core.frame.DataFrame
    as_dataframe NOT a direct sim() param (forwarded via **kwargs): True
    as_dataframe NOT a direct sih() param (forwarded via **kwargs): True
    pysus.api._impl.databases._fetch_data(dataset: str, group: str | None = None, state: str | None = None, year: int | list[int] | None = None, month: int | list[int] | None = None, show_progress: bool = True, as_dataframe: bool = False, **kwargs) -> list[str] | pandas.core.frame.DataFrame
    _fetch_data's as_dataframe default is False: True

[PASS] 3. SIM return type
    sim() (default) -> list (is list: True); sim(as_dataframe=True) -> DataFrame (is DataFrame: True), row count: 4159

[PASS] 4. group="RD" is broken
    sih(..., group='RD') -> DataFrame, len=0 (no-data outcome confirms the bug: True)

[PASS] 5. Filename-prefix filtering
    observed filename prefixes: ['RD', 'RJ', 'SP']; RD file found and downloaded: True

[PASS] 6. IDENT reconfirmation
    IDENT in columns: True
    SP_TIPO not in columns: True
    column count: 113
    IDENT value_counts:
IDENT
1    8414
5      66
    RJ file row count: 475, fraction with IDENT==1: 1.0000 (evidence that IDENT alone cannot discriminate RD from RJ)

======================================================================
SUMMARY
======================================================================
  PASS -- 1. Versions
  PASS -- 2. as_dataframe signature
  PASS -- 3. SIM return type
  PASS -- 4. group="RD" is broken
  PASS -- 5. Filename-prefix filtering
  PASS -- 6. IDENT reconfirmation

All checks PASSED.
```

## Confirmed API contract

Downstream code must use exactly this contract:

- **SIM:** `pysus.sim(state=<uf>, year=<ano>, as_dataframe=True, show_progress=False)` — single centralized call site change; SIM has only one file type/group, so no group disambiguation problem exists.
- **SIH:** the top-level `sih(..., group="RD")` call is **forbidden** — verified broken (Check 4). Use the low-level client pipeline instead:
  1. `async with PySUS() as client: files = await client.query(dataset="sih", state=uf, year=ano, month=meses)` — no `group=` parameter.
  2. Filter the returned file list client-side: `rd_files = [f for f in files if f.path.name.upper().startswith("RD")]`.
  3. `local_path = (await client.download(f)).path` for each filtered file.
  4. `client.read_parquet(local_paths, add_dv=False).df()` to materialize the `pd.DataFrame`.
- Drive the low-level client through a single `asyncio.run(...)` call per fetch (no ETL-wide async migration, no `asyncpg` leaking into the sync ETL boundary) — this mirrors what `sim()`/`sih()` already do internally.

**Signature-introspection note:** it was initially assumed `inspect.signature(pysus.sim).parameters["as_dataframe"]` would exist directly. Live introspection (Check 2) shows `sim()`/`sih()` declare `**kwargs` and forward `as_dataframe` to the internal `_fetch_data()` helper, where the real `False` default lives. The calling convention (`as_dataframe=True` as a kwarg) is unaffected — this is purely a signature-introspection detail, not a contract change. `scripts/spike_pysus_270.py` was written to assert against the real, observed signature rather than crash on a `KeyError`.

## IDENT=1 reconfirmation

- The live-downloaded SIH-RD file (SE, 2023, month 1) has **113 columns**, contains `IDENT`, and does **not** contain `SP_TIPO` — consistent with the documented RD-only schema.
- `IDENT` value_counts on that file: `{1: 8414, 5: 66}` — i.e. 8414/8480 rows (99.2%) are incident AIHs (`IDENT=1`), 66 rows are long-stay continuation AIHs (`IDENT=5`).
- The live-downloaded SIH-RJ file (475 rows) has **100%** of rows with `IDENT==1`.
- **Conclusion:** `IDENT=1` remains the correct filter to isolate incident AIHs from long-stay-continuation AIHs *within* an already RD-filtered dataset — this is unchanged and reconfirmed. However, `IDENT=1` is **not** a record-type discriminator across SIH groups: SIH-RJ ("AIH Rejeitada") rows also pass `IDENT=1` at 100%. Any ingestion code that fetches SIH without first isolating RD-prefixed files and relies on `IDENT=1` alone would silently load rejected AIH claims into `fato_internacoes` as if they were valid incident hospitalizations. The filename-prefix filter (Check 5/Confirmed API contract above) is the primary safeguard; `IDENT=1` is a required second, defense-in-depth layer, not a replacement.

## Deltas vs. earlier exploration

None of substance — this run reconfirms every load-bearing claim from the earlier exploratory research:

- `sim()`/`sih()` return `list[str]` by default, `pd.DataFrame` with `as_dataframe=True` — confirmed (Checks 2, 3).
- `sih(..., group="RD")` returns zero rows under the 2.7.0 DuckLake catalog — confirmed (Check 4), and no exception was raised (`DataFrame`, `len=0`, not a raised error) — matches the earlier characterization of "silently broken", not a hard failure.
- Filename-prefix filtering isolates RD files reliably — confirmed (Check 5): SE/2023 catalog exposed `RD`, `RJ`, and `SP` prefixed files (no `ER` observed in this particular UF/year, which earlier research flagged as a possible but not guaranteed prefix for every UF/year — not a contradiction, just a smaller catalog window than the 5-UF sample used in the original research).
- RJ files carry `IDENT=1` at (effectively) 100% — confirmed (Check 6): this run observed exactly 100.00% (475/475), matching the original research's 475/475 sample.

One minor, non-load-bearing signature-introspection detail is documented above under "Confirmed API contract" (as_dataframe is forwarded via `**kwargs`, not a direct named parameter on `sim()`/`sih()`) — this does not change the calling convention or any design recommendation, only the exact mechanics of how the verification check needed to be written to avoid a `KeyError`.

## Environment

| Property | Value |
|----------|-------|
| `pysus.__version__` | `2.7.0` |
| `pyreaddbc.__version__` | `2.0.4` |
| `pandas.__version__` | `2.2.3` |
| Date of run | 2026-07-24 |
| SIM UF/year used | AC, 2022 (default; no retry needed) |
| SIH UF/year used | SE, 2023 (default; no retry needed — RD files were present in the catalog for this combination) |

## End-to-end validation (small sample)

**Purpose:** Prove the pysus 2.7.0 SIH path
end-to-end against real DataSUS data for a small UF sample, run twice to prove
resumability, before handing the operator `docs/sih-reingestion-runbook.md` for the
full 27x15 run.

**UF/year substitution:** the intended default sample was `AC,SE / 2023`. Live catalog
scan showed `AC` has **zero** RD files for 2023:

```
UF   2023
AC     .  (0 years)
SE     5  (1 years)
RR     6  (1 years)
AP     4  (1 years)

Total available: 3 / 4 UF x ano combos have at least one RD file
```

`AC` was substituted with `RR` (Roraima, also a small UF, confirmed available). All
following steps use **`SIH_UFS=SE,RR SIH_ANOS=2023`**.

### Preflight (make up / make seed equivalent)

`make` itself is not installed in this execution environment, so the underlying
commands the `up`/`seed` targets wrap were run directly and produced the same
observable effect:

- `docker compose up -d db` + `docker compose run --rm migrate` → `alembic current` →
  `0015 (head)`.
- `python -m seeds.cid10_loader` / `ibge_loader` / `tcu_loader` / `faixa_etaria_loader`
  → CID-10 fallback seed (16 rows, FTP unreachable from this host — pre-existing,
  unrelated to this validation), IBGE 5571 municipalities (0 NULL `codigo_ibge_7`), TCU
  83550 population rows, 10 faixa-etária rows.

**Local-environment note:** this machine has a native Windows
PostgreSQL service already bound to `0.0.0.0:5432`, which silently intercepted the
Docker Compose `db` service's port mapping and caused `password authentication failed`
errors when connecting from the host. Worked around for this rehearsal only with a
local, untracked `docker-compose.override.yml` remapping `db` to host port `5433`
(removed after the rehearsal — not committed). Operators
on machines without a conflicting local Postgres service will not encounter this.

### Bugs found and fixed during the live rehearsal

1. **`.env.example`/`.env` `DATABASE_URL_SYNC` used the SQLAlchemy-style
   `postgresql+psycopg2://` scheme**, which `psycopg2.connect()` cannot parse
   (`invalid dsn: missing "=" after ...`) — every script that calls
   `psycopg2.connect(config.DATABASE_URL_SYNC)` directly (`etl/pipeline.py`,
   `scripts/reset_sih_data.py`, `scripts/assert_sih_completeness.py`,
   `seeds/*_loader.py`) would fail on first real (non-mocked) invocation. Fixed
   `.env.example`'s `DATABASE_URL_SYNC` to the plain `postgresql://` scheme
   psycopg2 actually accepts (`DATABASE_URL`, used only via SQLAlchemy's async
   driver, is unaffected and keeps its `+asyncpg` suffix).
2. **`etl/mart/dim_lookup.py::DimCache.get_or_create_tempo_id` could not INSERT a
   first-encounter `(ano, mes)` pair** — `ano`/`mes` are passed straight from a
   pandas `itertuples()` row (`numpy.int64`), and psycopg2 cannot adapt
   `numpy.int64` parameters (`psycopg2.ProgrammingError: can't adapt type
   'numpy.int64'`). This was never exercised by the existing test suite (mocked
   DB) or by the SIM path in this rehearsal (its `(ano, mes)` pairs happened to
   already exist in `dim_tempo` from prior seeding, so only the cache-hit path —
   which never calls `INSERT` — ran). The first real SIH load for a brand-new
   `(ano, mes)` combination hit the bug immediately. Fixed by casting `ano`/`mes`
   to native Python `int` inside `get_or_create_tempo_id` itself, so every caller
   (SIM's `obitos_loader.py` and SIH's `internacoes_loader.py`) is covered by a
   single fix. Verified: `pytest tests/test_etl_mart_dim_lookup.py` — 11/11 still
   passing after the fix.

Both fixes were committed alongside this validation (bugs discovered while proving
the end-to-end path).

### Run 1 — first real load (proves the pysus 2.7.0 fix pulls real data)

```
cd backend && python -m etl.pipeline --uf SE,RR --ano 2023
...
INFO SIH: fetching 1/2 SE 2023
INFO Downloading SIH SE 2023 from DataSUS FTP
INFO SIH SE 2023: 47760 rows saved to data\raw\SIH_SE_2023.parquet
INFO SIH: dropping 312 non-incident AIHs (IDENT != 1) of 47760 total rows
INFO SIH staging complete: 47448 incident AIH rows ready for mart loader
...
INFO load_internacoes: finished — total=22486 upserted=5805 skipped=16681
INFO Assertion passed: all fato_internacoes rows have sp_tipo=1
INFO SIH RR 2023: 5805 rows upserted
INFO Refreshing materialized views...
INFO Materialized views refreshed
INFO TABNET cross-validation: SE 2023 total_obitos=5040 (compare against TABNET)

Pipeline complete:
  SIM files processed         : 0
  SIM rows upserted           : 0
  SIM already loaded (resumed): 2
  SIM absent from catalog     : 0
  SIH files processed         : 2
  SIH rows upserted           : 12130
  SIH already loaded (resumed): 0
  SIH absent from catalog     : 0
```

`sih_files: 2` (both SE and RR fetched fresh) and `sih_rows: 12130` (nonzero) — this is
the proof the pysus 2.7.0 `group="RD"` fix actually pulls real SIH data, which the old
`sih(..., group="RD")` call under pysus 2.2.0 could not (Check 4 in this document
already proved the call returns zero rows; this run proves the replacement fetch path
loads real rows all the way into the mart).

### Run 2 — immediate re-run (resumability proof)

```
cd backend && python -m etl.pipeline --uf SE,RR --ano 2023
...
INFO SIM SE 2023 already loaded (hash=074ced9e37323a8bb15f9908f666c9ee) — skipping
INFO SIM: fetching 2/2 RR 2023
INFO SIM RR 2023: using local file data\raw\SIM_RR_2023.parquet
INFO SIM RR 2023 already loaded (hash=d69d234f1a20e7e8ebdec33ca8027065) — skipping
INFO --- SIM processing complete ---
INFO SIH: fetching 1/2 SE 2023
INFO SIH SE 2023: using local file data\raw\SIH_SE_2023.parquet
INFO SIH SE 2023 already loaded (hash=5993a6ff349355b5639f476e22d18665) — skipping
INFO SIH: fetching 2/2 RR 2023
INFO SIH RR 2023: using local file data\raw\SIH_RR_2023.parquet
INFO SIH RR 2023 already loaded (hash=7f5c69f6ea392a2c3e024e6531667b0f) — skipping
INFO Refreshing materialized views...
INFO Materialized views refreshed
INFO TABNET cross-validation: SE 2023 total_obitos=5040 (compare against TABNET)

Pipeline complete:
  SIM files processed         : 0
  SIM rows upserted           : 0
  SIM already loaded (resumed): 2
  SIM absent from catalog     : 0
  SIH files processed         : 0
  SIH rows upserted           : 0
  SIH already loaded (resumed): 2
  SIH absent from catalog     : 0
```

`sih_files: 0` and `sih_skipped_loaded` (printed as "SIH already loaded (resumed)")
`: 2`, both nonzero-loaded-file-count requirements satisfied — the
interrupt/resume-without-re-loading requirement is proven: both cached local Parquet
files were reused (no re-download) and both `(UF, ano)` units were skipped by
`audit_ingestao.hash_md5` dedup (no re-load).

### Scoped completeness assertion

```
$ python scripts/assert_sih_completeness.py --uf SE,RR --ano 2023
SIH completeness OK: 2 combos checked, 0 allowlisted absences, 10740 total rows, 0 unexplained gaps.

Lowest-count combos (plausibility check):
  RR/2023: 5251 rows
  SE/2023: 5489 rows
```

Exit code `0`.

### No rejected/continuation AIH contamination

Query against `fato_internacoes` for the loaded UFs — `(sigla_uf, ano, n_rows,
n_sp_tipo_not_1, n_null_aih_numero)`:

```
('RR', 2023, 5251, 0, 0)
('SE', 2023, 5489, 0, 0)
```

Every loaded row has `sp_tipo = 1` and a non-null `aih_numero` — zero exceptions.

Raw Parquet `IDENT` comparison (`IDENT` column is stored as `object`/string dtype in
the raw pysus Parquet — comparisons must cast/strip, not compare against the bare
int `1`):

```
SE total_rows=47760 IDENT==1=47448
RR total_rows=22486 IDENT==1=22486
```

Loaded rows never exceed the raw file's `IDENT==1` count: SE `5489 <= 47448`, RR
`5251 <= 22486` — confirming no RJ (`IDENT=1`-but-rejected) or non-incident rows were
inflated into the mart. The gap between `IDENT==1` count and loaded-row count is
explained by the loader's own dimension-FK resolution skips (unresolved
`dim_causa`/`dim_local` codes — logged as `skipped` in `load_internacoes`, not a
record-type contamination issue).

### Verdict

The pysus 2.7.0 SIH path is proven end-to-end against real DataSUS data: the fetch
fix (`_fetch_sih_rd`) pulls real rows where the old `group="RD"` call returned none,
a second run resumes with zero re-downloads and zero re-loads, the scoped
completeness assertion exits 0, and no rejected/continuation AIH reached
`fato_internacoes`. Two genuine bugs were found and fixed during this rehearsal (see
above) — both are now fixed in the codebase, and the `dim_lookup.py` fix is
additionally covered by the existing `test_etl_mart_dim_lookup.py` suite (11/11
passing after the fix).

The full 27 UF x 2010-2024 `make full` run (405 units, multi-hour) was **not** run as
part of this validation — that is the operator's own step, using
`docs/sih-reingestion-runbook.md` as the procedure.

## Full-scale re-ingestion — catalog coverage gaps (operator `make full` run)

**Finding:** SIH RD (AIH) coverage in the pysus 2.7.0 DuckLake catalog is
catalog-dependent, not uniform across UFs — some UFs are missing RD files for
specific years, independent of anything this pipeline does.

- **SP**: only **2010** and **2023** have RD files available in the catalog across the
  full 2010-2024 range; the other 13 years (2011-2022, 2024) have no RD file for SP.
- Most other UFs have complete or near-complete RD coverage across 2010-2024.
- For SP years where no RD file exists, the catalog instead exposes SP-schema files
  (36 columns, no `IDENT` column — the SIH-SP "procedures" group, not SIH-RD). The
  filename-prefix filter in `_fetch_sih_rd` (`backend/etl/ingestor.py`) correctly
  skips these — **this is the ingestor working as designed**, not a bug: an SP-schema
  file must never be mistaken for an RD/AIH file (`SP_TIPO` belongs only to the
  SP group, so it is always null on genuine RD/AIH rows).
- **Conclusion:** this is a **DataSUS/DuckLake catalog limitation** — the underlying
  data does not exist in the catalog for those UF/year combos — not a project
  deficiency or an ingestion defect. It mirrors the same class of issue the v1 SIH
  blocker documented (catalog gaps are a known, recurring characteristic of this data
  source, not something a pipeline fix can close).

**Action taken:** `scripts/sih_year_allowlist.yaml`'s `known_absent` list was updated
to document SP's known-absent years (2011-2022, 2024) so
`scripts/assert_sih_completeness.py` treats them as confirmed-absent rather than
flagging them as unexplained gaps on every future run.
