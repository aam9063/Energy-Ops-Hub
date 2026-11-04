"""Tests de integración de `POST /sync/hubspot` (docs/spec.md, sección 12).

PostgreSQL real (docker compose) y HubSpot simulado con `respx`. Cubre: actualizar el
estado solo cuando la fase cambió, ignorar fases desconocidas, no retroceder por una
respuesta vieja, actualizar la marca de la última sincronización correcta y no
actualizarla cuando HubSpot falla (la API responde 503, reintenable).
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx
from app.config import settings
from app.db import SessionLocal
from app.domain.cups import letras_control
from app.main import app
from app.models import Cliente, EventoSync, Suministro
from app.services import hubspot as modulo_hubspot
from app.services.hubspot import HubSpot
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete, func, select

NIF = "T07SYNC01"
BASE = "https://api.hubapi.com"
TOKEN = "hs-token-de-test"
_DIGITOS_A = "0123456789012345"
_DIGITOS_B = "5432109876543210"
_DIGITOS_C = "1111222233334444"
CUPS_A = "ES" + _DIGITOS_A + letras_control(_DIGITOS_A)
CUPS_B = "ES" + _DIGITOS_B + letras_control(_DIGITOS_B)
CUPS_C = "ES" + _DIGITOS_C + letras_control(_DIGITOS_C)
# Fase de negocio en HubSpot → estado de suministro (lo que iría en HS_MAPA_ESTADOS).
MAPA = {
    "stage-pendiente": "pendiente",
    "stage-en-tramite": "en_tramite",
    "stage-activo": "activo",
}


@pytest.fixture(autouse=True)
def entorno_hubspot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token y mapa de fases de prueba; el cliente compartido lleva el token simulado."""
    monkeypatch.setattr(settings, "hubspot_token", TOKEN)
    monkeypatch.setattr(settings, "hs_mapa_estados", dict(MAPA))
    monkeypatch.setattr(modulo_hubspot, "_cliente", HubSpot(token=TOKEN))


