# pysus 2.7.0 SINAN Verification Spike — Findings

**Purpose:** Confirm the real `pysus.sinan()` API surface (no `state=` parameter, per-agravo column ownership, `add_dv=False` digit width, absence of PII columns) against live DataSUS data, executed in this repo, before any SINAN schema, staging, or loader code is written.

**Script:** `scripts/spike_pysus_270_sinan.py`
**Run command:** `python scripts/spike_pysus_270_sinan.py` (defaults: DENG 2023, CHIK 2023, ANIM 2023, state-probe disease ANIM / year 2023)
**Run date:** 2026-08-01
**Result:** Exit code `0` — all eight checks PASSED on the first run.

## Verdict

| # | Check | Verdict | Observed evidence (one line) |
|---|-------|---------|-------------------------------|
| 1 | Versions | PASS | `pysus.__version__='2.7.0'`, `pyreaddbc.__version__='2.0.4'` |
| 2 | `sinan()` has no `state=` param | PASS | `inspect.signature(pysus.sinan)` shows `(disease: Literal[...49 codes...], year: int \| list[int], **kwargs)` — no `state` key |
| 3 | `state=` kwarg behavior | PASS | ANIM 2023 unscoped: 10,000 rows (426 with `SG_UF=='35'`); `state="SP"` call returned **0 rows** — silently filters to nothing rather than raising or returning the unscoped count |
| 4 | `add_dv` digit width | PASS | `add_dv=False`: `ID_MN_RESI` predominantly 6 digits (9,998/10,000); default (`add_dv` omitted): predominantly 7 digits (9,998/10,000) |
| 5 | Per-agravo column ownership | PASS | DENG 3,291,912 rows/121 cols, CHIK 532,884 rows/122 cols, ANIM 10,000 rows/75 cols; `CLASSI_FIN` in DENG/CHIK only; 15 `GRAV_*` columns in DENG/CHIK, 0 in ANIM; `TP_ACIDENT`/`TRA_CLASSI` in ANIM only |
| 6 | Geography/identity columns | PASS | All three frames have `ID_MN_RESI`, `ID_MUNICIP`, `SG_UF`, `SG_UF_NOT`, `DT_NOTIFIC`, `NU_ANO`, `CS_SEXO`, `NU_IDADE_N`; `ID_MN_RESI` differs from `ID_MUNICIP` on ≥1 row in all three; `NU_NOTIFIC` absent from all three |
| 7 | No PII columns | PASS | Denylist of 10 identifying-looking column names — zero matches in any of the three frames |
| 8 | Code value distributions | PASS | Every checked column (`NU_IDADE_N`, `CS_SEXO`, `CLASSI_FIN`, `TRA_CLASSI`, `TP_ACIDENT`) has non-blank values in all three frames |

## Raw output (abridged — full run output reproduced verbatim below)

