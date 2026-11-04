"""Tests de integración de `POST /facturas` y `GET /facturas` (docs/spec.md, secciones 15 y 17).

PostgreSQL real (docker compose en local, servicio en el CI) y LLM simulado: el doble de
`extraer_factura` se instala en `app.services.invoices`, así que ninguna prueba toca la red.
Los PDFs se generan con reportlab y cada test limpia sus filas al terminar.
"""

import io
from collections.abc import Iterator
from typing import Any

import pytest
from app.db import SessionLocal
from app.domain.cups import letras_control
from app.main import app
from app.models import Anomalia, Cliente, EventoSync, Factura, Suministro
from app.schemas import FacturaExtraida
from app.services import invoices
from app.services.extraction import ExtraccionInvalida
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

NIF = "T04TEST01"
_DIGITOS_A = "0123456789012345"
_DIGITOS_B = "5432109876543210"
_DIGITOS_FUERA = "1111222233334444"
CUPS_A = "ES" + _DIGITOS_A + letras_control(_DIGITOS_A)
CUPS_B = "ES" + _DIGITOS_B + letras_control(_DIGITOS_B)
CUPS_FUERA = "ES" + _DIGITOS_FUERA + letras_control(_DIGITOS_FUERA)


def _pdf(texto: str) -> bytes:
    """Un PDF mínimo con reportlab; el LLM va simulado, el contenido no importa."""
    buffer = io.BytesIO()
    lienzo = Canvas(buffer)
    lienzo.drawString(72, 750, texto)
    lienzo.save()
    return buffer.getvalue()


def _datos(**extra: Any) -> FacturaExtraida:
    valores: dict[str, Any] = {
        "cups": CUPS_A,
        "numero_factura": "T04-001",
        "comercializadora": "Voltia Energía",
        "fecha_emision": "2026-03-01",
        "fecha_inicio": "2026-02-01",
        "fecha_fin": "2026-02-28",
        "potencia_kw": 5.5,
        "consumo_kwh": 320.5,
        "importe_potencia": 30.25,
        "importe_energia": 45.1,
        "impuestos_otros": 15.87,
        "importe_total": 91.22,
        "lectura_estimada": False,
        "confianza": 0.95,
        "campos_dudosos": [],
    }
    valores.update(extra)
    return FacturaExtraida(**valores)


def _instalar_extraccion(
    monkeypatch: pytest.MonkeyPatch,
    datos: FacturaExtraida | None = None,
    error: Exception | None = None,
) -> list[bytes]:
    """Sustituye la extracción por un doble y devuelve la lista de PDFs recibidos."""
    llamadas: list[bytes] = []

    def doble(pdf_bytes: bytes) -> tuple[FacturaExtraida, dict[str, object]]:
        llamadas.append(pdf_bytes)
        if error is not None:
            raise error
        assert datos is not None
        return datos, {"modelo": "gpt-test", "tokens_entrada": 100, "tokens_salida": 40}

    monkeypatch.setattr(invoices, "extraer_factura", doble)
    return llamadas


def _subir(cliente_http: TestClient, contenido: bytes) -> Any:
    return cliente_http.post(
        "/facturas", files={"archivo": ("factura.pdf", contenido, "application/pdf")}
    )


def _limpiar() -> None:
    """Borra las filas creadas por los tests; el CI arranca con la base vacía."""
    with SessionLocal() as sesion:
        sesion.execute(
            delete(Anomalia).where(
                Anomalia.factura_id.in_(select(Factura.id).where(Factura.numero.like("T04-%")))
            )
        )
        sesion.execute(delete(Factura).where(Factura.numero.like("T04-%")))
        sesion.execute(delete(EventoSync).where(EventoSync.operacion == "extraer_factura"))
        sesion.execute(delete(Suministro).where(Suministro.cups.in_([CUPS_A, CUPS_B])))
        sesion.execute(delete(Cliente).where(Cliente.nif == NIF))
        sesion.commit()


@pytest.fixture(autouse=True)
def limpiar() -> Iterator[None]:
    yield
    _limpiar()


