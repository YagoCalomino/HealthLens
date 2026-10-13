from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)

# Imports below must run after load_dotenv: app.config reads the environment at import time.
import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi_pagination import add_pagination  # noqa: E402

from app.config import settings  # noqa: E402
from app.routers import (  # noqa: E402
    geo,
    indicadores,
    forecasts,
    clusters,
    risco_prospectivo,
    notificacoes,
)

# CORS wildcard guard — enforced before app creation
# Raises at startup if CORS_ORIGINS='*' to prevent allow_origins=["*"] + allow_credentials=True
# which would cause a runtime error on first request.
if settings.cors_origins.strip() == "*":
    raise ValueError(
        "CORS_ORIGINS='*' with allow_credentials=True is forbidden. "
        "Set CORS_ORIGINS to explicit origin(s), e.g. 'http://localhost:5173'"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("healthlens")
    logger.info(
        f"HealthLens starting. sample_mode={settings.sample_mode}, "
        f"cors_origins={settings.cors_origins}"
    )
    if not settings.sample_mode:
        from app.db import _get_engine

        _eng, _factory = _get_engine()
        async with _factory() as _sess:
            from sqlalchemy import text as _text

            # Executa a query real para asyncpg registrar os type codecs
            # antes da 1a requisicao HTTP chegar
            await _sess.execute(
                _text(
                    "SELECT ano_epidemiologico, semana_epidemiologica, "
                    "total_notificacoes, total_populacao "
                    "FROM mv_curva_epidemica_semana "
                    "WHERE agravo = 'DENG' LIMIT 1"
                )
            )
        logger.info("Connection pool and type codecs warmed up")
    yield


app = FastAPI(
    title="HealthLens API", version="0.1.0", redoc_url=None, lifespan=lifespan
)

origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(geo.router)
app.include_router(indicadores.router)
app.include_router(forecasts.router)
app.include_router(clusters.router)
app.include_router(risco_prospectivo.router)
app.include_router(notificacoes.router)

add_pagination(app)


@app.get("/health")
async def health():
    return {"status": "ok", "sample_mode": settings.sample_mode}
