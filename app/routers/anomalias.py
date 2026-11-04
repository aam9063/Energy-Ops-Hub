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
from app.models import Anomalia, Cliente, EventoSync, Factura, Suministro
from app.schemas import AnomaliaActualizacion, AnomaliaOut, TicketCreadoOut
from app.services.hubspot import HubSpotError, obtener_cliente

router = APIRouter(prefix="/anomalias", tags=["anomalias"])

SISTEMA = "hubspot"
OPERACION_TICKET = "ticket_anomalia"

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


def _cups_de_anomalia(sesion: Session, anomalia: Anomalia) -> str:
    """CUPS de la anomalía: el del suministro si está en cartera, o el de la factura."""
    if anomalia.suministro_id is not None:
        suministro = sesion.get(Suministro, anomalia.suministro_id)
        if suministro is not None:
            return suministro.cups
    if anomalia.factura_id is not None:
        factura = sesion.get(Factura, anomalia.factura_id)
        if factura is not None:
            return factura.cups_leido
    return ""


def _company_de_anomalia(sesion: Session, anomalia: Anomalia) -> str | None:
    """Empresa de HubSpot del cliente del suministro, si la anomalía tiene suministro."""
    if anomalia.suministro_id is None:
        return None
    return sesion.scalar(
        select(Cliente.hubspot_company_id)
        .join(Suministro, Suministro.cliente_id == Cliente.id)
        .where(Suministro.id == anomalia.suministro_id)
    )


@router.post("/{anomalia_id}/ticket", response_model=TicketCreadoOut)
def crear_ticket(
    anomalia_id: int, sesion: Annotated[Session, Depends(get_session)]
) -> TicketCreadoOut:
    """Crea el ticket en HubSpot de la anomalía, o devuelve el que ya existía.

    Idempotente: primero mira el `hubspot_ticket_id` guardado y después el servicio
    busca por `energy_ops_id`, así que repetir la llamada nunca duplica tickets.
    """
    anomalia = sesion.get(Anomalia, anomalia_id)
    if anomalia is None:
        raise HTTPException(status_code=404, detail="Anomalía no encontrada")
    existente = anomalia.hubspot_ticket_id
    if existente is not None:
        return TicketCreadoOut(anomalia_id=anomalia.id, hubspot_ticket_id=existente, creado=False)
    try:
        ticket_id = obtener_cliente().crear_ticket_anomalia(
            anomalia, _cups_de_anomalia(sesion, anomalia), _company_de_anomalia(sesion, anomalia)
        )
    except HubSpotError as exc:
        sesion.add(
            EventoSync(
                sistema=SISTEMA,
                operacion=OPERACION_TICKET,
                entidad_id=str(anomalia.id),
                ok=False,
                detalle={"error": str(exc)},
            )
        )
        sesion.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    anomalia.hubspot_ticket_id = ticket_id
    sesion.add(
        EventoSync(
            sistema=SISTEMA,
            operacion=OPERACION_TICKET,
            entidad_id=str(anomalia.id),
            ok=True,
            detalle={"hubspot_ticket_id": ticket_id},
        )
    )
    sesion.commit()
    return TicketCreadoOut(anomalia_id=anomalia.id, hubspot_ticket_id=ticket_id, creado=True)
