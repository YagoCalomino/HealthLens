import os
import pytest

# Set SAMPLE_MODE before any app import to avoid DB connection attempts during tests
os.environ.setdefault("SAMPLE_MODE", "true")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

# Pre-import statsforecast and coreforecast C extensions before pytest assertion rewriting
# runs exec_module on ML test files. On Windows, coreforecast.exponentially_weighted
# (a .pyd DLL) causes an access violation when first imported inside the assertion
# rewriter's exec() context. Pre-loading here ensures the DLL is already resident in
# sys.modules before any ML test file is collected.
import coreforecast.exponentially_weighted  # noqa: F401
import statsforecast.models  # noqa: F401


@pytest.fixture(scope="session")
def client():
    # Deferred import: only executed when this fixture is requested (e.g., by API
    # tests). ML-only test runs (pytest tests/test_ml_*.py) will not trigger
    # FastAPI startup if the fixture is never requested.
    from fastapi.testclient import TestClient
    from app.main import app  # noqa: E402 — import after env setup

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_data_dir():
    return os.environ.get("SAMPLE_DATA_DIR", "data/sample")
