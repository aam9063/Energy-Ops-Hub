"""Generador determinista de facturas sintéticas en PDF (docs/spec.md, sección 8).

Crea en `evals/dataset/` facturas ficticias de luz y gas con tres maquetaciones distintas
(una por comercializadora) y, junto a cada PDF, un JSON con la verdad esperada siguiendo el
esquema `FacturaExtraida` (docs/spec.md, sección 9) más dos claves: `anomalias_esperadas`
(regla prevista, R1–R11) y `tipo_anomalia`. El 15 % de las facturas lleva una anomalía
inyectada a propósito de entre seis clases.

Todo el azar sale de una semilla fija: con la misma semilla, dos ejecuciones producen
archivos idénticos byte a byte (reportlab se usa con `invariant=1` para fijar la fecha de
creación del PDF y el ID del documento). Los suministros se toman de `scripts/seed.py`,
nunca duplicados, para que el dataset y la base de datos hablen de los mismos CUPS.

Uso:
    uv run python -m scripts.generate_invoices
    uv run python -m scripts.generate_invoices --semilla 20261104 \
        --limite 120 --salida evals/dataset
"""

from __future__ import annotations

import argparse
import calendar
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import cast

from app.domain.cups import letras_control
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from scripts.seed import clientes_de_ejemplo, suministros_de_ejemplo

# PDFs deterministas: invariant=1 fija la fecha de creación y el ID del documento en cada
# ejecución; sin ello reportlab sellaría el PDF con la hora actual.
canvas_module.rl_config.invariant = 1

SEMILLA_DEFECTO = 20261104
LIMITE_DEFECTO = 120
SALIDA_DEFECTO = Path("evals/dataset")
MESES = 6
FACTOR_ANOMALIA = 0.15

# Fecha fija del dataset, nunca datetime.now(): el conjunto debe regenerarse igual cualquier día.
FECHA_HOY = date(2026, 11, 4)

IVA = Decimal("0.21")
IEE = Decimal("0.0511270")  # impuesto eléctrico sobre potencia + energía, solo luz
DOS = Decimal("0.01")
CINCO = Decimal("0.00001")

# Color corporativo común a las maquetaciones por tabla.
AZUL = colors.HexColor("#134074")

# Clase de anomalía → regla prevista (docs/spec.md, sección 10).
CLASES_ANOMALIA: dict[str, str] = {
    "duplicada": "R3",
    "total_no_cuadra": "R5",
    "consumo_disparado": "R6",
    "lecturas_estimadas_seguidas": "R7",
    "potencia_distinta": "R8",
    "cups_fuera_cartera": "R2",
}

# Claves del esquema FacturaExtraida (docs/spec.md, sección 9) y las dos extra del dataset.
CLAVES_FACTURA_EXTRAIDA = (
    "cups",
    "numero_factura",
    "comercializadora",
    "fecha_emision",
    "fecha_inicio",
    "fecha_fin",
    "potencia_kw",
    "consumo_kwh",
    "importe_potencia",
    "importe_energia",
    "impuestos_otros",
    "importe_total",
    "lectura_estimada",
    "confianza",
    "campos_dudosos",
)
CLAVES_EXTRA = ("anomalias_esperadas", "tipo_anomalia")

# El generador solo factura luz y gas: el agua de seed.py no lleva este tipo de factura.
# 4 gas + 10 en 3.0TD + 6 viviendas = 20 suministros × 6 meses = 120 facturas.
VIVIENDAS_FACTURADAS = 6


@dataclass(frozen=True)
class Tarifa:
    """Precios y parámetros por tarifa de acceso. Plausibles, no fiscalmente exactos."""

    potencia_eur_kw_dia: Decimal
    energia_eur_kwh: Decimal
    consumo_diario_por_kw: float
    impuesto_electrico: bool
    alquiler_mensual: Decimal  # 0 = sin contador en alquiler


TARIFAS: dict[str, Tarifa] = {
    "2.0TD": Tarifa(Decimal("0.0920"), Decimal("0.1520"), 2.4, True, Decimal("0.81")),
    "3.0TD": Tarifa(Decimal("0.0410"), Decimal("0.1180"), 4.0, True, Decimal("0.00")),
    "RL.1": Tarifa(Decimal("0.0280"), Decimal("0.0520"), 1.8, False, Decimal("0.60")),
}

