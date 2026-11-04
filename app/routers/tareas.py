"""Tareas programadas que llama n8n (docs/spec.md, secciones 10 y 15).

`POST /tareas/sin-facturar` ejecuta la regla R10 sobre toda la cartera: suministros
activos sin factura en los últimos 60 días. No cuelga de una factura concreta, así que
se lanza de forma programada y no durante la ingesta.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import TareaSinFacturarOut
from app.services.rules import evaluar_suministros_sin_facturar

router = APIRouter(prefix="/tareas", tags=["tareas"])


@router.post("/sin-facturar", response_model=TareaSinFacturarOut)
def ejecutar_sin_facturar(
    sesion: Annotated[Session, Depends(get_session)],
) -> TareaSinFacturarOut:
    """Ejecuta R10 sobre toda la cartera y devuelve cuántas anomalías nuevas creó.

    Idempotente: cada suministro activo tiene como mucho una anomalía R10 abierta, así
    que llamarla dos veces seguidas la segunda devuelve cero.
    """
    creadas = evaluar_suministros_sin_facturar(sesion)
    sesion.commit()
    return TareaSinFacturarOut(anomalias_creadas=creadas)
