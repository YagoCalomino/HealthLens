"""Verification spike: prove the real pysus 2.7.0 SINAN API surface live.

Re-runnable, self-contained (stdlib + pysus + pandas only, no project imports,
mirrors validate_env.py's zero-project-import convention). Runs eight numbered
checks against live DataSUS data and prints PASS/FAIL plus observed evidence
for each. Exit code 0 only if all mandatory checks pass.

This is the committed, re-runnable proof of the live SINAN findings: no
schema, staging, or loader code should rely on a field name until it is
confirmed against a real DataFrame produced by *this* script, not just
cited from earlier exploration.

Defaults fetch DENG/CHIK/ANIM for 2023 (small real sample, 1-2 agravos
x 1 recent year). DENG 2023 alone is ~3.3M rows -- each (disease, year) frame
is fetched at most once per run and shared across checks 3-8.
"""
import argparse
import inspect
import sys

import pandas as pd
import pysus


PII_COLUMN_DENYLIST = [
    "NM_PACIENT",
    "NM_PACIEN",
    "NU_CPF",
    "NM_MAE",
    "NM_LOGRADO",
    "NU_NUMERO",
    "NM_BAIRRO",
    "NU_CEP",
    "NU_TELEFON",
    "NM_REFEREN",
]

GEOGRAPHY_IDENTITY_COLUMNS = [
    "ID_MN_RESI",
    "ID_MUNICIP",
    "SG_UF",
    "SG_UF_NOT",
    "DT_NOTIFIC",
    "NU_ANO",
    "CS_SEXO",
    "NU_IDADE_N",
]


def check_versions() -> tuple[bool, str]:
    """Check 1: pysus >= 2.7.0, pyreaddbc >= 2.0.4."""
    try:
        import pyreaddbc
    except ImportError as exc:
        return False, f"pyreaddbc failed to import: {exc}"

    pysus_ok = pysus.__version__.startswith("2.7.0")
    pyreaddbc_version = tuple(
        int(p) for p in pyreaddbc.__version__.split(".")[:3]
    )
    pyreaddbc_ok = pyreaddbc_version >= (2, 0, 4)

    evidence = (
        f"pysus.__version__={pysus.__version__!r} "
        f"pyreaddbc.__version__={pyreaddbc.__version__!r}"
    )
    return (pysus_ok and pyreaddbc_ok), evidence


def check_sinan_no_state_param() -> tuple[bool, str]:
    """Check 2: sinan() has no state= parameter -- the central finding."""
    sig = inspect.signature(pysus.sinan)
    has_state = "state" in sig.parameters
    evidence = f"pysus.sinan{sig} -- 'state' in parameters: {has_state}"
    return (not has_state), evidence


def check_state_kwarg_behavior(disease: str, ano: int) -> tuple[bool, str]:
    """Check 3: what happens when state= is passed anyway.

    PASS when state= (forwarded via **kwargs) either raises, returns zero
    rows, or silently returns the unscoped national row count (parameter
    ignored). FAIL only if it returns a nonzero row count that is neither
    the unscoped count nor the UF=35 subset count -- that would mean an
    undocumented silent filter (the SIH group="RD" bug class).
    """
    try:
        df_unscoped = pysus.sinan(
            disease=disease,
            year=ano,
            as_dataframe=True,
            show_progress=False,
            add_dv=False,
        )
        n_unscoped = len(df_unscoped)
        n_uf35 = int((df_unscoped["SG_UF"].astype(str) == "35").sum())
    except Exception as exc:
        return False, f"FAIL (network, could not fetch unscoped baseline): {exc!r}"

    try:
        df_scoped = pysus.sinan(
            disease=disease,
            year=ano,
            state="SP",
            as_dataframe=True,
            show_progress=False,
            add_dv=False,
        )
        n_scoped = len(df_scoped)
        outcome = f"returned {n_scoped} rows"
        ok = n_scoped == 0 or n_scoped == n_unscoped
    except Exception as exc:
        outcome = f"raised {exc!r}"
        n_scoped = None
        ok = True

    evidence = (
        f"n_unscoped={n_unscoped} n_uf35={n_uf35} "
        f"state='SP' outcome: {outcome} -- PASS condition (raises, zero rows, "
        f"or equals n_unscoped): {ok}"
    )
    return ok, evidence


