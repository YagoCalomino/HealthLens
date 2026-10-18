"""Per-agravo SINAN classification decode dictionaries.

fato_notificacoes stores raw DataSUS codes only — classi_fin, tra_classi and
tp_acidente are all persisted as the numeric codes the source Parquet carries
(mirroring the existing sexo/raca_cor convention on fato_obitos). This
module is the single decode point that turns those raw codes into human
labels. It is deliberately a plain Python constants module rather than a
database lookup table because the project has no DB-side decode-table
precedent — dim_agravo, dim_causa and friends are dimension tables of
FK-bearing rows, not label-only code tables.

The `/notificacoes` routes use these decoders to surface labels. The per-agravo
CLASSI_FIN classification mapping is verified against the real sample values
recorded by the SINAN spike (docs/pysus-270-sinan-spike-findings.md).
"""

import logging

logger = logging.getLogger(__name__)

# Live-verified (docs/pysus-270-sinan-spike-findings.md): both an empty string and the literal 4-character string "None"
# occur as distinct "missing" encodings for these code columns in real
# pysus 2.7.0 Parquet output.
_MISSING_TOKENS = ("", "none")

# Transcribed from pysus's bundled per-disease dictionary archive
# (pysus/data/metadata/SINAN/DENG.tar.gz), cross-checked against every DENG
# CLASSI_FIN code observed in docs/pysus-270-sinan-spike-findings.md
# (10, 8, 11, 0, 12 — plus the documented-but-unobserved 5).
CLASSI_FIN_LABELS: dict[str, dict[int, str]] = {
    "DENG": {
        0: "Em investigação",
        5: "Descartado",
        8: "Inconclusivo",
        10: "Dengue",
        11: "Dengue com sinais de alarme",
        12: "Dengue grave",
    },
    # Transcribed from pysus's bundled per-disease dictionary archive
    # (pysus/data/metadata/SINAN/CHIK.tar.gz), cross-checked against every
    # CHIK CLASSI_FIN code observed in docs/pysus-270-sinan-spike-findings.md
    # (13, 5, 0). Deliberately a separate literal dict object from DENG's —
    # not a dict(...) copy — CHIK's key set is genuinely smaller (no
    # Dengue-specific alarm/severity codes 8/10/11 apply here).
    "CHIK": {
        0: "Em investigação",
        5: "Descartado",
        13: "Chikungunya",
    },
}
# ANIM has no CLASSI_FIN column at all in its real source data (confirmed
# absent, not merely null — docs/pysus-270-sinan-spike-findings.md check 5).
# There is deliberately no "ANIM" key in CLASSI_FIN_LABELS.

# Confirmed by pysus's bundled ANIM dictionary and live-verified against
# real SINAN data. ANIM only — TRA_CLASSI is a
# severity scale, not a confirm/discard classification like CLASSI_FIN.
TRA_CLASSI_LABELS: dict[int, str] = {
    1: "Leve",
    2: "Moderado",
    3: "Grave",
    9: "Ignorado",
}

# [ASSUMED] These labels are inferred from the observed TP_ACIDENT value
# distribution shape in docs/pysus-270-sinan-spike-findings.md (code 3
# dominant, matching general knowledge that scorpion stings are the most
# common venomous-animal notification nationally) — they are NOT confirmed
# against an official Ministério da Saúde dictionary table in this project's
# research session. Verify at opendatasus.saude.gov.br's SINAN ANIM
# dictionary page before relying on these labels.
TP_ACIDENTE_LABELS: dict[int, str] = {
    1: "Serpente",
    2: "Aranha",
    3: "Escorpião",
    4: "Lagarta",
    5: "Abelha",
    6: "Outros",
    9: "Ignorado",
}

UNKNOWN_CODE_TEMPLATE = "Código não documentado ({codigo})"


def _normalize_codigo(codigo) -> "int | None":
    """Coerce a raw code to int, treating blank/None/'None' as missing.

    Mirrors sinan_staging.py's _blank_mask missing-value duality: both a
    true empty string and the literal string "None" are treated as missing,
    not just Python None.
    """
    if codigo is None:
        return None
    stripped = str(codigo).strip().lower()
    if stripped in _MISSING_TOKENS:
        return None
    try:
        return int(float(codigo))
    except (ValueError, TypeError):
        return None


def decode_classi_fin(tipo_agravo: str, codigo) -> "str | None":
    """Decode a raw CLASSI_FIN code to a Portuguese label, per agravo.

    Returns None outright when tipo_agravo has no CLASSI_FIN dictionary at
    all (the ANIM case — the column does not exist in ANIM's source data,
    so there is nothing to decode). Returns None when codigo is missing
    (None, blank string, or the literal string "None"). On an unrecognised
    code, logs a warning and returns the UNKNOWN_CODE_TEMPLATE fallback
    string rather than raising KeyError.
    """
    tipo_agravo = tipo_agravo.strip().upper()
    labels = CLASSI_FIN_LABELS.get(tipo_agravo)
    if labels is None:
        return None

    normalized = _normalize_codigo(codigo)
    if normalized is None:
        return None

    label = labels.get(normalized)
    if label is None:
        logger.warning(
            "decode_classi_fin: unrecognised code %r for tipo_agravo=%s",
            codigo,
            tipo_agravo,
        )
        return UNKNOWN_CODE_TEMPLATE.format(codigo=normalized)
    return label


def decode_tra_classi(codigo) -> "str | None":
    """Decode a raw ANIM TRA_CLASSI severity code to a Portuguese label."""
    normalized = _normalize_codigo(codigo)
    if normalized is None:
        return None

    label = TRA_CLASSI_LABELS.get(normalized)
    if label is None:
        logger.warning("decode_tra_classi: unrecognised code %r", codigo)
        return UNKNOWN_CODE_TEMPLATE.format(codigo=normalized)
    return label


def decode_tp_acidente(codigo) -> "str | None":
    """Decode a raw ANIM TP_ACIDENT accident-type code to a Portuguese label.

    [ASSUMED] — see the module comment above TP_ACIDENTE_LABELS.
    """
    normalized = _normalize_codigo(codigo)
    if normalized is None:
        return None

    label = TP_ACIDENTE_LABELS.get(normalized)
    if label is None:
        logger.warning("decode_tp_acidente: unrecognised code %r", codigo)
        return UNKNOWN_CODE_TEMPLATE.format(codigo=normalized)
    return label
