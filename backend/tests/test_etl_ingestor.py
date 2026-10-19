"""Unit tests for etl.ingestor (DataSUS FTP downloader with local Parquet fallback).

All tests are pure-Python / mocked-pysus — no network access or database required.
Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_ingestor.py -v
"""

import hashlib
from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

import etl.ingestor as ingestor
from etl.ingestor import (
    _fetch_sih_rd,
    _fetch_sinan,
    compute_md5,
    get_or_download_sih,
    get_or_download_sim,
    get_or_download_sinan,
)


def test_ingestor_does_not_import_sih():
    """The broken sih(group="RD") convenience function must not be importable
    from this module's namespace at all — SIH fetches go through the
    low-level PySUS() client + _fetch_sih_rd instead.
    """
    assert not hasattr(ingestor, "sih")


def test_compute_md5_matches_hashlib(tmp_path):
    path = tmp_path / "sample.parquet"
    path.write_bytes(b"some binary parquet-like content")
    expected = hashlib.md5(b"some binary parquet-like content").hexdigest()
    assert compute_md5(path) == expected


def test_compute_md5_reads_in_chunks_for_large_file(tmp_path):
    path = tmp_path / "large.bin"
    payload = b"x" * (8192 * 3 + 17)  # spans multiple 8KB chunks
    path.write_bytes(payload)
    assert compute_md5(path) == hashlib.md5(payload).hexdigest()


def test_get_or_download_sim_uses_local_file_when_present(tmp_path):
    raw_dir = tmp_path
    parquet_path = raw_dir / "SIM_SP_2022.parquet"
    parquet_path.write_bytes(b"fake-parquet-bytes")

    with patch("etl.ingestor.sim") as mock_sim:
        result = get_or_download_sim("SP", 2022, raw_dir)
        mock_sim.assert_not_called()

    assert result is not None
    path, md5 = result
    assert path == parquet_path
    assert md5 == hashlib.md5(b"fake-parquet-bytes").hexdigest()


def test_get_or_download_sim_downloads_when_absent(tmp_path):
    raw_dir = tmp_path
    df = pd.DataFrame({"NUMERODO": ["1", "2"]})

    with patch("etl.ingestor.sim", return_value=df) as mock_sim:
        result = get_or_download_sim("SP", 2022, raw_dir)

    mock_sim.assert_called_once_with(
        state="SP", year=2022, as_dataframe=True, show_progress=False
    )
    assert result is not None
    path, _md5 = result
    assert path == raw_dir / "SIM_SP_2022.parquet"
    assert path.exists()


def test_get_or_download_sim_returns_none_on_empty_catalog(tmp_path):
    raw_dir = tmp_path
    empty_df = pd.DataFrame()

    with patch("etl.ingestor.sim", return_value=empty_df):
        result = get_or_download_sim("AC", 2022, raw_dir)

    assert result is None
    assert not (raw_dir / "SIM_AC_2022.parquet").exists()


def test_get_or_download_sim_returns_none_on_download_error(tmp_path):
    raw_dir = tmp_path

    with patch("etl.ingestor.sim", side_effect=RuntimeError("network unreachable")):
        result = get_or_download_sim("SP", 2022, raw_dir)

    assert result is None


def test_get_or_download_sih_uses_local_file_when_present(tmp_path):
    raw_dir = tmp_path
    parquet_path = raw_dir / "SIH_SP_2022.parquet"
    parquet_path.write_bytes(b"fake-sih-bytes")

    with patch("etl.ingestor._fetch_sih_rd") as mock_fetch:
        result = get_or_download_sih("SP", 2022, raw_dir)
        mock_fetch.assert_not_called()

    assert result is not None
    path, md5 = result
    assert path == parquet_path
    assert md5 == hashlib.md5(b"fake-sih-bytes").hexdigest()


def test_get_or_download_sih_downloads_when_absent(tmp_path):
    raw_dir = tmp_path
    df = pd.DataFrame({"N_AIH": ["1"], "IDENT": [1]})

    with patch("etl.ingestor._fetch_sih_rd", return_value=df) as mock_fetch:
        result = get_or_download_sih("SP", 2022, raw_dir)

    mock_fetch.assert_called_once_with("SP", 2022, list(range(1, 13)))
    assert result is not None
    path, _md5 = result
    assert path == raw_dir / "SIH_SP_2022.parquet"
    assert path.exists()


