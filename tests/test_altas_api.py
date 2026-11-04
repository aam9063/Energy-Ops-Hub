"""Tests de integración de `POST /altas/lote` (docs/spec.md, sección 15).

PostgreSQL real (docker compose) y HubSpot simulado con `respx`: ninguna prueba toca la
red. Cada test limpia las filas que crea (clientes, suministros y eventos de sync).
"""

import re
from collections.abc import Iterator
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

NIF = "T07TEST01"
NIF_SIN_EMPRESA = "T07TEST02"
_DIGITOS_A = "0123456789012345"
_DIGITOS_B = "5432109876543210"
CUPS_A = "ES" + _DIGITOS_A + letras_control(_DIGITOS_A)
CUPS_B = "ES" + _DIGITOS_B + letras_control(_DIGITOS_B)
CUPS_MALO = "ES" + _DIGITOS_A + "ZZ"
BASE = "https://api.hubapi.com"
TOKEN = "hs-token-de-test"


@pytest.fixture(autouse=True)
def entorno_hubspot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token y configuración de prueba; el cliente compartido lleva el token simulado."""
    monkeypatch.setattr(settings, "hubspot_token", TOKEN)
    monkeypatch.setattr(settings, "hs_pipeline_altas", "pipe-altas")
    monkeypatch.setattr(settings, "hs_stage_pendiente", "stage-pendiente")
    monkeypatch.setattr(settings, "hs_mapa_estados", {})
    monkeypatch.setattr(modulo_hubspot, "_cliente", HubSpot(token=TOKEN))


def _limpiar() -> None:
    with SessionLocal() as sesion:
        sesion.execute(delete(Suministro).where(Suministro.cups.in_([CUPS_A, CUPS_B])))
        sesion.execute(delete(Cliente).where(Cliente.nif.in_([NIF, NIF_SIN_EMPRESA])))
        sesion.execute(delete(EventoSync).where(EventoSync.sistema == "hubspot"))
        sesion.commit()


@pytest.fixture(autouse=True)
def limpiar() -> Iterator[None]:
    yield
    _limpiar()


def _crear_clientes() -> None:
    """Un cliente con empresa en HubSpot y otro sin ella."""
    with SessionLocal() as sesion:
        sesion.add(Cliente(nombre="Cliente con empresa", nif=NIF, hubspot_company_id="77"))
        sesion.add(Cliente(nombre="Cliente sin empresa", nif=NIF_SIN_EMPRESA))
        sesion.commit()


def _fila(**extra: Any) -> dict[str, Any]:
    valores: dict[str, Any] = {
        "fila": 2,
        "cliente_nif": NIF,
        "cups": CUPS_A,
        "tipo": "luz",
        "direccion": "Calle Falsa 123",
        "tarifa_acceso": "2.0TD",
        "potencia_kw": 5.5,
    }
    valores.update(extra)
    return valores


def _mock_hubspot_crea() -> None:
    """La búsqueda no encuentra nada y la creación devuelve ids secuenciales."""
    buscar = respx.post(f"{BASE}/crm/v3/objects/deals/search")
    buscar.side_effect = [
        Response(200, json={"results": []}),
        Response(200, json={"results": []}),
        Response(200, json={"results": []}),
        Response(200, json={"results": []}),
    ]
    crear = respx.post(f"{BASE}/crm/v3/objects/deals")
    crear.side_effect = [
        Response(200, json={"id": "1001"}),
        Response(200, json={"id": "1002"}),
    ]
    respx.put(
        re.compile(rf"^{BASE}/crm/v4/objects/deals/\d+/associations/default/companies/77$")
    ).mock(return_value=Response(200, json={}))


@respx.mock
def test_lote_mixto_valida_fila_a_fila() -> None:
    """Las filas malas no abortan el lote: cada una lleva su mensaje y las buenas se crean."""
    _crear_clientes()
    _mock_hubspot_crea()
    cliente_http = TestClient(app)
    filas = [
        _fila(fila=10),
        _fila(fila=5, cups=CUPS_MALO),
        _fila(fila=7, cups=CUPS_B, tipo="viento"),
        _fila(fila=3, cups=CUPS_B, tipo="gas", cliente_nif=NIF_SIN_EMPRESA),
    ]

    respuesta = cliente_http.post("/altas/lote", json={"filas": filas})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resumen"] == {
        "recibidas": 4,
        "creadas": 1,
        "actualizadas": 0,
        "errores": 3,
    }
    resultados = cuerpo["resultados"]
    # Eco exacto: cada resultado devuelve el `fila` que mandó el cliente, aunque
    # el lote venga desordenado.
    assert [r["fila"] for r in resultados] == [10, 5, 7, 3]
    assert resultados[0]["ok"] is True
    assert resultados[0]["cups"] == CUPS_A
    assert resultados[0]["hubspot_deal_id"] == "1001"
    assert resultados[1]["ok"] is False
    assert "CUPS inválido" in resultados[1]["mensaje"]
    assert "Tipo inválido" in resultados[2]["mensaje"]
    assert "empresa" in resultados[3]["mensaje"]

    # Auditoría: un evento por lote y uno por cada fila fallida, sin datos personales.
    with SessionLocal() as sesion:
        eventos = sesion.scalars(
            select(EventoSync).where(EventoSync.sistema == "hubspot").order_by(EventoSync.id)
        ).all()
        lote = [e for e in eventos if e.operacion == "altas_lote"]
        assert len(lote) == 1
        assert lote[0].ok is False  # el lote terminó con 3 filas fallidas
        assert lote[0].detalle == {"recibidas": 4, "creadas": 1, "actualizadas": 0, "errores": 3}
        fallidas = [e for e in eventos if e.operacion == "altas_lote_fila"]
        assert len(fallidas) == 3
        assert all(e.ok is False for e in fallidas)
        assert all("T07" not in str(e.detalle) for e in fallidas)


@respx.mock
def test_mismo_lote_dos_veces_no_duplica_nada() -> None:
    """El segundo envío actualiza (creadas=0), va por PATCH y no crea otro negocio."""
    _crear_clientes()
    buscar = respx.post(f"{BASE}/crm/v3/objects/deals/search").mock(
        return_value=Response(200, json={"results": []})
    )
    crear = respx.post(f"{BASE}/crm/v3/objects/deals").mock(
        return_value=Response(200, json={"id": "1001"})
    )
    respx.put(f"{BASE}/crm/v4/objects/deals/1001/associations/default/companies/77").mock(
        return_value=Response(200, json={})
    )
    parchar = respx.patch(f"{BASE}/crm/v3/objects/deals/1001").mock(
        return_value=Response(200, json={"id": "1001"})
    )
    cliente_http = TestClient(app)
    lote = {"filas": [_fila(fila=2)]}

    primera = cliente_http.post("/altas/lote", json=lote)
    segunda = cliente_http.post("/altas/lote", json=lote)

    assert primera.status_code == 200
    assert primera.json()["resumen"] == {
        "recibidas": 1,
        "creadas": 1,
        "actualizadas": 0,
        "errores": 0,
    }
    assert segunda.status_code == 200
    assert segunda.json()["resumen"] == {
        "recibidas": 1,
        "creadas": 0,
        "actualizadas": 1,
        "errores": 0,
    }
    assert crear.call_count == 1  # el negocio no se crea dos veces
    assert buscar.call_count == 1  # la segunda va directa por hubspot_deal_id
    assert parchar.call_count == 1
    assert b"dealstage" not in parchar.calls.last.request.read()

    with SessionLocal() as sesion:
        suministros = sesion.scalars(select(Suministro).where(Suministro.cups == CUPS_A)).all()
        assert len(suministros) == 1
        assert suministros[0].hubspot_deal_id == "1001"
        assert suministros[0].estado == "pendiente"


@respx.mock
def test_cada_suministro_creado_guarda_su_deal_id() -> None:
    """Dos filas buenas: cada suministro queda enlazado a su negocio de HubSpot."""
    _crear_clientes()
    _mock_hubspot_crea()
    cliente_http = TestClient(app)
    filas = [
        _fila(fila=4, cups=CUPS_A, tipo="luz"),
        _fila(fila=9, cups=CUPS_B, tipo="gas", tarifa_acceso="3.0TD", potencia_kw=None),
    ]

    respuesta = cliente_http.post("/altas/lote", json={"filas": filas})

    assert respuesta.status_code == 200
    assert respuesta.json()["resumen"] == {
        "recibidas": 2,
        "creadas": 2,
        "actualizadas": 0,
        "errores": 0,
    }
    with SessionLocal() as sesion:
        a = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_A))
        b = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_B))
        assert a is not None
        assert a.hubspot_deal_id == "1001"
        assert b is not None
        assert b.hubspot_deal_id == "1002"
        assert b.tarifa_acceso == "3.0TD"
        assert (
            sesion.scalar(
                select(func.count())
                .select_from(Suministro)
                .where(Suministro.cups.in_([CUPS_A, CUPS_B]))
            )
            == 2
        )


@respx.mock
def test_alias_nif_aceptado_por_compatibilidad() -> None:
    """`nif` sigue aceptándose como alias, aunque `cliente_nif` es el canónico."""
    _crear_clientes()
    _mock_hubspot_crea()
    cliente_http = TestClient(app)
    fila = _fila(fila=6)
    fila["nif"] = fila.pop("cliente_nif")

    respuesta = cliente_http.post("/altas/lote", json={"filas": [fila]})

    assert respuesta.status_code == 200
    assert respuesta.json()["resumen"] == {
        "recibidas": 1,
        "creadas": 1,
        "actualizadas": 0,
        "errores": 0,
    }