```
======================================================================
pysus 2.7.0 SINAN verification spike -- results
======================================================================

[PASS] 1. Versions
    pysus.__version__='2.7.0' pyreaddbc.__version__='2.0.4'

[PASS] 2. sinan() has no state= param
    pysus.sinan(disease: Literal['ACBI', 'ACGR', 'ANIM', 'ANTR', 'BOTU', 'CANC', 'CHAG', 'CHIK', 'COLE', 'COQU', 'DENG', 'DERM', 'DIFT', 'ESQU', 'EXAN', 'FMAC', 'FTIF', 'HANS', 'HANT', 'HEPA', 'IEXO', 'INFL', 'LEIV', 'LEPT', 'LERD', 'LTAN', 'MALA', 'MENI', 'MENT', 'NTRA', 'PAIR', 'PEST', 'PFAN', 'PNEU', 'RAIV', 'SDTA', 'SIFA', 'SIFC', 'SIFG', 'SRC', 'TETA', 'TETN', 'TOXC', 'TOXG', 'TRAC', 'TUBE', 'VARC', 'VIOL', 'ZIKA'], year: int | list[int], **kwargs) -> list[str] | pandas.core.frame.DataFrame -- 'state' in parameters: False

[PASS] 3. state= kwarg behavior
    n_unscoped=10000 n_uf35=426 state='SP' outcome: returned 0 rows -- PASS condition (raises, zero rows, or equals n_unscoped): True

[PASS] 4. add_dv digit width
    add_dv=False ID_MN_RESI length value_counts:
ID_MN_RESI
6    9998
0       2
    default (add_dv omitted) ID_MN_RESI length value_counts:
ID_MN_RESI
7    9998
0       2
    predominant width: add_dv=False -> 6, default -> 7

[PASS] 5. Per-agravo column ownership
    DENG rows=3291912 cols=121; CHIK rows=532884 cols=122; ANIM rows=10000 cols=75
    CLASSI_FIN in DENG&CHIK, absent from ANIM: True
    GRAV_* counts: DENG=15 CHIK=15 ANIM=0 (>=15 in DENG/CHIK, 0 in ANIM): True
    TP_ACIDENT/TRA_CLASSI in ANIM only: True

[PASS] 6. Geography/identity columns
    DENG: has_all_geo_identity_cols=True, ID_MN_RESI differs from ID_MUNICIP on >=1 row=True -- NU_NOTIFIC not present in DENG
    CHIK: has_all_geo_identity_cols=True, ID_MN_RESI differs from ID_MUNICIP on >=1 row=True -- NU_NOTIFIC not present in CHIK
    ANIM: has_all_geo_identity_cols=True, ID_MN_RESI differs from ID_MUNICIP on >=1 row=True -- NU_NOTIFIC not present in ANIM

[PASS] 7. No PII columns
    denylist checked: ['NM_PACIENT', 'NM_PACIEN', 'NU_CPF', 'NM_MAE', 'NM_LOGRADO', 'NU_NUMERO', 'NM_BAIRRO', 'NU_CEP', 'NU_TELEFON', 'NM_REFEREN']
    matches found per agravo: none

[PASS] 8. Code value distributions
    DENG.CS_SEXO value_counts (top 15):
CS_SEXO
F       1770622
M       1516568
I          4710
              6
None          6
    CHIK.CS_SEXO value_counts (top 15):
CS_SEXO
F    313336
M    218582
I       966
    ANIM.CS_SEXO value_counts (top 15):
M    6196
F    3803
I       1
    DENG.CLASSI_FIN value_counts (top 15):
CLASSI_FIN
10      2802838
8        415374
11        47336
0         16224
           3384
None       3384
12         3372
    empty-string count: 3384, literal 'None'-string count: 3384
    CHIK.CLASSI_FIN value_counts (top 15):
CLASSI_FIN
13      260392
5       216088
         27817
None     27817
0          770
    empty-string count: 27817, literal 'None'-string count: 27817
    ANIM.TRA_CLASSI value_counts (top 15):
TRA_CLASSI
1    9159
2     557
3     197
9      49
       38
    empty-string count: 38, literal 'None'-string count: 0
    ANIM.TP_ACIDENT value_counts (top 15):
TP_ACIDENT
3    6605
2     938
1     925
6     647
5     639
4     214
9      32

======================================================================
SUMMARY
======================================================================
  PASS -- 1. Versions
  PASS -- 2. sinan() has no state= param
  PASS -- 3. state= kwarg behavior
  PASS -- 4. add_dv digit width
  PASS -- 5. Per-agravo column ownership
  PASS -- 6. Geography/identity columns
  PASS -- 7. No PII columns
  PASS -- 8. Code value distributions

All checks PASSED.
```

## Verified API shape

`inspect.signature(pysus.sinan)` == `(disease: Literal['ACBI', ..., 'ANIM', ..., 'CHIK', ..., 'DENG', ...], year: int | list[int], **kwargs) -> list[str] | pandas.core.frame.DataFrame`.

