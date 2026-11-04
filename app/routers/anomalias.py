"""Endpoints de anomalías: listado con filtros y cierre con comentario (sección 15).

`GET /anomalias` filtra por `estado`, `severidad` y `cups` (normalizando el CUPS; la
búsqueda encuentra también las anomalías de suministro, como la R10, a través del
suministro). `PATCH /anomalias/{id}` pasa la anomalía a `resuelta` o `descartada` con un
comentario obligatorio que se añade a `detalle`, de modo que quede trazabilidad de quién
cerró la anomalía y por qué.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.cups import normalizar_cups
from app.models import Anomalia, Factura, Suministro
from app.schemas import AnomaliaActualizacion, AnomaliaOut

router = APIRouter(prefix="/anomalias", tags=["anomalias"])

EstadoAnomalia = Literal["abierta", "resuelta", "descartada"]
SeveridadAnomalia = Literal["alta", "media", "baja"]


@router.get("", response_model=list[AnomaliaOut])
def listar_anomalias(
    sesion: Annotated[Session, Depends(get_session)],
    estado: Annotated[EstadoAnomalia | None, Query()] = None,
    severidad: Annotated[SeveridadAnomalia | None, Query()] = None,
    cups: Annotated[str | None, Query()] = None,
) -> list[AnomaliaOut]:
    """Lista anomalías con filtros por `estado`, `severidad` y `cups`.

    El filtro de CUPS acepta minúsculas y espacios (se normaliza) y cubre tanto las
    anomalías de una factura como las del suministro, que no tienen factura (R10).
    """
    consulta = select(Anomalia).order_by(Anomalia.id)
    if estado is not None:
        consulta = consulta.where(Anomalia.estado == estado)
    if severidad is not None:
        consulta = consulta.where(Anomalia.severidad == severidad)
    if cups:
        cups_normalizado = normalizar_cups(cups)
        consulta = (
            consulta.join(Factura, Anomalia.factura_id == Factura.id, isouter=True)
            .join(Suministro, Anomalia.suministro_id == Suministro.id, isouter=True)
            .where(or_(Factura.cups_leido == cups_normalizado, Suministro.cups == cups_normalizado))
        )
    anomalias = sesion.scalars(consulta).all()
    return [AnomaliaOut.model_validate(anomalia, from_attributes=True) for anomalia in anomalias]


@router.patch("/{anomalia_id}", response_model=AnomaliaOut)
def actualizar_anomalia(
    anomalia_id: int,
    cambio: AnomaliaActualizacion,
    sesion: Annotated[Session, Depends(get_session)],
) -> AnomaliaOut:
    """Resuelve o descarta una anomalía; el comentario obligatorio queda en `detalle`."""
    anomalia = sesion.get(Anomalia, anomalia_id)
    if anomalia is None:
        raise HTTPException(status_code=404, detail="Anomalía no encontrada")
    anomalia.estado = cambio.estado
    anomalia.detalle = f"{anomalia.detalle} | {cambio.estado}: {cambio.comentario}"
    sesion.commit()
    sesion.refresh(anomalia)
    return AnomaliaOut.model_validate(anomalia, from_attributes=True)