def check_add_dv_digit_width(disease: str, ano: int, frames: dict) -> tuple[bool, str]:
    """Check 4: add_dv=False -> 6-digit ID_MN_RESI; default add_dv -> 7-digit."""
    try:
        df_false = frames[disease]
        false_lens = df_false["ID_MN_RESI"].dropna().astype(str).str.len().value_counts()
        false_mode = false_lens.idxmax()

        df_default = pysus.sinan(
            disease=disease, year=ano, as_dataframe=True, show_progress=False
        )
        default_lens = df_default["ID_MN_RESI"].dropna().astype(str).str.len().value_counts()
        default_mode = default_lens.idxmax()

        ok = false_mode == 6 and default_mode == 7
        evidence = (
            f"add_dv=False ID_MN_RESI length value_counts:\n"
            f"{false_lens.to_string()}\n"
            f"    default (add_dv omitted) ID_MN_RESI length value_counts:\n"
            f"{default_lens.to_string()}\n"
            f"    predominant width: add_dv=False -> {false_mode}, default -> {default_mode}"
        )
        return ok, evidence
    except Exception as exc:
        return False, f"FAIL (network): {exc!r}"


def check_per_agravo_column_ownership(frames: dict) -> tuple[bool, str]:
    """Check 5: CLASSI_FIN/GRAV_* -> DENG/CHIK only; TP_ACIDENT/TRA_CLASSI -> ANIM only."""
    deng_cols = set(frames["DENG"].columns)
    chik_cols = set(frames["CHIK"].columns)
    anim_cols = set(frames["ANIM"].columns)

    classi_fin_ok = (
        "CLASSI_FIN" in deng_cols
        and "CLASSI_FIN" in chik_cols
        and "CLASSI_FIN" not in anim_cols
    )

    deng_grav_count = len([c for c in deng_cols if c.startswith("GRAV_")])
    chik_grav_count = len([c for c in chik_cols if c.startswith("GRAV_")])
    anim_grav_count = len([c for c in anim_cols if c.startswith("GRAV_")])
    grav_ok = deng_grav_count >= 15 and chik_grav_count >= 15 and anim_grav_count == 0

    anim_only_ok = (
        "TP_ACIDENT" in anim_cols
        and "TRA_CLASSI" in anim_cols
        and "TP_ACIDENT" not in deng_cols
        and "TP_ACIDENT" not in chik_cols
        and "TRA_CLASSI" not in deng_cols
        and "TRA_CLASSI" not in chik_cols
    )

    ok = classi_fin_ok and grav_ok and anim_only_ok
    evidence = (
        f"DENG rows={len(frames['DENG'])} cols={len(deng_cols)}; "
        f"CHIK rows={len(frames['CHIK'])} cols={len(chik_cols)}; "
        f"ANIM rows={len(frames['ANIM'])} cols={len(anim_cols)}\n"
        f"    CLASSI_FIN in DENG&CHIK, absent from ANIM: {classi_fin_ok}\n"
        f"    GRAV_* counts: DENG={deng_grav_count} CHIK={chik_grav_count} ANIM={anim_grav_count} "
        f"(>=15 in DENG/CHIK, 0 in ANIM): {grav_ok}\n"
        f"    TP_ACIDENT/TRA_CLASSI in ANIM only: {anim_only_ok}"
    )
    return ok, evidence


def check_geography_and_identity_columns(frames: dict) -> tuple[bool, str]:
    """Check 6: geography/identity columns present and ID_MN_RESI != ID_MUNICIP on real rows.

    Also reports (informational, not part of PASS) whether NU_NOTIFIC exists
    per agravo and whether its values are unique -- input to the
    numero_notificacao design.
    """
    all_ok = True
    lines = []
    for disease, df in frames.items():
        cols = set(df.columns)
        has_all = all(col in cols for col in GEOGRAPHY_IDENTITY_COLUMNS)
        differs = False
        if "ID_MN_RESI" in cols and "ID_MUNICIP" in cols:
            differs = bool((df["ID_MN_RESI"].astype(str) != df["ID_MUNICIP"].astype(str)).any())
        disease_ok = has_all and differs
        all_ok = all_ok and disease_ok

        nu_notific_line = f"NU_NOTIFIC not present in {disease}"
        if "NU_NOTIFIC" in cols:
            non_null = int(df["NU_NOTIFIC"].notna().sum())
            is_unique = df["NU_NOTIFIC"].dropna().is_unique
            nu_notific_line = (
                f"NU_NOTIFIC present in {disease}: non_null={non_null}, "
                f"unique={is_unique}"
            )

        lines.append(
            f"{disease}: has_all_geo_identity_cols={has_all}, "
            f"ID_MN_RESI differs from ID_MUNICIP on >=1 row={differs} -- {nu_notific_line}"
        )

    evidence = "\n    ".join(lines)
    return all_ok, evidence


