"""Endpoint de sincronización HubSpot → Energy Ops: `POST /sync/hubspot` (sección 15).

Un fallo del proveedor es reintentable, no un error del cliente: `HubSpotError` se
traduce a 503 con un evento `ok=False` en `eventos_sync`, con el mismo criterio que la
extracción con LLM.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import EventoSync
from app.schemas import SyncResumenOut
from app.services.hubspot import HubSpotError
from app.services.hubspot_sync import OPERACION_SYNC, SISTEMA, sincronizar_estados

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/hubspot", response_model=SyncResumenOut)
def sincronizar_hubspot(sesion: Annotated[Session, Depends(get_session)]) -> SyncResumenOut:
    """Refleja en `suministros` las fases que el equipo ha movido en HubSpot."""
    try:
        resumen = sincronizar_estados(sesion)
    except HubSpotError as exc:
        sesion.rollback()  # nada del sync queda a medias cuando el proveedor falla
        sesion.add(
            EventoSync(
                sistema=SISTEMA,
                operacion=OPERACION_SYNC,
                ok=False,
                detalle={"error": str(exc)},
            )
        )
        sesion.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SyncResumenOut(**resumen)