def test_get_or_download_sih_returns_none_on_empty_catalog(tmp_path):
    raw_dir = tmp_path
    empty_df = pd.DataFrame()

    with patch("etl.ingestor._fetch_sih_rd", return_value=empty_df):
        result = get_or_download_sih("AC", 2022, raw_dir)

    assert result is None


def test_get_or_download_sih_returns_none_when_fetch_returns_none(tmp_path):
    raw_dir = tmp_path

    with patch("etl.ingestor._fetch_sih_rd", return_value=None):
        result = get_or_download_sih("SP", 2022, raw_dir)

    assert result is None
    assert not (raw_dir / "SIH_SP_2022.parquet").exists()


def test_get_or_download_sih_returns_none_on_download_error(tmp_path):
    raw_dir = tmp_path

    with patch(
        "etl.ingestor._fetch_sih_rd", side_effect=RuntimeError("network unreachable")
    ):
        result = get_or_download_sih("SP", 2022, raw_dir)

    assert result is None


def _make_fake_file(name: str) -> MagicMock:
    fake_file = MagicMock()
    fake_file.path.name = name
    return fake_file


def test_fetch_sih_rd_downloads_only_rd_prefixed_files():
    rd_file = _make_fake_file("RDSE2301.parquet")
    sp_file = _make_fake_file("SPSE2301.parquet")
    rj_file = _make_fake_file("RJSE2301.parquet")
    er_file = _make_fake_file("ERSE2301.parquet")

    fake_local = MagicMock()
    fake_local.path = "downloaded/RDSE2301.parquet"

    fake_df = pd.DataFrame({"N_AIH": ["1"], "IDENT": [1]})
    fake_read_result = MagicMock()
    fake_read_result.df.return_value = fake_df

    fake_client = MagicMock()
    fake_client.query = AsyncMock(return_value=[rd_file, sp_file, rj_file, er_file])
    fake_client.download = AsyncMock(return_value=fake_local)
    fake_client.read_parquet = MagicMock(return_value=fake_read_result)

    fake_client_cm = AsyncMock()
    fake_client_cm.__aenter__.return_value = fake_client

    with patch("etl.ingestor.PySUS", return_value=fake_client_cm):
        result = _fetch_sih_rd("SE", 2023, list(range(1, 13)))

    fake_client.download.assert_called_once_with(rd_file)
    fake_client.read_parquet.assert_called_once_with(
        ["downloaded/RDSE2301.parquet"], add_dv=False
    )
    assert result is fake_df


def test_get_or_download_sinan_uses_local_file_when_present(tmp_path):
    raw_dir = tmp_path
    parquet_path = raw_dir / "SINAN_ANIM_2023.parquet"
    parquet_path.write_bytes(b"fake-sinan-bytes")

    with patch("etl.ingestor._fetch_sinan") as mock_sinan:
        result = get_or_download_sinan("ANIM", 2023, raw_dir)
        mock_sinan.assert_not_called()

    assert result is not None
    path, md5 = result
    assert path == parquet_path
    assert md5 == hashlib.md5(b"fake-sinan-bytes").hexdigest()


def test_get_or_download_sinan_downloads_when_absent(tmp_path):
    raw_dir = tmp_path
    df = pd.DataFrame({"ID_MN_RESI": ["354990", "355030"]})

    with patch("etl.ingestor._fetch_sinan", return_value=df) as mock_sinan:
        result = get_or_download_sinan("DENG", 2023, raw_dir)

    mock_sinan.assert_called_once_with("DENG", 2023)

    assert result is not None
    path, _md5 = result
    assert path == raw_dir / "SINAN_DENG_2023.parquet"
    assert path.exists()


def test_get_or_download_sinan_uppercases_lowercase_disease(tmp_path):
    raw_dir = tmp_path
    df = pd.DataFrame({"ID_MN_RESI": ["354990"]})

    with patch("etl.ingestor._fetch_sinan", return_value=df) as mock_sinan:
        result = get_or_download_sinan("deng", 2023, raw_dir)

    assert mock_sinan.call_args.args[0] == "DENG"
    assert result is not None
    path, _md5 = result
    assert path == raw_dir / "SINAN_DENG_2023.parquet"


def test_get_or_download_sinan_returns_none_on_empty_catalog(tmp_path):
    raw_dir = tmp_path
    empty_df = pd.DataFrame()

    with patch("etl.ingestor._fetch_sinan", return_value=empty_df):
        result = get_or_download_sinan("ANIM", 2023, raw_dir)

    assert result is None
    assert not (raw_dir / "SINAN_ANIM_2023.parquet").exists()


