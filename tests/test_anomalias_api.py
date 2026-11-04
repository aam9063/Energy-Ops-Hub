"""Tests de integración de las anomalías (docs/spec.md, secciones 7, 10 y 15).

Cubre `GET /anomalias` y `PATCH /anomalias/{id}`, `POST /tareas/sin-facturar` (R10) y la
evaluación de reglas durante la ingesta: consumo disparado (R6), duplicado (R3), solape
(R4), descuadre (R5) y precio fuera de rango (R9), comprobando que reprocesar no duplica
anomalías. PostgreSQL real (docker compose) y LLM simulado: ninguna prueba toca la red.
"""

import io
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from app.db import SessionLocal
from app.domain.cups import letras_control
from app.main import app
from app.models import Anomalia, Cliente, EventoSync, Factura, Suministro
from app.schemas import FacturaExtraida
from app.services import invoices
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

NIF_5 = "T05TEST01"
_DIGITOS_A = "1111222233330001"
_DIGITOS_B = "1111222233330002"
_DIGITOS_C = "1111222233330003"
CUPS_5A = "ES" + _DIGITOS_A + letras_control(_DIGITOS_A)
CUPS_5B = "ES" + _DIGITOS_B + letras_control(_DIGITOS_B)
CUPS_5C = "ES" + _DIGITOS_C + letras_control(_DIGITOS_C)

# Cuatro periodos de 30 días seguidos, sin solapes: enero, febrero, marzo y abril de 2026.
PERIODOS = [
    (date(2026, 1, 1), date(2026, 1, 30)),
    (date(2026, 2, 1), date(2026, 3, 2)),
    (date(2026, 3, 3), date(2026, 4, 1)),
    (date(2026, 4, 2), date(2026, 5, 1)),
]


def _pdf(texto: str) -> bytes:
    """Un PDF mínimo con reportlab; el LLM va simulado, el contenido no importa."""
    buffer = io.BytesIO()
    lienzo = Canvas(buffer)
    lienzo.drawString(72, 750, texto)
    lienzo.save()
    return buffer.getvalue()


def _datos(**extra: Any) -> FacturaExtraida:
    """Factura limpia y cuadrada (91,22 € = 30,25 + 45,10 + 15,87) sobre CUPS_5A."""
    valores: dict[str, Any] = {
        "cups": CUPS_5A,
        "numero_factura": "T05-000",
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
) -> None:
    """Sustituye la extracción por un doble: ninguna prueba llama al LLM real."""

    def doble(pdf_bytes: bytes) -> tuple[FacturaExtraida, dict[str, object]]:
        assert datos is not None
        return datos, {"modelo": "gpt-test", "tokens_entrada": 100, "tokens_salida": 40}

    monkeypatch.setattr(invoices, "extraer_factura", doble)


def _subir(cliente_http: TestClient, contenido: bytes) -> Any:
    return cliente_http.post(
        "/facturas", files={"archivo": ("factura.pdf", contenido, "application/pdf")}
    )


def _limpiar() -> None:
    """Borra las filas creadas por los tests; el CI arranca con la base vacía."""
    with SessionLocal() as sesion:
        sesion.execute(
            delete(Anomalia).where(
                Anomalia.factura_id.in_(select(Factura.id).where(Factura.numero.like("T05-%")))
            )
        )
        sesion.execute(
            delete(Anomalia).where(
                Anomalia.suministro_id.in_(
                    select(Suministro.id).where(Suministro.cups.in_([CUPS_5A, CUPS_5B, CUPS_5C]))
                )
            )
        )
        # R10 corre sobre toda la cartera: sus anomalías no cuelgan de una factura.
        sesion.execute(delete(Anomalia).where(Anomalia.regla == "R10"))
        sesion.execute(delete(Factura).where(Factura.numero.like("T05-%")))
        sesion.execute(delete(EventoSync).where(EventoSync.operacion == "extraer_factura"))
        sesion.execute(delete(Suministro).where(Suministro.cups.in_([CUPS_5A, CUPS_5B, CUPS_5C])))
        sesion.execute(delete(Cliente).where(Cliente.nif == NIF_5))
        sesion.commit()


