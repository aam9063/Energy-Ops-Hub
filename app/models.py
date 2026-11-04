"""Modelo relacional (docs/spec.md, sección 7).

Los nombres de tablas y columnas se mantienen en español, igual que en la especificación,
porque son parte del contrato de datos que consumen las reglas y los reportes.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    nif: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sector: Mapped[str | None] = mapped_column(Text)
    hubspot_company_id: Mapped[str | None] = mapped_column(Text, unique=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Suministro(Base):
    __tablename__ = "suministros"
    __table_args__ = (
        CheckConstraint("tipo IN ('luz','gas','agua')", name="ck_suministros_tipo"),
        CheckConstraint(
            "estado IN ('pendiente','en_tramite','activo','rechazado','baja')",
            name="ck_suministros_estado",
        ),
        Index("ix_suministros_estado_desde", "estado", "estado_desde"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), nullable=False)
    cups: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    direccion: Mapped[str] = mapped_column(Text, nullable=False)
    tarifa_acceso: Mapped[str | None] = mapped_column(Text)
    potencia_kw: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    comercializadora: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(Text, nullable=False, server_default="pendiente")
    estado_desde: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    hubspot_deal_id: Mapped[str | None] = mapped_column(Text, unique=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Factura(Base):
    __tablename__ = "facturas"
    __table_args__ = (
        UniqueConstraint(
            "cups_leido", "numero", "comercializadora", name="uq_facturas_clave_negocio"
        ),
        CheckConstraint("fecha_fin >= fecha_inicio", name="ck_facturas_periodo"),
        Index("ix_facturas_suministro_fecha", "suministro_id", text("fecha_fin DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    suministro_id: Mapped[int | None] = mapped_column(ForeignKey("suministros.id"))
    cups_leido: Mapped[str] = mapped_column(Text, nullable=False)
    numero: Mapped[str] = mapped_column(Text, nullable=False)
    comercializadora: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_emision: Mapped[date | None] = mapped_column(Date)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    potencia_kw: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    consumo_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    importe_potencia: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    importe_energia: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    impuestos_otros: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    importe_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    lectura_estimada: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    confianza: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    archivo_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    datos_crudos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Anomalia(Base):
    __tablename__ = "anomalias"
    __table_args__ = (
        UniqueConstraint("factura_id", "regla", name="uq_anomalias_factura_regla"),
        CheckConstraint("severidad IN ('alta','media','baja')", name="ck_anomalias_severidad"),
        CheckConstraint(
            "estado IN ('abierta','resuelta','descartada')", name="ck_anomalias_estado"
        ),
        Index("ix_anomalias_estado_severidad", "estado", "severidad"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id"))
    suministro_id: Mapped[int | None] = mapped_column(ForeignKey("suministros.id"))
    regla: Mapped[str] = mapped_column(Text, nullable=False)
    severidad: Mapped[str] = mapped_column(Text, nullable=False)
    detalle: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(Text, nullable=False, server_default="abierta")
    hubspot_ticket_id: Mapped[str | None] = mapped_column(Text, unique=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventoSync(Base):
    __tablename__ = "eventos_sync"

    id: Mapped[int] = mapped_column(primary_key=True)
    sistema: Mapped[str] = mapped_column(Text, nullable=False)
    operacion: Mapped[str] = mapped_column(Text, nullable=False)
    entidad_id: Mapped[str | None] = mapped_column(Text)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
