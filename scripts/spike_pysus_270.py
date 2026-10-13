"""Verification spike: prove the real pysus 2.7.0 API surface live.

Re-runnable, self-contained (stdlib + pysus + pandas only, no project imports,
mirrors validate_env.py's zero-project-import convention). Runs six numbered
checks against live DataSUS data and prints PASS/FAIL plus observed evidence
for each. Exit code 0 only if all mandatory checks pass.

Defaults use small UFs (AC, SE) to keep the live download modest -- never SP.
"""
import argparse
import asyncio
import inspect
import sys

import pandas as pd
import pysus
from pysus.api.client import PySUS


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


def check_as_dataframe_signature() -> tuple[bool, str]:
    """Check 2: as_dataframe defaults to False.

    NOTE (live-discovered correction vs. plan assumption): sim()/sih() do NOT
    declare as_dataframe as a named parameter directly -- they declare
    **kwargs and forward it to the internal _fetch_data() helper, where it
    IS a named parameter defaulting to False. inspect.signature(pysus.sim)
    therefore has no "as_dataframe" key. We inspect _fetch_data directly
    (the actual source of the default) and print both convenience-function
    and internal signatures for full transparency.
    """
    sig_sim = inspect.signature(pysus.sim)
    sig_sih = inspect.signature(pysus.sih)

    lines = [f"pysus.sim{sig_sim}", f"pysus.sih{sig_sih}"]

    sim_has_kwarg = "as_dataframe" not in sig_sim.parameters
    sih_has_kwarg = "as_dataframe" not in sig_sih.parameters
    lines.append(
        f"as_dataframe NOT a direct sim() param (forwarded via **kwargs): {sim_has_kwarg}"
    )
    lines.append(
        f"as_dataframe NOT a direct sih() param (forwarded via **kwargs): {sih_has_kwarg}"
    )

    try:
        from pysus.api._impl.databases import _fetch_data

        sig_fetch = inspect.signature(_fetch_data)
        default_is_false = sig_fetch.parameters["as_dataframe"].default is False
        lines.append(f"pysus.api._impl.databases._fetch_data{sig_fetch}")
        lines.append(
            f"_fetch_data's as_dataframe default is False: {default_is_false}"
        )
        ok = sim_has_kwarg and sih_has_kwarg and default_is_false
    except (ImportError, KeyError) as exc:
        lines.append(f"could not introspect _fetch_data: {exc}")
        ok = False

    return ok, "\n    ".join(lines)


def check_sim_return_type(sim_uf: str, sim_ano: int) -> tuple[bool, str]:
    """Check 3: sim() returns list[str] by default, DataFrame with as_dataframe=True."""
    try:
        paths = pysus.sim(state=sim_uf, year=sim_ano)
        is_list = isinstance(paths, list)

        df = pysus.sim(state=sim_uf, year=sim_ano, as_dataframe=True, show_progress=False)
        is_df = isinstance(df, pd.DataFrame)
        n_rows = len(df) if is_df else -1
        has_rows = n_rows > 0

        evidence = (
            f"sim() (default) -> {type(paths).__name__} (is list: {is_list}); "
            f"sim(as_dataframe=True) -> {type(df).__name__} (is DataFrame: {is_df}), "
            f"row count: {n_rows}"
        )
        return (is_list and is_df and has_rows), evidence
    except Exception as exc:
        return False, f"FAIL (network): {exc!r}"


def check_group_rd_broken(sih_uf: str, sih_ano: int) -> tuple[bool, str]:
    """Check 4: sih(..., group="RD") returns no data -- proving the DuckLake bug exists.

    This check PASSES when zero rows come back: it is proving the bug is real,
    not testing for correct behavior.
    """
    try:
        result = pysus.sih(
            state=sih_uf,
            year=sih_ano,
            month=[1],
            group="RD",
            as_dataframe=True,
            show_progress=False,
        )
        is_none = result is None
        is_empty = hasattr(result, "__len__") and len(result) == 0
        no_data = is_none or is_empty
        evidence = (
            f"sih(..., group='RD') -> {type(result).__name__}, "
            f"len={len(result) if hasattr(result, '__len__') else 'n/a'} "
            f"(no-data outcome confirms the bug: {no_data})"
        )
        return no_data, evidence
    except Exception as exc:
        # An exception is also an acceptable "no data" outcome for this check.
        return True, f"sih(..., group='RD') raised (also confirms no data): {exc!r}"


