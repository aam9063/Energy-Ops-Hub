"""Capa de I/O de las reglas (docs/spec.md, sección 10).

Aquí vive todo lo que toca la base de datos: cargar el contexto de evaluación de una
factura (suministro, histórico, candidatos de R3/R4 y mediana de €/kWh de la cartera),
persistir las anomalías de forma idempotente respecto de `UNIQUE (factura_id, regla)` y
ejecutar R10 sobre toda la cartera. Las reglas en sí son puras: `app/domain/rules.py`.
"""

import statistics
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cups import normalizar_cups
from app.domain.rules import (
    DIAS_SIN_FACTURAR,
    ContextoReglas,
    FacturaDatos,
    SuministroDatos,
    evaluar,
    r10_suministro_sin_facturar,
)
from app.domain.rules import (
    Anomalia as AnomaliaDominio,
)
from app.models import Anomalia as AnomaliaDB
from app.models import Factura, Suministro
from app.schemas import FacturaExtraida

REGLA_SIN_FACTURAR = "R10"


def _a_suministro_datos(suministro: Suministro) -> SuministroDatos:
    """Convierte un `Suministro` de la base de datos al tipo puro de las reglas."""
    return SuministroDatos(
        cups=suministro.cups,
        estado=suministro.estado,
        potencia_kw=float(suministro.potencia_kw) if suministro.potencia_kw is not None else None,
        tarifa_acceso=suministro.tarifa_acceso,
    )


def _a_factura_datos(factura: Factura) -> FacturaDatos:
    """Convierte una `Factura` de la base de datos al tipo puro de las reglas."""
    crudos = factura.datos_crudos or {}
    dudosos = crudos.get("campos_dudosos") or []
    return FacturaDatos(
        id=factura.id,
        cups_leido=factura.cups_leido,
        numero=factura.numero,
        comercializadora=factura.comercializadora,
        fecha_inicio=factura.fecha_inicio,
        fecha_fin=factura.fecha_fin,
        potencia_kw=float(factura.potencia_kw) if factura.potencia_kw is not None else None,
        consumo_kwh=float(factura.consumo_kwh),
        importe_potencia=(
            float(factura.importe_potencia) if factura.importe_potencia is not None else None
        ),
        importe_energia=(
            float(factura.importe_energia) if factura.importe_energia is not None else None
        ),
        impuestos_otros=(
            float(factura.impuestos_otros) if factura.impuestos_otros is not None else None
        ),
        importe_total=float(factura.importe_total),
        lectura_estimada=factura.lectura_estimada,
        confianza=float(factura.confianza) if factura.confianza is not None else None,
        campos_dudosos=[str(campo) for campo in dudosos],
        archivo_hash=factura.archivo_hash,
    )


def a_factura_de_extraccion(datos: FacturaExtraida, archivo_hash: str) -> FacturaDatos:
    """Convierte la salida del LLM al tipo puro, para evaluarla sin fila en la base.

    Es la candidata que llega cuando el mismo PDF (misma clave de negocio) ya existe:
    dispara R3 contra la factura guardada, aunque la nueva copia no se llegue a insertar.
    """
    return FacturaDatos(
        id=None,
        cups_leido=normalizar_cups(datos.cups),
        numero=datos.numero_factura.strip(),
        comercializadora=datos.comercializadora.strip(),
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
        potencia_kw=datos.potencia_kw,
        consumo_kwh=datos.consumo_kwh,
        importe_potencia=datos.importe_potencia,
        importe_energia=datos.importe_energia,
        impuestos_otros=datos.impuestos_otros,
        importe_total=datos.importe_total,
        lectura_estimada=datos.lectura_estimada,
        confianza=datos.confianza,
        campos_dudosos=list(datos.campos_dudosos),
        archivo_hash=archivo_hash,
    )


def mediana_precio_kwh(
    sesion: Session, tarifa: str | None, factura_excluida: int | None = None
) -> float | None:
    """Mediana de €/kWh de energía en la cartera para la tarifa dada.

    Excluye la factura que se está evaluando (su precio es justo el que se contrasta).
    Sin tarifa o sin facturas con precio calculable, devuelve `None` y R9 no dispara.
    """
    if tarifa is None:
        return None
    condiciones = [
        Suministro.tarifa_acceso == tarifa,
        Factura.importe_energia.is_not(None),
        Factura.consumo_kwh > 0,
    ]
    if factura_excluida is not None:
        condiciones.append(Factura.id != factura_excluida)
    filas = sesion.execute(
        select(Factura.importe_energia, Factura.consumo_kwh)
        .join(Suministro, Factura.suministro_id == Suministro.id)
        .where(*condiciones)
    ).all()
    precios = [float(importe) / float(consumo) for importe, consumo in filas if importe is not None]
    if not precios:
        return None
    return statistics.median(precios)


