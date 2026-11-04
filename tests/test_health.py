"""Tests de `/health` y del middleware de API key."""

import pytest
from app.config import Settings
from app.main import app, create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_health_ok_con_base_de_datos_accesible() -> None:
    with TestClient(app) as cliente:
        respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok", "database": "ok"}


def test_health_devuelve_503_si_la_base_de_datos_no_responde(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.database_ok", lambda: False)

    with TestClient(app) as cliente:
        respuesta = cliente.get("/health")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "degraded", "database": "error"}


def _app_con_ruta_protegida() -> FastAPI:
    app_prueba = create_app(Settings(api_key="clave-de-prueba"))

    @app_prueba.get("/protegida")
    def protegida() -> dict[str, str]:
        return {"ok": "sí"}

    return app_prueba


def test_ruta_protegida_sin_api_key_da_401() -> None:
    with TestClient(_app_con_ruta_protegida()) as cliente:
        respuesta = cliente.get("/protegida")

    assert respuesta.status_code == 401


def test_ruta_protegida_con_api_key_incorrecta_da_401() -> None:
    with TestClient(_app_con_ruta_protegida()) as cliente:
        respuesta = cliente.get("/protegida", headers={"X-API-Key": "otra"})

    assert respuesta.status_code == 401


def test_ruta_protegida_con_api_key_correcta_pasa() -> None:
    with TestClient(_app_con_ruta_protegida()) as cliente:
        respuesta = cliente.get("/protegida", headers={"X-API-Key": "clave-de-prueba"})

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": "sí"}


def test_health_es_publico_aunque_haya_api_key() -> None:
    with TestClient(_app_con_ruta_protegida()) as cliente:
        respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
