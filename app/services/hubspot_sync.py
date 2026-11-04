"""Sincronización HubSpot → Energy Ops (docs/spec.md, sección 12).

El equipo mueve las fases de los negocios en HubSpot y aquí se reflejan en
`suministros.estado`. HubSpot es la fuente de verdad del estado, pero nunca se retrocede:
un negocio cuya última modificación es anterior a `estado_desde` es una respuesta vieja y
se ignora. La marca de la última sincronización correcta vive en `eventos_sync` y solo se
actualiza si el proceso completo termina sin errores.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EventoSync, Suministro
from app.services.hubspot import obtener_cliente

logger = logging.getLogger(__name__)

SISTEMA = "hubspot"
OPERACION_MARCA = "sync_marca"
OPERACION_SYNC = "sync_estados"


def leer_marca(sesion: Session) -> datetime | None:
    """Última fecha de sincronización correcta, guardada en `eventos_sync`.

    Devuelve None si nunca se ha sincronizado: entonces se leen todos los negocios.
    """
    evento = sesion.scalar(
        select(EventoSync)
        .where(
            EventoSync.sistema == SISTEMA,
            EventoSync.operacion == OPERACION_MARCA,
            EventoSync.ok.is_(True),
        )
        .order_by(EventoSync.id.desc())
        .limit(1)
    )
    if evento is None or not evento.detalle or "desde" not in evento.detalle:
        return None
    return datetime.fromisoformat(str(evento.detalle["desde"]))


def _fecha_negocio(negocio: dict[str, Any]) -> datetime | None:
    """`hs_lastmodifieddate` del negocio como fecha con zona, o None si no se puede leer."""
    iso = negocio.get("properties", {}).get("hs_lastmodifieddate")
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _procesar_negocio(sesion: Session, negocio: dict[str, Any], resumen: dict[str, int]) -> None:
    """Aplica la fase de un negocio al suministro, contando el resultado en el resumen."""
    propiedades = negocio.get("properties", {})
    nuevo_estado = settings.hs_mapa_estados.get(propiedades.get("dealstage") or "")
    id_hubspot = negocio.get("id")
    suministro = None
    if id_hubspot:
        suministro = sesion.scalar(
            select(Suministro).where(Suministro.hubspot_deal_id == str(id_hubspot))
        )
    if suministro is None and propiedades.get("cups"):
        suministro = sesion.scalar(select(Suministro).where(Suministro.cups == propiedades["cups"]))
    if suministro is None or nuevo_estado is None:
        resumen["omitidos"] += 1  # sin suministro local o fase sin traducción
        return
    if nuevo_estado == suministro.estado:
        resumen["omitidos"] += 1  # solo se toca el estado cuando la fase cambió
        return
    fecha_negocio = _fecha_negocio(negocio)
    if fecha_negocio is not None and fecha_negocio < suministro.estado_desde:
        resumen["omitidos"] += 1  # respuesta vieja: no retrocede el estado
        return
    suministro.estado = nuevo_estado
    suministro.estado_desde = datetime.now(UTC)
    resumen["actualizados"] += 1


def sincronizar_estados(sesion: Session) -> dict[str, int]:
    """Refleja en `suministros` las fases movidas en HubSpot desde la última marca.

    Devuelve `{revisados, actualizados, omitidos, errores}`. La marca (`sync_marca`) solo
    se actualiza si el proceso termina sin errores, para no saltarse cambios la próxima
    vez; un fallo del proveedor se propaga como `HubSpotError` sin escribir nada.
    """
    ahora = datetime.now(UTC)
    marca = leer_marca(sesion)
    negocios = obtener_cliente().negocios_modificados_desde(marca)
    resumen: dict[str, int] = {"revisados": 0, "actualizados": 0, "omitidos": 0, "errores": 0}
    for negocio in negocios:
        resumen["revisados"] += 1
        try:
            _procesar_negocio(sesion, negocio, resumen)
        except Exception:
            resumen["errores"] += 1
            logger.exception("Error aplicando la fase de un negocio durante el sync")
    ok = resumen["errores"] == 0
    if ok:
        sesion.add(
            EventoSync(
                sistema=SISTEMA,
                operacion=OPERACION_MARCA,
                ok=True,
                detalle={"desde": ahora.isoformat()},
            )
        )
    sesion.add(EventoSync(sistema=SISTEMA, operacion=OPERACION_SYNC, ok=ok, detalle=dict(resumen)))
    sesion.commit()
    return resumen
