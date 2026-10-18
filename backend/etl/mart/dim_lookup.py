import logging
import math
from typing import Optional


logger = logging.getLogger(__name__)


class DimCache:
    """
    Preloads all dimension tables into memory at pipeline start.
    Eliminates N+1 DB queries during fact-table loading.

    Not thread-safe — single-threaded pipeline only.
    """

    def __init__(self):
        self.tempo: dict[tuple[int, Optional[int]], int] = {}  # (ano, mes) -> id
        self.local: dict[str, int] = {}  # codigo_ibge_6 -> id
        self.causa: dict[str, int] = {}  # codigo_cid10 (+ prefixes) -> id
        self.faixa_etaria: dict[str, int] = {}  # codigo -> id
        self.agravo: dict[str, int] = {}  # codigo (uppercase, e.g. "DENG") -> id
        self.populacao: dict[
            tuple[str, int], int
        ] = {}  # (codigo_ibge_6, ano) -> populacao_total

    def load_all(self, conn) -> None:
        """Bulk-load all 6 dimension tables from the database."""
        with conn.cursor() as cur:
            # dim_tempo
            cur.execute("SELECT id, ano, mes FROM dim_tempo")
            for row in cur.fetchall():
                self.tempo[(row[1], row[2])] = row[0]
            logger.info("dim_tempo loaded: %d rows", len(self.tempo))

            # dim_local — only current rows; DataSUS FKs on fact tables use codigo_ibge_6
            cur.execute(
                "SELECT id, codigo_ibge_6 FROM dim_local WHERE is_current = TRUE"
            )
            for row in cur.fetchall():
                self.local[row[1]] = row[0]
            logger.info("dim_local loaded: %d rows", len(self.local))

            # dim_causa — store full code plus 3-char and 2-char prefix fallbacks.
            # SIM records sometimes carry truncated or category-level CID-10 codes,
            # so prefix resolution lets us map them without losing the record.
            cur.execute("SELECT id, codigo_cid10 FROM dim_causa")
            for row in cur.fetchall():
                codigo = row[1].strip().upper()
                self.causa[codigo] = row[0]
                if len(codigo) >= 3:
                    prefix3 = codigo[:3]
                    if prefix3 not in self.causa:
                        self.causa[prefix3] = row[0]
                if len(codigo) >= 2:
                    prefix2 = codigo[:2]
                    if prefix2 not in self.causa:
                        self.causa[prefix2] = row[0]
            # Count full codes only (not prefix aliases) for an accurate log
            cur.execute("SELECT COUNT(*) FROM dim_causa")
            n_causa = cur.fetchone()[0]
            logger.info(
                "dim_causa loaded: %d rows (%d lookup keys including prefixes)",
                n_causa,
                len(self.causa),
            )

            # dim_faixa_etaria
            cur.execute("SELECT id, codigo FROM dim_faixa_etaria")
            for row in cur.fetchall():
                self.faixa_etaria[row[1]] = row[0]
            logger.info("dim_faixa_etaria loaded: %d rows", len(self.faixa_etaria))

            # dim_agravo — static 3-row lookup
            cur.execute("SELECT id, codigo FROM dim_agravo")
            for row in cur.fetchall():
                self.agravo[row[1]] = row[0]
            logger.info("dim_agravo loaded: %d rows", len(self.agravo))

            # dim_populacao — used to compute taxa_por_100k at load time
            cur.execute("SELECT codigo_ibge_6, ano, populacao_total FROM dim_populacao")
            for row in cur.fetchall():
                self.populacao[(row[0], row[1])] = row[2]
            logger.info("dim_populacao loaded: %d rows", len(self.populacao))

    def get_or_create_tempo_id(self, ano: int, mes: Optional[int], conn) -> int:
        """
        Return dim_tempo.id for (ano, mes).
        Creates the row on first encounter — annual aggregates (mes=None) and
        monthly rows are both valid per schema.

        Callers commonly pass `ano`/`mes` straight from a pandas
        `itertuples()` row (numpy.int64), which psycopg2 cannot adapt on
        first-encounter INSERTs (cache-hit lookups happen to work because the
        dict key still hashes/compares equal to a native int). Cast to native
        Python int here so both the cache key and the INSERT parameters are
        always plain ints, regardless of caller dtype.
        """
        ano = int(ano)
        mes = int(mes) if mes is not None else None
        key = (ano, mes)
        if key in self.tempo:
            return self.tempo[key]

        trimestre = math.ceil(mes / 3) if mes else None
        semestre = math.ceil(mes / 6) if mes else None

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dim_tempo (ano, mes, trimestre, semestre)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (ano, mes, trimestre, semestre),
            )
            new_id = cur.fetchone()[0]

        self.tempo[key] = new_id
        logger.debug("dim_tempo created: ano=%s mes=%s id=%s", ano, mes, new_id)
        return new_id

    def get_local_id(self, codigo_ibge_6: str) -> Optional[int]:
        """
        Return dim_local.id for a 6-digit IBGE municipality code.
        Returns None and warns when the code is absent from the current dimension
        (e.g. extinct municipality not yet in seed data).
        """
        dim_id = self.local.get(codigo_ibge_6)
        if dim_id is None:
            logger.debug("dim_local not found: %s", codigo_ibge_6)
        return dim_id

    def get_causa_id(self, codigo: str) -> Optional[int]:
        """
        Return dim_causa.id for a CID-10 code.

        Resolution order:
          1. Exact normalised match  (e.g. "J180")
          2. 3-character prefix      (e.g. "J18")
          3. 2-character prefix      (e.g. "J1")

        SIM source data can carry 3- or 4-character codes; truncated codes are
        common in older DBF exports.
        """
        normalised = codigo.strip().upper()

        dim_id = self.causa.get(normalised)
        if dim_id is not None:
            return dim_id

        dim_id = self.causa.get(normalised[:3])
        if dim_id is not None:
            return dim_id

        dim_id = self.causa.get(normalised[:2])
        if dim_id is not None:
            return dim_id

        logger.warning("dim_causa not found: %s", codigo)
        return None

    def get_faixa_etaria_id(self, codigo: str) -> Optional[int]:
        """
        Return dim_faixa_etaria.id for a faixa-etaria code.
        Falls back to the 'ignorada' bucket when the code is unrecognised —
        this covers DataSUS records with missing or malformed age fields.
        Returns None only if the seed omitted 'ignorada' entirely (should not happen).
        """
        dim_id = self.faixa_etaria.get(codigo)
        if dim_id is not None:
            return dim_id

        fallback = self.faixa_etaria.get("ignorada")
        if fallback is None:
            logger.warning(
                "dim_faixa_etaria not found for codigo=%r and 'ignorada' fallback is missing",
                codigo,
            )
        return fallback

    def get_agravo_id(self, codigo: str) -> Optional[int]:
        """
        Return dim_agravo.id for a pysus disease keyword (DENG/CHIK/ANIM).

        Normalizes to uppercase before lookup, matching dim_agravo.codigo
        and pysus's own Literal casing. Returns None and logs a warning on a
        miss — unlike get_faixa_etaria_id, there is deliberately no fallback
        bucket, because dim_agravo is a closed 3-value static
        seed with no dynamic growth. tipo_agravo is always caller-controlled
        (the pipeline passes the same literal it handed to
        pysus.sinan(disease=...)), never derived from untrusted row data —
        an unresolvable code means a programming error, not a
        data-quality event.
        """
        if not codigo:
            return None

        normalised = codigo.strip().upper()
        dim_id = self.agravo.get(normalised)
        if dim_id is None:
            logger.warning("dim_agravo not found: %s", codigo)
        return dim_id

    def get_populacao(self, codigo_ibge_6: str, ano: int) -> Optional[int]:
        """
        Return populacao_total for a municipality × year combination.
        Returns None silently — some municipality × year combos have no TCU estimate
        (recently created municipalities, very small populations, etc.).
        Callers must guard against None before computing taxa_por_100k.
        """
        return self.populacao.get((codigo_ibge_6, ano))
