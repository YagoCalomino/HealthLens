# S3 Mirror Fallback Runbook (SIH)

Manual, documented-not-coded procedure for fetching a SIH `.dbc` file directly from the
DataSUS FTP mirror when the pysus DuckLake catalog cannot serve a given (UF, ano) combo.
No `boto3` code exists in this repo for this path — this document is the fallback
until a real catalog gap is confirmed against the operator's own full 27x15 run.

## When to use this

Follow this decision tree when `scripts/assert_sih_completeness.py` reports a failing
(UF, ano) combo:

1. Run `python scripts/scan_sih_catalog.py --uf <UF> --ano <ano>` for the failing combo(s).
2. **If the scan finds RD files** (month count > 0) but `fato_internacoes` is still
   missing rows for that combo — this is a **pipeline bug**, not a data-availability
   problem. Do not use this runbook; investigate `backend/etl/ingestor.py::_fetch_sih_rd`
   and `stage_sih.py` instead.
3. **If the scan finds nothing** (catalog shows `.` for that UF/ano), check whether the
   DataSUS FTP tree itself has the file via this mirror (Mirror layout section below).
   - **If the mirror has it:** follow the rest of this runbook to fetch, convert, and
     load it manually.
   - **If neither the pysus catalog nor the mirror has it:** the combo is genuinely
     absent upstream. Add it to `scripts/sih_year_allowlist.yaml` with a dated comment
     — it is not a bug and not fetchable by any path.

## Mirror layout

- Host: `datasus-ftp-mirror.nyc3.cdn.digitaloceanspaces.com`
- This is a DigitalOcean Spaces mirror of the DataSUS FTP directory tree. It is a
  real, community-maintained fallback data source, but it is **NOT integrated with
  pysus** — pysus's own DuckLake catalog store points to a completely different
  S3-compatible endpoint/bucket (Hetzner-backed, `nbg1.your-objectstorage.com`,
  bucket `pysus`). Do not confuse the two: this mirror must be reached directly over
  HTTPS, never through the `pysus.api.client.PySUS` client.
- SIH-RD files live under the SIHSUS reduced-AIH path of the mirrored FTP tree
  (`dissemin/publicos/SIHSUS/...` in the canonical DataSUS FTP layout).
- Filename convention: `RD{UF}{YY}{MM}.dbc` — a 2-character group prefix (`RD`),
  2-character UF code, 2-digit year, 2-digit month. Example: `RDSE2301.dbc` is the
  January 2023 reduced-AIH file for Sergipe. This is the exact same prefix rule
  `backend/etl/ingestor.py::_fetch_sih_rd` uses to filter the pysus catalog's file
  list (`f.path.name.upper().startswith("RD")`) — only ever fetch `RD`-prefixed
  files from the mirror; never `SP`, `RJ`, or `ER`-prefixed files.
- This mirror serves raw `.dbc` files, **not** the `.parquet` files pysus's own
  DuckLake catalog serves. A manual conversion step (below) is required before the
  data can enter the pipeline.

## Fetching a file

No credentials are required for public reads, and this project stores no keys for
this host. Fetch a single object over HTTPS with a plain download:

```bash
curl -O "https://datasus-ftp-mirror.nyc3.cdn.digitaloceanspaces.com/<path-to-file>/RDSE2301.dbc"
```

A browser download of the same URL works identically — no API client, no signed
request, no S3 SDK is needed for a read-only fetch from this particular mirror.

Repeat for every month of the target (UF, ano) that the mirror actually has.

## Converting `.dbc` to a DataFrame

`pyreaddbc` (pinned `>=2.0.4` in `backend/requirements.txt`) is already installed as
a transitive pysus dependency — no extra install is needed.

```python
import pandas as pd
from pyreaddbc import read_dbc

df_jan = read_dbc("RDSE2301.dbc")
df_feb = read_dbc("RDSE2302.dbc")
# ... one DataFrame per monthly .dbc actually fetched for this UF/ano

df_year = pd.concat([df_jan, df_feb, ...], ignore_index=True)
df_year.to_parquet("data/raw/SIH_SE_2023.parquet")
```

Name the output file `data/raw/SIH_{UF}_{ANO}.parquet` exactly — this is the integration
point that makes the manual path work with zero code changes. The existing
`get_or_download_sih` local-cache short-circuit in `backend/etl/ingestor.py` checks
`data/raw/` for a file matching this pattern before calling out to pysus, so placing
the Parquet there is sufficient for the next `make full` invocation to pick it up
without touching any ETL code.

## Re-entering the pipeline

1. Place the converted Parquet at `data/raw/SIH_{UF}_{ANO}.parquet`.
2. Re-run the pipeline for that UF/year (e.g. `make full` scoped to the UF/ano, or the
   equivalent `backend/etl/pipeline.py --uf <UF> --ano <ano>` invocation).
3. The `audit_ingestao` dedup means already-loaded combos are skipped on re-run — only
   the manually-supplied combo actually loads.
4. Re-run `python scripts/assert_sih_completeness.py` to confirm the combo now passes.

## Caveats

- If the mirror only has some months for the target year, the resulting `data/raw/`
  Parquet legitimately represents partial-year coverage — this matches the same
  partial-month reality the pysus catalog itself exhibits (see
  `docs/sih-reingestion-runbook.md`); it is not a defect of this manual path.
- Multiple monthly `.dbc` files must be concatenated into one yearly Parquet exactly
  as shown above — `_fetch_sih_rd`'s existing caller expects one Parquet per (UF, ano),
  not per (UF, ano, mes).
- The `IDENT=1` filter in `stage_sih.py` still applies downstream to manually supplied
  data, exactly as it does to pysus-sourced data — do not pre-filter `IDENT` in the
  conversion step above; let staging own that filter so the same tested logic covers
  both provenance paths.
- Only `RD`-prefixed files may ever be used from this mirror. `RJ` (AIH Rejeitada)
  files pass the `IDENT=1` filter at 100% (verified in `docs/pysus-270-spike-findings.md`)
  and would silently corrupt `fato_internacoes` with rejected claims if fetched and
  loaded as if they were incident hospitalizations.

## Why this is not automated

Rationale: at the time of writing, the full 27x15 `make full` run has not yet been
executed by the operator, so no confirmed pysus catalog gap exists. Writing speculative
`boto3` fallback code against an unconfirmed failure mode would be premature — the
gap this runbook exists for may never materialize, or may materialize for a different
set of (UF, ano) combos than any guess made now. Automation is deferred until a real
gap appears in the operator's own run.

A future automation task would add:

- A `boto3` client configured against `datasus-ftp-mirror.nyc3.cdn.digitaloceanspaces.com`
  (distinct from the S3 client pysus itself already uses internally against its own
  Hetzner-backed bucket) to list and fetch objects programmatically instead of manual
  `curl`.
- The `.dbc` -> Parquet conversion already described above, wrapped in a small script
  that writes directly to `data/raw/SIH_{UF}_{ANO}.parquet`, reusing the same naming
  convention so no downstream code changes would be needed at that point either.