# Estacionalidad mensual del consumo: más en invierno y verano (docs/spec.md, sección 8).
FACTOR_LUZ = {
    1: 1.30,
    2: 1.20,
    3: 1.10,
    4: 1.00,
    5: 0.95,
    6: 1.10,
    7: 1.30,
    8: 1.25,
    9: 1.05,
    10: 0.95,
    11: 1.05,
    12: 1.25,
}
FACTOR_GAS = {
    1: 2.60,
    2: 2.30,
    3: 1.80,
    4: 1.10,
    5: 0.70,
    6: 0.50,
    7: 0.40,
    8: 0.40,
    9: 0.50,
    10: 0.90,
    11: 1.60,
    12: 2.40,
}


@dataclass(frozen=True)
class Comercializadora:
    """Datos fiscales ficticios del emisor y prefijo para numerar sus facturas."""

    nif: str
    direccion: str
    prefijo: str


COMERCIALIZADORAS: dict[str, Comercializadora] = {
    "Voltia Energía": Comercializadora("B22222222", "Calle Ficticia 1, 28001 Madrid", "VOL"),
    "Luminar Comercializadora": Comercializadora(
        "A33333333", "Avenida Inventada 12, 28020 Madrid", "LUM"
    ),
    "Ecoflux": Comercializadora("B44444444", "Plaza de Ejemplo 3, 41001 Sevilla", "ECO"),
}


@dataclass
class FacturaSintetica:
    """Una factura del plan de generación, ya sea limpia o con anomalía inyectada."""

    suministro: dict[str, object]
    cups: str
    numero: str
    slug: str
    comercializadora: str
    fecha_emision: date
    fecha_inicio: date
    fecha_fin: date
    potencia_contratada: Decimal
    potencia_facturada: Decimal
    consumo: Decimal
    precio_potencia: Decimal
    precio_energia: Decimal
    lectura_estimada: bool
    importe_potencia: Decimal = Decimal("0.00")
    importe_energia: Decimal = Decimal("0.00")
    impuesto_electrico: Decimal = Decimal("0.00")
    alquiler: Decimal = Decimal("0.00")
    iva: Decimal = Decimal("0.00")
    impuestos_otros: Decimal = Decimal("0.00")
    importe_total: Decimal = Decimal("0.00")
    tipo_anomalia: str | None = None
    regla: str | None = None


def _cups_fuera_de_cartera(indice: int) -> str:
    """CUPS válido fuera de los 40 de seed.py, con la misma función de letras de control."""
    digitos = f"0031{indice:012d}"
    return f"ES{digitos}{letras_control(digitos)}"


CUPOS_FUERA = tuple(_cups_fuera_de_cartera(i) for i in (900, 901, 902))


def _din2(valor: Decimal) -> Decimal:
    return valor.quantize(DOS, rounding=ROUND_HALF_UP)


def _din(valor: float) -> Decimal:
    return _din2(Decimal(str(valor)))


def recalcular(factura: FacturaSintetica) -> None:
    """Recalcula importes desde potencia facturada, consumo y precios.

    Se llama al crear la factura y tras cualquier anomalía que cambie consumo o potencia,
    para que la suma de conceptos siga cuadrando (R5) salvo en el descuadre inyectado.
    """
    tarifa = TARIFAS[str(factura.suministro["tarifa_acceso"])]
    dias = (factura.fecha_fin - factura.fecha_inicio).days + 1
    factura.importe_potencia = _din2(factura.potencia_facturada * factura.precio_potencia * dias)
    factura.importe_energia = _din2(factura.consumo * factura.precio_energia)
    if tarifa.impuesto_electrico:
        base_iee = factura.importe_potencia + factura.importe_energia
        factura.impuesto_electrico = _din2(base_iee * IEE)
    else:
        factura.impuesto_electrico = Decimal("0.00")
    factura.alquiler = tarifa.alquiler_mensual
    base = (
        factura.importe_potencia
        + factura.importe_energia
        + factura.impuesto_electrico
        + factura.alquiler
    )
    factura.iva = _din2(base * IVA)
    factura.impuestos_otros = factura.impuesto_electrico + factura.alquiler + factura.iva
    factura.importe_total = (
        factura.importe_potencia + factura.importe_energia + (factura.impuestos_otros)
    )


