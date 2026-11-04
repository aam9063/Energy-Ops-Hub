"""Tests de integración de `POST /anomalias/{id}/ticket` (docs/spec.md, secciones 12 y 15).

Cubre el hueco que dejó la feature 07: la idempotencia del ticket estaba probada a nivel de
servicio, no en la API. PostgreSQL real y HubSpot simulado con `respx`: ninguna prueba hace red.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
import respx
from app.config import settings
from app.db import SessionLocal
from app.domain.cups import letras_control
from app.main import app
from app.models import Anomalia, Cliente, EventoSync, Factura, Suministro
from app.services import hubspot as modulo_hubspot
from app.services.hubspot import HubSpot
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete, select

NIF = "T07TCK01"
_DIGITOS = "9876543210987654"
CUPS = "ES" + _DIGITOS + letras_control(_DIGITOS)
BASE = "https://api.hubapi.com"
TOKEN = "hs-token-de-test"
EMPRESA = "777"
TICKET = "900"


@pytest.fixture(autouse=True)
def entorno_hubspot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token y configuración de prueba, con el cliente de HubSpot apuntando a respx."""
    monkeypatch.setattr(settings, "hubspot_token", TOKEN)
    monkeypatch.setattr(settings, "hs_ticket_pipeline", "pipe-tickets")
    monkeypatch.setattr(settings, "hs_ticket_stage_nuevo", "stage-nuevo")
    monkeypatch.setattr(modulo_hubspot, "_cliente", HubSpot(token=TOKEN))


@pytest.fixture(autouse=True)
def limpiar() -> Iterator[None]:
    """Limpia antes y después: una base local con filas de una corrida anterior no debe romper."""
    _limpiar()
    yield
    _limpiar()


def _limpiar() -> None:
    with SessionLocal() as sesion:
        sesion.execute(
            delete(Anomalia).where(
                Anomalia.factura_id.in_(select(Factura.id).where(Factura.numero == "T07-TICKET"))
            )
        )
        sesion.execute(delete(Factura).where(Factura.numero == "T07-TICKET"))
        sesion.execute(delete(Suministro).where(Suministro.cups == CUPS))
        sesion.execute(delete(Cliente).where(Cliente.nif == NIF))
        sesion.execute(delete(EventoSync).where(EventoSync.sistema == "hubspot"))
        sesion.commit()


def _crear_anomalia() -> int:
    """Cliente con empresa, suministro, factura y una anomalía abierta; devuelve su id."""
    with SessionLocal() as sesion:
        cliente = Cliente(
            nombre="Cliente ticket", nif=NIF, sector="oficinas", hubspot_company_id=EMPRESA
        )
        sesion.add(cliente)
        sesion.flush()
        suministro = Suministro(
            cliente_id=cliente.id, cups=CUPS, tipo="luz", direccion="Calle Falsa 123"
        )
        sesion.add(suministro)
        sesion.flush()
        factura = Factura(
            suministro_id=suministro.id,
            cups_leido=CUPS,
            numero="T07-TICKET",
            comercializadora="Voltia Energía",
            fecha_inicio="2026-05-01",
            fecha_fin="2026-05-31",
            consumo_kwh=Decimal("100.00"),
            importe_total=Decimal("30.00"),
            archivo_hash="hash-t07-ticket",
            datos_crudos={"cups": CUPS},
        )
        sesion.add(factura)
        sesion.flush()
        anomalia = Anomalia(
            factura_id=factura.id,
            suministro_id=suministro.id,
            regla="R5",
            severidad="alta",
            detalle="Suma de conceptos 91,22 € frente a total 95,00 €",
        )
        sesion.add(anomalia)
        sesion.commit()
        return anomalia.id


def test_el_ticket_se_crea_una_vez_y_se_reutiliza() -> None:
    anomalia_id = _crear_anomalia()
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/crm/v3/objects/tickets/search").mock(
            return_value=Response(200, json={"results": []})
        )
        crear = router.post(f"{BASE}/crm/v3/objects/tickets").mock(
            return_value=Response(200, json={"id": TICKET})
        )
        router.put(
            f"{BASE}/crm/v4/objects/tickets/{TICKET}/associations/default/companies/{EMPRESA}"
        ).mock(return_value=Response(204))
        cliente_http = TestClient(app)

        primera = cliente_http.post(f"/anomalias/{anomalia_id}/ticket")
        segunda = cliente_http.post(f"/anomalias/{anomalia_id}/ticket")

    assert primera.status_code == 200
    assert primera.json() == {
        "anomalia_id": anomalia_id,
        "hubspot_ticket_id": TICKET,
        "creado": True,
    }
    assert segunda.status_code == 200
    assert segunda.json() == {
        "anomalia_id": anomalia_id,
        "hubspot_ticket_id": TICKET,
        "creado": False,
    }
    # La segunda llamada no vuelve a crear el ticket: sale del id guardado localmente.
    assert crear.call_count == 1

    with SessionLocal() as sesion:
        guardada = sesion.get(Anomalia, anomalia_id)
        assert guardada is not None
        assert guardada.hubspot_ticket_id == TICKET


def test_ticket_de_anomalia_inexistente_da_404() -> None:
    with respx.mock(assert_all_called=False):
        respuesta = TestClient(app).post("/anomalias/999999/ticket")

    assert respuesta.status_code == 404


def test_un_fallo_de_hubspot_al_crear_ticket_da_503_y_no_guarda_id() -> None:
    anomalia_id = _crear_anomalia()
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE}/crm/v3/objects/tickets/search").mock(
            return_value=Response(200, json={"results": []})
        )
        router.post(f"{BASE}/crm/v3/objects/tickets").mock(return_value=Response(500))

        respuesta = TestClient(app).post(f"/anomalias/{anomalia_id}/ticket")

    assert respuesta.status_code == 503
    with SessionLocal() as sesion:
        guardada = sesion.get(Anomalia, anomalia_id)
        assert guardada is not None
        assert guardada.hubspot_ticket_id is None
        # El evento de *esta* anomalía: buscar «el primero de la operación» dependía del orden
        # de la tabla y de filas de otras corridas.
        evento = sesion.scalar(
            select(EventoSync).where(
                EventoSync.sistema == "hubspot",
                EventoSync.operacion == "ticket_anomalia",
                EventoSync.entidad_id == str(anomalia_id),
            )
        )
        assert evento is not None
        assert evento.ok is False