@pytest.fixture(autouse=True)
def esperas(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Sustituye la espera del reintento para que los tests no duerman de verdad."""
    dormidas: list[float] = []
    monkeypatch.setattr(modulo_hubspot.time, "sleep", dormidas.append)
    return dormidas


def _limpiar() -> None:
    with SessionLocal() as sesion:
        sesion.execute(delete(Suministro).where(Suministro.cups.in_([CUPS_A, CUPS_B, CUPS_C])))
        sesion.execute(delete(Cliente).where(Cliente.nif == NIF))
        sesion.execute(delete(EventoSync).where(EventoSync.sistema == "hubspot"))
        sesion.commit()


@pytest.fixture(autouse=True)
def limpiar() -> Iterator[None]:
    yield
    _limpiar()


def _cartera() -> None:
    """Un cliente con empresa y tres suministros: dos pendientes (hace 1 h) y uno activo."""
    hace_una_hora = datetime.now(UTC) - timedelta(hours=1)
    with SessionLocal() as sesion:
        cliente = Cliente(nombre="Cliente sync", nif=NIF, hubspot_company_id="77")
        sesion.add(cliente)
        sesion.flush()
        sesion.add(
            Suministro(
                cliente_id=cliente.id,
                cups=CUPS_A,
                tipo="luz",
                direccion="Calle Falsa 123",
                estado="pendiente",
                estado_desde=hace_una_hora,
            )
        )
        sesion.add(
            Suministro(
                cliente_id=cliente.id,
                cups=CUPS_B,
                tipo="gas",
                direccion="Calle Falsa 125",
                estado="pendiente",
                estado_desde=hace_una_hora,
            )
        )
        sesion.add(
            Suministro(
                cliente_id=cliente.id,
                cups=CUPS_C,
                tipo="luz",
                direccion="Calle Falsa 127",
                estado="activo",
                estado_desde=datetime.now(UTC),
            )
        )
        sesion.commit()


def _negocio(id_negocio: str, cups: str, fase: str, iso: str) -> dict[str, Any]:
    return {
        "id": id_negocio,
        "properties": {"cups": cups, "dealstage": fase, "hs_lastmodifieddate": iso},
    }


def _paginar(negocios: list[dict[str, Any]]) -> Response:
    return Response(200, json={"results": negocios, "total": len(negocios)})


def _ruta_buscar() -> Any:
    return respx.post(f"{BASE}/crm/v3/objects/deals/search")


@respx.mock
def test_sync_actualiza_solo_si_cambia_la_fase() -> None:
    """La fase nueva se aplica; la misma fase y el mismo estado se cuentan como omitidos."""
    _cartera()
    ahora = datetime.now(UTC).isoformat()
    _ruta_buscar().mock(
        return_value=_paginar(
            [
                _negocio("1", CUPS_A, "stage-en-tramite", ahora),  # cambia → actualiza
                _negocio("2", CUPS_B, "stage-pendiente", ahora),  # misma fase → omitido
                _negocio("3", CUPS_C, "stage-activo", ahora),  # mismo estado → omitido
            ]
        )
    )
    with SessionLocal() as sesion:
        b_antes = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_B))
        assert b_antes is not None
        estado_desde_b = b_antes.estado_desde

    respuesta = TestClient(app).post("/sync/hubspot")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "revisados": 3,
        "actualizados": 1,
        "omitidos": 2,
        "errores": 0,
    }
    with SessionLocal() as sesion:
        a = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_A))
        b = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_B))
        c = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_C))
        assert a is not None
        assert a.estado == "en_tramite"
        assert a.estado_desde is not None
        assert b is not None
        assert b.estado == "pendiente"
        assert b.estado_desde == estado_desde_b  # no se toca estado_desde sin cambio
        assert c is not None
        assert c.estado == "activo"


@respx.mock
def test_sync_ignora_fases_desconocidas() -> None:
    """Una fase que no está en `hs_mapa_estados` se omite y no toca el suministro."""
    _cartera()
    ahora = datetime.now(UTC).isoformat()
    _ruta_buscar().mock(
        return_value=_paginar([_negocio("1", CUPS_A, "stage-que-no-existe", ahora)])
    )

    respuesta = TestClient(app).post("/sync/hubspot")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"revisados": 1, "actualizados": 0, "omitidos": 1, "errores": 0}
    with SessionLocal() as sesion:
        a = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_A))
        assert a is not None
        assert a.estado == "pendiente"


@respx.mock
def test_sync_no_retrocede_por_respuesta_vieja() -> None:
    """Un negocio modificado antes de `estado_desde` es una respuesta vieja: no lo pisa."""
    _cartera()
    vieja = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    _ruta_buscar().mock(return_value=_paginar([_negocio("3", CUPS_C, "stage-pendiente", vieja)]))
    with SessionLocal() as sesion:
        c_antes = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_C))
        assert c_antes is not None
        estado_desde_c = c_antes.estado_desde

    respuesta = TestClient(app).post("/sync/hubspot")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"revisados": 1, "actualizados": 0, "omitidos": 1, "errores": 0}
    with SessionLocal() as sesion:
        c = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_C))
        assert c is not None
        assert c.estado == "activo"
        assert c.estado_desde == estado_desde_c


@respx.mock
def test_sync_actualiza_la_marca_y_la_usa_en_la_siguiente() -> None:
    """La marca de la última sincronización correcta queda guardada y se filtra por ella."""
    _cartera()
    buscar = _ruta_buscar().mock(return_value=_paginar([]))
    cliente_http = TestClient(app)

    primera = cliente_http.post("/sync/hubspot")
    assert primera.status_code == 200
    with SessionLocal() as sesion:
        marca = sesion.scalar(
            select(EventoSync)
            .where(
                EventoSync.sistema == "hubspot",
                EventoSync.operacion == "sync_marca",
                EventoSync.ok.is_(True),
            )
            .order_by(EventoSync.id.desc())
        )
        assert marca is not None
        assert marca.detalle is not None
        valor_marca = str(marca.detalle["desde"])

    segunda = cliente_http.post("/sync/hubspot")
    assert segunda.status_code == 200
    cuerpo = buscar.calls.last.request.read()
    assert valor_marca.encode() in cuerpo  # el filtro GTE usa la marca guardada


@respx.mock
def test_hubspot_agotado_responde_503_y_no_actualiza_la_marca(
    esperas: list[float],
) -> None:
    """HubSpot caído: la API responde 503, deja el evento `ok=False` y no mueve la marca."""
    _cartera()
    _ruta_buscar().mock(return_value=Response(500))

    respuesta = TestClient(app).post("/sync/hubspot")

    assert respuesta.status_code == 503
    assert esperas == [1.0, 2.0, 4.0, 8.0]  # se agotaron los cinco intentos
    with SessionLocal() as sesion:
        marcas = sesion.scalar(
            select(func.count())
            .select_from(EventoSync)
            .where(
                EventoSync.sistema == "hubspot",
                EventoSync.operacion == "sync_marca",
            )
        )
        assert marcas == 0  # la marca no se actualiza si el sync no termina bien
        fallo = sesion.scalar(
            select(EventoSync).where(
                EventoSync.sistema == "hubspot",
                EventoSync.operacion == "sync_estados",
                EventoSync.ok.is_(False),
            )
        )
        assert fallo is not None
