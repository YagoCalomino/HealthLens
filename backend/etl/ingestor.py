"""DataSUS FTP downloader with local Parquet fallback.

pysus 2.7.0: sim()/sih()/sinan() return list[str] (Parquet paths) by
default; pass as_dataframe=True to get a pd.DataFrame directly. SIH
additionally requires bypassing the top-level sih() convenience function
entirely — its group= parameter is non-functional against the DuckLake
catalog (see _fetch_sih_rd's docstring for the full rationale). Save
explicitly with df.to_parquet().

Offline fallback: if data/raw/{fonte}_{UF}_{YEAR}.parquet already exists, download
is skipped. Returns None when the catalog has no data for a UF×year pair.
SINAN's fallback file follows a different, national-grain naming convention:
data/raw/SINAN_{DISEASE}_{ano}.parquet (see get_or_download_sinan) — there is
no UF component because sinan() has no state= parameter.
"""

import asyncio
import hashlib
import logging
from pathlib import Path

import pandas as pd
from pysus import sim, sinan
from pysus.api.client import PySUS

logger = logging.getLogger(__name__)


def compute_md5(path: Path) -> str:
    """Return the MD5 hex digest of a file, reading in 8 KB chunks."""
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_or_download_sim(uf: str, ano: int, raw_dir: Path) -> tuple[Path, str] | None:
    """Return (parquet_path, md5) for SIM mortality data, downloading if absent.

    Args:
        uf:      Two-letter UF code (e.g. "SP").
        ano:     Reference year (e.g. 2022).
        raw_dir: Directory where raw Parquet files are stored.

    Returns:
        A (Path, str) tuple or None when the cloud catalog has no data for this pair.

    Raises:
        RuntimeError: When the download fails with a network error.
    """
    parquet_path = raw_dir / f"SIM_{uf}_{ano}.parquet"

    if parquet_path.exists():
        logger.info("SIM %s %s: using local file %s", uf, ano, parquet_path)
        return parquet_path, compute_md5(parquet_path)

    logger.info("Downloading SIM %s %s from DataSUS FTP", uf, ano)
    try:
        # as_dataframe=True is mandatory under pysus 2.7.0: the default
        # return type is list[str] (Parquet file paths), not a DataFrame.
        # show_progress=False keeps a 405-unit batch run's logs readable.
        df = sim(state=uf, year=ano, as_dataframe=True, show_progress=False)
    except Exception as exc:
        logger.warning("SIM %s %s: download failed (%s) — skipping", uf, ano, exc)
        return None

    if len(df) == 0:
        logger.warning("SIM %s %s: no data in catalog — skipping", uf, ano)
        return None

    raw_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    logger.info("SIM %s %s: %d rows saved to %s", uf, ano, len(df), parquet_path)

    return parquet_path, compute_md5(parquet_path)


def get_or_download_sinan(
    disease: str, ano: int, raw_dir: Path
) -> tuple[Path, str] | None:
    """Return (parquet_path, md5) for SINAN notification data, downloading if absent.

    Args:
        disease: pysus disease keyword ("DENG"/"CHIK"/"ANIM"), any case.
        ano:     Reference year (e.g. 2023).
        raw_dir: Directory where raw Parquet files are stored.

    Returns:
        A (Path, str) tuple or None when the cloud catalog has no data for this pair.

    Three non-obvious facts, each live-verified in
    docs/pysus-270-sinan-spike-findings.md before this function was written:

    1. sinan() has NO state= parameter. Unlike sim()/sih(), every call
       returns one NATIONAL file covering all 27 UFs — the checkpoint/cache
       grain here is (agravo, ano), never (agravo, UF). Passing state= via
       **kwargs was tested live and silently returns zero rows rather than
       raising or scoping the result, mirroring the SIH group="RD" bug
       class — never pass it.
    2. Passing add_dv False is mandatory. It keeps ID_MN_RESI/ID_MUNICIP as raw
       6-digit DataSUS codes matching dim_local.codigo_ibge_6. With add_dv
       at its default (True), pysus appends the IBGE check digit and every
       downstream FK resolution against dim_local silently fails (skipped,
       not errored).
    3. as_dataframe=True is mandatory under pysus 2.7.0 — the default
       return type is list[str] (Parquet file paths), not a DataFrame.
    """
    disease = disease.strip().upper()
    parquet_path = raw_dir / f"SINAN_{disease}_{ano}.parquet"

    if parquet_path.exists():
        logger.info("SINAN %s %s: using local file %s", disease, ano, parquet_path)
        return parquet_path, compute_md5(parquet_path)

    logger.info("Downloading SINAN %s %s from DataSUS FTP", disease, ano)
    try:
        df = sinan(
            disease=disease,
            year=ano,
            as_dataframe=True,
            show_progress=False,
            add_dv=False,
        )
    except Exception as exc:
        logger.warning(
            "SINAN %s %s: download failed (%s) — skipping", disease, ano, exc
        )
        return None

    if df is None or not isinstance(df, pd.DataFrame) or len(df) == 0:
        logger.warning(
            "SINAN %s %s: no data in pysus catalog — trying FTP fallback", disease, ano
        )
        from etl.ingestor_ftp import fetch_sinan_ftp

        ftp_path = fetch_sinan_ftp(disease, ano, str(raw_dir))
        if ftp_path is None:
            logger.warning(
                "SINAN %s %s: absent from catalog (pysus + FTP)", disease, ano
            )
            return None
        parquet_path = Path(ftp_path)
        logger.info(
            "SINAN %s %s: loaded via FTP fallback — %s", disease, ano, parquet_path
        )
        return parquet_path, compute_md5(parquet_path)

    raw_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    logger.info("SINAN %s %s: %d rows saved to %s", disease, ano, len(df), parquet_path)

    return parquet_path, compute_md5(parquet_path)


