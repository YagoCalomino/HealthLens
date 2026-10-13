"""Unit tests for the per-agravo SINAN classification decode module
(app/constants/sinan.py).

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_app_constants_sinan.py -v
"""

from app.constants.sinan import (
    CLASSI_FIN_LABELS,
    decode_classi_fin,
    decode_tp_acidente,
    decode_tra_classi,
)


def test_decode_classi_fin_returns_nonempty_label_for_deng_and_chik():
    deng_label = decode_classi_fin("DENG", 12)
    chik_label = decode_classi_fin("CHIK", 13)

    assert deng_label and isinstance(deng_label, str)
    assert chik_label and isinstance(chik_label, str)


def test_classi_fin_labels_are_distinct_dicts_with_different_keys():
    assert "DENG" in CLASSI_FIN_LABELS
    assert "CHIK" in CLASSI_FIN_LABELS
    assert CLASSI_FIN_LABELS["DENG"] is not CLASSI_FIN_LABELS["CHIK"]
    assert set(CLASSI_FIN_LABELS["DENG"]) != set(CLASSI_FIN_LABELS["CHIK"])


def test_anim_absent_from_classi_fin_labels_and_decode_returns_none():
    assert "ANIM" not in CLASSI_FIN_LABELS
    assert decode_classi_fin("ANIM", 1) is None


def test_decode_classi_fin_unknown_code_returns_fallback_and_never_raises():
    result = decode_classi_fin("DENG", 9999)

    assert result is not None
    assert "9999" in result


def test_decode_classi_fin_missing_values_return_none():
    assert decode_classi_fin("DENG", None) is None
    assert decode_classi_fin("DENG", "") is None
    assert decode_classi_fin("DENG", "None") is None


def test_decode_tra_classi_known_codes():
    assert decode_tra_classi(3) == "Grave"
    assert decode_tra_classi(9) == "Ignorado"


def test_decode_tp_acidente_covers_observed_codes_and_falls_back():
    # Codes observed in docs/pysus-270-sinan-spike-findings.md ANIM.TP_ACIDENT
    for codigo in (1, 2, 3, 4, 5, 6, 9):
        label = decode_tp_acidente(codigo)
        assert label is not None
        assert "não documentado" not in label

    fallback = decode_tp_acidente(777)
    assert "777" in fallback


def test_all_observed_deng_and_chik_classi_fin_codes_resolve_to_real_labels():
    # Codes observed in docs/pysus-270-sinan-spike-findings.md CLASSI_FIN
    # value_counts (excluding the blank/"None"-string missing buckets).
    observed_deng = (10, 8, 11, 0, 12)
    observed_chik = (13, 5, 0)

    for codigo in observed_deng:
        label = decode_classi_fin("DENG", codigo)
        assert label is not None
        assert "não documentado" not in label

    for codigo in observed_chik:
        label = decode_classi_fin("CHIK", codigo)
        assert label is not None
        assert "não documentado" not in label


def test_decode_classi_fin_case_insensitive_tipo_agravo():
    assert decode_classi_fin("deng", 10) == decode_classi_fin("DENG", 10)
