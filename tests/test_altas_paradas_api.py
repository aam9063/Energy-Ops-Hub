"""Tests de integración de `GET /altas` (docs/spec.md, sección 15).

PostgreSQL real (docker compose), sin red: crea su propio escenario de suministros
con `estado_desde` fijado a mano y limpia las filas que crea.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.db import SessionLocal
from app.domain.cups import letras_control
from app.main import app
from app.models import Cliente, Suministro
from fastapi.testclient import TestClient
from sqlalchemy import delete

NIF = "T08TEST01"
CLIENTE = "Cliente altas paradas"
_DIGITOS = {
    "pendiente_30d": "0123456789012345",
    "en_tramite_3d": "5432109876543210",
    "activo_90d": "1111111111111110",
}
CUPS = {nombre: "ES" + digitos + letras_control(digitos) for nombre, digitos in _DIGITOS.items()}
# {cups: (estado, dias en ese estado)}
ESCENARIO = {
    CUPS["pendiente_30d"]: ("pendiente", 30),
    CUPS["en_tramite_3d"]: ("en_tramite", 3),
    CUPS["activo_90d"]: ("activo", 90),
}


def _limpiar() -> None:
    with SessionLocal() as sesion:
        sesion.execute(delete(Suministro).where(Suministro.cups.in_(CUPS.values())))
        sesion.execute(delete(Cliente).where(Cliente.nif == NIF))
        sesion.commit()


@pytest.fixture(autouse=True)
def escenario() -> Iterator[None]:
    """Crea un cliente y tres suministros con su antigüedad en estado, y limpia al salir."""
    _limpiar()
    with SessionLocal() as sesion:
        cliente = Cliente(nombre=CLIENTE, nif=NIF, hubspot_company_id="88")
        sesion.add(cliente)
        sesion.flush()
        ahora = datetime.now(UTC)
        for cups, (estado, dias) in ESCENARIO.items():
            sesion.add(
                Suministro(
                    cliente_id=cliente.id,
                    cups=cups,
                    tipo="luz",
                    direccion="Calle Sintética 1",
                    estado=estado,
                    estado_desde=ahora - timedelta(days=dias),
                )
            )
        sesion.commit()
    yield
    _limpiar()


def _cups_de(respuesta_json: list[dict]) -> list[str]:
    return [fila["cups"] for fila in respuesta_json]


def test_sin_filtro_devuelve_pendientes_y_en_tramite() -> None:
    """Sin `parada_dias` aparecen las altas en `pendiente` y `en_tramite`, con su cliente."""
    cuerpo = TestClient(app).get("/altas").json()

    de_nuestros = [fila for fila in cuerpo if fila["cups"] in CUPS.values()]
    assert _cups_de(de_nuestros) == [CUPS["pendiente_30d"], CUPS["en_tramite_3d"]]
    for fila in de_nuestros:
        assert fila["cliente"] == CLIENTE
        assert fila["estado"] in ("pendiente", "en_tramite")
        assert set(fila) == {"cups", "cliente", "estado", "dias_parada"}


def test_parada_dias_deja_fuera_la_de_tres_dias() -> None:
    """Con `parada_dias=7` la alta de 3 días queda fuera y la de 30 dentro."""
    cuerpo = TestClient(app).get("/altas", params={"parada_dias": 7}).json()

    de_nuestros = _cups_de([f for f in cuerpo if f["cups"] in CUPS.values()])
    assert CUPS["pendiente_30d"] in de_nuestros
    assert CUPS["en_tramite_3d"] not in de_nuestros


def test_dias_parada_se_calcula_en_dias_enteros() -> None:
    """`dias_parada` es el número entero de días en el mismo estado."""
    cuerpo = TestClient(app).get("/altas").json()

    por_cups = {fila["cups"]: fila for fila in cuerpo}
    assert por_cups[CUPS["pendiente_30d"]]["dias_parada"] == 30
    assert por_cups[CUPS["en_tramite_3d"]]["dias_parada"] == 3


def test_suministro_activo_no_aparece() -> None:
    """Solo se listan las altas en trámite: un suministro `activo` no aparece."""
    cuerpo = TestClient(app).get("/altas").json()

    assert CUPS["activo_90d"] not in _cups_de(cuerpo)


def test_orden_de_mas_antigua_a_mas_reciente() -> None:
    """Las altas van ordenadas de más días paradas a menos."""
    cuerpo = TestClient(app).get("/altas").json()

    dias_de_nuestros = [fila["dias_parada"] for fila in cuerpo if fila["cups"] in CUPS.values()]
    assert dias_de_nuestros == sorted(dias_de_nuestros, reverse=True)
    assert dias_de_nuestros == [30, 3]