def _meses() -> list[tuple[date, date]]:
    """Los últimos 6 meses completos antes de FECHA_HOY, en orden cronológico."""
    pares: list[tuple[date, date]] = []
    anio, mes = FECHA_HOY.year, FECHA_HOY.month
    for _ in range(MESES):
        mes -= 1
        if mes == 0:
            anio, mes = anio - 1, 12
        inicio = date(anio, mes, 1)
        fin = date(anio, mes, calendar.monthrange(anio, mes)[1])
        pares.append((inicio, fin))
    pares.reverse()
    return pares


def _seleccionar_suministros(rng: random.Random) -> list[dict[str, object]]:
    """Reparte la cartera de seed.py: gas, 3.0TD y una muestra fija de viviendas."""
    todos = [s for s in suministros_de_ejemplo() if s["tipo"] in ("luz", "gas")]
    gas = [s for s in todos if s["tipo"] == "gas"]
    alta = [s for s in todos if s["tipo"] == "luz" and s["tarifa_acceso"] == "3.0TD"]
    viviendas = [s for s in todos if s["tarifa_acceso"] == "2.0TD"]
    return gas + alta + rng.sample(viviendas, VIVIENDAS_FACTURADAS)


def _nueva_factura(
    rng: random.Random,
    suministro: dict[str, object],
    periodo: tuple[date, date],
    indice_suministro: int,
    anterior_estimada: bool,
) -> FacturaSintetica:
    """Crea una factura limpia del mes dado con ruido y estacionalidad deterministas."""
    tarifa = TARIFAS[str(suministro["tarifa_acceso"])]
    comercializadora = str(suministro["comercializadora"])
    inicio, fin = periodo
    dias = (fin - inicio).days + 1
    factor = (FACTOR_GAS if suministro["tipo"] == "gas" else FACTOR_LUZ)[inicio.month]
    consumo_base = float(str(suministro["potencia_kw"])) * tarifa.consumo_diario_por_kw
    consumo = _din2(Decimal(str(consumo_base * factor * dias * rng.uniform(0.92, 1.08))))
    precio_potencia = (tarifa.potencia_eur_kw_dia * Decimal(str(rng.uniform(0.92, 1.08)))).quantize(
        CINCO, rounding=ROUND_HALF_UP
    )
    precio_energia = (tarifa.energia_eur_kwh * Decimal(str(rng.uniform(0.92, 1.08)))).quantize(
        CINCO, rounding=ROUND_HALF_UP
    )
    # Aislar las lecturas estimadas sueltas para que R7 solo dispare donde se inyecta.
    lectura_estimada = rng.random() < 0.06 and not anterior_estimada
    emision = min(fin + timedelta(days=rng.randint(2, 6)), FECHA_HOY)
    prefijo = COMERCIALIZADORAS[comercializadora].prefijo
    numero = f"{prefijo}-{fin.year}{fin.month:02d}-{indice_suministro:03d}"
    potencia = _din2(Decimal(str(suministro["potencia_kw"])))
    factura = FacturaSintetica(
        suministro=suministro,
        cups=str(suministro["cups"]),
        numero=numero,
        slug=numero.lower(),
        comercializadora=comercializadora,
        fecha_emision=emision,
        fecha_inicio=inicio,
        fecha_fin=fin,
        potencia_contratada=potencia,
        potencia_facturada=potencia,
        consumo=consumo,
        precio_potencia=precio_potencia,
        precio_energia=precio_energia,
        lectura_estimada=lectura_estimada,
    )
    recalcular(factura)
    return factura


def _es_candidata(clase: str, indice: int, plan: list[FacturaSintetica], usadas: set[int]) -> bool:
    """Un hueco es candidato si la clase es aplicable y no choca con otra anomalía."""
    mes = indice % MESES
    if mes == 0 and clase in ("duplicada", "lecturas_estimadas_seguidas"):
        return False  # necesitan la factura del mes anterior
    if mes < 3 and clase == "consumo_disparado":
        return False  # R6 pide al menos 3 meses de histórico
    if clase == "lecturas_estimadas_seguidas" and indice - 1 in usadas:
        return False  # el mes anterior no debe llevar otra anomalía primaria
    return indice not in usadas


