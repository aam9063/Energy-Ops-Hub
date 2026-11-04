"""Carga clientes y suministros de ejemplo (docs/spec.md, sección 8).

Es idempotente: se puede ejecutar las veces que haga falta. Los clientes se buscan por NIF y
los suministros por CUPS, así que una segunda ejecución no duplica nada.

Uso:
    uv run python -m scripts.seed
    uv run python -m scripts.seed --reset   # borra suministros y clientes de ejemplo primero
"""

import argparse
import random
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db import SessionLocal
from app.domain.cups import letras_control
from app.models import Cliente, Suministro
from sqlalchemy import delete, select

SEMILLA = 20261104
DISTRIBUIDORAS = ("0031", "0021", "0022")
ESTADOS = ("pendiente", "en_tramite", "activo", "activo", "activo", "rechazado", "baja")


def cups_ejemplo(indice: int) -> str:
    """CUPS válido y estable para el índice dado: 16 dígitos + letras de control."""
    digitos = DISTRIBUIDORAS[indice % len(DISTRIBUIDORAS)] + f"{indice:012d}"
    return f"ES{digitos}{letras_control(digitos)}"


def suministros_de_ejemplo() -> list[dict[str, object]]:
    """Tres clientes de sectores distintos con unos 40 suministros en total."""
    filas: list[dict[str, object]] = []
    indice = 0

    # Build to rent: 24 viviendas en luz 2.0TD y 4 portales con gas.
    for numero in range(1, 25):
        filas.append(
            {
                "cliente_nif": "B87654321",
                "tipo": "luz",
                "tarifa_acceso": "2.0TD",
                "potencia_kw": random.Random(SEMILLA + indice).choice([3.3, 4.6, 5.75, 6.9]),
                "direccion": f"Calle Alameda {numero}, 28001 Madrid",
                "comercializadora": "Voltia Energía",
            }
        )
        indice += 1
    for portal in range(1, 5):
        filas.append(
            {
                "cliente_nif": "B87654321",
                "tipo": "gas",
                "tarifa_acceso": "RL.1",
                "potencia_kw": 24.0,
                "direccion": f"Portal {portal}, Calle Alameda, 28001 Madrid",
                "comercializadora": "Ecoflux",
            }
        )
        indice += 1

    # Oficinas: 6 suministros en 3.0TD.
    for planta in range(1, 7):
        filas.append(
            {
                "cliente_nif": "A12345678",
                "tipo": "luz",
                "tarifa_acceso": "3.0TD",
                "potencia_kw": 45.0,
                "direccion": f"Torre Iberia, planta {planta}, 28020 Madrid",
                "comercializadora": "Luminar Comercializadora",
            }
        )
        indice += 1

    # Logística: 4 naves en 3.0TD y 2 acometidas de agua.
    for nave in range(1, 5):
        filas.append(
            {
                "cliente_nif": "B99887766",
                "tipo": "luz",
                "tarifa_acceso": "3.0TD",
                "potencia_kw": 120.0,
                "direccion": f"Polígono Las Canteras, nave {nave}, 28850 Torrejón",
                "comercializadora": "Voltia Energía",
            }
        )
        indice += 1
    for acometida in range(1, 3):
        filas.append(
            {
                "cliente_nif": "B99887766",
                "tipo": "agua",
                "tarifa_acceso": None,
                "potencia_kw": None,
                "direccion": f"Polígono Las Canteras, acometida {acometida}, 28850 Torrejón",
                "comercializadora": "Canal Local",
            }
        )
        indice += 1

    for numero, fila in enumerate(filas):
        fila["cups"] = cups_ejemplo(numero)
    return filas


def clientes_de_ejemplo() -> list[dict[str, str]]:
    return [
        {"nombre": "Alameda Living S.L.", "nif": "B87654321", "sector": "build_to_rent"},
        {"nombre": "Oficinas Iberia S.A.", "nif": "A12345678", "sector": "oficinas"},
        {"nombre": "Logística Canteras S.L.", "nif": "B99887766", "sector": "logistica"},
    ]


def estado_de_ejemplo(indice: int) -> tuple[str, datetime]:
    estado = ESTADOS[indice % len(ESTADOS)]
    dias = random.Random(SEMILLA * (indice + 1)).randint(0, 90)
    return estado, datetime.now(tz=UTC) - timedelta(days=dias)


def sembrar(reset: bool = False) -> dict[str, int]:
    """Crea o actualiza clientes y suministros. Devuelve cuántos se crearon y actualizaron."""
    creados = 0
    actualizados = 0
    with SessionLocal() as sesion:
        if reset:
            sesion.execute(delete(Suministro))
            sesion.execute(delete(Cliente))
            sesion.commit()

        clientes: dict[str, Cliente] = {}
        for datos in clientes_de_ejemplo():
            cliente = sesion.scalar(select(Cliente).where(Cliente.nif == datos["nif"]))
            if cliente is None:
                cliente = Cliente(**datos)
                sesion.add(cliente)
                creados += 1
            else:
                cliente.nombre = datos["nombre"]
                cliente.sector = datos["sector"]
            clientes[datos["nif"]] = cliente
        sesion.flush()

        for indice, fila in enumerate(suministros_de_ejemplo()):
            cups = str(fila["cups"])
            cliente = clientes[str(fila["cliente_nif"])]
            suministro = sesion.scalar(select(Suministro).where(Suministro.cups == cups))
            if suministro is None:
                estado, estado_desde = estado_de_ejemplo(indice)
                sesion.add(
                    Suministro(
                        cliente_id=cliente.id,
                        cups=cups,
                        tipo=str(fila["tipo"]),
                        direccion=str(fila["direccion"]),
                        tarifa_acceso=_texto(fila["tarifa_acceso"]),
                        potencia_kw=_decimal(fila["potencia_kw"]),
                        comercializadora=_texto(fila["comercializadora"]),
                        estado=estado,
                        estado_desde=estado_desde,
                    )
                )
                creados += 1
            else:
                # No se toca el estado: en la demo lo mueve el equipo desde HubSpot.
                suministro.cliente_id = cliente.id
                suministro.direccion = str(fila["direccion"])
                suministro.tarifa_acceso = _texto(fila["tarifa_acceso"])
                suministro.potencia_kw = _decimal(fila["potencia_kw"])
                suministro.comercializadora = _texto(fila["comercializadora"])
                actualizados += 1

        sesion.commit()

    return {"creados": creados, "actualizados": actualizados}


def _texto(valor: object) -> str | None:
    return None if valor is None else str(valor)


def _decimal(valor: object) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Carga datos de ejemplo en la base de datos.")
    parser.add_argument(
        "--reset", action="store_true", help="Borra suministros y clientes antes de sembrar"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    resultado = sembrar(reset=args.reset)
    print(f"creados={resultado['creados']} actualizados={resultado['actualizados']}")


if __name__ == "__main__":
    main()