def _fetch_sih_rd(uf: str, ano: int, meses: list[int]) -> "pd.DataFrame | None":
    """Fetch only SIH-RD (AIH Reduzida) records for a UF/year.

    WHY not sih(..., group='RD'): under pysus 2.7.0's DuckLake catalog, the
    group= query parameter filters against a catalog metadata field that is
    None for every SIH file (RD/SP/RJ/ER alike) — it silently returns zero
    results for every UF/year, verified live against SP/SE/AC/RJ/BA. Filtering
    the file *list* by filename prefix ("RD" is the first 2 chars of every
    AIH Reduzida filename, e.g. RDSP2305.parquet) is the only reliable way to
    isolate RD files pre-download.

    WHY not just fetch everything + rely on IDENT=1: SIH-RJ ("AIH Rejeitada")
    files also carry IDENT=1 on 100% of their rows (verified: 475/475 in a
    live sample) — IDENT alone cannot distinguish valid RD records from
    rejected RJ claims. The filename-prefix filter here is the primary
    safeguard; stage_sih's existing IDENT=1 filter remains a second,
    defense-in-depth layer against long-stay continuation AIHs (IDENT=5)
    within genuine RD files.

    add_dv=False: dim_local / seeds/ibge_loader.py remains the single source
    of truth for the codigo_ibge_7 check digit — pysus must not compute its own.
    """

    async def _fetch():
        async with PySUS() as client:
            files = await client.query(dataset="sih", state=uf, year=ano, month=meses)
            rd_files = [f for f in files if f.path.name.upper().startswith("RD")]
            if not rd_files:
                return None
            local_paths = [(await client.download(f)).path for f in rd_files]
            return client.read_parquet(local_paths, add_dv=False).df()

    return asyncio.run(_fetch())


def get_or_download_sih(uf: str, ano: int, raw_dir: Path) -> tuple[Path, str] | None:
    """Return (parquet_path, md5) for SIH hospitalisation data, downloading if absent.

    Args:
        uf:      Two-letter UF code (e.g. "SP").
        ano:     Reference year (e.g. 2022).
        raw_dir: Directory where raw Parquet files are stored.

    Returns:
        A (Path, str) tuple or None when the cloud catalog has no data for this pair.

    Raises:
        RuntimeError: When the download fails with a network error.
    """
    parquet_path = raw_dir / f"SIH_{uf}_{ano}.parquet"

    if parquet_path.exists():
        logger.info("SIH %s %s: using local file %s", uf, ano, parquet_path)
        return parquet_path, compute_md5(parquet_path)

    logger.info("Downloading SIH %s %s from DataSUS FTP", uf, ano)
    try:
        df = _fetch_sih_rd(uf, ano, list(range(1, 13)))
    except Exception as exc:
        logger.warning("SIH %s %s: download failed (%s) — skipping", uf, ano, exc)
        return None

    if df is None or len(df) == 0:
        logger.warning("SIH %s %s: no data in catalog — skipping", uf, ano)
        return None

    raw_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    logger.info("SIH %s %s: %d rows saved to %s", uf, ano, len(df), parquet_path)

    return parquet_path, compute_md5(parquet_path)