async def _fetch_rd_and_rj(sih_uf: str, sih_ano: int):
    """Low-level query + filename-prefix filter + download + read_parquet.

    WHY the low-level client instead of sih(group="RD"): the top-level group=
    filter is broken under 2.7.0's DuckLake catalog (Check 4 proves this) --
    the only reliable way to isolate SIH-RD (AIH Reduzida) files is to query
    without group=, then filter the returned file list by filename prefix
    ("RD" is the first two characters of every AIH Reduzida filename).
    """
    async with PySUS() as client:
        files = await client.query(
            dataset="sih", state=sih_uf, year=sih_ano, month=list(range(1, 13))
        )
        prefixes = sorted({f.path.name[:2].upper() for f in files})

        rd_files = [f for f in files if f.path.name.upper().startswith("RD")]
        rj_files = [f for f in files if f.path.name.upper().startswith("RJ")]

        rd_df = None
        if rd_files:
            first_rd = rd_files[0]
            local_path = (await client.download(first_rd)).path
            # add_dv=False: MUNIC_RES is not in pysus's own geocode-prefix
            # list, so add_dv is a no-op for this field either way -- set
            # explicitly False to keep dim_local's own codigo_ibge_7
            # computation (seeds/ibge_loader.py) as the single source of
            # truth, not relying on that no-op remaining permanently true.
            rd_df = client.read_parquet([local_path], add_dv=False).df()

        rj_df = None
        if rj_files:
            first_rj = rj_files[0]
            local_rj_path = (await client.download(first_rj)).path
            rj_df = client.read_parquet([local_rj_path], add_dv=False).df()

        return prefixes, rd_df, rj_df


def run_spike(args: argparse.Namespace) -> int:
    results: list[tuple[str, bool, str]] = []

    ok, evidence = check_versions()
    results.append(("1. Versions", ok, evidence))

    ok, evidence = check_as_dataframe_signature()
    results.append(("2. as_dataframe signature", ok, evidence))

    ok, evidence = check_sim_return_type(args.sim_uf, args.sim_ano)
    results.append(("3. SIM return type", ok, evidence))

    ok, evidence = check_group_rd_broken(args.sih_uf, args.sih_ano)
    results.append(('4. group="RD" is broken', ok, evidence))

    # Checks 5 and 6 share one asyncio.run() call for the low-level client work.
    try:
        prefixes, rd_df, rj_df = asyncio.run(_fetch_rd_and_rj(args.sih_uf, args.sih_ano))

        has_rd = any(p.startswith("RD") for p in prefixes)
        ok5 = has_rd and rd_df is not None
        evidence5 = (
            f"observed filename prefixes: {prefixes}; "
            f"RD file found and downloaded: {rd_df is not None}"
        )
        results.append(("5. Filename-prefix filtering", ok5, evidence5))

        if rd_df is not None:
            has_ident = "IDENT" in rd_df.columns
            no_sp_tipo = "SP_TIPO" not in rd_df.columns
            ident_numeric = pd.to_numeric(rd_df["IDENT"], errors="coerce") if has_ident else pd.Series(dtype=float)
            ident_eq_1_count = int((ident_numeric == 1).sum()) if has_ident else 0
            ok6 = has_ident and no_sp_tipo and ident_eq_1_count > 0

            evidence6_lines = [
                f"IDENT in columns: {has_ident}",
                f"SP_TIPO not in columns: {no_sp_tipo}",
                f"column count: {len(rd_df.columns)}",
            ]
            if has_ident:
                evidence6_lines.append(
                    f"IDENT value_counts:\n{ident_numeric.value_counts(dropna=False).to_string()}"
                )

            if rj_df is not None and "IDENT" in rj_df.columns:
                rj_ident = pd.to_numeric(rj_df["IDENT"], errors="coerce")
                rj_frac = float((rj_ident == 1).mean())
                evidence6_lines.append(
                    f"RJ file row count: {len(rj_df)}, fraction with IDENT==1: {rj_frac:.4f} "
                    "(evidence that IDENT alone cannot discriminate RD from RJ)"
                )
            else:
                evidence6_lines.append(
                    "no RJ-prefixed file captured in this run (non-fatal, best-effort)"
                )

            results.append(("6. IDENT reconfirmation", ok6, "\n    ".join(evidence6_lines)))
        else:
            results.append(("6. IDENT reconfirmation", False, "no RD file downloaded in check 5"))
    except Exception as exc:
        results.append(("5. Filename-prefix filtering", False, f"FAIL (network): {exc!r}"))
        results.append(("6. IDENT reconfirmation", False, f"FAIL (network): {exc!r}"))

    print("=" * 70)
    print("pysus 2.7.0 verification spike -- results")
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
        description="Verification spike: prove the real pysus 2.7.0 API surface live."
    )
    parser.add_argument("--sim-uf", default="AC", help="SIM state to query (default: AC)")
    parser.add_argument("--sim-ano", type=int, default=2022, help="SIM year to query (default: 2022)")
    parser.add_argument("--sih-uf", default="SE", help="SIH state to query (default: SE)")
    parser.add_argument("--sih-ano", type=int, default=2023, help="SIH year to query (default: 2023)")
    args = parser.parse_args()
    return run_spike(args)


if __name__ == "__main__":
    sys.exit(main())
