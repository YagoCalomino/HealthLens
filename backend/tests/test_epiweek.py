"""Self-consistency tests for the semana_epidemiologica helper.

These tests assert the helper is internally consistent (correct tuple shape,
never returns week 0 or > 53, handles datetime vs. date, and gets the
known year-boundary cases right). The *external*
proof that this convention actually matches the published DataSUS/SVS SE
calendar lives in test_epiweek_calendario_datasus.py, not here.
"""

from datetime import date, datetime

import pytest

from app.lib.epiweek import epi_weeks_no_intervalo, semana_epidemiologica


def test_returns_tuple_of_two_ints():
    result = semana_epidemiologica(date(2023, 1, 15))
    assert isinstance(result, tuple)
    assert len(result) == 2
    ano, semana = result
    assert isinstance(ano, int)
    assert isinstance(semana, int)


def test_jan_1_2023_opens_epi_week_1_of_2023():
    assert semana_epidemiologica(date(2023, 1, 1)) == (2023, 1)


def test_dec_31_2022_closes_epi_week_52_of_2022():
    assert semana_epidemiologica(date(2022, 12, 31)) == (2022, 52)


def test_jan_1_2021_belongs_to_epi_year_2020_week_53():
    assert semana_epidemiologica(date(2021, 1, 1)) == (2020, 53)


@pytest.mark.parametrize(
    "dt",
    [
        date(2023, 1, 1),
        date(2022, 12, 31),
        date(2021, 1, 1),
        date(2023, 6, 15),
    ],
)
def test_week_is_never_zero_or_greater_than_53(dt):
    _, semana = semana_epidemiologica(dt)
    assert 1 <= semana <= 53


def test_accepts_datetime_and_ignores_time_component():
    dt_date = date(2023, 6, 15)
    dt_datetime = datetime(2023, 6, 15, 13, 45, 30)
    assert semana_epidemiologica(dt_date) == semana_epidemiologica(dt_datetime)


def test_epi_weeks_no_intervalo_returns_ordered_deduplicated_pairs():
    pares = epi_weeks_no_intervalo(date(2023, 1, 1), date(2023, 1, 15))
    assert pares == sorted(set(pares), key=pares.index)
    assert (2023, 1) in pares
    assert len(pares) == len(set(pares))


def test_epi_weeks_no_intervalo_spans_year_boundary():
    pares = epi_weeks_no_intervalo(date(2020, 12, 20), date(2021, 1, 10))
    assert (2020, 52) in pares
    assert (2020, 53) in pares
    assert (2021, 1) in pares