@pytest.fixture(autouse=True)
def limpiar() -> Iterator[None]:
    yield
    _limpiar()


def _suministro_db(sesion: Session, cliente: Cliente, cups: str, **extra: Any) -> Suministro:
    suministro = Suministro(
        cliente_id=cliente.id,
        cups=cups,
        tipo="luz",
        direccion="Calle Falsa 123",
        **extra,
    )
    sesion.add(suministro)
    sesion.flush()
    return suministro


def _factura_db(sesion: Session, suministro: Suministro, numero: str, fecha_fin: date) -> Factura:
    factura = Factura(
        suministro_id=suministro.id,
        cups_leido=suministro.cups,
        numero=numero,
        comercializadora="Voltia Energía",
        fecha_inicio=fecha_fin - timedelta(days=29),
        fecha_fin=fecha_fin,
        consumo_kwh=Decimal("300.00"),
        importe_total=Decimal("91.22"),
        confianza=Decimal("0.95"),
        archivo_hash=f"t05-hash-{numero}",
        datos_crudos={},
    )
    sesion.add(factura)
    sesion.flush()
    return factura


def _anomalia_db(
    sesion: Session,
    factura: Factura | None,
    suministro: Suministro | None,
    regla: str,
    severidad: str,
    estado: str = "abierta",
) -> Anomalia:
    anomalia = Anomalia(
        factura_id=factura.id if factura is not None else None,
        suministro_id=factura.suministro_id
        if factura is not None
        else (suministro.id if suministro is not None else None),
        regla=regla,
        severidad=severidad,
        detalle=f"Prueba de la regla {regla}",
        estado=estado,
    )
    sesion.add(anomalia)
    sesion.flush()
    return anomalia


@pytest.fixture
def cartera_5a() -> None:
    """Un cliente con el suministro CUPS_5A activo (sin tarifa: R9 sin mediana)."""
    with SessionLocal() as sesion:
        cliente = Cliente(nombre="Cartera T05", nif=NIF_5, sector="oficinas")
        sesion.add(cliente)
        sesion.flush()
        _suministro_db(sesion, cliente, CUPS_5A, estado="activo")
        sesion.commit()


@pytest.fixture
def cartera_5b() -> None:
    """Suministro CUPS_5B con tarifa 2.0TD: la mediana de R9 sí tiene datos."""
    with SessionLocal() as sesion:
        cliente = Cliente(nombre="Cartera T05", nif=NIF_5, sector="oficinas")
        sesion.add(cliente)
        sesion.flush()
        _suministro_db(sesion, cliente, CUPS_5B, estado="activo", tarifa_acceso="2.0TD")
        sesion.commit()


@pytest.fixture
def cartera_r10() -> None:
    """Tres suministros: 61 días sin facturar, 59 días, y uno de baja sin facturas."""
    with SessionLocal() as sesion:
        cliente = Cliente(nombre="Cartera R10", nif=NIF_5, sector="oficinas")
        sesion.add(cliente)
        sesion.flush()
        activo_viejo = _suministro_db(sesion, cliente, CUPS_5A, estado="activo")
        activo_reciente = _suministro_db(sesion, cliente, CUPS_5B, estado="activo")
        _suministro_db(sesion, cliente, CUPS_5C, estado="baja")
        _factura_db(sesion, activo_viejo, "T05-901", date.today() - timedelta(days=61))
        _factura_db(sesion, activo_reciente, "T05-902", date.today() - timedelta(days=59))
        sesion.commit()


