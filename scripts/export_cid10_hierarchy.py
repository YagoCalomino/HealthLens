"""Export the static CID-10 hierarchy JSON consumed by the FilterPanel cascade.

Output shape (frontend/public/cid10_hierarchy.json):
    { "capitulos": [ { "id", "descricao", "grupos": [ { "id", "descricao", "codigos": [
        { "id", "descricao" } ] } ] } ] }

Capitulos (I-XXII) are ALWAYS all 22, hardcoded below — independent of DB state, so the
top-level FilterPanel select is never empty even when dim_causa only has the seed
fallback subset.

Schema note — dim_causa (backend/alembic/versions/0003_create_dim_causa.py) does NOT
have a separate "grupo" table or cid_grupo/cid_codigo columns as a hypothetical schema
might suggest. The actual columns are:
    codigo_cid10, descricao, capitulo, categoria, subcategoria, grupo_descricao
`categoria` (the 3-character CID-10 category prefix, e.g. "I21") is the closest existing
grouping level under capitulo, so it is used as the "grupo" id here. `grupo_descricao`
is currently always NULL in the loader (backend/seeds/cid10_loader.py) — fall back to
the categoria-level descricao when grupo_descricao is absent, so the FilterPanel never
renders a blank grupo label.
`codigos` are the individual codigo_cid10 rows (categoria + subcategoria) within a
categoria/grupo.

Degrades gracefully when DATABASE_URL_SYNC is unset, SAMPLE_MODE is true, or the DB is
unreachable: still emits all 22 chapters with empty grupos arrays.
"""
import json
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_FILE = (
    Path(__file__).parent.parent / "frontend" / "public" / "cid10_hierarchy.json"
)

# Full 22-chapter CID-10 dict (PT-BR), independent of DB state.
CAPITULOS_CID10: list[dict[str, str]] = [
    {"id": "I", "descricao": "Algumas doenças infecciosas e parasitárias"},
    {"id": "II", "descricao": "Neoplasias (tumores)"},
    {"id": "III", "descricao": "Doenças do sangue e dos órgãos hematopoéticos e alguns transtornos imunitários"},
    {"id": "IV", "descricao": "Doenças endócrinas, nutricionais e metabólicas"},
    {"id": "V", "descricao": "Transtornos mentais e comportamentais"},
    {"id": "VI", "descricao": "Doenças do sistema nervoso"},
    {"id": "VII", "descricao": "Doenças do olho e anexos"},
    {"id": "VIII", "descricao": "Doenças do ouvido e da apófise mastóide"},
    {"id": "IX", "descricao": "Doenças do aparelho circulatório"},
    {"id": "X", "descricao": "Doenças do aparelho respiratório"},
    {"id": "XI", "descricao": "Doenças do aparelho digestivo"},
    {"id": "XII", "descricao": "Doenças da pele e do tecido subcutâneo"},
    {"id": "XIII", "descricao": "Doenças do sistema osteomuscular e do tecido conjuntivo"},
    {"id": "XIV", "descricao": "Doenças do aparelho geniturinário"},
    {"id": "XV", "descricao": "Gravidez, parto e puerpério"},
    {"id": "XVI", "descricao": "Algumas afecções originadas no período perinatal"},
    {"id": "XVII", "descricao": "Malformações congênitas, deformidades e anomalias cromossômicas"},
    {"id": "XVIII", "descricao": "Sintomas, sinais e achados anormais de exames clínicos e laboratoriais"},
    {"id": "XIX", "descricao": "Lesões, envenenamentos e outras consequências de causas externas"},
    {"id": "XX", "descricao": "Causas externas de morbidade e mortalidade"},
    {"id": "XXI", "descricao": "Fatores que influenciam o estado de saúde e o contato com os serviços de saúde"},
    {"id": "XXII", "descricao": "Códigos para propósitos especiais"},
]


def _connect():
    if os.environ.get("SAMPLE_MODE", "").lower() in ("true", "1"):
        logger.info("SAMPLE_MODE active — skipping DB connection")
        return None

    database_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url:
        logger.info("DATABASE_URL_SYNC not set — skipping DB connection")
        return None

    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed — skipping DB connection")
        return None

    try:
        return psycopg2.connect(database_url, connect_timeout=5)
    except Exception as exc:
        logger.warning(f"DB connection failed: {exc}")
        return None


def _build_grupos_for_chapter(conn, capitulo_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT categoria, grupo_descricao
        FROM dim_causa
        WHERE capitulo = %s
        ORDER BY categoria
        """,
        (capitulo_id,),
    )
    grupo_rows = cur.fetchall()

    grupos: list[dict] = []
    for categoria, grupo_descricao in grupo_rows:
        cur.execute(
            """
            SELECT codigo_cid10, descricao
            FROM dim_causa
            WHERE categoria = %s AND capitulo = %s
            ORDER BY codigo_cid10
            """,
            (categoria, capitulo_id),
        )
        codigo_rows = cur.fetchall()
        codigos = [{"id": cod, "descricao": desc} for cod, desc in codigo_rows]

        # grupo_descricao is currently always NULL in the loader — fall back to the
        # first codigo's descricao so the FilterPanel never shows a blank grupo label.
        descricao = grupo_descricao or (codigos[0]["descricao"] if codigos else categoria)

        grupos.append({"id": categoria, "descricao": descricao, "codigos": codigos})

    cur.close()
    return grupos


def build_hierarchy() -> dict:
    conn = _connect()
    capitulos: list[dict] = []

    if conn is None:
        for cap in CAPITULOS_CID10:
            capitulos.append({"id": cap["id"], "descricao": cap["descricao"], "grupos": []})
        return {"capitulos": capitulos}

    try:
        for cap in CAPITULOS_CID10:
            grupos = _build_grupos_for_chapter(conn, cap["id"])
            capitulos.append({"id": cap["id"], "descricao": cap["descricao"], "grupos": grupos})
    finally:
        conn.close()

    return {"capitulos": capitulos}


def main() -> int:
    hierarchy = build_hierarchy()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(hierarchy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    n_chapters = len(hierarchy["capitulos"])
    n_grupos = sum(len(c["grupos"]) for c in hierarchy["capitulos"])
    logger.info(
        f"Wrote {OUTPUT_FILE} — {n_chapters} capitulos, {n_grupos} grupos total"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