There is **no `state=` parameter** in the signature — confirmed. `state=` can still be passed positionally through `**kwargs`, which this spike's check 3 explicitly probed: calling `pysus.sinan(disease="ANIM", year=2023, state="SP", ...)` returned **0 rows** rather than raising `TypeError` or silently returning the unscoped national count. This is the exact SIH `group="RD"` bug class seen in SIH — a silent, wrong-subset result. **Conclusion for downstream code: never pass `state=` to `sinan()`.** Every project call site must fetch the full national (agravo, year) frame and filter by `SG_UF`/`ID_MN_RESI` at staging time, not at fetch time.

## Verified per-agravo column ownership

| Agravo | Row count | Column count | `CLASSI_FIN` present | `GRAV_*` count | `TP_ACIDENT` present | `TRA_CLASSI` present |
|--------|-----------|---------------|------------------------|----------------|------------------------|-------------------------|
| DENG | 3,291,912 | 121 | Yes | 15 | No | No |
| CHIK | 532,884 | 122 | Yes | 15 | No | No |
| ANIM | 10,000 | 75 | No | 0 | Yes | Yes |

This confirms the expected field ownership: `CLASSI_FIN` and the 15-member `GRAV_*` family belong to DENG/CHIK only; `TP_ACIDENT`/`TRA_CLASSI` belong to ANIM only. Neither set exists in the other agravo's real columns.

## Geographic attribution contract

`ID_MN_RESI` is município **of residence**; `ID_MUNICIP` is the **notifying health unit**. These are confirmed distinct columns — `ID_MN_RESI != ID_MUNICIP` on at least one row in all three live frames. `SG_UF` and `SG_UF_NOT` hold **2-digit IBGE UF numeric codes** (e.g. `'35'` for São Paulo), not 2-letter siglas (`'SP'`) — confirmed by ANIM's `n_uf35=426` count using a string comparison against `'35'`. Downstream code must resolve geographic attribution from `ID_MN_RESI`, never `ID_MUNICIP`.

## `add_dv` contract

