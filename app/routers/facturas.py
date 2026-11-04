"""Endpoints de facturas: `POST /facturas` y `GET /facturas` (docs/spec.md, sección 15).

Cada operación queda registrada en `eventos_sync` (sistema `api`, operación
`extraer_factura`) sin guardar contenido del documento, solo identificadores y resultado.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.cups import normalizar_cups
from app.models import Anomalia, Cliente, EventoSync, Factura, Suministro
from app.schemas import AnomaliaOut, FacturaOut, FacturaSubidaOut
from app.services.extraction import ExtraccionInvalida
from app.services.invoices import hash_factura, procesar_factura

router = APIRouter(prefix="/facturas", tags=["facturas"])

SISTEMA = "api"
OPERACION = "extraer_factura"


def _registrar_evento(
    sesion: Session,
    ok: bool,
    entidad_id: str,
    detalle: dict[str, object],
) -> None:
    """Deja constancia de la operación en `eventos_sync`, sin contenido del documento."""
    sesion.add(
        EventoSync(
            sistema=SISTEMA,
            operacion=OPERACION,
            entidad_id=entidad_id,
            ok=ok,
            detalle=detalle,
        )
    )


def _respuesta_factura(sesion: Session, factura: Factura, creada: bool) -> FacturaSubidaOut:
    """Construye la respuesta con la factura y sus anomalías."""
    salida = FacturaOut.model_validate(factura, from_attributes=True)
    anomalias = sesion.scalars(
        select(Anomalia).where(Anomalia.factura_id == factura.id).order_by(Anomalia.id)
    ).all()
    salida.anomalias = [AnomaliaOut.model_validate(a, from_attributes=True) for a in anomalias]
    return FacturaSubidaOut(**salida.model_dump(), creada=creada)


@router.post("", response_model=FacturaSubidaOut)
def subir_factura(
    archivo: Annotated[UploadFile, File()],
    sesion: Annotated[Session, Depends(get_session)],
) -> FacturaSubidaOut:
    """Sube un PDF: extrae con el LLM, guarda y devuelve la factura con sus anomalías.

    Idempotente: reprocesar el mismo PDF (o la misma clave de negocio) devuelve la factura
    existente con `creada=False`.
    """
    nombre = archivo.filename or ""
    tipo = archivo.content_type or ""
    pdf_bytes = archivo.file.read()
    es_pdf = pdf_bytes.startswith(b"%PDF") and (
        "pdf" in tipo.lower() or nombre.lower().endswith(".pdf")
    )
    if not es_pdf:
        raise HTTPException(status_code=422, detail="El archivo debe ser un PDF de factura")
    archivo_hash = hash_factura(pdf_bytes)
    try:
        resultado = procesar_factura(sesion, pdf_bytes)
    except ExtraccionInvalida as exc:
        sesion.rollback()
        _registrar_evento(
            sesion,
            ok=False,
            entidad_id=archivo_hash,
            detalle={"archivo_hash": archivo_hash, "error": str(exc)},
        )
        sesion.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _registrar_evento(
        sesion,
        ok=True,
        entidad_id=str(resultado.factura.id),
        detalle={
            "archivo_hash": archivo_hash,
            "creada": resultado.creada,
            "factura_id": resultado.factura.id,
            "suministro_id": resultado.factura.suministro_id,
        },
    )
    sesion.commit()
    return _respuesta_factura(sesion, resultado.factura, resultado.creada)


@router.get("", response_model=list[FacturaOut])
def listar_facturas(
    sesion: Annotated[Session, Depends(get_session)],
    cups: Annotated[str | None, Query()] = None,
    cliente_nif: Annotated[str | None, Query()] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> list[FacturaOut]:
    """Lista facturas con filtros por `cups`, `cliente_nif` y periodo (`desde`, `hasta`).

    `desde` acota el inicio del periodo facturado y `hasta` su fin. El filtro
    `cliente_nif` solo devuelve facturas de suministros en cartera (las que tienen
    suministro asociado).
    """
    consulta = select(Factura).order_by(Factura.id)
    if cups:
        consulta = consulta.where(Factura.cups_leido == normalizar_cups(cups))
    if cliente_nif:
        consulta = consulta.join(Suministro, Factura.suministro_id == Suministro.id).join(
            Cliente, Suministro.cliente_id == Cliente.id
        )
        consulta = consulta.where(Cliente.nif == cliente_nif)
    if desde:
        consulta = consulta.where(Factura.fecha_inicio >= desde)
    if hasta:
        consulta = consulta.where(Factura.fecha_fin <= hasta)
    facturas = sesion.scalars(consulta).all()
    respuestas = [FacturaOut.model_validate(f, from_attributes=True) for f in facturas]
    if respuestas:
        ids = [f.id for f in facturas]
        anomalias = sesion.scalars(
            select(Anomalia).where(Anomalia.factura_id.in_(ids)).order_by(Anomalia.id)
        ).all()
        por_factura: dict[int, list[AnomaliaOut]] = {}
        for a in anomalias:
            por_factura.setdefault(a.factura_id or 0, []).append(
                AnomaliaOut.model_validate(a, from_attributes=True)
            )
        for respuesta, factura in zip(respuestas, facturas, strict=True):
            respuesta.anomalias = por_factura.get(factura.id, [])
    return respuestas