@pytest.fixture
def cartera_con_anomalias() -> dict[str, int]:
    """Anomalías sembradas para probar los filtros y el cierre con comentario."""
    with SessionLocal() as sesion:
        cliente = Cliente(nombre="Cartera T05", nif=NIF_5, sector="oficinas")
        sesion.add(cliente)
        sesion.flush()
        suministro_a = _suministro_db(sesion, cliente, CUPS_5A, estado="activo")
        suministro_b = _suministro_db(sesion, cliente, CUPS_5B, estado="activo")
        suministro_c = _suministro_db(sesion, cliente, CUPS_5C, estado="activo")
        factura_1 = _factura_db(sesion, suministro_a, "T05-801", date(2026, 2, 28))
        factura_2 = _factura_db(sesion, suministro_b, "T05-802", date(2026, 3, 31))
        duplicada = _anomalia_db(sesion, factura_1, None, "R3", "alta")
        _anomalia_db(sesion, factura_1, None, "R11", "media")
        _anomalia_db(sesion, factura_2, None, "R9", "baja", estado="descartada")
        _anomalia_db(sesion, None, suministro_c, "R10", "media")
        sesion.commit()
        return {"duplicada": duplicada.id, "factura_1": factura_1.id}


# GET /anomalias -----------------------------------------------------------------


def test_get_anomalias_filtra_por_estado_severidad_y_cups(
    cartera_con_anomalias: dict[str, int],
) -> None:
    cliente_http = TestClient(app)

    todas = cliente_http.get("/anomalias")
    assert todas.status_code == 200
    assert len(todas.json()) == 4

    abiertas = cliente_http.get("/anomalias", params={"estado": "abierta"})
    assert len(abiertas.json()) == 3

    descartadas = cliente_http.get("/anomalias", params={"estado": "descartada"})
    assert [a["regla"] for a in descartadas.json()] == ["R9"]

    altas = cliente_http.get("/anomalias", params={"severidad": "alta"})
    assert [a["regla"] for a in altas.json()] == ["R3"]

    # Normaliza mayúsculas y encuentra la R10 a través del suministro (sin factura).
    por_cups = cliente_http.get("/anomalias", params={"cups": CUPS_5A.lower()})
    assert sorted(a["regla"] for a in por_cups.json()) == ["R11", "R3"]
    por_cups_r10 = cliente_http.get("/anomalias", params={"cups": CUPS_5C})
    assert [a["regla"] for a in por_cups_r10.json()] == ["R10"]

    invalida = cliente_http.get("/anomalias", params={"estado": "cerrada"})
    assert invalida.status_code == 422


# PATCH /anomalias/{id} -----------------------------------------------------------