def _aplicar_anomalia(
    rng: random.Random, plan: list[FacturaSintetica], indice: int, clase: str
) -> None:
    """Muta la factura del hueco según la clase; después de aplicar se recalcula."""
    factura = plan[indice]
    if clase == "duplicada":
        # Misma clave de negocio (cups + numero + comercializadora), archivo distinto: R3.
        original = plan[indice - indice % MESES]
        factura.numero = original.numero
        factura.slug = f"{original.numero.lower()}-duplicada"
        factura.fecha_emision = original.fecha_emision
        factura.fecha_inicio = original.fecha_inicio
        factura.fecha_fin = original.fecha_fin
        factura.consumo = original.consumo
        factura.precio_potencia = original.precio_potencia
        factura.precio_energia = original.precio_energia
        factura.potencia_facturada = original.potencia_facturada
        factura.lectura_estimada = original.lectura_estimada
        recalcular(factura)
    elif clase == "total_no_cuadra":
        descuadre = _din(rng.uniform(2.0, 20.0))
        if rng.random() < 0.5:
            descuadre = -descuadre
        factura.importe_total += descuadre
    elif clase == "consumo_disparado":
        factura.consumo = _din2(factura.consumo * Decimal("3.2"))
        recalcular(factura)
        previos = plan[indice - indice % MESES : indice]
        media = sum(f.consumo / ((f.fecha_fin - f.fecha_inicio).days + 1) for f in previos) / len(
            previos
        )
        diario = factura.consumo / ((factura.fecha_fin - factura.fecha_inicio).days + 1)
        if not diario > 2 * media:
            raise RuntimeError(f"el consumo disparado de {factura.slug} no supera 2x su histórico")
    elif clase == "lecturas_estimadas_seguidas":
        # Esta y la anterior estimadas; solo la actual lleva la etiqueta de anomalía (R7).
        factura.lectura_estimada = True
        plan[indice - 1].lectura_estimada = True
    elif clase == "potencia_distinta":
        factura.potencia_facturada = _din2(factura.potencia_facturada * Decimal("1.4"))
        recalcular(factura)
    elif clase == "cups_fuera_cartera":
        factura.cups = CUPOS_FUERA[indice % len(CUPOS_FUERA)]
    factura.tipo_anomalia = clase
    factura.regla = CLASES_ANOMALIA[clase]


def _inyectar_anomalias(rng: random.Random, plan: list[FacturaSintetica]) -> None:
    """Reparte un 15 % de anomalías, como máximo una primaria por factura, entre las 6 clases."""
    total = int(len(plan) * FACTOR_ANOMALIA)  # 18 de 120
    por_clase = total // len(CLASES_ANOMALIA)  # 3 de cada clase
    usadas: set[int] = set()
    for clase in CLASES_ANOMALIA:
        candidatos = [i for i in range(len(plan)) if _es_candidata(clase, i, plan, usadas)]
        for indice in rng.sample(candidatos, por_clase):
            usadas.add(indice)
            _aplicar_anomalia(rng, plan, indice, clase)


def construir_plan(rng: random.Random) -> list[FacturaSintetica]:
    """Plan completo: 20 suministros × 6 meses, con las anomalías ya inyectadas."""
    periodos = _meses()
    plan: list[FacturaSintetica] = []
    for indice_suministro, suministro in enumerate(_seleccionar_suministros(rng)):
        anterior_estimada = False
        for periodo in periodos:
            factura = _nueva_factura(rng, suministro, periodo, indice_suministro, anterior_estimada)
            plan.append(factura)
            anterior_estimada = factura.lectura_estimada
    _inyectar_anomalias(rng, plan)
    return plan