@pytest.fixture
def cartera() -> None:
    """Un cliente con dos suministros en cartera (CUPS_A y CUPS_B)."""
    with SessionLocal() as sesion:
        cliente = Cliente(nombre="Cartera de prueba", nif=NIF, sector="oficinas")
        sesion.add(cliente)
        sesion.flush()
        for cups in (CUPS_A, CUPS_B):
            sesion.add(
                Suministro(
                    cliente_id=cliente.id,
                    cups=cups,
                    tipo="luz",
                    direccion="Calle Falsa 123",
                )
            )
        sesion.commit()
    return


def _contar(sesion: Session, modelo: Any) -> int:
    return int(sesion.scalar(select(func.count()).select_from(modelo)) or 0)


def test_mismo_pdf_no_duplica_nada(monkeypatch: pytest.MonkeyPatch, cartera: None) -> None:
    llamadas = _instalar_extraccion(monkeypatch, datos=_datos())
    cliente_http = TestClient(app)
    contenido = _pdf("Factura T04-001 de Voltia Energia")

    primera = _subir(cliente_http, contenido)
    assert primera.status_code == 200
    cuerpo1 = primera.json()
    assert cuerpo1["creada"] is True
    assert cuerpo1["numero"] == "T04-001"
    assert cuerpo1["archivo_hash"]
    assert cuerpo1["anomalias"] == []

    segunda = _subir(cliente_http, contenido)
    assert segunda.status_code == 200
    cuerpo2 = segunda.json()
    assert cuerpo2["creada"] is False
    assert cuerpo2["id"] == cuerpo1["id"]
    assert len(llamadas) == 1  # el LLM solo se paga una vez

    with SessionLocal() as sesion:
        facturas = sesion.scalars(select(Factura).where(Factura.numero.like("T04-%"))).all()
        assert len(facturas) == 1
        assert (
            sesion.scalar(
                select(func.count())
                .select_from(Anomalia)
                .join(Factura, Anomalia.factura_id == Factura.id)
                .where(Factura.numero.like("T04-%"))
            )
            == 0
        )
        eventos = sesion.scalars(
            select(EventoSync).where(EventoSync.operacion == "extraer_factura")
        ).all()
        assert [e.ok for e in eventos] == [True, True]
        assert all(e.detalle is not None and "archivo_hash" in e.detalle for e in eventos)


def test_pdf_distinto_misma_clave_negocio_no_duplica(
    monkeypatch: pytest.MonkeyPatch, cartera: None
) -> None:
    """Otro PDF (otro hash) con los mismos CUPS, número y comercializadora no crea fila."""
    llamadas = _instalar_extraccion(monkeypatch, datos=_datos())
    cliente_http = TestClient(app)

    primera = _subir(cliente_http, _pdf("Factura T04-001 original"))
    segunda = _subir(cliente_http, _pdf("Factura T04-001 reescaneada"))

    assert primera.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json()["creada"] is False
    assert segunda.json()["id"] == primera.json()["id"]
    assert len(llamadas) == 2  # el hash era distinto, así que sí se llamó al LLM
    with SessionLocal() as sesion:
        assert (
            sesion.scalar(
                select(func.count()).select_from(Factura).where(Factura.numero.like("T04-%"))
            )
            == 1
        )


def test_salida_invalida_da_422_y_no_guarda_nada(
    monkeypatch: pytest.MonkeyPatch, cartera: None
) -> None:
    _instalar_extraccion(
        monkeypatch,
        error=ExtraccionInvalida("La respuesta del modelo no cumple el esquema de factura"),
    )
    cliente_http = TestClient(app)

    respuesta = _subir(cliente_http, _pdf("Factura T04-009 rota"))

    assert respuesta.status_code == 422
    assert "no cumple el esquema" in respuesta.json()["detail"]
    with SessionLocal() as sesion:
        assert (
            sesion.scalar(
                select(func.count()).select_from(Factura).where(Factura.numero.like("T04-%"))
            )
            == 0
        )
        eventos = sesion.scalars(
            select(EventoSync).where(EventoSync.operacion == "extraer_factura")
        ).all()
        assert len(eventos) == 1
        assert eventos[0].ok is False