def test_patch_resuelve_con_comentario_y_deja_trazabilidad(
    cartera_con_anomalias: dict[str, int],
) -> None:
    cliente_http = TestClient(app)

    respuesta = cliente_http.patch(
        f"/anomalias/{cartera_con_anomalias['duplicada']}",
        json={"estado": "resuelta", "comentario": "Verificado con Laura: es un reenvío"},
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "resuelta"
    assert "Verificado con Laura: es un reenvío" in cuerpo["detalle"]
    assert "Prueba de la regla R3" in cuerpo["detalle"]
    with SessionLocal() as sesion:
        anomalia = sesion.get(Anomalia, cartera_con_anomalias["duplicada"])
        assert anomalia is not None
        assert anomalia.estado == "resuelta"
        assert "reenvío" in anomalia.detalle


def test_patch_descarta_con_comentario(cartera_con_anomalias: dict[str, int]) -> None:
    cliente_http = TestClient(app)

    respuesta = cliente_http.patch(
        f"/anomalias/{cartera_con_anomalias['duplicada']}",
        json={"estado": "descartada", "comentario": "Falso positivo"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "descartada"


def test_patch_da_404_si_la_anomalia_no_existe(
    cartera_con_anomalias: dict[str, int],
) -> None:
    cliente_http = TestClient(app)

    respuesta = cliente_http.patch(
        "/anomalias/999999", json={"estado": "resuelta", "comentario": "nada"}
    )

    assert respuesta.status_code == 404


def test_patch_rechaza_estados_distintos_de_resuelta_y_descartada(
    cartera_con_anomalias: dict[str, int],
) -> None:
    cliente_http = TestClient(app)

    abierta = cliente_http.patch(
        f"/anomalias/{cartera_con_anomalias['duplicada']}",
        json={"estado": "abierta", "comentario": "reabrir"},
    )
    assert abierta.status_code == 422

    inventada = cliente_http.patch(
        f"/anomalias/{cartera_con_anomalias['duplicada']}",
        json={"estado": "cerrada", "comentario": "x"},
    )
    assert inventada.status_code == 422

    sin_comentario = cliente_http.patch(
        f"/anomalias/{cartera_con_anomalias['duplicada']}",
        json={"estado": "resuelta", "comentario": ""},
    )
    assert sin_comentario.status_code == 422


# POST /tareas/sin-facturar (R10) --------------------------------------------------


def test_tarea_sin_facturar_crea_r10_y_es_idempotente(cartera_r10: None) -> None:
    cliente_http = TestClient(app)

    primera = cliente_http.post("/tareas/sin-facturar")
    assert primera.status_code == 200
    assert primera.json()["anomalias_creadas"] >= 1  # al menos el CUPS con 61 días

    segunda = cliente_http.post("/tareas/sin-facturar")
    assert segunda.status_code == 200
    assert segunda.json()["anomalias_creadas"] == 0

    with SessionLocal() as sesion:
        suministro = sesion.scalar(select(Suministro).where(Suministro.cups == CUPS_5A))
        assert suministro is not None
        anomalia = sesion.scalar(
            select(Anomalia).where(Anomalia.suministro_id == suministro.id, Anomalia.regla == "R10")
        )
        assert anomalia is not None
        assert anomalia.factura_id is None
        assert anomalia.estado == "abierta"
        assert "61" in anomalia.detalle

    # El filtro por CUPS encuentra la R10 a través del suministro.
    respuesta = cliente_http.get("/anomalias", params={"cups": CUPS_5A})
    assert any(a["regla"] == "R10" for a in respuesta.json())


# Evaluación de reglas durante la ingesta ------------------------------------------


def test_ingesta_crea_r6_con_consumo_disparado_y_no_duplica_al_reprocesar(
    monkeypatch: pytest.MonkeyPatch, cartera_5a: None
) -> None:
    cliente_http = TestClient(app)
    for i, (inicio, fin) in enumerate(PERIODOS[:3], start=1):
        _instalar_extraccion(
            monkeypatch,
            datos=_datos(
                numero_factura=f"T05-10{i}",
                fecha_inicio=inicio.isoformat(),
                fecha_fin=fin.isoformat(),
                consumo_kwh=300.0,
            ),
        )
        respuesta = _subir(cliente_http, _pdf(f"Factura T05-10{i} normal"))
        assert respuesta.status_code == 200
        assert respuesta.json()["anomalias"] == []  # sin histórico suficiente, sin R6

    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            numero_factura="T05-104",
            fecha_inicio=PERIODOS[3][0].isoformat(),
            fecha_fin=PERIODOS[3][1].isoformat(),
            consumo_kwh=900.0,  # 30 kWh/día frente a 10 kWh/día del histórico
        ),
    )
    contenido = _pdf("Factura T05-104 pico")
    respuesta = _subir(cliente_http, contenido)
    assert respuesta.status_code == 200
    assert [a["regla"] for a in respuesta.json()["anomalias"]] == ["R6"]
    id_factura = respuesta.json()["id"]

    reprocesada = _subir(cliente_http, contenido)  # mismos bytes: mismo archivo_hash
    assert reprocesada.status_code == 200
    assert reprocesada.json()["creada"] is False
    with SessionLocal() as sesion:
        total = sesion.scalar(
            select(func.count()).select_from(Anomalia).where(Anomalia.factura_id == id_factura)
        )
        assert total == 1  # reprocesar no duplica


def test_ingesta_crea_r3_para_el_duplicado_y_no_lo_duplica(
    monkeypatch: pytest.MonkeyPatch, cartera_5a: None
) -> None:
    cliente_http = TestClient(app)
    _instalar_extraccion(monkeypatch, datos=_datos(numero_factura="T05-201"))
    original = _pdf("Factura T05-201 original")
    primera = _subir(cliente_http, original)
    assert primera.status_code == 200
    assert primera.json()["anomalias"] == []

    # Otro PDF (otro hash) con la misma clave de negocio: la factura es una duplicada.
    _instalar_extraccion(monkeypatch, datos=_datos(numero_factura="T05-201"))
    reescaneada = _pdf("Factura T05-201 reescaneada")
    segunda = _subir(cliente_http, reescaneada)
    assert segunda.status_code == 200
    assert segunda.json()["creada"] is False
    assert segunda.json()["id"] == primera.json()["id"]
    assert [a["regla"] for a in segunda.json()["anomalias"]] == ["R3"]

    # Reprocesar cualquiera de los dos PDFs, o subir una tercera copia, no duplica la R3.
    _subir(cliente_http, original)
    _subir(cliente_http, reescaneada)
    _instalar_extraccion(monkeypatch, datos=_datos(numero_factura="T05-201"))
    tercera = _subir(cliente_http, _pdf("Factura T05-201 tercera copia"))
    assert tercera.status_code == 200
    with SessionLocal() as sesion:
        anomalias = sesion.scalars(
            select(Anomalia).where(Anomalia.factura_id == primera.json()["id"])
        ).all()
        assert [a.regla for a in anomalias] == ["R3"]


def test_ingesta_crea_r5_con_el_total_descuadrado(
    monkeypatch: pytest.MonkeyPatch, cartera_5a: None
) -> None:
    cliente_http = TestClient(app)
    _instalar_extraccion(monkeypatch, datos=_datos(numero_factura="T05-301", importe_total=99.99))

    respuesta = _subir(cliente_http, _pdf("Factura T05-301 descuadrada"))

    assert respuesta.status_code == 200
    anomalias = respuesta.json()["anomalias"]
    assert [a["regla"] for a in anomalias] == ["R5"]
    assert "99.99" in anomalias[0]["detalle"]


def test_ingesta_crea_r4_con_periodo_solapado_y_clave_distinta(
    monkeypatch: pytest.MonkeyPatch, cartera_5a: None
) -> None:
    cliente_http = TestClient(app)
    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            numero_factura="T05-401",
            fecha_inicio="2026-02-01",
            fecha_fin="2026-02-28",
        ),
    )
    primera = _subir(cliente_http, _pdf("Factura T05-401 de febrero"))
    assert primera.status_code == 200
    assert primera.json()["anomalias"] == []

    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            numero_factura="T05-402",
            fecha_inicio="2026-02-10",
            fecha_fin="2026-03-05",
        ),
    )
    segunda = _subir(cliente_http, _pdf("Factura T05-402 solapada"))

    assert segunda.status_code == 200
    assert [a["regla"] for a in segunda.json()["anomalias"]] == ["R4"]


