"""Esquemas Pydantic de la API (docs/spec.md, secciones 9 y 15).

`FacturaExtraida` está copiado literalmente de la sección 9: es el esquema fijo que el LLM
debe rellenar (Structured Outputs) y el que valida su salida. `AnomaliaOut`, `FacturaOut` y
`FacturaSubidaOut` son los esquemas de respuesta de `POST /facturas` y `GET /facturas`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FacturaExtraida(BaseModel):
    """Datos que el LLM debe extraer de un PDF de factura (sección 9, literal)."""

    cups: str = Field(description="Código CUPS, empieza por ES")
    numero_factura: str
    comercializadora: str
    fecha_emision: date | None = None
    fecha_inicio: date = Field(description="Inicio del periodo facturado")
    fecha_fin: date = Field(description="Fin del periodo facturado")
    potencia_kw: float | None = Field(
        None, description="Potencia contratada en kW (P1 si hay varias)"
    )
    consumo_kwh: float = Field(description="Consumo total del periodo en kWh")
    importe_potencia: float | None = None
    importe_energia: float | None = None
    impuestos_otros: float | None = Field(
        None, description="Impuesto eléctrico, alquiler de equipos, IVA y otros"
    )
    importe_total: float
    lectura_estimada: bool = Field(description="True si la factura indica lectura estimada")
    confianza: float = Field(ge=0, le=1, description="Confianza global en la extracción")
    campos_dudosos: list[str] = Field(
        default_factory=list, description="Campos que no se leen con claridad"
    )

    @model_validator(mode="after")
    def _periodo_coherente(self) -> "FacturaExtraida":
        """Un periodo invertido no es una factura válida: es una extracción errónea (422).

        Sin esta comprobación, `fecha_fin < fecha_inicio` llegaría a PostgreSQL y el CHECK de la
        tabla lo convertiría en un 500 en lugar de un error de validación controlado.
        """
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")
        return self


class AnomaliaOut(BaseModel):
    """Anomalía de una factura, tal y como se expone en la API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    factura_id: int | None
    suministro_id: int | None
    regla: str
    severidad: str
    detalle: str
    estado: str
    creado_en: datetime


class AnomaliaActualizacion(BaseModel):
    """Cuerpo de `PATCH /anomalias/{id}`: cerrar la anomalía con un comentario.

    Solo se permite pasar a `resuelta` o `descartada` (cualquier otro estado, incluida
    `abierta`, se rechaza con 422 en la validación). El comentario es obligatorio y queda
    añadido a `detalle` como trazabilidad.
    """

    estado: Literal["resuelta", "descartada"] = Field(description="Nuevo estado de la anomalía")
    comentario: str = Field(min_length=1, description="Motivo del cierre; se añade a `detalle`")


class TareaSinFacturarOut(BaseModel):
    """Respuesta de `POST /tareas/sin-facturar`: cuántas anomalías R10 creó."""

    anomalias_creadas: int


class FacturaOut(BaseModel):
    """Factura guardada, con sus anomalías."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    suministro_id: int | None
    cups_leido: str
    numero: str
    comercializadora: str
    fecha_emision: date | None
    fecha_inicio: date
    fecha_fin: date
    potencia_kw: Decimal | None
    consumo_kwh: Decimal
    importe_potencia: Decimal | None
    importe_energia: Decimal | None
    impuestos_otros: Decimal | None
    importe_total: Decimal
    lectura_estimada: bool
    confianza: Decimal | None
    archivo_hash: str
    creado_en: datetime
    anomalias: list[AnomaliaOut] = Field(default_factory=list)


class FacturaSubidaOut(FacturaOut):
    """Respuesta de `POST /facturas`: la factura, sus anomalías y si se ha creado ahora."""

    creada: bool


class FilaAlta(BaseModel):
    """Una fila del lote de altas (`POST /altas/lote`)."""

    nif: str = Field(description="NIF del cliente al que pertenece el suministro")
    cups: str = Field(description="CUPS, se normaliza y valida con las letras de control")
    tipo: str = Field(description="Tipo de suministro: luz, gas o agua")
    direccion: str = Field(description="Dirección del punto de suministro")
    tarifa_acceso: str | None = None
    potencia_kw: Decimal | None = None


class ResultadoFila(BaseModel):
    """Resultado de una fila del lote: ok con el negocio, o fallo con mensaje."""

    fila: int = Field(description="Posición de la fila en el lote, empezando en 1")
    ok: bool
    cups: str | None = None
    hubspot_deal_id: str | None = None
    mensaje: str | None = None


class ResumenLote(BaseModel):
    """Recuento del lote: recibidas, creadas, actualizadas y con error."""

    recibidas: int
    creadas: int
    actualizadas: int
    errores: int


class AltaLoteIn(BaseModel):
    """Cuerpo de `POST /altas/lote`: filas de altas, normalmente de una hoja de cálculo."""

    filas: list[FilaAlta]


class AltaLoteOut(BaseModel):
    """Respuesta de `POST /altas/lote`: resultado por fila y resumen (sección 15)."""

    resultados: list[ResultadoFila]
    resumen: ResumenLote


class TicketCreadoOut(BaseModel):
    """Respuesta de `POST /anomalias/{id}/ticket`: el ticket, creado ahora o ya existente."""

    anomalia_id: int
    hubspot_ticket_id: str
    creado: bool


class SyncResumenOut(BaseModel):
    """Respuesta de `POST /sync/hubspot`: recuento de negocios revisados."""

    revisados: int
    actualizados: int
    omitidos: int
    errores: int