def test_confianza_baja_y_campos_dudosos_crea_r11(
    monkeypatch: pytest.MonkeyPatch, cartera: None
) -> None:
    _instalar_extraccion(
        monkeypatch,
        datos=_datos(confianza=0.5, campos_dudosos=["importe_total"]),
    )
    cliente_http = TestClient(app)

    respuesta = _subir(cliente_http, _pdf("Factura T04-002 dudosa"))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["creada"] is True
    assert len(cuerpo["anomalias"]) == 1
    anomalia = cuerpo["anomalias"][0]
    assert anomalia["regla"] == "R11"
    assert anomalia["severidad"] == "media"
    assert anomalia["estado"] == "abierta"
    assert "confianza 0.50" in anomalia["detalle"]
    assert "importe_total" in anomalia["detalle"]
    with SessionLocal() as sesion:
        anomalias = sesion.scalars(select(Anomalia)).all()
        assert len(anomalias) == 1
        assert anomalias[0].regla == "R11"


def test_confianza_alta_sin_dudosos_no_crea_anomalia(
    monkeypatch: pytest.MonkeyPatch, cartera: None
) -> None:
    _instalar_extraccion(monkeypatch, datos=_datos(confianza=0.9, campos_dudosos=[]))
    cliente_http = TestClient(app)

    respuesta = _subir(cliente_http, _pdf("Factura T04-003 limpia"))

    assert respuesta.status_code == 200
    assert respuesta.json()["anomalias"] == []
    with SessionLocal() as sesion:
        assert _contar(sesion, Anomalia) == 0


def test_cups_fuera_de_cartera_guarda_suministro_nulo(
    monkeypatch: pytest.MonkeyPatch, cartera: None
) -> None:
    _instalar_extraccion(
        monkeypatch,
        datos=_datos(cups=CUPS_FUERA, numero_factura="T04-004"),
    )
    cliente_http = TestClient(app)

    respuesta = _subir(cliente_http, _pdf("Factura T04-004 fuera de cartera"))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["suministro_id"] is None
    assert cuerpo["cups_leido"] == CUPS_FUERA


def test_archivo_no_pdf_da_422(monkeypatch: pytest.MonkeyPatch, cartera: None) -> None:
    llamadas = _instalar_extraccion(monkeypatch, datos=_datos())
    cliente_http = TestClient(app)

    respuesta = cliente_http.post(
        "/facturas", files={"archivo": ("notas.txt", b"esto no es un pdf", "text/plain")}
    )

    assert respuesta.status_code == 422
    assert "PDF" in respuesta.json()["detail"]
    assert llamadas == []


def test_get_facturas_filtros(monkeypatch: pytest.MonkeyPatch, cartera: None) -> None:
    cliente_http = TestClient(app)
    _instalar_extraccion(monkeypatch, datos=_datos(numero_factura="T04-005"))
    factura_a = _subir(cliente_http, _pdf("Factura T04-005 de febrero"))
    assert factura_a.status_code == 200
    id_a = factura_a.json()["id"]

    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            cups=CUPS_B,
            numero_factura="T04-006",
            fecha_emision="2026-04-01",
            fecha_inicio="2026-03-01",
            fecha_fin="2026-03-31",
        ),
    )
    factura_b = _subir(cliente_http, _pdf("Factura T04-006 de marzo"))
    assert factura_b.status_code == 200
    id_b = factura_b.json()["id"]

    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            cups=CUPS_FUERA,
            numero_factura="T04-007",
            fecha_emision="2026-05-01",
            fecha_inicio="2026-04-01",
            fecha_fin="2026-04-30",
        ),
    )
    factura_fuera = _subir(cliente_http, _pdf("Factura T04-007 fuera"))
    assert factura_fuera.status_code == 200
    id_fuera = factura_fuera.json()["id"]

    todas = cliente_http.get("/facturas")
    assert todas.status_code == 200
    assert [f["id"] for f in todas.json()] == [id_a, id_b, id_fuera]

    por_cups = cliente_http.get("/facturas", params={"cups": CUPS_A.lower()})
    assert [f["id"] for f in por_cups.json()] == [id_a]  # normaliza mayúsculas

    por_nif = cliente_http.get("/facturas", params={"cliente_nif": NIF})
    assert [f["id"] for f in por_nif.json()] == [id_a, id_b]  # la de fuera de cartera, no

    por_desde = cliente_http.get("/facturas", params={"desde": "2026-03-01"})
    assert [f["id"] for f in por_desde.json()] == [id_b, id_fuera]

    por_hasta = cliente_http.get("/facturas", params={"hasta": "2026-02-28"})
    assert [f["id"] for f in por_hasta.json()] == [id_a]