def check_no_pii_columns(frames: dict) -> tuple[bool, str]:
    """Check 7: no patient-identifying column reaches the ingestion path."""
    found = {}
    for disease, df in frames.items():
        cols = set(df.columns)
        hits = [c for c in PII_COLUMN_DENYLIST if c in cols]
        if hits:
            found[disease] = hits

    ok = len(found) == 0
    evidence = (
        f"denylist checked: {PII_COLUMN_DENYLIST}\n"
        f"    matches found per agravo: {found if found else 'none'}"
    )
    return ok, evidence


def check_code_value_distributions(frames: dict) -> tuple[bool, str]:
    """Check 8: informational-but-asserting value_counts for key coded columns."""
    lines = []
    all_have_values = True

    for disease, df in frames.items():
        for col in ("NU_IDADE_N", "CS_SEXO"):
            if col not in df.columns:
                lines.append(f"{disease}.{col}: column absent")
                all_have_values = False
                continue
            vc = df[col].value_counts(dropna=False).head(15)
            has_values = vc.sum() > 0
            all_have_values = all_have_values and has_values
            lines.append(f"{disease}.{col} value_counts (top 15):\n{vc.to_string()}")

    per_agravo_col = {"DENG": "CLASSI_FIN", "CHIK": "CLASSI_FIN", "ANIM": "TRA_CLASSI"}
    for disease, col in per_agravo_col.items():
        df = frames[disease]
        if col not in df.columns:
            lines.append(f"{disease}.{col}: column absent")
            all_have_values = False
            continue
        vc = df[col].value_counts(dropna=False).head(15)
        has_values = vc.sum() > 0
        all_have_values = all_have_values and has_values
        empty_count = int((df[col].astype(str) == "").sum())
        literal_none_count = int((df[col].astype(str) == "None").sum())
        lines.append(
            f"{disease}.{col} value_counts (top 15):\n{vc.to_string()}\n"
            f"    empty-string count: {empty_count}, literal 'None'-string count: {literal_none_count}"
        )

    if "ANIM" in frames and "TP_ACIDENT" in frames["ANIM"].columns:
        vc = frames["ANIM"]["TP_ACIDENT"].value_counts(dropna=False).head(15)
        has_values = vc.sum() > 0
        all_have_values = all_have_values and has_values
        lines.append(f"ANIM.TP_ACIDENT value_counts (top 15):\n{vc.to_string()}")
    else:
        lines.append("ANIM.TP_ACIDENT: column absent")
        all_have_values = False

    evidence = "\n    ".join(lines)
    return all_have_values, evidence


