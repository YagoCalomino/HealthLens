"""Scan the pysus cloud catalog for SIH-RD file availability across 27 UFs x 2010-2024.

Prints a summary grid (month count per UF/ano) and writes available_sih.txt for
allowlist/completeness-assertion input.

RD (AIH Reduzida) is the only group loaded into fato_internacoes -- SP (Servicos
Profissionais), RJ (AIH Rejeitada) and ER files are deliberately excluded from the
availability count. A UF-ano whose catalog holds only SP/RJ/ER files is NOT
available for this pipeline's purposes.

A combo absent from this scan's output is a legitimate scripts/sih_year_allowlist.yaml
candidate (with a dated comment). A combo present here but missing from
fato_internacoes is a pipeline bug, not an allowlist candidate.
"""
import argparse
import asyncio
from pysus.api.client import PySUS

UFS = [
    'AC','AL','AM','AP','BA','CE','DF','ES','GO',
    'MA','MG','MS','MT','PA','PB','PE','PI','PR',
    'RJ','RN','RO','RR','RS','SC','SE','SP','TO'
]
YEARS = list(range(2010, 2025))


def _parse_list(value, valid, label):
    if value is None:
        return valid
    items = [v.strip().upper() if isinstance(valid[0], str) else int(v.strip()) for v in value.split(",")]
    unknown = [v for v in items if v not in valid]
    if unknown:
        raise SystemExit(f"Unknown {label}: {unknown}")
    return items


async def scan(ufs=None, years=None):
    ufs = ufs or UFS
    years = years or YEARS

    available = {}
    async with PySUS() as client:
        for uf in ufs:
            available[uf] = {}
            for year in years:
                try:
                    files = await client.query(dataset="sih", state=uf, year=year)
                except Exception as exc:  # noqa: BLE001 -- keep scanning the other 404 combos
                    available[uf][year] = None
                    print(f"  ! query error for {uf}/{year}: {exc}")
                    continue
                rd_files = [f for f in files if f.path.name.upper().startswith("RD")]
                available[uf][year] = len(rd_files)

    # Print grid: month count per (uf, ano), '.' for none, '?' for query error
    print(f"{'UF':4s}", end="")
    for y in years:
        print(f" {y}", end="")
    print()
    for uf in ufs:
        print(f"{uf:4s}", end="")
        n_years_available = 0
        for y in years:
            n = available[uf][y]
            if n is None:
                cell = "?"
            elif n == 0:
                cell = "."
            else:
                cell = str(n)
                n_years_available += 1
            print(f"  {cell:>2s}", end="")
        print(f"  ({n_years_available} years)")

    # Summary
    pairs = [(uf, y, available[uf][y]) for uf in ufs for y in years if available[uf][y]]
    total_combos = len(ufs) * len(years)
    print(f"\nTotal available: {len(pairs)} / {total_combos} UF x ano combos have at least one RD file")
    print(
        "Any combo absent above is a legitimate scripts/sih_year_allowlist.yaml candidate "
        "(add a dated comment). A combo present here but missing from fato_internacoes "
        "is a pipeline bug, not an allowlist candidate."
    )

    # Write to file for pipeline/allowlist input
    with open("available_sih.txt", "w") as f:
        for uf, y, n_meses in pairs:
            f.write(f"{uf},{y},{n_meses}\n")
    print("Written: available_sih.txt")

    return available


def _build_argparser():
    parser = argparse.ArgumentParser(
        description="Scan the pysus DuckLake catalog for SIH-RD file availability per (UF, ano)."
    )
    parser.add_argument(
        "--uf",
        help="Comma-separated list of UF codes to scan (default: all 27 UFs).",
        default=None,
    )
    parser.add_argument(
        "--ano",
        help="Comma-separated list of years to scan (default: 2010-2024).",
        default=None,
    )
    return parser


if __name__ == "__main__":
    args = _build_argparser().parse_args()
    ufs = _parse_list(args.uf, UFS, "--uf")
    years = _parse_list(args.ano, YEARS, "--ano")
    asyncio.run(scan(ufs=ufs, years=years))
