"""Transform real TCU/IBGE population CSV to the format expected by tcu_loader.py."""
import io
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://raw.githubusercontent.com/lsbastos/popBR_mun/refs/heads/master/popBR2000-2024.long.csv"
OUT = Path(__file__).resolve().parent.parent / "backend" / "seeds" / "data" / "tcu_populacao.csv"

print(f"Downloading from {URL} ...")
with urllib.request.urlopen(URL, timeout=60) as r:
    raw = r.read()
print(f"Download OK: {len(raw):,} bytes")

df_raw = pd.read_csv(io.BytesIO(raw), dtype={"MUNCOD": str})
print(f"Raw shape: {df_raw.shape}  columns: {df_raw.columns.tolist()}")

# Filter 2010-2023 (14 years matching the prior synthetic dataset)
df = df_raw[df_raw["Ano"].between(2010, 2023)].copy()

# Ensure exactly 6-char zero-padded IBGE code
df["MUNCOD"] = df["MUNCOD"].str.zfill(6)
bad = df[df["MUNCOD"].str.len() != 6]
if not bad.empty:
    raise ValueError(f"{len(bad)} rows with codigo_ibge_6 length != 6:\n{bad.head()}")

# Rename and select columns
df = df.rename(columns={"MUNCOD": "codigo_ibge_6", "Ano": "ano", "POP": "populacao_total"})
df = (
    df[["codigo_ibge_6", "ano", "populacao_total"]]
    .sort_values(["codigo_ibge_6", "ano"])
    .reset_index(drop=True)
)

n_mun = df["codigo_ibge_6"].nunique()
n_anos = df["ano"].nunique()
anos = sorted(df["ano"].unique().tolist())
nulls = int(df["populacao_total"].isnull().sum())

print(f"Filtered: {len(df):,} rows  |  municipios: {n_mun}  |  anos: {n_anos}  |  null_pop: {nulls}")
print(f"Anos: {anos}")
print(df.head(3).to_string())

# Write with same layout as original:
#   line 1: comment (#) — skipped by tcu_loader.py via comment="#"
#   line 2: header (codigo_ibge_6,ano,populacao_total)
#   lines 3+: data
with open(OUT, "w", encoding="utf-8", newline="") as f:
    f.write("# Fonte: IBGE estimativas populacionais enviadas ao TCU (FPM) via lsbastos/popBR_mun\n")
    df.to_csv(f, index=False)

print(f"\nSalvo em: {OUT}")
print("Primeiras 4 linhas do arquivo:")
with open(OUT, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        print(f"  {i+1}: {line.rstrip()}")
        if i >= 3:
            break
