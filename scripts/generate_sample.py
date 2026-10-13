"""Generate synthetic sample Parquet files for SIM and SIH data.

Files are committed to git and used by SAMPLE_MODE=true pipeline runs.
No PostgreSQL required.
"""
import random
from pathlib import Path

import pandas as pd

random.seed(42)

# 5 UFs with representative municipality codes (6-digit IBGE)
# SP=35, RJ=33, MG=31, BA=29, RS=43
MUNICIPALITIES = {
    # SP — 10 municipalities
    "35": ["350140", "350300", "350550", "350600", "350900", "351060", "352590", "353440", "354340", "355030"],
    # RJ — 10 municipalities
    "33": ["330010", "330045", "330100", "330170", "330200", "330250", "330285", "330350", "330430", "330455"],
    # MG — 10 municipalities
    "31": ["310010", "310100", "310200", "310430", "310670", "311330", "312330", "313000", "314330", "315780"],
    # BA — 10 municipalities
    "29": ["290010", "290070", "290160", "290320", "290350", "290490", "290570", "290720", "290800", "292740"],
    # RS — 10 municipalities
    "43": ["430010", "430060", "430090", "430100", "430190", "430200", "430230", "430270", "430330", "430460"],
}

YEARS = [2019, 2020, 2021, 2022, 2023]

# Representative CID-10 codes covering key chapters
CID_CODES = [
    "J18",  # Pneumonia (X — Respiratory)
    "I21",  # Acute MI (IX — Circulatory)
    "I64",  # Stroke (IX — Circulatory)
    "C34",  # Lung cancer (II — Neoplasms)
    "K70",  # Alcoholic liver disease (XI — Digestive)
    "R99",  # Ill-defined cause (XVIII — Signs/symptoms)
    "Z00",  # General examination (XXI — Health factors)
    "A09",  # Diarrhea (I — Infectious)
    "J44",  # COPD (X — Respiratory)
    "E11",  # Type 2 diabetes (IV — Endocrine)
]

SEXO_OPTIONS = ["1", "2", "9"]  # M, F, Ignored


def _random_date(year: int) -> str:
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{year}{month:02d}{day:02d}"


def _random_age_encoded() -> int:
    # DataSUS age encoding: 400 + years for ages 0-99
    age = random.randint(0, 99)
    return 400 + age


def generate_sim_sample(output_path: Path, n_rows: int = 1200) -> pd.DataFrame:
    all_munic = [m for codes in MUNICIPALITIES.values() for m in codes]
    records = []
    numerodo_set: set = set()

    for i in range(n_rows):
        year = random.choice(YEARS)
        codmunres = random.choice(all_munic)
        coduf = codmunres[:2]
        numerodo = f"DO{year}{coduf}{i:06d}"
        while numerodo in numerodo_set:
            numerodo = f"DO{year}{coduf}{i:06d}X"
        numerodo_set.add(numerodo)

        records.append({
            "NUMERODO": numerodo,
            "DTOBITO": _random_date(year),
            "CAUSABAS": random.choice(CID_CODES),
            "CODMUNRES": codmunres,
            "SEXO": random.choice(SEXO_OPTIONS),
            "IDADE": _random_age_encoded(),
            "CODUF": coduf,
            "REVISAO": 0,
        })

    df = pd.DataFrame(records)
    df.to_parquet(output_path, index=False, engine="pyarrow")
    return df


def generate_sih_sample(output_path: Path, n_rows: int = 1200) -> pd.DataFrame:
    all_munic = [m for codes in MUNICIPALITIES.values() for m in codes]
    records = []
    aih_set: set = set()

    for i in range(n_rows):
        year = random.choice(YEARS)
        munic_res = random.choice(all_munic)
        coduf = munic_res[:2]
        n_aih = f"AIH{year}{coduf}{i:06d}"
        while n_aih in aih_set:
            n_aih = f"AIH{year}{coduf}{i:06d}X"
        aih_set.add(n_aih)

        dt_inter = _random_date(year)
        dias = random.randint(1, 30)
        month = int(dt_inter[4:6])
        day_out = min(int(dt_inter[6:8]) + dias, 28)
        dt_saida = f"{year}{month:02d}{day_out:02d}"
        nasc_year = year - random.randint(1, 90)
        nasc = f"{nasc_year}{random.randint(1,12):02d}{random.randint(1,28):02d}"

        records.append({
            "N_AIH": n_aih,
            "DT_INTER": dt_inter,
            "DT_SAIDA": dt_saida,
            "DIAG_PRINC": random.choice(CID_CODES),
            "MUNIC_RES": munic_res,
            "SEXO": random.choice(SEXO_OPTIONS),
            "NASC": nasc,
            "CNES": f"CNES{random.randint(1000, 9999)}",
            # IDENT=1 marks incident (normal) AIHs — the real discriminator in
            # pysus 2.2.0 SIH-RD output. SP_TIPO is deliberately omitted: on
            # real data it belongs to the separate SP group and is always
            # null on RD rows, so it must never be used as an incident filter.
            "IDENT": "1",
            "MORTE": random.choices([0, 1], weights=[95, 5])[0],
            "VAL_TOT": round(random.uniform(500, 20000), 2),
            "QT_DIARIAS": dias,
        })

    df = pd.DataFrame(records)
    df.to_parquet(output_path, index=False, engine="pyarrow")
    return df


def main() -> None:
    base = Path(__file__).parent.parent
    sample_dir = base / "data" / "sample"
    sample_dir.mkdir(parents=True, exist_ok=True)

    sim_path = sample_dir / "sim_sample.parquet"
    sih_path = sample_dir / "sih_sample.parquet"

    print("Generating SIM sample...")
    df_sim = generate_sim_sample(sim_path, n_rows=1200)
    print(f"  Rows: {len(df_sim)}")
    print(f"  UFs: {df_sim['CODUF'].nunique()} ({sorted(df_sim['CODUF'].unique())})")
    print(f"  Years: {sorted(df_sim['DTOBITO'].str[:4].unique())}")
    print(f"  File: {sim_path} ({sim_path.stat().st_size / 1024:.0f} KB)")

    print("\nGenerating SIH sample...")
    df_sih = generate_sih_sample(sih_path, n_rows=1200)
    print(f"  Rows: {len(df_sih)}")
    print(f"  IDENT unique values: {df_sih['IDENT'].unique()} (should only be ['1'])")
    print(f"  File: {sih_path} ({sih_path.stat().st_size / 1024:.0f} KB)")

    # Verification assertions
    assert df_sim["CODUF"].nunique() >= 5, "SIM sample must cover >= 5 UFs"
    assert len(df_sim) >= 1000, "SIM sample must have >= 1000 rows"
    assert df_sim["NUMERODO"].nunique() == len(df_sim), "SIM NUMERODO must be unique"
    assert df_sih["IDENT"].eq("1").all(), "SIH IDENT must all be '1'"
    assert len(df_sih) >= 1000, "SIH sample must have >= 1000 rows"
    assert df_sih["N_AIH"].nunique() == len(df_sih), "SIH N_AIH must be unique"
    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
