"""Build the real-data extract used by the analysis notebooks.

Aggregates SIM death records (by residence) for SP, RJ and MG, 2015-2022, down
to município x ano x capítulo CID-10 x sexo x faixa etária. Aggregating keeps
the file small enough to track in git while preserving exact counts, so every
rate the notebooks compute matches what the full records would give.

Each row also carries the município's TCU population for that year and
`taxa_mortalidade` = obitos / populacao * 100000. Because the denominator is
the whole município, summing `taxa_mortalidade` over the rows of a município and
year gives its overall rate. Rows whose município has no TCU estimate (e.g. the
"ignored município" codes ending in 0000) keep NULL population and rate.

The extract only feeds notebooks/. data/sample/ stays synthetic: it is the
fixture for SAMPLE_MODE, the tests and the CI query budgets.

Usage:
    python scripts/build_notebook_extract.py

Raw files are read from data/raw/SIM_{UF}_{ANO}.parquet and downloaded through
the regular ingestor when missing.
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from etl.ingestor import get_or_download_sim  # noqa: E402

UFS = {"SP": "35", "RJ": "33", "MG": "31"}
ANOS = range(2015, 2023)
RAW_DIR = REPO_ROOT / "data" / "raw"
POP_CSV = REPO_ROOT / "backend" / "seeds" / "data" / "tcu_populacao.csv"
OUT_PATH = REPO_ROOT / "data" / "notebooks" / "sim_agregado.parquet"

# SIM IDADE: first digit is the unit. 0-3 = minutes/hours/days/months (under
# one year), 4 = years, 5 = 100 + years, 9 = unknown.
AGGREGATE_SQL = """
WITH obitos AS (
    SELECT
        CODMUNRES                                   AS codigo_ibge_6,
        CAST(RIGHT(DTOBITO, 4) AS INTEGER)          AS ano,
        UPPER(SUBSTRING(CAUSABAS, 1, 1))            AS capitulo_cid,
        CASE SEXO WHEN '1' THEN 'M' WHEN '2' THEN 'F' ELSE 'I' END AS sexo,
        CASE
            WHEN SUBSTRING(IDADE, 1, 1) IN ('0', '1', '2', '3') THEN 0
            WHEN SUBSTRING(IDADE, 1, 1) = '4' THEN TRY_CAST(SUBSTRING(IDADE, 2) AS INTEGER)
            WHEN SUBSTRING(IDADE, 1, 1) = '5' THEN 100 + TRY_CAST(SUBSTRING(IDADE, 2) AS INTEGER)
        END                                          AS idade_anos
    FROM read_parquet($files)
    WHERE LENGTH(DTOBITO) = 8
      AND SUBSTRING(CODMUNRES, 1, 2) IN (SELECT codigo_uf FROM ufs)
),
agregado AS (
SELECT
    codigo_ibge_6,
    ano,
    capitulo_cid,
    sexo,
    CASE
        WHEN idade_anos IS NULL THEN 'Ignorada'
        WHEN idade_anos >= 100 THEN '100+'
        ELSE CAST(idade_anos // 10 * 10 AS VARCHAR) || '-' || CAST(idade_anos // 10 * 10 + 9 AS VARCHAR)
    END                                              AS faixa_etaria,
    COUNT(*)::INTEGER                                AS obitos
FROM obitos
WHERE ano BETWEEN 2015 AND 2022
GROUP BY ALL
)
SELECT
    a.codigo_ibge_6                                  AS municipio_codigo,
    u.sigla_uf,
    a.ano,
    a.capitulo_cid,
    a.sexo,
    a.faixa_etaria,
    a.obitos,
    p.populacao_total                                AS populacao,
    a.obitos * 100000.0 / p.populacao_total          AS taxa_mortalidade
FROM agregado a
JOIN ufs u ON u.codigo_uf = SUBSTRING(a.codigo_ibge_6, 1, 2)
LEFT JOIN populacao p ON p.codigo_ibge_6 = a.codigo_ibge_6 AND p.ano = a.ano
ORDER BY municipio_codigo, a.ano, a.capitulo_cid, a.sexo, a.faixa_etaria
"""


def main() -> int:
    files = []
    for uf in UFS:
        for ano in ANOS:
            result = get_or_download_sim(uf, ano, RAW_DIR)
            if result is None:
                print(
                    f"SIM {uf} {ano} unavailable; aborting so the extract is never partial"
                )
                return 1
            files.append(str(result[0]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register(
        "ufs", pd.DataFrame({"sigla_uf": list(UFS), "codigo_uf": list(UFS.values())})
    )
    # pandas, not read_csv: DuckDB's sniffer trips on the em-dash in the header comment
    populacao = pd.read_csv(
        POP_CSV,
        skiprows=1,
        dtype={"codigo_ibge_6": str, "ano": int, "populacao_total": int},
    )
    con.register("populacao", populacao)
    con.execute(
        f"COPY ({AGGREGATE_SQL}) TO '{OUT_PATH.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)",
        {"files": files},
    )
    linhas, obitos = con.execute(
        "SELECT COUNT(*), SUM(obitos) FROM read_parquet(?)", [str(OUT_PATH)]
    ).fetchone()
    print(f"{OUT_PATH.relative_to(REPO_ROOT)}: {linhas:,} rows, {obitos:,} deaths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
