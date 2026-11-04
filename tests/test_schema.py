"""Tests del esquema: las restricciones de PostgreSQL se cumplen.

Cubren lo que los modelos prometen en `docs/spec.md` sección 7 y que las reglas de negocio dan por
hecho: claves únicas, `CHECK` de dominios y periodos coherentes. Cada test escribe dentro de una
transacción que se revierte al terminar, así que la base de datos queda como estaba.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from app.db import SessionLocal
from app.models import Anomalia, Cliente, Factura, Suministro
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def sesion() -> Iterator[Session]:
    with SessionLocal() as sesion:
        yield sesion
        sesion.rollback()


def crear_cliente(sesion: Session, nif: str = "B12345678") -> Cliente:
    cliente = Cliente(nombre="Cliente de prueba", nif=nif, sector="oficinas")
    sesion.add(cliente)
    sesion.flush()
    return cliente


def crear_suministro(sesion: Session, cliente: Cliente, cups: str, **extra: object) -> Suministro:
    datos: dict[str, object] = {
        "cliente_id": cliente.id,
        "cups": cups,
        "tipo": "luz",
        "direccion": "Calle Falsa 123",
    }
    datos.update(extra)
    suministro = Suministro(**datos)
    sesion.add(suministro)
    sesion.flush()
    return suministro


def crear_factura(sesion: Session, **extra: object) -> Factura:
    datos: dict[str, object] = {
        "cups_leido": "ES0021000000000001RK",
        "numero": "F-2026-001",
        "comercializadora": "Voltia Energía",
        "fecha_inicio": date(2026, 1, 1),
        "fecha_fin": date(2026, 1, 31),
        "consumo_kwh": Decimal("250.00"),
        "importe_total": Decimal("60.00"),
        "archivo_hash": "hash-001",
        "datos_crudos": {"modelo": "test"},
    }
    datos.update(extra)
    factura = Factura(**datos)
    sesion.add(factura)
    sesion.flush()
    return factura


def test_cups_duplicado_se_rechaza(sesion: Session) -> None:
    cliente = crear_cliente(sesion)
    crear_suministro(sesion, cliente, "ES0021000000000001RK")

    with pytest.raises(IntegrityError):
        crear_suministro(sesion, cliente, "ES0021000000000001RK")


@pytest.mark.parametrize("tipo", ["petroleo", "Luz", ""])
def test_tipo_de_suministro_fuera_del_dominio_se_rechaza(sesion: Session, tipo: str) -> None:
    cliente = crear_cliente(sesion)

    with pytest.raises(IntegrityError):
        crear_suministro(sesion, cliente, "ES0021000000000001RK", tipo=tipo)


def test_estado_fuera_del_dominio_se_rechaza(sesion: Session) -> None:
    cliente = crear_cliente(sesion)

    with pytest.raises(IntegrityError):
        crear_suministro(sesion, cliente, "ES0021000000000001RK", estado="en_limbo")


def test_clave_de_negocio_de_factura_evita_duplicados(sesion: Session) -> None:
    crear_factura(sesion)

    with pytest.raises(IntegrityError):
        crear_factura(sesion, archivo_hash="hash-002")


def test_archivo_hash_evita_procesar_dos_veces_el_mismo_pdf(sesion: Session) -> None:
    crear_factura(sesion)

    with pytest.raises(IntegrityError):
        crear_factura(sesion, numero="F-2026-002")


def test_periodo_invertido_se_rechaza(sesion: Session) -> None:
    with pytest.raises(IntegrityError):
        crear_factura(
            sesion, fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 1, 1), archivo_hash="h-3"
        )


def crear_anomalia(sesion: Session, factura: Factura, regla: str, severidad: str) -> Anomalia:
    anomalia = Anomalia(
        factura_id=factura.id, regla=regla, severidad=severidad, detalle="Detalle de prueba"
    )
    sesion.add(anomalia)
    sesion.flush()
    return anomalia


def test_una_anomalia_por_regla_y_factura(sesion: Session) -> None:
    factura = crear_factura(sesion)
    crear_anomalia(sesion, factura, "R5", "alta")

    with pytest.raises(IntegrityError):
        crear_anomalia(sesion, factura, "R5", "media")


def test_severidad_de_anomalia_fuera_del_dominio_se_rechaza(sesion: Session) -> None:
    factura = crear_factura(sesion)

    with pytest.raises(IntegrityError):
        crear_anomalia(sesion, factura, "R1", "crítica")
