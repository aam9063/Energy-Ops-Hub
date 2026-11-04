"""Esquemas Pydantic de la API (docs/spec.md, secciones 9 y 15).

`FacturaExtraida` está copiado literalmente de la sección 9: es el esquema fijo que el LLM
debe rellenar (Structured Outputs) y el que valida su salida. `AnomaliaOut`, `FacturaOut` y
`FacturaSubidaOut` son los esquemas de respuesta de `POST /facturas` y `GET /facturas`.
"""

from datetime import date, datetime
from decimal import Decimal

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
    regla: str
    severidad: str
    detalle: str
    estado: str
    creado_en: datetime


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
