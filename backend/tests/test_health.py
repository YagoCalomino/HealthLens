import os
import sys

import pytest


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "sample_mode" in body


def test_health_sample_mode_true_when_env_set(client):
    # conftest sets SAMPLE_MODE=true before import
    assert client.get("/health").json()["sample_mode"] is True


def test_cors_wildcard_raises_at_import():
    os.environ["CORS_ORIGINS"] = "*"
    # Remove cached module to force re-import
    for mod in list(sys.modules.keys()):
        if "app.main" in mod or "app.config" in mod:
            del sys.modules[mod]
    try:
        with pytest.raises(ValueError, match="CORS_ORIGINS"):
            import app.main  # noqa: F401
    finally:
        os.environ["CORS_ORIGINS"] = "http://localhost:5173"
        for mod in list(sys.modules.keys()):
            if "app.main" in mod or "app.config" in mod:
                del sys.modules[mod]