def cargar_contexto(
    sesion: Session,
    factura: Factura,
    candidatas_extra: Sequence[FacturaDatos] = (),
) -> ContextoReglas:
    """Carga el contexto de evaluación de una factura: suministro, histórico y candidatos.

    `historico` son las facturas anteriores del mismo suministro ordenadas por `fecha_fin`;
    `mismo_cups` son las otras facturas del mismo CUPS (candidatas a R3/R4) más las
    candidatas extra que llegan sin fila propia (la copia duplicada que se acaba de subir).
    """
    suministro = sesion.scalar(select(Suministro).where(Suministro.cups == factura.cups_leido))
    mismo_cups = list(
        sesion.scalars(
            select(Factura)
            .where(Factura.cups_leido == factura.cups_leido, Factura.id != factura.id)
            .order_by(Factura.fecha_fin, Factura.id)
        )
    )
    historico: list[Factura] = []
    if suministro is not None:
        historico = list(
            sesion.scalars(
                select(Factura)
                .where(
                    Factura.suministro_id == suministro.id,
                    Factura.id != factura.id,
                )
                .order_by(Factura.fecha_fin, Factura.id)
            )
        )
    tarifa = suministro.tarifa_acceso if suministro is not None else None
    return ContextoReglas(
        suministro=_a_suministro_datos(suministro) if suministro is not None else None,
        historico=[_a_factura_datos(historica) for historica in historico],
        mismo_cups=[_a_factura_datos(candidata) for candidata in mismo_cups]
        + list(candidatas_extra),
        mediana_precio_kwh=mediana_precio_kwh(sesion, tarifa, factura.id),
    )


def guardar_anomalias(
    sesion: Session,
    factura: Factura,
    anomalias: Sequence[AnomaliaDominio],
) -> None:
    """Persiste las anomalías de una factura de forma idempotente.

    Respeta `UNIQUE (factura_id, regla)`: si la anomalía de esa regla ya existe, no se
    duplica. Así, reevaluar una factura (por ejemplo al llegar un duplicado) no crea filas
    repetidas. No hace commit: lo hace el router.
    """
    if not anomalias:
        return
    reglas = [anomalia.regla for anomalia in anomalias]
    existentes = set(
        sesion.scalars(
            select(AnomaliaDB.regla).where(
                AnomaliaDB.factura_id == factura.id, AnomaliaDB.regla.in_(reglas)
            )
        )
    )
    for anomalia in anomalias:
        if anomalia.regla in existentes:
            continue
        sesion.add(
            AnomaliaDB(
                factura_id=factura.id,
                suministro_id=factura.suministro_id,
                regla=anomalia.regla,
                severidad=anomalia.severidad,
                detalle=anomalia.detalle,
            )
        )
    sesion.flush()


def evaluar_y_guardar(
    sesion: Session,
    factura: Factura,
    candidatas_extra: Sequence[FacturaDatos] = (),
) -> list[AnomaliaDominio]:
    """Evalúa todas las reglas por factura con su contexto real y guarda el resultado."""
    contexto = cargar_contexto(sesion, factura, candidatas_extra)
    anomalias = evaluar(_a_factura_datos(factura), contexto)
    guardar_anomalias(sesion, factura, anomalias)
    return anomalias


def evaluar_suministros_sin_facturar(sesion: Session, dias: int = DIAS_SIN_FACTURAR) -> int:
    """Ejecuta R10 sobre toda la cartera y devuelve cuántas anomalías nuevas creó.

    Como R10 no cuelga de una factura (`factura_id` es NULL) la restricción
    `UNIQUE (factura_id, regla)` no la protege de duplicados: la idempotencia es que cada
    suministro tenga como mucho una R10 abierta. No hace commit: lo hace el router.
    """
    activos = sesion.scalars(
        select(Suministro).where(Suministro.estado == "activo").order_by(Suministro.id)
    ).all()
    creadas = 0
    for suministro in activos:
        ultima = sesion.scalar(
            select(Factura)
            .where(Factura.cups_leido == suministro.cups)
            .order_by(Factura.fecha_fin.desc(), Factura.id.desc())
            .limit(1)
        )
        anomalia = r10_suministro_sin_facturar(
            _a_suministro_datos(suministro),
            _a_factura_datos(ultima) if ultima is not None else None,
            dias,
        )
        if anomalia is None:
            continue
        ya_abierta = sesion.scalar(
            select(AnomaliaDB).where(
                AnomaliaDB.suministro_id == suministro.id,
                AnomaliaDB.regla == REGLA_SIN_FACTURAR,
                AnomaliaDB.factura_id.is_(None),
                AnomaliaDB.estado == "abierta",
            )
        )
        if ya_abierta is not None:
            continue
        sesion.add(
            AnomaliaDB(
                suministro_id=suministro.id,
                regla=REGLA_SIN_FACTURAR,
                severidad=anomalia.severidad,
                detalle=anomalia.detalle,
            )
        )
        creadas += 1
    return creadas
