"""Endpoints de altas de suministros (docs/spec.md, sección 15).

`POST /altas/lote` valida fila a fila sin abortar el lote, hace upsert del suministro por CUPS
(si ya existe se actualizan los datos técnicos, nunca el estado) y deja el negocio en HubSpot de
forma idempotente con `upsert_deal_alta`. Cada fila lleva el `fila` de la hoja de origen y el
resultado lo devuelve tal cual. Si HubSpot no responde, la fila local ya está guardada: la alta
no se pierde y el reintento del lote la completa. Cada lote y cada fila fallida quedan en
`eventos_sync`, sin datos personales.

`GET /altas` lista las altas en trámite (`pendiente` o `en_tramite`), opcionalmente las que
llevan más de `parada_dias` días en el mismo estado, de más antigua a más reciente.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.cups import cups_valido, normalizar_cups
from app.models import Cliente, EventoSync, Suministro
from app.schemas import (
    AltaLoteIn,
    AltaLoteOut,
    AltaParadaOut,
    FilaAlta,
    ResultadoFila,
    ResumenLote,
)
from app.services.hubspot import HubSpotError, obtener_cliente

router = APIRouter(prefix="/altas", tags=["altas"])

SISTEMA = "hubspot"
OPERACION_LOTE = "altas_lote"
OPERACION_FILA = "altas_lote_fila"
TIPOS_VALIDOS = ("luz", "gas", "agua")
ESTADOS_EN_TRAMITE = ("pendiente", "en_tramite")


def _validar_fila(sesion: Session, fila: FilaAlta) -> Cliente | str:
    """Devuelve el cliente de la fila, o el mensaje de error que la rechaza."""
    if not cups_valido(fila.cups):
        return "CUPS inválido: letras de control incorrectas"
    if fila.tipo not in TIPOS_VALIDOS:
        return f"Tipo inválido: {fila.tipo!r}; debe ser luz, gas o agua"
    if not fila.direccion.strip():
        return "La dirección es obligatoria"
    cliente = sesion.scalar(select(Cliente).where(Cliente.nif == fila.cliente_nif))
    if cliente is None:
        return f"No existe ningún cliente con NIF {fila.cliente_nif}"
    if not cliente.hubspot_company_id:
        return (
            "El cliente no tiene empresa en HubSpot: hay que crearla antes de dar de "
            "alta el suministro"
        )
    return cliente


def _registrar_fila_fallida(sesion: Session, fila: FilaAlta, mensaje: str) -> None:
    """Audita la fila fallida sin datos personales: número de fila y mensaje."""
    sesion.add(
        EventoSync(
            sistema=SISTEMA,
            operacion=OPERACION_FILA,
            entidad_id=f"fila:{fila.fila}",
            ok=False,
            detalle={"mensaje": mensaje},
        )
    )


def _procesar_fila(sesion: Session, fila: FilaAlta) -> tuple[ResultadoFila, bool]:
    """Valida, guarda el suministro y crea o actualiza el negocio; nunca aborta el lote.

    Devuelve el resultado de la fila (con el `fila` de origen, eco exacto) y si el
    suministro se ha creado ahora.
    """
    cups = normalizar_cups(fila.cups)
    validacion = _validar_fila(sesion, fila)
    if isinstance(validacion, str):
        _registrar_fila_fallida(sesion, fila, validacion)
        sesion.commit()
        return ResultadoFila(fila=fila.fila, ok=False, cups=cups, mensaje=validacion), False
    cliente = validacion

    suministro = sesion.scalar(select(Suministro).where(Suministro.cups == cups))
    if suministro is None:
        suministro = Suministro(
            cliente_id=cliente.id,
            cups=cups,
            tipo=fila.tipo,
            direccion=fila.direccion.strip(),
            tarifa_acceso=fila.tarifa_acceso,
            potencia_kw=fila.potencia_kw,
            estado="pendiente",
        )
        sesion.add(suministro)
        creada = True
    else:
        # La alta ya existía: se actualizan los datos técnicos, nunca el estado.
        suministro.direccion = fila.direccion.strip()
        suministro.tarifa_acceso = fila.tarifa_acceso
        suministro.potencia_kw = fila.potencia_kw
        creada = False
    sesion.commit()  # la fila local se guarda aunque HubSpot falle: no se pierde la alta

    try:
        assert cliente.hubspot_company_id is not None  # garantizado por _validar_fila
        deal_id = obtener_cliente().upsert_deal_alta(suministro, cliente.hubspot_company_id)
    except HubSpotError as exc:
        mensaje = f"HubSpot no disponible: {exc}"
        _registrar_fila_fallida(sesion, fila, mensaje)
        sesion.commit()
        return ResultadoFila(fila=fila.fila, ok=False, cups=cups, mensaje=mensaje), False
    suministro.hubspot_deal_id = deal_id
    sesion.commit()
    return ResultadoFila(fila=fila.fila, ok=True, cups=cups, hubspot_deal_id=deal_id), creada


@router.post("/lote", response_model=AltaLoteOut)
def alta_en_lote(lote: AltaLoteIn, sesion: Annotated[Session, Depends(get_session)]) -> AltaLoteOut:
    """Procesa el lote fila a fila: las filas malas no impiden las buenas."""
    resultados: list[ResultadoFila] = []
    resumen = ResumenLote(recibidas=len(lote.filas), creadas=0, actualizadas=0, errores=0)
    for fila in lote.filas:
        resultado, creada = _procesar_fila(sesion, fila)
        resultados.append(resultado)
        if not resultado.ok:
            resumen.errores += 1
        elif creada:
            resumen.creadas += 1
        else:
            resumen.actualizadas += 1
    sesion.add(
        EventoSync(
            sistema=SISTEMA,
            operacion=OPERACION_LOTE,
            ok=resumen.errores == 0,
            detalle=resumen.model_dump(),
        )
    )
    sesion.commit()
    return AltaLoteOut(resultados=resultados, resumen=resumen)


@router.get("", response_model=list[AltaParadaOut])
def altas(
    sesion: Annotated[Session, Depends(get_session)],
    parada_dias: Annotated[int | None, Query(ge=0)] = None,
) -> list[AltaParadaOut]:
    """Altas en trámite (`pendiente` o `en_tramite`), de más antigua a más reciente.

    Con `parada_dias`, solo las que llevan más de ese número de días en el mismo
    estado (`estado_desde` anterior a ahora menos el filtro).
    """
    consulta = (
        select(Suministro, Cliente)
        .join(Cliente, Suministro.cliente_id == Cliente.id)
        .where(Suministro.estado.in_(ESTADOS_EN_TRAMITE))
        .order_by(Suministro.estado_desde.asc())
    )
    if parada_dias is not None:
        limite = datetime.now(UTC) - timedelta(days=parada_dias)
        consulta = consulta.where(Suministro.estado_desde < limite)
    ahora = datetime.now(UTC)
    return [
        AltaParadaOut(
            cups=suministro.cups,
            cliente=cliente.nombre,
            estado=suministro.estado,
            dias_parada=(ahora - suministro.estado_desde).days,
        )
        for suministro, cliente in sesion.execute(consulta).all()
    ]
