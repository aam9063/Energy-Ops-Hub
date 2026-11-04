"""Aplicación FastAPI: middleware de API key y `/health`."""

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.config import Settings, settings
from app.db import engine

logger = logging.getLogger(__name__)

# Rutas sin credenciales: el smoke test del despliegue y la documentación.
RUTAS_PUBLICAS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


def database_ok() -> bool:
    """True si la base de datos responde a una consulta trivial."""
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("La base de datos no responde")
        return False
    return True


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Exige la cabecera `X-API-Key`, salvo en las rutas públicas.

    Si no hay `API_KEY` configurada la API queda abierta: es el modo local y de tests.
    """

    def __init__(self, app: ASGIApp, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ruta = request.url.path
        if not self.api_key or ruta in RUTAS_PUBLICAS or ruta.startswith("/docs"):
            return await call_next(request)

        recibida = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(recibida, self.api_key):
            return JSONResponse({"detail": "API key inválida o ausente"}, status_code=401)
        return await call_next(request)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """Construye la aplicación. Recibe los ajustes para poder inyectarlos en los tests."""
    configuracion = app_settings or settings
    aplicacion = FastAPI(
        title="Energy Ops Hub",
        version="0.1.0",
        summary="Automatización de operaciones energéticas para carteras inmobiliarias",
    )
    aplicacion.add_middleware(ApiKeyMiddleware, api_key=configuracion.api_key)

    @aplicacion.get("/health", tags=["sistema"])
    def health() -> JSONResponse:
        if database_ok():
            return JSONResponse({"status": "ok", "database": "ok"})
        return JSONResponse({"status": "degraded", "database": "error"}, status_code=503)

    return aplicacion


app = create_app()
