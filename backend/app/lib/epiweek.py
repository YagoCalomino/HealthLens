"""Epidemiological-week helper.

DataSUS/SINAN's "semana epidemiológica" (SE) follows the CDC/MMWR
Sunday-anchored convention, which diverges from Python stdlib's
`date.isocalendar()` (ISO 8601, Monday-anchored) at year boundaries — a
January date can belong to the *previous* epidemiological year (e.g.
2021-01-01 is SE 53/2020, not week 1 of 2021) and a late-December date can
belong to the *next* one. Hand-rolled day-count-divided-by-seven arithmetic
is explicitly rejected because these
boundary cases are exactly the class of off-by-one bug such arithmetic gets
subtly wrong.

This module trusts the `epiweeks` library (PyPI, `dralshehri/epiweeks`,
zero dependencies) for the CDC/MMWR math. The library's *convention* is
proven to actually match the published Brazilian MS/SVS SE calendar by
`backend/tests/test_epiweek_calendario_datasus.py` — that file is the
authority; this module is not free to change conventions (e.g. the
`system=` argument) without that test going red.
"""

from datetime import date

from epiweeks import Week


def semana_epidemiologica(dt: date) -> tuple[int, int]:
    """Return (ano_epidemiologico, semana_epidemiologica) for a given date.

    Accepts both `date` and `datetime` (the time component is ignored by
    `epiweeks.Week.fromdate`). Uses the CDC/MMWR Sunday-start system
    explicitly — it is the library default, but the
    convention is documented in code on purpose, not implied.
    """
    w = Week.fromdate(dt, system="cdc")
    return w.year, w.week


def epi_weeks_no_intervalo(inicio: date, fim: date) -> list[tuple[int, int]]:
    """Return the ordered, de-duplicated (ano_epi, semana_epi) pairs
    spanning [inicio, fim], inclusive.

    The epidemic-curve endpoint needs this to emit zero-count weeks rather
    than a gapped series — the caller iterates this list and fills in a
    zero for any (ano_epi, semana_epi) missing from the aggregated query
    result.
    """
    if fim < inicio:
        inicio, fim = fim, inicio

    pares: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    semana_atual = Week.fromdate(inicio, system="cdc")
    semana_fim = Week.fromdate(fim, system="cdc")

    while True:
        par = (semana_atual.year, semana_atual.week)
        if par not in seen:
            seen.add(par)
            pares.append(par)
        if semana_atual == semana_fim:
            break
        semana_atual = semana_atual + 1

    return pares
