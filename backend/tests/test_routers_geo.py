def test_listar_ufs_sample_mode_returns_503(client):
    response = client.get("/geo/ufs")
    assert response.status_code == 503


def test_listar_municipios_sample_mode_returns_503(client):
    response = client.get("/geo/ufs/SP/municipios")
    assert response.status_code == 503


def test_openapi_docs_accessible(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_redoc_disabled(client):
    # ReDoc disabled (redoc_url=None) — cdn.jsdelivr.net blocked on restricted networks
    response = client.get("/redoc")
    assert response.status_code == 404