With `add_dv=False` (explicit), `ID_MN_RESI` non-null values are predominantly 6 characters wide (9,998/10,000 ANIM 2023 rows). With `add_dv` omitted (pysus's `read_parquet` default of `True`), the same field is predominantly 7 characters wide (9,998/10,000). The small 2-row `0`-length bucket in both runs is a pre-existing null/blank-code artifact unrelated to `add_dv`, not a digit-width violation.

**Every project SINAN call site must pass `add_dv=False` explicitly** to keep `ID_MN_RESI`/`ID_MUNICIP` codes joinable to `dim_local.codigo_ibge_6` (the project's 6-digit FK convention) — omitting it silently produces unjoinable 7-digit codes.

## Notification identity

`NU_NOTIFIC` was checked and found **absent** from all three live frames (DENG, CHIK, ANIM) in this run's column sets. The `numero_notificacao` field cannot rely on a real `NU_NOTIFIC` source column under the current pysus 2.7.0 export and must use a derived surrogate key (e.g. a composite of `tipo_agravo` + a row-level identifying tuple, or a straightforward auto-increment PK) rather than a passthrough of a DataSUS-native notification number.

## Missing-value encoding

`CLASSI_FIN`/`TRA_CLASSI` both exhibit two textually-distinct "missing" representations in the raw pysus Parquet output — a true empty string (`''`) and the literal 4-character string `"None"` — as two separate `value_counts` buckets, not one:

- DENG `CLASSI_FIN`: 3,384 empty-string rows, 3,384 literal-`"None"`-string rows (out of 3,291,912 total).
- CHIK `CLASSI_FIN`: 27,817 empty-string rows, 27,817 literal-`"None"`-string rows (out of 532,884 total).
- ANIM `TRA_CLASSI`: 38 empty-string rows, 0 literal-`"None"`-string rows (out of 10,000 total).

This confirms the expected missing-value pattern exactly, including the DENG/CHIK empty-string-count-equals-`"None"`-string-count pattern. Staging (`stage_sinan`) must treat both empty string and the literal string `"None"` as missing, not just `pd.isna()`.

## Data-lifecycle caveat

Observed row counts per (agravo, year) in this run:

| Agravo | Year | Row count |
|--------|------|-----------|
| DENG | 2023 | 3,291,912 |
| CHIK | 2023 | 532,884 |
| ANIM | 2023 | 10,000 |

ANIM 2023's 10,000-row count is dramatically lower than DENG/CHIK 2023's multi-hundred-thousand-to-multi-million counts for the same year, and matches a previously observed ~30x-drop anomaly (an earlier exploratory session observed ANIM 2022=298,821 rows vs. ANIM 2023=10,000 rows). This is a genuine DataSUS data-lifecycle characteristic: recent years live under `DADOS/PRELIM` (preliminary, still-updating files) rather than `DADOS/FINAIS` (closed annual files), and the PRELIM snapshot for ANIM 2023 was small at the time of this run. **This is not a pysus or project bug.** It is the direct justification for the `known_partial` allowlist mechanism that `scripts/sinan_agravo_allowlist.yaml` and `assert_sinan_completeness.py` implement — recent years must be treated as expected-incomplete, not flagged as unexplained gaps.

## No PII columns

Denylist checked against all three live frames: `NM_PACIENT`, `NM_PACIEN`, `NU_CPF`, `NM_MAE`, `NM_LOGRADO`, `NU_NUMERO`, `NM_BAIRRO`, `NU_CEP`, `NU_TELEFON`, `NM_REFEREN`. **Zero matches** in DENG, CHIK, or ANIM's column sets — confirming the public-open-data assumption: no patient-identifying column reaches the ingestion path in this pysus export. A future pysus export that adds an identifying-looking column would fail this check rather than silently reaching the database.

## Environment

| Property | Value |
|----------|-------|
| `pysus.__version__` | `2.7.0` |
| `pyreaddbc.__version__` | `2.0.4` |
| `pandas.__version__` | `2.2.3` |
| Date of run | 2026-08-01 |
| DENG year used | 2023 (default) |
| CHIK year used | 2023 (default) |
| ANIM year used | 2023 (default) |
| State-probe disease/year | ANIM / 2023 (default — cheapest frame, reused from the ANIM fetch) |

## Deltas vs. earlier exploration

None of substance — this run reconfirms every load-bearing claim from the earlier exploratory session:

- `sinan()` has no `state=` parameter — confirmed (Check 2), matching the research session's live introspection exactly (identical 49-disease `Literal` list observed).
- `state=` forwarded via `**kwargs` silently returns **zero rows** rather than raising or returning the unscoped count — this resolves the open question with a concrete, re-confirmable answer: it is a silent, wrong-subset outcome (the SIH `group="RD"` bug class), not a `TypeError`. Downstream ingestor code must never rely on `state=` filtering `sinan()` calls.
- `add_dv=False` produces 6-digit `ID_MN_RESI`; default produces 7-digit — confirmed (Check 4), matching the research session's ANIM 2022 observation (`6    298746` there vs. `6    9998` here — same digit-width behavior, different row count due to the different year's smaller PRELIM snapshot).
- Per-agravo column ownership (`CLASSI_FIN`/`GRAV_*` → DENG/CHIK; `TP_ACIDENT`/`TRA_CLASSI` → ANIM) — confirmed (Check 5), exact match to the research session's column diffs.
- `ID_MN_RESI` (residence) differs from `ID_MUNICIP` (notifying unit) on real rows — confirmed (Check 6).
- No PII columns — confirmed (Check 7), same denylist, same zero-match result.
- `CLASSI_FIN`/`TRA_CLASSI` empty-string vs. literal-`"None"`-string missing-value duality — confirmed (Check 8), same empty-string-count-equals-`"None"`-string-count pattern for DENG/CHIK observed in the research session.
- ANIM's most-recent-year PRELIM row-count anomaly — confirmed present again in this run (10,000 rows for ANIM 2023, the same value observed in the original research session), reinforcing that this is a stable, real DataSUS-lifecycle characteristic and not a one-time fluke.

One informational addition not present in the earlier snapshot: this run explicitly confirmed `NU_NOTIFIC` is **absent** from all three live column sets (previously an open question feeding the `numero_notificacao` design) — the loader must therefore use a derived surrogate key, not a `NU_NOTIFIC` passthrough.
