"""Scan the pysus cloud catalog for all available SIM files across 27 UFs × 2010-2023.

Prints a summary grid and writes available_sim.txt for pipeline input.
"""
import asyncio
from pysus.api.client import PySUS

UFS = [
    'AC','AL','AM','AP','BA','CE','DF','ES','GO',
    'MA','MG','MS','MT','PA','PB','PE','PI','PR',
    'RJ','RN','RO','RR','RS','SC','SE','SP','TO'
]
YEARS = list(range(2010, 2024))


async def scan():
    available = {}
    async with PySUS() as client:
        for uf in UFS:
            available[uf] = []
            for year in YEARS:
                files = await client.query(dataset="sim", state=uf, year=year)
                if files:
                    available[uf].append(year)

    # Print grid
    print(f"{'UF':4s}", end="")
    for y in YEARS:
        print(f" {y}", end="")
    print()
    for uf in UFS:
        print(f"{uf:4s}", end="")
        for y in YEARS:
            print(f"  {'Y' if y in available[uf] else '.'}", end="")
        print(f"  ({len(available[uf])} years)")

    # Summary
    pairs = [(uf, y) for uf in UFS for y in available[uf]]
    print(f"\nTotal available: {len(pairs)} UF×year pairs")

    # Write to file for pipeline input
    with open("available_sim.txt", "w") as f:
        for uf, y in pairs:
            f.write(f"{uf},{y}\n")
    print("Written: available_sim.txt")

    return available


if __name__ == "__main__":
    asyncio.run(scan())
