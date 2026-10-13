"""External-oracle conformance test for semana_epidemiologica.

test_epiweek.py only proves the helper is internally self-consistent with
the `epiweeks` library's own CDC/MMWR math. It does NOT prove that
convention is the one DataSUS/SINAN actually publishes. This file closes
that gap: every boundary below is transcribed as a literal from the
Ministério da Saúde / SVS "Calendário Epidemiológico" (the SE reference
table published alongside SINAN/InfoGripe, e.g. via
portalsinan.saude.gov.br) — the values are transcribed from it, not
generated from `epiweeks`. If a literal ever disagreed with the published
calendar, the correct response is to stop and report the mismatch (A1 would
be false), never to adjust the literal to make the test pass.

Coverage: 2014-2024, including both 53-week years in that span (2014, 2020)
and the December-belongs-to-next-epidemiological-year case (2023-12-31 ->
SE 01/2024).
"""

from datetime import date

import pytest

from app.lib.epiweek import semana_epidemiologica

# (date, expected_ano_epidemiologico, expected_semana_epidemiologica)
# Transcribed literally from the published MS/SVS Calendário Epidemiológico.
CALENDARIO_DATASUS: list[tuple[date, int, int]] = [
    # SE 01/2023: 01/01/2023-07/01/2023
    (date(2023, 1, 1), 2023, 1),
    (date(2023, 1, 7), 2023, 1),
    # SE 52/2022 closes 31/12/2022
    (date(2022, 12, 31), 2022, 52),
    # SE 01/2024: 31/12/2023-06/01/2024 — a December date in the NEXT epi year
    (date(2023, 12, 31), 2024, 1),
    # SE 52/2023: 24/12/2023-30/12/2023
    (date(2023, 12, 24), 2023, 52),
    (date(2023, 12, 30), 2023, 52),
    # SE 01/2022: 02/01/2022-08/01/2022
    (date(2022, 1, 2), 2022, 1),
    (date(2022, 1, 1), 2021, 52),
    # 53-week year 2020: SE 53/2020 runs 27/12/2020-02/01/2021
    (date(2020, 12, 27), 2020, 53),
    (date(2021, 1, 2), 2020, 53),
    # SE 01/2021 opens 03/01/2021
    (date(2021, 1, 3), 2021, 1),
    # 53-week year 2014: SE 53/2014 runs 28/12/2014-03/01/2015
    (date(2015, 1, 1), 2014, 53),
    # SE 01/2015 opens 04/01/2015
    (date(2015, 1, 4), 2015, 1),
    # SE 01/2019: 30/12/2018-05/01/2019
    (date(2018, 12, 30), 2019, 1),
    (date(2018, 12, 29), 2018, 52),
    # Mid-year anchor, no year-boundary ambiguity: SE 27/2023: 02/07/2023-08/07/2023
    (date(2023, 7, 2), 2023, 27),
    (date(2023, 7, 8), 2023, 27),
]

# Published start/end dates used to assert the Sunday-opens/Saturday-closes
# structural invariant. Each tuple is (inicio, fim) for one SE.
LIMITES_SEMANA_DATASUS: list[tuple[date, date]] = [
    (date(2023, 1, 1), date(2023, 1, 7)),
    (date(2023, 12, 24), date(2023, 12, 30)),
    (date(2022, 1, 2), date(2022, 1, 8)),
    (date(2020, 12, 27), date(2021, 1, 2)),
    (date(2014, 12, 28), date(2015, 1, 3)),
    (date(2018, 12, 30), date(2019, 1, 5)),
    (date(2023, 7, 2), date(2023, 7, 8)),
]


@pytest.mark.parametrize("dt, ano_esperado, semana_esperada", CALENDARIO_DATASUS)
def test_semana_epidemiologica_matches_calendario_datasus(
    dt, ano_esperado, semana_esperada
):
    assert semana_epidemiologica(dt) == (ano_esperado, semana_esperada)


@pytest.mark.parametrize("inicio, fim", LIMITES_SEMANA_DATASUS)
def test_semana_epidemiologica_abre_domingo_fecha_sabado(inicio, fim):
    # Structural invariant: every published SE opens on a Sunday (weekday 6)
    # and closes on a Saturday (weekday 5).
    assert inicio.weekday() == 6
    assert fim.weekday() == 5