def run_spike(args: argparse.Namespace) -> int:
    results: list[tuple[str, bool, str]] = []

    ok, evidence = check_versions()
    results.append(("1. Versions", ok, evidence))

    ok, evidence = check_sinan_no_state_param()
    results.append(("2. sinan() has no state= param", ok, evidence))

    # Fetch each (disease, year) frame at most once per run and share across
    # checks 3-8. DENG 2023 alone is ~3.3M rows -- must not re-download.
    frames: dict[str, pd.DataFrame] = {}
    fetch_years = {
        "DENG": args.deng_ano,
        "CHIK": args.chik_ano,
        "ANIM": args.anim_ano,
    }
    fetch_error: Exception | None = None
    for disease, ano in fetch_years.items():
        if disease in frames:
            continue
        try:
            frames[disease] = pysus.sinan(
                disease=disease,
                year=ano,
                as_dataframe=True,
                show_progress=False,
                add_dv=False,
            )
        except Exception as exc:
            fetch_error = exc
            break

    probe_disease = args.state_probe_disease
    probe_ano = args.state_probe_ano

    if fetch_error is not None:
        results.append(("3. state= kwarg behavior", False, f"FAIL (network): {fetch_error!r}"))
        results.append(("4. add_dv digit width", False, "skipped: frame fetch failed"))
        results.append(("5. Per-agravo column ownership", False, "skipped: frame fetch failed"))
        results.append(("6. Geography/identity columns", False, "skipped: frame fetch failed"))
        results.append(("7. No PII columns", False, "skipped: frame fetch failed"))
        results.append(("8. Code value distributions", False, "skipped: frame fetch failed"))
    else:
        # The probe disease/year is reused from the already-fetched frames
        # whenever it matches one of DENG/CHIK/ANIM's configured years
        # (true by default: ANIM 2023 == args.anim_ano's default) to avoid
        # a second download; otherwise fetch the probe frame separately.
        if probe_disease in frames and probe_ano == fetch_years.get(probe_disease):
            probe_frame = frames[probe_disease]
        else:
            probe_frame = None
            try:
                probe_frame = pysus.sinan(
                    disease=probe_disease,
                    year=probe_ano,
                    as_dataframe=True,
                    show_progress=False,
                    add_dv=False,
                )
            except Exception as exc:
                results.append(
                    ("3. state= kwarg behavior", False, f"FAIL (network, could not fetch unscoped baseline): {exc!r}")
                )

        if probe_frame is not None:
            n_unscoped = len(probe_frame)
            n_uf35 = int((probe_frame["SG_UF"].astype(str) == "35").sum())
            try:
                scoped = pysus.sinan(
                    disease=probe_disease,
                    year=probe_ano,
                    state="SP",
                    as_dataframe=True,
                    show_progress=False,
                    add_dv=False,
                )
                n_scoped = len(scoped)
                outcome = f"returned {n_scoped} rows"
                ok = n_scoped == 0 or n_scoped == n_unscoped
            except Exception as exc:
                outcome = f"raised {exc!r}"
                ok = True
            evidence = (
                f"n_unscoped={n_unscoped} n_uf35={n_uf35} "
                f"state='SP' outcome: {outcome} -- PASS condition (raises, zero rows, "
                f"or equals n_unscoped): {ok}"
            )
            results.append(("3. state= kwarg behavior", ok, evidence))

        probe_frames_for_digit_width = (
            frames if probe_disease in frames else {probe_disease: probe_frame}
        )
        ok, evidence = check_add_dv_digit_width(probe_disease, probe_ano, probe_frames_for_digit_width)
        results.append(("4. add_dv digit width", ok, evidence))

        ok, evidence = check_per_agravo_column_ownership(frames)
        results.append(("5. Per-agravo column ownership", ok, evidence))

        ok, evidence = check_geography_and_identity_columns(frames)
        results.append(("6. Geography/identity columns", ok, evidence))

        ok, evidence = check_no_pii_columns(frames)
        results.append(("7. No PII columns", ok, evidence))

        ok, evidence = check_code_value_distributions(frames)
        results.append(("8. Code value distributions", ok, evidence))

    print("=" * 70)
    print("pysus 2.7.0 SINAN verification spike -- results")
    print("=" * 70)
    failures = []
    for name, ok, evidence in results:
        verdict = "PASS" if ok else "FAIL"
        if not ok:
            failures.append(name)
        print(f"\n[{verdict}] {name}")
        print(f"    {evidence}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, ok, _ in results:
        print(f"  {'PASS' if ok else 'FAIL'} -- {name}")

    if failures:
        print(f"\n{len(failures)} check(s) FAILED: {failures}")
        return 1

    print("\nAll checks PASSED.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verification spike: prove the real pysus 2.7.0 SINAN API surface live."
    )
    parser.add_argument("--deng-ano", type=int, default=2023, help="DENG year to query (default: 2023)")
    parser.add_argument("--chik-ano", type=int, default=2023, help="CHIK year to query (default: 2023)")
    parser.add_argument("--anim-ano", type=int, default=2023, help="ANIM year to query (default: 2023)")
    parser.add_argument(
        "--state-probe-disease",
        default="ANIM",
        help="Disease used for the state= kwarg probe (default: ANIM, cheapest frame)",
    )
    parser.add_argument(
        "--state-probe-ano",
        type=int,
        default=2023,
        help="Year used for the state= kwarg probe (default: 2023)",
    )
    args = parser.parse_args()
    return run_spike(args)


if __name__ == "__main__":
    sys.exit(main())
