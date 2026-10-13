import gzip
import json
from unittest.mock import MagicMock, patch

from seeds.ibge_loader import _fetch_municipios

_SAMPLE_PAYLOAD = [
    {
        "id": 3550308,
        "nome": "São Paulo",
        "microrregiao": {
            "mesorregiao": {
                "UF": {
                    "sigla": "SP",
                    "nome": "São Paulo",
                    "id": 35,
                }
            }
        },
    }
]


def _make_mock_resp(body_bytes, encoding):
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body_bytes
    mock_info = MagicMock()
    mock_info.get.side_effect = (
        lambda key, default="": encoding if key == "Content-Encoding" else default
    )
    mock_resp.info.return_value = mock_info
    return mock_resp


def test_fetch_municipios_handles_gzip_response():
    compressed = gzip.compress(json.dumps(_SAMPLE_PAYLOAD).encode())
    mock_resp = _make_mock_resp(compressed, "gzip")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_municipios()
    assert len(result) == 1
    assert result[0]["id"] == 3550308


def test_fetch_municipios_handles_plain_response():
    plain = json.dumps(_SAMPLE_PAYLOAD).encode()
    mock_resp = _make_mock_resp(plain, "")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _fetch_municipios()
    assert len(result) == 1
    assert result[0]["id"] == 3550308