def test_get_or_download_sinan_returns_none_on_download_error(tmp_path):
    raw_dir = tmp_path

    with patch(
        "etl.ingestor._fetch_sinan", side_effect=RuntimeError("network unreachable")
    ):
        result = get_or_download_sinan("DENG", 2023, raw_dir)

    assert result is None


def test_get_or_download_sinan_returns_none_when_result_not_dataframe(tmp_path):
    raw_dir = tmp_path

    with patch("etl.ingestor._fetch_sinan", return_value=["not-a-dataframe.parquet"]):
        result = get_or_download_sinan("DENG", 2023, raw_dir)

    assert result is None
    assert not (raw_dir / "SINAN_DENG_2023.parquet").exists()


def _make_fake_sinan_file(source: str, name: str) -> MagicMock:
    fake_file = MagicMock()
    fake_file.path = PurePosixPath(f"public/data/{source}/sinan/X/2025/_/BR/{name}")
    return fake_file


def _fake_pysus_client(files: list) -> tuple[MagicMock, AsyncMock]:
    fake_local = MagicMock()
    fake_local.path = "downloaded/file.parquet"
    fake_read_result = MagicMock()
    fake_read_result.df.return_value = pd.DataFrame({"ID_MN_RESI": ["354990"]})

    fake_client = MagicMock()
    fake_client.query = AsyncMock(return_value=files)
    fake_client.download = AsyncMock(return_value=fake_local)
    fake_client.read_parquet = MagicMock(return_value=fake_read_result)

    fake_client_cm = AsyncMock()
    fake_client_cm.__aenter__.return_value = fake_client
    return fake_client, fake_client_cm


def test_fetch_sinan_downloads_single_copy_preferring_ftp_source():
    # pysus lists the same file from two sources that download to the same
    # local path; fetching both corrupts the read (TProtocolException).
    dadosgov = _make_fake_sinan_file("dadosgov", "CHIKBR25.parquet")
    ftp = _make_fake_sinan_file("ftp", "CHIKBR25.parquet")
    other = _make_fake_sinan_file("ftp", "DENGBR25.parquet")
    fake_client, fake_client_cm = _fake_pysus_client([dadosgov, other, ftp])

    with patch("etl.ingestor.PySUS", return_value=fake_client_cm):
        result = _fetch_sinan("CHIK", 2025)

    fake_client.download.assert_called_once_with(ftp)
    fake_client.read_parquet.assert_called_once_with(
        ["downloaded/file.parquet"], add_dv=False
    )
    assert list(result.columns) == ["ID_MN_RESI"]


def test_fetch_sinan_falls_back_to_other_source_when_no_ftp_copy():
    dadosgov = _make_fake_sinan_file("dadosgov", "DENGBR25.parquet")
    fake_client, fake_client_cm = _fake_pysus_client([dadosgov])

    with patch("etl.ingestor.PySUS", return_value=fake_client_cm):
        _fetch_sinan("DENG", 2025)

    fake_client.download.assert_called_once_with(dadosgov)


def test_fetch_sinan_returns_none_when_disease_absent():
    other = _make_fake_sinan_file("ftp", "ANIMBR25.parquet")
    fake_client, fake_client_cm = _fake_pysus_client([other])

    with patch("etl.ingestor.PySUS", return_value=fake_client_cm):
        result = _fetch_sinan("CHIK", 2025)

    assert result is None
    fake_client.download.assert_not_called()


def test_fetch_sih_rd_returns_none_when_no_rd_files():
    sp_file = _make_fake_file("SPSE2301.parquet")
    rj_file = _make_fake_file("RJSE2301.parquet")
    er_file = _make_fake_file("ERSE2301.parquet")

    fake_client = MagicMock()
    fake_client.query = AsyncMock(return_value=[sp_file, rj_file, er_file])
    fake_client.download = AsyncMock()
    fake_client.read_parquet = MagicMock()

    fake_client_cm = AsyncMock()
    fake_client_cm.__aenter__.return_value = fake_client

    with patch("etl.ingestor.PySUS", return_value=fake_client_cm):
        result = _fetch_sih_rd("SE", 2023, list(range(1, 13)))

    assert result is None
    fake_client.download.assert_not_called()
