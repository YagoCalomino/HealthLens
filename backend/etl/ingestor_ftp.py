"""FTP fallback fetcher para agravos ausentes do catálogo pysus.

Usado para DENG (dengue), cujos arquivos .dbc não estão indexados
no pysus 2.7.0 mas estão disponíveis no FTP público do DataSUS:
ftp://ftp.datasus.gov.br/dissemin/publicos/SINAN/DADOS/FINAIS/
"""

import ftplib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_FTP_HOST = "ftp.datasus.gov.br"
_FTP_DIR = "/dissemin/publicos/SINAN/DADOS/FINAIS"

# Mapeamento agravo → prefixo do arquivo no FTP
_AGRAVO_PREFIX = {
    "DENG": "DENGBR",
}


def fetch_sinan_ftp(agravo: str, ano: int, raw_dir: str = "data/raw") -> str | None:
    """Baixa um arquivo .dbc do FTP DataSUS e converte para Parquet.

    Retorna o path do Parquet resultante, ou None se o arquivo não
    existir no FTP para o ano solicitado.

    Args:
        agravo: Código do agravo (ex: 'DENG').
        ano: Ano de 4 dígitos (ex: 2023).
        raw_dir: Diretório onde salvar o Parquet.

    Returns:
        Path do Parquet ou None.
    """
    prefix = _AGRAVO_PREFIX.get(agravo.upper())
    if prefix is None:
        logger.warning("fetch_sinan_ftp: agravo %s não suportado", agravo)
        return None

    suffix = str(ano)[-2:]  # 2023 → "23"
    filename = f"{prefix}{suffix}.dbc"
    parquet_path = str(Path(raw_dir) / f"SINAN_{agravo}_{ano}.parquet")

    if os.path.exists(parquet_path):
        logger.info("fetch_sinan_ftp: usando cache %s", parquet_path)
        return parquet_path

    logger.info("fetch_sinan_ftp: baixando %s do FTP DataSUS", filename)
    dbc_path = str(Path(raw_dir) / filename)

    try:
        ftp = ftplib.FTP(_FTP_HOST, timeout=120)
        ftp.login()
        ftp.cwd(_FTP_DIR)
        available = ftp.nlst()
        if filename not in available:
            logger.warning("fetch_sinan_ftp: %s não encontrado no FTP", filename)
            ftp.quit()
            return None
        with open(dbc_path, "wb") as f:
            ftp.retrbinary(f"RETR {filename}", f.write)
        ftp.quit()
        logger.info("fetch_sinan_ftp: download concluído — %s", dbc_path)
    except Exception as e:
        logger.error("fetch_sinan_ftp: erro no FTP — %s", e)
        return None

    try:
        import pyreaddbc

        df = pyreaddbc.read_dbc(dbc_path)
        df.to_parquet(parquet_path, index=False)
        os.remove(dbc_path)
        logger.info(
            "fetch_sinan_ftp: convertido para Parquet — %s (%d rows)",
            parquet_path,
            len(df),
        )
        return parquet_path
    except Exception as e:
        logger.error("fetch_sinan_ftp: erro ao converter .dbc — %s", e)
        return None
