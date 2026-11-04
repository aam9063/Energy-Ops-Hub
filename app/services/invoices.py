"""Orquestación de la ingesta de facturas (docs/spec.md, secciones 7 y 9).

Idempotencia en dos niveles, que son las dos restricciones UNIQUE de `facturas`:

- `archivo_hash` UNIQUE: el mismo PDF no se procesa dos veces y, sobre todo, no se vuelve a
  pagar una llamada al LLM.
- `(cups_leido, numero, comercializadora)` UNIQUE: dos PDFs distintos de la misma factura
  tampoco duplican nada.

La política de revisión humana (R11) es la primera anomalía del sistema: confianza < 0,85 o
algún campo dudoso la disparan (sección 9). El servicio no hace commit: lo hace el router,
junto con la fila de auditoría en `eventos_sync`.
"""

import hashlib
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cups import normalizar_cups
from app.models import Anomalia, Factura, Suministro
from app.schemas import FacturaExtraida
from app.services.extraction import extraer_factura

UMBRAL_CONFIANZA = 0.85
REGLA_REVISION = "R11"


def hash_factura(pdf_bytes: bytes) -> str:
    """SHA-256 del documento: la clave de idempotencia por archivo."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def _dinero(valor: float | None) -> Decimal | None:
    """Convierte un importe del esquema de extracción a `Decimal` con dos decimales."""
    if valor is None:
        return None
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _confianza(valor: float) -> Decimal:
    """La confianza se guarda en NUMERIC(3,2): dos decimales, entre 0 y 1."""
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ResultadoFactura:
    """Resultado de procesar un PDF: la factura y si se ha creado en esta llamada."""

    factura: Factura
    creada: bool
    archivo_hash: str


def procesar_factura(sesion: Session, pdf_bytes: bytes) -> ResultadoFactura:
    """Procesa un PDF de factura: extrae con el LLM, resuelve idempotencia y persiste.

    Si el PDF ya se procesó (por hash) o la factura ya existe (por clave de negocio),
    devuelve la factura existente con `creada=False` sin llamar al LLM en el primer caso.
    """
    archivo_hash = hash_factura(pdf_bytes)
    existente = sesion.scalar(select(Factura).where(Factura.archivo_hash == archivo_hash))
    if existente is not None:
        return ResultadoFactura(factura=existente, creada=False, archivo_hash=archivo_hash)

    datos, meta = extraer_factura(pdf_bytes)
    cups = normalizar_cups(datos.cups)
    numero = datos.numero_factura.strip()
    comercializadora = datos.comercializadora.strip()
    existente = sesion.scalar(
        select(Factura).where(
            Factura.cups_leido == cups,
            Factura.numero == numero,
            Factura.comercializadora == comercializadora,
        )
    )
    if existente is not None:
        return ResultadoFactura(factura=existente, creada=False, archivo_hash=archivo_hash)

    suministro = sesion.scalar(select(Suministro).where(Suministro.cups == cups))
    # La salida completa del modelo, serializable, más los metadatos de la llamada (modelo y
    # tokens) bajo una clave reservada: así se audita el coste sin llamar otra vez (sección 7).
    crudos: dict[str, Any] = datos.model_dump(mode="json")
    crudos["_extraccion"] = meta
    factura = Factura(
        suministro_id=suministro.id if suministro is not None else None,
        cups_leido=cups,
        numero=numero,
        comercializadora=comercializadora,
        fecha_emision=datos.fecha_emision,
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        potencia_kw=_dinero(datos.potencia_kw),
        consumo_kwh=_dinero(datos.consumo_kwh),
        importe_potencia=_dinero(datos.importe_potencia),
        importe_energia=_dinero(datos.importe_energia),
        impuestos_otros=_dinero(datos.impuestos_otros),
        importe_total=_dinero(datos.importe_total),
        lectura_estimada=datos.lectura_estimada,
        confianza=_confianza(datos.confianza),
        archivo_hash=archivo_hash,
        datos_crudos=crudos,
    )
    sesion.add(factura)
    sesion.flush()  # hace falta factura.id para la anomalía de revisión
    _crear_revision_humana(sesion, factura, datos)
    return ResultadoFactura(factura=factura, creada=True, archivo_hash=archivo_hash)


def _crear_revision_humana(sesion: Session, factura: Factura, datos: FacturaExtraida) -> None:
    """R11 «Revisión de extracción»: confianza < 0,85 o campos dudosos (sección 9).

    Idempotente respecto de la restricción UNIQUE (factura_id, regla): si la anomalía ya
    existe, no se duplica.
    """
    if datos.confianza >= UMBRAL_CONFIANZA and not datos.campos_dudosos:
        return
    motivos = []
    if datos.confianza < UMBRAL_CONFIANZA:
        motivos.append(f"confianza {datos.confianza:.2f} (umbral {UMBRAL_CONFIANZA})")
    if datos.campos_dudosos:
        motivos.append("campos dudosos: " + ", ".join(datos.campos_dudosos))
    existe = sesion.scalar(
        select(Anomalia).where(Anomalia.factura_id == factura.id, Anomalia.regla == REGLA_REVISION)
    )
    if existe is not None:
        return
    sesion.add(
        Anomalia(
            factura_id=factura.id,
            suministro_id=factura.suministro_id,
            regla=REGLA_REVISION,
            severidad="media",
            detalle="Revisión de extracción: " + "; ".join(motivos),
        )
    )