def _fmt_num(valor: Decimal, decimales: int = 2) -> str:
    """Número en formato español: punto de millar y coma decimal."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def _fmt_eur(valor: Decimal) -> str:
    return _fmt_num(valor) + " €"


def _fmt_fecha(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def _estilos() -> dict[str, ParagraphStyle]:
    """Estilos de las tres maquetaciones; se crean por llamada para no compartir estado."""
    gris = colors.HexColor("#666666")
    return {
        "titulo": ParagraphStyle(
            "titulo", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=AZUL
        ),
        "cabecera": ParagraphStyle(
            "cabecera", fontName="Helvetica", fontSize=8.5, leading=11, textColor=gris
        ),
        "texto": ParagraphStyle("texto", fontName="Helvetica", fontSize=9.5, leading=13),
        "etiqueta": ParagraphStyle("etiqueta", fontName="Helvetica-Bold", fontSize=9.5, leading=13),
        "estimada": ParagraphStyle(
            "estimada",
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#b45309"),
        ),
        "corrido": ParagraphStyle(
            "corrido", fontName="Times-Roman", fontSize=10.5, leading=15, alignment=TA_JUSTIFY
        ),
        "centrado": ParagraphStyle(
            "centrado", fontName="Times-Bold", fontSize=15, leading=19, alignment=TA_CENTER
        ),
    }


def _tabla_estilo() -> TableStyle:
    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9db4d0")),
            ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f6fb")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _historia_voltia(f: FacturaSintetica, titular: str) -> list[Flowable]:
    """Voltia Energía: maquetación clásica con tabla de conceptos."""
    e = _estilos()
    emisor = COMERCIALIZADORAS[f.comercializadora]
    nif_titular = str(f.suministro["cliente_nif"])
    historia: list[Flowable] = [
        Paragraph("Voltia Energía, S.L.", e["titulo"]),
        Paragraph(f"{emisor.nif} · {emisor.direccion}", e["cabecera"]),
        Spacer(1, 8 * mm),
        Table(
            [
                ["Número de factura:", f.numero, "Fecha de emisión:", _fmt_fecha(f.fecha_emision)],
                [
                    "Titular:",
                    f"{titular} ({nif_titular})",
                    "Periodo:",
                    f"del {_fmt_fecha(f.fecha_inicio)} al {_fmt_fecha(f.fecha_fin)}",
                ],
                [
                    "CUPS:",
                    f.cups,
                    "Lectura:",
                    "ESTIMADA" if f.lectura_estimada else "real",
                ],
            ],
            colWidths=[32 * mm, 68 * mm, 30 * mm, 44 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            ),
        ),
        Spacer(1, 6 * mm),
        Paragraph(str(f.suministro["direccion"]), e["texto"]),
        Spacer(1, 6 * mm),
    ]
    dias = (f.fecha_fin - f.fecha_inicio).days + 1
    filas: list[list[str]] = [
        ["Concepto", "Detalle", "Importe"],
        [
            "Término de potencia",
            f"{_fmt_num(f.potencia_facturada)} kW × {dias} días × "
            f"{_fmt_num(f.precio_potencia, 5)} €/kW/día",
            _fmt_eur(f.importe_potencia),
        ],
        [
            "Término de energía",
            f"{_fmt_num(f.consumo)} kWh × {_fmt_num(f.precio_energia, 5)} €/kWh",
            _fmt_eur(f.importe_energia),
        ],
    ]
    if f.impuesto_electrico:
        filas.append(["Impuesto eléctrico", "", _fmt_eur(f.impuesto_electrico)])
    if f.alquiler:
        filas.append(["Alquiler de equipos", "", _fmt_eur(f.alquiler)])
    filas.append(["IVA 21 %", "", _fmt_eur(f.iva)])
    filas.append(["TOTAL A PAGAR", "", _fmt_eur(f.importe_total)])
    historia.append(Table(filas, colWidths=[48 * mm, 92 * mm, 34 * mm], style=_tabla_estilo()))
    if f.lectura_estimada:
        historia.append(Spacer(1, 4 * mm))
        historia.append(Paragraph("Aviso: la lectura de este periodo es estimada.", e["estimada"]))
    return historia


def _historia_luminar(f: FacturaSintetica, titular: str) -> list[Flowable]:
    """Luminar: texto corrido con los importes integrados en la prosa."""
    e = _estilos()
    emisor = COMERCIALIZADORAS[f.comercializadora]
    dias = (f.fecha_fin - f.fecha_inicio).days + 1
    nif_titular = str(f.suministro["cliente_nif"])
    otros = f.impuesto_electrico + f.alquiler
    lectura = "ESTIMADA" if f.lectura_estimada else "real"
    return [
        Paragraph("Luminar Comercializadora, S.A.", e["centrado"]),
        Paragraph(f"{emisor.nif} — {emisor.direccion}", e["centrado"]),
        Spacer(1, 10 * mm),
        Paragraph(
            f"Estimado cliente: le emitimos la factura número <b>{f.numero}</b>, con fecha "
            f"{_fmt_fecha(f.fecha_emision)}, para el titular {titular} (NIF {nif_titular}), "
            f"referida al punto de suministro identificado por el CUPS {f.cups}, ubicado en "
            f"{f.suministro['direccion']}.",
            e["corrido"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            f"El periodo de facturación abarca del {_fmt_fecha(f.fecha_inicio)} al "
            f"{_fmt_fecha(f.fecha_fin)}, un total de {dias} días, con una potencia contratada "
            f"de {_fmt_num(f.potencia_facturada)} kW y un consumo de energía activa de "
            f"{_fmt_num(f.consumo)} kWh. La lectura de este periodo ha sido de carácter "
            f"{lectura}.",
            e["corrido"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Desglose económico: por la potencia contratada se devengan "
            f"{_fmt_eur(f.importe_potencia)}, a los que se añaden {_fmt_eur(f.importe_energia)} "
            f"por la energía consumida y {_fmt_eur(otros)} entre impuesto eléctrico, alquiler "
            f"de equipos y demás conceptos; el IVA (21 %) asciende a {_fmt_eur(f.iva)}. "
            f"El importe total de la factura es de <b>{_fmt_eur(f.importe_total)}</b>.",
            e["corrido"],
        ),
    ]


def _historia_ecoflux(f: FacturaSintetica, titular: str) -> list[Flowable]:
    """Ecoflux: tabla con otros nombres de concepto, otro orden y el total arriba."""
    e = _estilos()
    emisor = COMERCIALIZADORAS[f.comercializadora]
    nif_titular = str(f.suministro["cliente_nif"])
    historia: list[Flowable] = [
        Table(
            [
                [Paragraph("ECOFLUX", e["titulo"]), ""],
                [
                    Paragraph(f"{emisor.nif} · {emisor.direccion}", e["cabecera"]),
                    Paragraph(
                        f"<b>IMPORTE TOTAL: {_fmt_eur(f.importe_total)}</b>",
                        ParagraphStyle(
                            "total",
                            fontName="Helvetica-Bold",
                            fontSize=12,
                            leading=15,
                            alignment=TA_CENTER,
                            textColor=AZUL,
                        ),
                    ),
                ],
            ],
            colWidths=[100 * mm, 80 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOX", (1, 0), (1, -1), 1, AZUL),
                    ("SPAN", (1, 0), (1, 0)),
                    ("BACKGROUND", (1, 1), (1, 1), colors.HexColor("#eaf6ee")),
                ]
            ),
        ),
        Spacer(1, 8 * mm),
    ]
    filas: list[list[str]] = [["Concepto", "Importe"]]
    filas.append(["Consumo facturado", f"{_fmt_num(f.consumo)} kWh"])
    filas.append(["Potencia pico facturada", f"{_fmt_num(f.potencia_facturada)} kW"])
    filas.append(["Cargo por energía", _fmt_eur(f.importe_energia)])
    filas.append(["Cargo por potencia", _fmt_eur(f.importe_potencia)])
    if f.impuesto_electrico:
        filas.append(["Impuesto eléctrico de generación", _fmt_eur(f.impuesto_electrico)])
    if f.alquiler:
        filas.append(["Alquiler de contador", _fmt_eur(f.alquiler)])
    filas.append(["Impuesto indirecto (IVA 21 %)", _fmt_eur(f.iva)])
    filas.append(["Total", _fmt_eur(f.importe_total)])
    historia.append(Table(filas, colWidths=[110 * mm, 70 * mm], style=_tabla_estilo()))
    historia.append(Spacer(1, 8 * mm))
    estimada = "SÍ" if f.lectura_estimada else "NO"
    pie = [
        ["Ref. documento:", f.numero],
        ["Periodo facturado:", f"Del {_fmt_fecha(f.fecha_inicio)} al {_fmt_fecha(f.fecha_fin)}"],
        ["Punto de suministro (CUPS):", f.cups],
        ["Titular:", f"{titular} · {nif_titular}"],
        ["Dirección de suministro:", str(f.suministro["direccion"])],
        ["Lectura estimada:", estimada],
    ]
    historia.append(
        Table(
            pie,
            colWidths=[55 * mm, 125 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            ),
        )
    )
    return historia


PINTORES: dict[str, Callable[[FacturaSintetica, str], list[Flowable]]] = {
    "Voltia Energía": _historia_voltia,
    "Luminar Comercializadora": _historia_luminar,
    "Ecoflux": _historia_ecoflux,
}


def _escribir_pdf(ruta: Path, factura: FacturaSintetica, clientes: dict[str, str]) -> None:
    """Renderiza la maquetación de su comercializadora con PDF determinista (invariant=1)."""
    doc = SimpleDocTemplate(
        str(ruta),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Factura {factura.numero}",
        author=factura.comercializadora,
    )
    titular = clientes[str(factura.suministro["cliente_nif"])]
    doc.build(PINTORES[factura.comercializadora](factura, titular))


def _verdad_esperada(f: FacturaSintetica) -> dict[str, object]:
    """JSON de verdad esperada: forma de FacturaExtraida más las anomalías previstas."""
    return {
        "cups": f.cups,
        "numero_factura": f.numero,
        "comercializadora": f.comercializadora,
        "fecha_emision": f.fecha_emision.isoformat(),
        "fecha_inicio": f.fecha_inicio.isoformat(),
        "fecha_fin": f.fecha_fin.isoformat(),
        "potencia_kw": float(f.potencia_facturada),
        "consumo_kwh": float(f.consumo),
        "importe_potencia": float(f.importe_potencia),
        "importe_energia": float(f.importe_energia),
        "impuestos_otros": float(f.impuestos_otros),
        "importe_total": float(f.importe_total),
        "lectura_estimada": f.lectura_estimada,
        # El extractor ideal devuelve confianza máxima sin campos dudosos: no hay que dudar
        # de lo que el propio dataset imprime.
        "confianza": 1.0,
        "campos_dudosos": [],
        "anomalias_esperadas": [f.regla] if f.regla else [],
        "tipo_anomalia": f.tipo_anomalia,
    }


def generar_dataset(
    semilla: int = SEMILLA_DEFECTO,
    limite: int | None = None,
    salida: str | Path = SALIDA_DEFECTO,
) -> dict[str, object]:
    """Genera PDFs y JSON en `salida`. Devuelve un resumen para el CLI y los tests.

    La semilla controla todo el azar y `limite` recorta el número de facturas escritas
    (el plan se construye entero siempre, para que el prefijo sea idéntico al completo).
    """
    ruta_salida = Path(salida)
    ruta_salida.mkdir(parents=True, exist_ok=True)
    plan = construir_plan(random.Random(semilla))
    seleccionadas = plan if limite is None else plan[:limite]
    clientes = {str(c["nif"]): str(c["nombre"]) for c in clientes_de_ejemplo()}
    total_bytes = 0
    anomalias: dict[str, int] = {}
    for factura in seleccionadas:
        _escribir_pdf(ruta_salida / f"{factura.slug}.pdf", factura, clientes)
        with open(ruta_salida / f"{factura.slug}.json", "w", encoding="utf-8") as fichero:
            json.dump(_verdad_esperada(factura), fichero, ensure_ascii=False, indent=2)
            fichero.write("\n")
        total_bytes += (ruta_salida / f"{factura.slug}.pdf").stat().st_size
        total_bytes += (ruta_salida / f"{factura.slug}.json").stat().st_size
        if factura.tipo_anomalia:
            anomalias[factura.tipo_anomalia] = anomalias.get(factura.tipo_anomalia, 0) + 1
    return {
        "facturas": len(seleccionadas),
        "tamaño_bytes": total_bytes,
        "total_anomalias": sum(anomalias.values()),
        "anomalias_por_clase": anomalias,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Genera facturas sintéticas en PDF con su verdad esperada."
    )
    parser.add_argument("--semilla", type=int, default=SEMILLA_DEFECTO, help="Semilla del azar")
    parser.add_argument(
        "--limite", type=int, default=None, help="Número máximo de facturas (todas si se omite)"
    )
    parser.add_argument(
        "--salida", type=Path, default=SALIDA_DEFECTO, help="Directorio de destino del dataset"
    )
    args = parser.parse_args(argv)

    resumen = generar_dataset(semilla=args.semilla, limite=args.limite, salida=args.salida)
    n = cast(int, resumen["facturas"])
    total_anomalias = cast(int, resumen["total_anomalias"])
    por_clase = cast(dict[str, int], resumen["anomalias_por_clase"])
    mb = cast(int, resumen["tamaño_bytes"]) / (1024 * 1024)
    print(f"{n} facturas: {n} PDFs y {n} JSON en {args.salida} ({mb:.2f} MB)")
    print(f"anomalías: {total_anomalias}/{n} ({100 * total_anomalias / n:.1f}%)")
    for clase, cuenta in por_clase.items():
        print(f"  {clase}: {cuenta}")


if __name__ == "__main__":
    main()
