"""Tests del cliente de HubSpot con `respx`: ninguna prueba toca la red.

Cubre la idempotencia de `upsert_deal_alta` y `crear_ticket_anomalia`, el reintento con
espera exponencial en 429 y 5xx (respetando `Retry-After`), el error controlado
`HubSpotError` tras agotar los intentos y la asociación con la empresa. El token nunca
aparece en los mensajes de error.
"""

from types import SimpleNamespace
from typing import Any

import pytest
import respx
from app.config import settings
from app.domain.cups import letras_control
from app.services import hubspot as modulo_hubspot
from app.services.hubspot import HubSpot, HubSpotError
from httpx import Response

TOKEN = "hs-token-secreto"
BASE = "https://api.hubapi.com"
_DIGITOS = "0123456789012345"
CUPS_A = "ES" + _DIGITOS + letras_control(_DIGITOS)


@pytest.fixture
def cliente() -> HubSpot:
    """Cliente directo con token de prueba: los tests no leen el entorno real."""
    return HubSpot(token=TOKEN)


@pytest.fixture
def esperas(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Sustituye la espera del reintento: se registran sin dormir de verdad."""
    dormidas: list[float] = []
    monkeypatch.setattr(modulo_hubspot.time, "sleep", dormidas.append)
    return dormidas


@pytest.fixture
def configuracion_hs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pipelines y fases de prueba; el repositorio no contiene ninguno real."""
    monkeypatch.setattr(settings, "hs_pipeline_altas", "pipe-altas")
    monkeypatch.setattr(settings, "hs_stage_pendiente", "stage-pendiente")
    monkeypatch.setattr(settings, "hs_ticket_pipeline", "pipe-tickets")
    monkeypatch.setattr(settings, "hs_ticket_stage_nuevo", "stage-nuevo")


def _suministro() -> Any:
    return SimpleNamespace(
        id=1, cups=CUPS_A, tipo="luz", direccion="Calle Falsa 123", hubspot_deal_id=None
    )


def _anomalia() -> Any:
    return SimpleNamespace(id=7, regla="R6", severidad="alta", detalle="Consumo disparado")


@respx.mock
def test_dos_upserts_no_duplican_negocio(cliente: HubSpot, configuracion_hs: None) -> None:
    """El segundo upsert va por PATCH (sin dealstage) y no crea ni asocia otra vez."""
    buscar = respx.post(f"{BASE}/crm/v3/objects/deals/search")
    buscar.side_effect = [Response(200, json={"results": []})]
    crear = respx.post(f"{BASE}/crm/v3/objects/deals").mock(
        return_value=Response(200, json={"id": "1001"})
    )
    asociar = respx.put(f"{BASE}/crm/v4/objects/deals/1001/associations/default/companies/77").mock(
        return_value=Response(200, json={})
    )
    parchar = respx.patch(f"{BASE}/crm/v3/objects/deals/1001").mock(
        return_value=Response(200, json={"id": "1001"})
    )

    suministro = _suministro()
    primero = cliente.upsert_deal_alta(suministro, "77")
    suministro.hubspot_deal_id = primero
    segundo = cliente.upsert_deal_alta(suministro, "77")

    assert primero == segundo == "1001"
    assert crear.call_count == 1
    assert asociar.call_count == 1
    assert parchar.call_count == 1
    cuerpo = parchar.calls.last.request.read()
    assert b"dealstage" not in cuerpo  # la fase la mueve el equipo: el PATCH no la toca


@respx.mock
def test_429_con_retry_after_se_reintenta_y_termina_bien(
    cliente: HubSpot, esperas: list[float], configuracion_hs: None
) -> None:
    """Un 429 respeta `Retry-After` y el reintento siguiente ya funciona."""
    buscar = respx.post(f"{BASE}/crm/v3/objects/deals/search")
    buscar.side_effect = [
        Response(429, headers={"Retry-After": "0"}),
        Response(200, json={"results": [{"id": "1001", "properties": {}}]}),
    ]
    parchar = respx.patch(f"{BASE}/crm/v3/objects/deals/1001").mock(
        return_value=Response(200, json={"id": "1001"})
    )

    resultado = cliente.upsert_deal_alta(_suministro(), "77")

    assert resultado == "1001"
    assert esperas == [0.0]  # se respeta el Retry-After de la respuesta
    assert parchar.call_count == 1


@respx.mock
def test_500_se_reintenta_con_espera_exponencial(
    cliente: HubSpot, esperas: list[float], configuracion_hs: None
) -> None:
    """Un 5xx es temporal: se reintenta con la espera exponencial inicial."""
    buscar = respx.post(f"{BASE}/crm/v3/objects/deals/search")
    buscar.side_effect = [
        Response(500),
        Response(200, json={"results": [{"id": "1001", "properties": {}}]}),
    ]
    respx.patch(f"{BASE}/crm/v3/objects/deals/1001").mock(
        return_value=Response(200, json={"id": "1001"})
    )

    assert cliente.upsert_deal_alta(_suministro(), "77") == "1001"
    assert esperas == [1.0]  # sin Retry-After: espera exponencial desde 1 segundo


@respx.mock
def test_cinco_429_agotan_en_hubspot_error(cliente: HubSpot, esperas: list[float]) -> None:
    """Agotados los cinco intentos se lanza `HubSpotError` con el código, sin el token."""
    respx.post(f"{BASE}/crm/v3/objects/deals/search").mock(return_value=Response(429))

    with pytest.raises(HubSpotError) as error:
        cliente.buscar_uno("deals", "cups", CUPS_A)

    assert error.value.codigo == 429
    assert esperas == [1.0, 2.0, 4.0, 8.0]  # espera exponencial entre intentos
    assert TOKEN not in str(error.value)  # el token nunca sale en los mensajes
    assert "Bearer" not in str(error.value)


@respx.mock
def test_ticket_idempotente_por_energy_ops_id(cliente: HubSpot, configuracion_hs: None) -> None:
    """Dos llamadas devuelven el mismo ticket: la segunda encuentra el `energy_ops_id`."""
    buscar = respx.post(f"{BASE}/crm/v3/objects/tickets/search")
    buscar.side_effect = [
        Response(200, json={"results": []}),
        Response(200, json={"results": [{"id": "5001", "properties": {}}]}),
    ]
    crear = respx.post(f"{BASE}/crm/v3/objects/tickets").mock(
        return_value=Response(200, json={"id": "5001"})
    )
    asociar = respx.put(
        f"{BASE}/crm/v4/objects/tickets/5001/associations/default/companies/77"
    ).mock(return_value=Response(200, json={}))

    anomalia = _anomalia()
    primero = cliente.crear_ticket_anomalia(anomalia, CUPS_A, "77")
    segundo = cliente.crear_ticket_anomalia(anomalia, CUPS_A, "77")

    assert primero == segundo == "5001"
    assert crear.call_count == 1
    assert asociar.call_count == 1  # la asociación a la empresa solo en la creación
    cuerpo = crear.calls.last.request.read()
    assert f"[ALTA] R6 · {CUPS_A}".encode() in cuerpo
    assert b"pipe-tickets" in cuerpo
