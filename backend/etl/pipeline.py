"""Main ETL pipeline orchestrator for HealthLens.

Entry point for loading DataSUS SIM (mortality), SIH (hospitalisation) and
SINAN (agravos de notificação) data into the PostgreSQL star schema. Supports
two modes:

- SAMPLE_MODE=true  : reads pre-committed Parquet files from data/sample/;
                      no FTP download, no full DB required. SINAN has no
                      sample fixture and is skipped entirely in this mode.
- SAMPLE_MODE=false : downloads raw data from DataSUS FTP. SIM and SIH are
                      processed per UF × year combination; SINAN has no UF
                      dimension (pysus.sinan() has no state= parameter) and
                      is processed per agravo × ano combination instead.

In both modes the DimCache is loaded once and reused for all files; materialized
views are refreshed at the end; and a TABNET cross-validation log entry is
written for the first UF × year in the run.
"""

import argparse
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg2

from etl import config
from etl.ingestor import get_or_download_sim, get_or_download_sih, get_or_download_sinan
from etl.mart.dim_lookup import DimCache
from etl.mart.internacoes_loader import load_internacoes
from etl.mart.notificacoes_loader import load_notificacoes
from etl.mart.obitos_loader import load_obitos
from etl.staging.sim_staging import stage_sim
from etl.staging.sih_staging import stage_sih
from etl.staging.sinan_staging import stage_sinan

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# SIH files for large UFs (e.g. SP) can carry ~2.8M rows; staging the whole
# DataFrame at once risks OOM, so SIH is staged/loaded in chunks.
SIH_CHUNK_SIZE = 200_000
SINAN_CHUNK_SIZE = 200_000


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def _already_loaded(conn, hash_md5: str) -> bool:
    """Return True when this file hash already exists in audit_ingestao."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM audit_ingestao WHERE hash_md5 = %s", (hash_md5,))
    result = cur.fetchone() is not None
    cur.close()
    return result


def _write_audit(
    conn, arquivo: str, hash_md5: str, uf: Optional[str], ano: int, fonte: str
) -> None:
    """Insert an audit record; ON CONFLICT DO NOTHING makes this idempotent.

    SINAN passes uf=None because pysus.sinan() downloads one national file
    per (agravo, ano) covering all 27 UFs — there is no UF-scoped download to
    attribute. This is legal only from migration 0019 onward,
    which dropped audit_ingestao.uf's NOT NULL constraint and widened the
    fonte CHECK to include 'SINAN'. The SQL itself is unchanged for all three
    sources — hash_md5 remains the resumability key regardless of fonte.
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit_ingestao (arquivo, hash_md5, uf, ano, fonte)"
        " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (hash_md5) DO NOTHING",
        (arquivo, hash_md5, uf, ano, fonte),
    )
    cur.close()


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_pipeline(
    ufs: list[str],
    anos: list[int],
    raw_dir: Path,
    conn,
    sim_only: bool = False,
    agravos: list[str] | None = None,
    sinan_only: bool = False,
    sih_only: bool = False,
) -> dict:
    """Execute the full ETL pipeline for the given UF × year combinations.

    Args:
        ufs:        List of two-letter UF codes (e.g. ["SP", "RJ"]).
        anos:       List of reference years (e.g. [2022, 2023]).
        raw_dir:    Directory for downloaded raw Parquet files (full mode only).
        conn:       Live psycopg2 connection with autocommit disabled.
        sim_only:   When True, skip SIH hospitalisation download and load.
        agravos:    List of SINAN agravo codes (e.g. ["DENG", "CHIK", "ANIM"]).
                    When None or empty, SINAN is not processed at all — the
                    default is inert so existing SIM/SIH-only callers are
                    unaffected. SINAN is processed at the (agravo, ano) grain,
                    never (agravo, UF): pysus.sinan() has no state= parameter.
        sinan_only: When True, skip SIM and SIH entirely and process only
                    SINAN agravos.
        sih_only:   When True, skip SIM mortality download and load. Lets SIH
                    run with a different year range than SIM (e.g. SIH 2025
                    is published before SIM 2025).

    Returns:
        Summary dict with keys: sim_files, sih_files, sim_rows, sih_rows,
        sim_skipped_loaded, sih_skipped_loaded, sim_skipped_absent,
        sih_skipped_absent, and four SINAN keys always present (0 when SINAN
        did not run): sinan_files, sinan_rows, sinan_skipped_loaded,
        sinan_skipped_absent.
    """
    # ------------------------------------------------------------------
    # 1. Load dimension cache once — reused for every file in this run
    # ------------------------------------------------------------------
    cache = DimCache()
    cache.load_all(conn)

    agravos = agravos or []

    sim_rows = 0
    sih_rows = 0
    sim_files = 0
    sih_files = 0
    sim_skipped_loaded = 0
    sim_skipped_absent = 0
    sih_skipped_loaded = 0
    sih_skipped_absent = 0
    sinan_rows = 0
    sinan_files = 0
    sinan_skipped_loaded = 0
    sinan_skipped_absent = 0

    # ------------------------------------------------------------------
    # 2. SAMPLE_MODE: load from pre-committed Parquet files
    # ------------------------------------------------------------------
    if config.SAMPLE_MODE:
        logger.info("SAMPLE_MODE=true — loading from sample Parquet files")

        # Replicate sample_loader.py path resolution: env var takes precedence;
        # otherwise anchor to repo root relative to this file's location.
        if os.environ.get("SAMPLE_DATA_DIR"):
            sample_dir = Path(config.SAMPLE_DATA_DIR)
        else:
            # backend/etl/pipeline.py → backend/etl → backend → repo root
            sample_dir = (
                Path(__file__).resolve().parent.parent.parent / "data" / "sample"
            )

        # --- SIM sample ---
        # audit_ingestao (CHAR(2) uf, hash dedup, TABNET cross-validation) is
        # only meaningful for real DataSUS downloads; skip it entirely in sample
        # mode. Upserts are idempotent so reloading on each run is harmless.
        sim_path = sample_dir / "sim_sample.parquet"
        logger.info("Loading SIM sample: %s", sim_path)
        df_sim = pd.read_parquet(sim_path)
        staged_sim = stage_sim(df_sim)
        sim_rows = load_obitos(staged_sim, cache, conn)
        conn.commit()
        logger.info("SIM sample loaded: %d rows upserted", sim_rows)
        sim_files = 1

        logger.info("--- SIM processing complete ---")

        # --- SIH sample ---
        sih_path = sample_dir / "sih_sample.parquet"
        logger.info("Loading SIH sample: %s", sih_path)
        df_sih = pd.read_parquet(sih_path)
        staged_sih = stage_sih(df_sih)
        sih_rows = load_internacoes(staged_sih, cache, conn)
        conn.commit()
        logger.info("SIH sample loaded: %d rows upserted", sih_rows)

        sih_files = 1

        # --- SINAN sample ---
        # No data/sample/sinan_sample.parquet fixture exists — SINAN is
        # skipped entirely in sample mode. Counters stay at 0.
        logger.info("SAMPLE_MODE=true — no SINAN sample fixture, skipping SINAN load")

    # ------------------------------------------------------------------
    # 3. Full mode: download from DataSUS FTP and load each UF × year
    # ------------------------------------------------------------------
    else:
        logger.info("Full mode — processing %d UF(s) × %d year(s)", len(ufs), len(anos))

        if sinan_only:
            logger.info("--sinan-only flag set: skipping SIM and SIH downloads")
        else:
            if sih_only:
                logger.info("--sih-only flag set: skipping SIM downloads")
            sim_units = [] if sih_only else [(uf, ano) for uf in ufs for ano in anos]
            total_sim_units = len(sim_units)
            for idx, (uf, ano) in enumerate(sim_units, start=1):
                # --- SIM ---
                logger.info("SIM: fetching %d/%d %s %s", idx, total_sim_units, uf, ano)
                sim_result = get_or_download_sim(uf, ano, raw_dir)

                if sim_result is None:
                    sim_skipped_absent += 1
                    logger.info("SIM %s %s: not in catalog — skipped", uf, ano)
                else:
                    sim_path, sim_md5 = sim_result
                    if _already_loaded(conn, sim_md5):
                        sim_skipped_loaded += 1
                        logger.info(
                            "SIM %s %s already loaded (hash=%s) — skipping",
                            uf,
                            ano,
                            sim_md5,
                        )
                    else:
                        df_sim = pd.read_parquet(sim_path)
                        staged_sim = stage_sim(df_sim, uf=uf, ano=ano)
                        n = load_obitos(staged_sim, cache, conn)
                        _write_audit(conn, str(sim_path), sim_md5, uf, ano, "SIM")
                        conn.commit()
                        sim_rows += n
                        sim_files += 1
                        logger.info("SIM %s %s: %d rows upserted", uf, ano, n)

            if not sih_only:
                logger.info("--- SIM processing complete ---")

            if sim_only:
                logger.info("--sim-only flag set: skipping SIH downloads")
            else:
                sih_units = [(uf, ano) for uf in ufs for ano in anos]
                total_sih_units = len(sih_units)
                for idx, (uf, ano) in enumerate(sih_units, start=1):
                    # --- SIH ---
                    logger.info(
                        "SIH: fetching %d/%d %s %s", idx, total_sih_units, uf, ano
                    )
                    sih_result = get_or_download_sih(uf, ano, raw_dir)

                    if sih_result is None:
                        sih_skipped_absent += 1
                        logger.info("SIH %s %s: not in catalog — skipped", uf, ano)
                    else:
                        sih_path, sih_md5 = sih_result
                        if _already_loaded(conn, sih_md5):
                            sih_skipped_loaded += 1
                            logger.info(
                                "SIH %s %s already loaded (hash=%s) — skipping",
                                uf,
                                ano,
                                sih_md5,
                            )
                        else:
                            raw_sih = pd.read_parquet(sih_path)
                            n = 0
                            for start in range(0, len(raw_sih), SIH_CHUNK_SIZE):
                                chunk = raw_sih.iloc[start : start + SIH_CHUNK_SIZE]
                                staged_sih = stage_sih(chunk)
                                n += load_internacoes(staged_sih, cache, conn)
                            _write_audit(conn, str(sih_path), sih_md5, uf, ano, "SIH")
                            conn.commit()
                            sih_rows += n
                            sih_files += 1
                            logger.info("SIH %s %s: %d rows upserted", uf, ano, n)

        # --- SINAN: (agravo, ano) grain — never (agravo, UF). pysus.sinan()
        # has no state= parameter; every call downloads one national file
        # covering all 27 UFs, so uf=None is passed to _write_audit below
        # (legal only from migration 0019 onward). ---
        if agravos:
            sinan_units = [(agravo, ano) for agravo in agravos for ano in anos]
            total_sinan_units = len(sinan_units)
            for idx, (agravo, ano) in enumerate(sinan_units, start=1):
                logger.info(
                    "SINAN: fetching %d/%d %s %s", idx, total_sinan_units, agravo, ano
                )
                sinan_result = get_or_download_sinan(agravo, ano, raw_dir)

                if sinan_result is None:
                    sinan_skipped_absent += 1
                    logger.info("SINAN %s %s: not in catalog — skipped", agravo, ano)
                else:
                    sinan_path, sinan_md5 = sinan_result
                    if _already_loaded(conn, sinan_md5):
                        sinan_skipped_loaded += 1
                        logger.info(
                            "SINAN %s %s already loaded (hash=%s) — skipping",
                            agravo,
                            ano,
                            sinan_md5,
                        )
                    else:
                        raw_sinan_df = pd.read_parquet(sinan_path)
                        n = 0
                        for start in range(0, len(raw_sinan_df), SINAN_CHUNK_SIZE):
                            chunk = raw_sinan_df.iloc[start : start + SINAN_CHUNK_SIZE]
                            staged_sinan = stage_sinan(chunk, tipo_agravo=agravo)
                            n += load_notificacoes(staged_sinan, cache, conn)
                        _write_audit(
                            conn, str(sinan_path), sinan_md5, None, ano, "SINAN"
                        )
                        conn.commit()
                        sinan_rows += n
                        sinan_files += 1
                        logger.info("SINAN %s %s: %d rows upserted", agravo, ano, n)

    # ------------------------------------------------------------------
    # 4. Refresh materialized views in dependency order (always, regardless of mode)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 4. Refresh aggregation tables (regular tables, not real MVs)
    #    autocommit=True per step to avoid DiskFull on free-tier Neon.
    # ------------------------------------------------------------------
    logger.info("Refreshing aggregation tables...")
    # When no unit was loaded, the DimCache/_already_loaded SELECTs leave a
    # read transaction open and psycopg2 refuses the autocommit switch.
    conn.commit()
    _orig_ac = conn.autocommit
    conn.autocommit = True
    cur = conn.cursor()

    def _refresh(tname, insert_sql):
        cur.execute("SELECT relkind FROM pg_class WHERE relname = %s", (tname,))
        row = cur.fetchone()
        if row and row[0] == "m":
            cur.execute(f"REFRESH MATERIALIZED VIEW {tname}")
        else:
            cur.execute(f"TRUNCATE {tname}")
            cur.execute(insert_sql)

    _refresh(
        "mv_curva_epidemica_semana",
        """
        INSERT INTO mv_curva_epidemica_semana
        WITH pop_ref AS (
            SELECT DISTINCT ON (codigo_ibge_6) codigo_ibge_6, populacao_total
            FROM dim_populacao ORDER BY codigo_ibge_6, ano DESC
        ),
        mun_week AS (
            SELECT f.tipo_agravo AS agravo, l.sigla_uf, f.dim_local_id,
                   fn_epi_year(f.dt_notific) AS epi_year,
                   fn_epi_week(f.dt_notific) AS epi_week,
                   SUM(f.notificacoes) AS total_notificacoes,
                   MAX(p.populacao_total)::numeric AS pop_municipio
            FROM fato_notificacoes f
            JOIN dim_local l ON l.id = f.dim_local_id
            LEFT JOIN pop_ref p ON p.codigo_ibge_6 = l.codigo_ibge_6
            WHERE f.dt_notific IS NOT NULL
            GROUP BY f.tipo_agravo, l.sigla_uf, f.dim_local_id,
                     fn_epi_year(f.dt_notific), fn_epi_week(f.dt_notific)
        )
        SELECT agravo, sigla_uf, epi_year AS ano_epidemiologico,
               epi_week AS semana_epidemiologica,
               SUM(total_notificacoes) AS total_notificacoes,
               SUM(pop_municipio) AS total_populacao
        FROM mun_week GROUP BY agravo, sigla_uf, epi_year, epi_week
    """,
    )
    logger.info("  mv_curva_epidemica_semana ok")

    _refresh(
        "mv_curva_epidemica_municipio_semana",
        """
        INSERT INTO mv_curva_epidemica_municipio_semana
        WITH pop_ref AS (
            SELECT DISTINCT ON (codigo_ibge_6) codigo_ibge_6, populacao_total
            FROM dim_populacao ORDER BY codigo_ibge_6, ano DESC
        )
        SELECT f.tipo_agravo AS agravo, l.sigla_uf, f.dim_local_id,
               fn_epi_year(f.dt_notific) AS ano_epidemiologico,
               fn_epi_week(f.dt_notific) AS semana_epidemiologica,
               SUM(f.notificacoes) AS total_notificacoes,
               MAX(p.populacao_total)::numeric AS total_populacao
        FROM fato_notificacoes f
        JOIN dim_local l ON l.id = f.dim_local_id
        LEFT JOIN pop_ref p ON p.codigo_ibge_6 = l.codigo_ibge_6
        WHERE f.dt_notific IS NOT NULL
        GROUP BY f.tipo_agravo, l.sigla_uf, f.dim_local_id,
                 fn_epi_year(f.dt_notific), fn_epi_week(f.dt_notific)
    """,
    )
    logger.info("  mv_curva_epidemica_municipio_semana ok")

    _refresh(
        "mv_uf_summary_anual",
        """
        INSERT INTO mv_uf_summary_anual
        SELECT agravo, sigla_uf, ano_epidemiologico AS ano,
               SUM(total_notificacoes) AS total_notificacoes,
               SUM(max_populacao) AS total_populacao
        FROM (
            SELECT agravo, sigla_uf, dim_local_id, ano_epidemiologico,
                   SUM(total_notificacoes) AS total_notificacoes,
                   MAX(total_populacao) AS max_populacao
            FROM mv_curva_epidemica_municipio_semana
            GROUP BY agravo, sigla_uf, dim_local_id, ano_epidemiologico
        ) muni_annual
        GROUP BY agravo, sigla_uf, ano_epidemiologico
    """,
    )
    logger.info("  mv_uf_summary_anual ok")

    _refresh(
        "mv_breakdown_anual",
        """
        INSERT INTO mv_breakdown_anual
        SELECT da.codigo AS agravo, dl.sigla_uf, dt.ano,
               fn.sexo, fn.classi_fin, fn.gravidade_grave, fn.tra_classi, fn.tp_acidente,
               df.codigo AS faixa_etaria_codigo, df.descricao AS faixa_etaria_descricao,
               df.ordem AS faixa_etaria_ordem,
               SUM(fn.notificacoes) AS total_notificacoes
        FROM fato_notificacoes fn
        JOIN dim_agravo       da ON fn.dim_agravo_id       = da.id
        JOIN dim_local        dl ON fn.dim_local_id        = dl.id
        JOIN dim_tempo        dt ON fn.dim_tempo_id        = dt.id
        JOIN dim_faixa_etaria df ON fn.dim_faixa_etaria_id = df.id
        GROUP BY da.codigo, dl.sigla_uf, dt.ano,
                 fn.sexo, fn.classi_fin, fn.gravidade_grave, fn.tra_classi, fn.tp_acidente,
                 df.codigo, df.descricao, df.ordem
    """,
    )
    logger.info("  mv_breakdown_anual ok")

    _refresh(
        "mv_taxa_uf_ano",
        """
        INSERT INTO mv_taxa_uf_ano
        WITH pop_uf AS (
            SELECT dl.sigla_uf, dp.ano, SUM(dp.populacao_total) AS populacao_uf
            FROM dim_populacao dp
            JOIN dim_local dl ON dp.codigo_ibge_6 = dl.codigo_ibge_6 AND dl.is_current = TRUE
            GROUP BY dl.sigla_uf, dp.ano
        ),
        obitos_uf AS (
            SELECT dl.sigla_uf, dt.ano, SUM(fo.obitos) AS total_eventos
            FROM fato_obitos fo
            JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
            JOIN dim_local dl ON fo.dim_local_id = dl.id
            GROUP BY dl.sigla_uf, dt.ano
        ),
        internacoes_uf AS (
            SELECT dl.sigla_uf, dt.ano, SUM(fi.internacoes) AS total_eventos
            FROM fato_internacoes fi
            JOIN dim_tempo dt ON fi.dim_tempo_id = dt.id
            JOIN dim_local dl ON fi.dim_local_id = dl.id
            GROUP BY dl.sigla_uf, dt.ano
        )
        SELECT o.sigla_uf, o.ano, o.total_eventos, p.populacao_uf,
               o.total_eventos * 100000.0 / NULLIF(p.populacao_uf, 0) AS taxa_por_100k,
               'SIM'::VARCHAR(3) AS fonte
        FROM obitos_uf o JOIN pop_uf p ON o.sigla_uf = p.sigla_uf AND o.ano = p.ano
        UNION ALL
        SELECT i.sigla_uf, i.ano, i.total_eventos, p.populacao_uf,
               i.total_eventos * 100000.0 / NULLIF(p.populacao_uf, 0) AS taxa_por_100k,
               'SIH'::VARCHAR(3) AS fonte
        FROM internacoes_uf i JOIN pop_uf p ON i.sigla_uf = p.sigla_uf AND i.ano = p.ano
    """,
    )
    logger.info("  mv_taxa_uf_ano ok")

    _refresh(
        "mv_taxa_municipio_ano",
        """
        INSERT INTO mv_taxa_municipio_ano
        WITH obitos_mun AS (
            SELECT dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao,
                   dt.ano, SUM(fo.obitos) AS total_eventos
            FROM fato_obitos fo
            JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
            JOIN dim_local dl ON fo.dim_local_id = dl.id
            GROUP BY dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao, dt.ano
        ),
        internacoes_mun AS (
            SELECT dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao,
                   dt.ano, SUM(fi.internacoes) AS total_eventos
            FROM fato_internacoes fi
            JOIN dim_tempo dt ON fi.dim_tempo_id = dt.id
            JOIN dim_local dl ON fi.dim_local_id = dl.id
            GROUP BY dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao, dt.ano
        )
        SELECT o.codigo_ibge_6, o.codigo_ibge_7, o.nome_municipio, o.sigla_uf, o.regiao,
               o.ano, o.total_eventos, dp.populacao_total AS populacao_municipio,
               o.total_eventos * 100000.0 / NULLIF(dp.populacao_total, 0) AS taxa_por_100k,
               'SIM'::VARCHAR(3) AS fonte
        FROM obitos_mun o
        LEFT JOIN dim_populacao dp ON o.codigo_ibge_6 = dp.codigo_ibge_6 AND o.ano = dp.ano
        UNION ALL
        SELECT i.codigo_ibge_6, i.codigo_ibge_7, i.nome_municipio, i.sigla_uf, i.regiao,
               i.ano, i.total_eventos, dp.populacao_total AS populacao_municipio,
               i.total_eventos * 100000.0 / NULLIF(dp.populacao_total, 0) AS taxa_por_100k,
               'SIH'::VARCHAR(3) AS fonte
        FROM internacoes_mun i
        LEFT JOIN dim_populacao dp ON i.codigo_ibge_6 = dp.codigo_ibge_6 AND i.ano = dp.ano
    """,
    )
    logger.info("  mv_taxa_municipio_ano ok")

    conn.autocommit = _orig_ac
    cur.close()
    logger.info("Aggregation tables refreshed")

    # ------------------------------------------------------------------
    # 5. TABNET cross-validation log for the first UF × year in the run
    # ------------------------------------------------------------------
    uf_check = ufs[0] if ufs else "SP"
    ano_check = anos[0] if anos else 2023
    cur = conn.cursor()
    cur.execute(
        """
        SELECT SUM(fo.obitos)
        FROM fato_obitos fo
        JOIN dim_local dl ON fo.dim_local_id = dl.id
        JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
        WHERE dl.sigla_uf = %s AND dt.ano = %s
        """,
        (uf_check, ano_check),
    )
    total = cur.fetchone()[0] or 0
    logger.info(
        "TABNET cross-validation: %s %s total_obitos=%s (compare against TABNET)",
        uf_check,
        ano_check,
        total,
    )
    cur.close()

    # ------------------------------------------------------------------
    # 6. Return summary
    # ------------------------------------------------------------------
    return {
        "sim_files": sim_files,
        "sih_files": sih_files,
        "sim_rows": sim_rows,
        "sih_rows": sih_rows,
        "sim_skipped_loaded": sim_skipped_loaded,
        "sih_skipped_loaded": sih_skipped_loaded,
        "sim_skipped_absent": sim_skipped_absent,
        "sih_skipped_absent": sih_skipped_absent,
        "sinan_files": sinan_files,
        "sinan_rows": sinan_rows,
        "sinan_skipped_loaded": sinan_skipped_loaded,
        "sinan_skipped_absent": sinan_skipped_absent,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HealthLens ETL pipeline — loads DataSUS SIM and SIH data into PostgreSQL."
    )
    parser.add_argument(
        "--uf",
        default="SP",
        help="Comma-separated UF codes to process (default: SP).",
    )
    parser.add_argument(
        "--ano",
        default="2023",
        help="Comma-separated reference years to process (default: 2023).",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory for downloaded raw Parquet files (default: data/raw).",
    )
    parser.add_argument(
        "--sim-only",
        action="store_true",
        default=False,
        help="Process SIM mortality data only; skip SIH hospitalisation downloads.",
    )
    parser.add_argument(
        "--sih-only",
        action="store_true",
        default=False,
        help="Process SIH hospitalisation data only; skip SIM mortality downloads.",
    )
    parser.add_argument(
        "--agravo",
        default="",
        help=(
            "Comma-separated SINAN agravo codes to process, e.g. DENG,CHIK,ANIM "
            "(default: empty — no SINAN processing, existing SIM/SIH invocations "
            "are unaffected)."
        ),
    )
    parser.add_argument(
        "--sinan-only",
        action="store_true",
        default=False,
        help="Process SINAN agravos only; skip SIM and SIH entirely.",
    )
    args = parser.parse_args()
    if args.sim_only and args.sih_only:
        parser.error("--sim-only and --sih-only are mutually exclusive")

    ufs = [u.strip().upper() for u in args.uf.split(",") if u.strip()]
    anos = [int(y.strip()) for y in args.ano.split(",") if y.strip()]
    agravos = [a.strip().upper() for a in args.agravo.split(",") if a.strip()]
    raw_dir = Path(args.raw_dir)

    if not config.DATABASE_URL_SYNC:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    logger.info(
        "Starting pipeline: UFs=%s anos=%s agravos=%s raw_dir=%s SAMPLE_MODE=%s",
        ufs,
        anos,
        agravos,
        raw_dir,
        config.SAMPLE_MODE,
    )

    conn = psycopg2.connect(config.DATABASE_URL_SYNC)
    try:
        summary = run_pipeline(
            ufs,
            anos,
            raw_dir,
            conn,
            sim_only=args.sim_only,
            agravos=agravos,
            sinan_only=args.sinan_only,
            sih_only=args.sih_only,
        )
    finally:
        conn.close()

    print(
        f"\nPipeline complete:\n"
        f"  SIM files processed         : {summary['sim_files']}\n"
        f"  SIM rows upserted           : {summary['sim_rows']}\n"
        f"  SIM already loaded (resumed): {summary['sim_skipped_loaded']}\n"
        f"  SIM absent from catalog     : {summary['sim_skipped_absent']}\n"
        f"  SIH files processed         : {summary['sih_files']}\n"
        f"  SIH rows upserted           : {summary['sih_rows']}\n"
        f"  SIH already loaded (resumed): {summary['sih_skipped_loaded']}\n"
        f"  SIH absent from catalog     : {summary['sih_skipped_absent']}\n"
        f"  SINAN files processed       : {summary['sinan_files']}\n"
        f"  SINAN notificações upserted : {summary['sinan_rows']}\n"
        f"  SINAN already loaded (resumed): {summary['sinan_skipped_loaded']}\n"
        f"  SINAN absent from catalog   : {summary['sinan_skipped_absent']}\n"
    )