def test_ingesta_crea_r9_con_la_mediana_de_la_cartera(
    monkeypatch: pytest.MonkeyPatch, cartera_5b: None
) -> None:
    cliente_http = TestClient(app)
    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            cups=CUPS_5B,
            numero_factura="T05-501",
            fecha_inicio="2026-01-01",
            fecha_fin="2026-01-30",
            consumo_kwh=100.0,
            importe_potencia=None,
            importe_energia=10.0,
            impuestos_otros=None,
            importe_total=10.0,
            potencia_kw=None,
        ),
    )
    primera = _subir(cliente_http, _pdf("Factura T05-501 barata"))
    assert primera.status_code == 200
    assert primera.json()["anomalias"] == []  # sin mediana previa, R9 no dispara

    _instalar_extraccion(
        monkeypatch,
        datos=_datos(
            cups=CUPS_5B,
            numero_factura="T05-502",
            fecha_inicio="2026-02-01",
            fecha_fin="2026-03-02",
            consumo_kwh=100.0,
            importe_potencia=None,
            importe_energia=20.0,  # 0,20 €/kWh frente a la mediana 0,10: +100 %
            impuestos_otros=None,
            importe_total=20.0,
            potencia_kw=None,
        ),
    )
    segunda = _subir(cliente_http, _pdf("Factura T05-502 cara"))

    assert segunda.status_code == 200
    assert [a["regla"] for a in segunda.json()["anomalias"]] == ["R9"]
