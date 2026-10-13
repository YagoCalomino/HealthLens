"""Sample mode pipeline loader.

Reads SIM and SIH sample Parquet files when SAMPLE_MODE=true.
Does NOT write to PostgreSQL — sample mode is read-only Parquet.
"""

import logging
import os
from pathlib import Path
from typing import Dict

import pandas as pd

from etl import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SIM_REQUIRED_COLS = {"NUMERODO", "CODMUNRES", "CAUSABAS"}
SIH_REQUIRED_COLS = {"N_AIH", "MUNIC_RES", "DIAG_PRINC"}


def load_sample() -> Dict[str, pd.DataFrame]:
    if not config.SAMPLE_MODE:
        raise RuntimeError(
            "sample_loader called but SAMPLE_MODE is not true. "
            "Set SAMPLE_MODE=true in the environment to use sample mode."
        )

    # Use env-provided path when explicitly set; otherwise anchor to repo root via __file__
    if os.environ.get("SAMPLE_DATA_DIR"):
        sample_dir = Path(config.SAMPLE_DATA_DIR)
    else:
        sample_dir = Path(__file__).resolve().parent.parent.parent / "data" / "sample"
    sim_path = sample_dir / "sim_sample.parquet"
    sih_path = sample_dir / "sih_sample.parquet"

    logger.info(f"Loading SIM sample from {sim_path}")
    df_sim = pd.read_parquet(sim_path)

    logger.info(f"Loading SIH sample from {sih_path}")
    df_sih = pd.read_parquet(sih_path)

    # Validate required columns
    missing_sim = SIM_REQUIRED_COLS - set(df_sim.columns)
    if missing_sim:
        raise ValueError(f"SIM sample missing required columns: {missing_sim}")

    missing_sih = SIH_REQUIRED_COLS - set(df_sih.columns)
    if missing_sih:
        raise ValueError(f"SIH sample missing required columns: {missing_sih}")

    # Validate no nulls in key columns
    for col in SIM_REQUIRED_COLS:
        null_count = df_sim[col].isnull().sum()
        if null_count:
            raise ValueError(f"SIM sample: {null_count} null values in column {col}")

    for col in SIH_REQUIRED_COLS:
        null_count = df_sih[col].isnull().sum()
        if null_count:
            raise ValueError(f"SIH sample: {null_count} null values in column {col}")

    print(
        f"Sample mode: loaded {len(df_sim)} SIM rows, {len(df_sih)} SIH rows "
        f"from {config.SAMPLE_DATA_DIR}"
    )

    return {"sim": df_sim, "sih": df_sih}


if __name__ == "__main__":
    data = load_sample()
    print(data["sim"].describe())
