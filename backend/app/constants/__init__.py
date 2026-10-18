"""Backend-wide constants package.

Sits alongside the flat-module convention used elsewhere under backend/app/
(config.py, db.py). Currently holds only the SINAN classification decode
dictionaries (backend/app/constants/sinan.py); re-exported here for a
shorter import path (`from app.constants import decode_classi_fin`).
"""

from app.constants.sinan import (
    CLASSI_FIN_LABELS,
    TP_ACIDENTE_LABELS,
    TRA_CLASSI_LABELS,
    UNKNOWN_CODE_TEMPLATE,
    decode_classi_fin,
    decode_tp_acidente,
    decode_tra_classi,
)

__all__ = [
    "CLASSI_FIN_LABELS",
    "TP_ACIDENTE_LABELS",
    "TRA_CLASSI_LABELS",
    "UNKNOWN_CODE_TEMPLATE",
    "decode_classi_fin",
    "decode_tp_acidente",
    "decode_tra_classi",
]
