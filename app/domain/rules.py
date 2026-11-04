"""Reglas de anomalías como funciones puras (docs/spec.md, sección 10).

Cada regla recibe la factura y el contexto (suministro, histórico y candidatos de R3/R4)
y devuelve `None` o una `Anomalia` con la severidad y el detalle que Laura necesita para
decidir: cifras concretas, no solo el código de la regla. Ninguna función abre sesión,
consulta la base de datos ni toca la red: el I/O vive en `app/services/rules.py`.

| ID | Regla | Severidad |
|---|---|---|
| R1 | CUPS inválido | Alta |
| R2 | CUPS fuera de cartera | Media |
| R3 | Factura duplicada | Alta |
| R4 | Periodo solapado | Alta |
| R5 | El total no cuadra | Alta |
| R6 | Consumo atípico | Media |
| R7 | Lecturas estimadas seguidas | Media |
| R8 | Potencia distinta de la contratada | Media |
| R9 | Precio fuera de rango | Baja |
| R10 | Suministro sin facturar (tarea programada) | Media |
| R11 | Revisión de extracción | Media |
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.domain.cups import cups_valido

UMBRAL_CONFIANZA = 0.85
TOLERANCIA_TOTAL_EUR = Decimal("0.05")
TOLERANCIA_POTENCIA_KW = Decimal("0.01")
MARGEN_PRECIO = Decimal("0.4")  # ±40 % de la mediana de la cartera
DIAS_SIN_FACTURAR = 60


@dataclass
class SuministroDatos:
    """Datos del suministro que las reglas necesitan, sin SQLAlchemy."""

    cups: str
    estado: str
    potencia_kw: float | None
    tarifa_acceso: str | None


@dataclass
class FacturaDatos:
    """Datos de una factura que las reglas necesitan, sin SQLAlchemy."""

    id: int | None
    cups_leido: str
    numero: str
    comercializadora: str
    fecha_inicio: date
    fecha_fin: date
    potencia_kw: float | None
    consumo_kwh: float
    importe_potencia: float | None
    importe_energia: float | None
    impuestos_otros: float | None
    importe_total: float
    lectura_estimada: bool
    confianza: float | None
    campos_dudosos: list[str]
    archivo_hash: str

    @property
    def dias(self) -> int:
        """Días del periodo facturado, ambos extremos incluidos."""
        return (self.fecha_fin - self.fecha_inicio).days + 1

    @property
    def clave_negocio(self) -> tuple[str, str, str]:
        """La clave de idempotencia de la tabla `facturas`."""
        return (self.cups_leido, self.numero, self.comercializadora)


@dataclass
class ContextoReglas:
    """Lo que las reglas necesitan y no pueden consultar por sí mismas.

    `historico` son las facturas anteriores del suministro ordenadas por `fecha_fin`
    (la última es `historico[-1]`, la que usa R7 y las últimas seis R6). `mismo_cups`
    son otras facturas del mismo CUPS, candidatas a duplicado (R3) o solape (R4).
    """

    suministro: SuministroDatos | None
    historico: list[FacturaDatos]
    mismo_cups: list[FacturaDatos]
    mediana_precio_kwh: float | None


@dataclass
class Anomalia:
    """Resultado de una regla: qué regla, con qué severidad y por qué, con cifras."""

    regla: str
    severidad: str
    detalle: str


def _dinero(valor: float) -> Decimal:
    """Convierte un importe a `Decimal` con dos decimales para comparar sin sorpresas."""
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _misma_clave(otra: FacturaDatos, factura: FacturaDatos) -> bool:
    """True si las dos facturas comparten la clave de negocio (CUPS, número, comercializadora)."""
    return otra.clave_negocio == factura.clave_negocio


def _solapa(otra: FacturaDatos, factura: FacturaDatos) -> bool:
    """True si los periodos `[inicio, fin]` de ambas facturas se pisan (daterange '[]')."""
    return otra.fecha_inicio <= factura.fecha_fin and otra.fecha_fin >= factura.fecha_inicio


def r1_cups_invalido(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R1 «CUPS inválido»: `cups_valido()` falla (severidad alta)."""
    if cups_valido(factura.cups_leido):
        return None
    return Anomalia(
        "R1",
        "alta",
        f"CUPS inválido: {factura.cups_leido} no supera la validación de formato y letras "
        "de control",
    )


def r2_cups_fuera_de_cartera(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R2 «CUPS fuera de cartera»: el CUPS no existe en `suministros` (severidad media)."""
    if contexto.suministro is not None:
        return None
    return Anomalia(
        "R2",
        "media",
        f"CUPS {factura.cups_leido} no está en la cartera de suministros",
    )


def r3_factura_duplicada(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R3 «Factura duplicada»: misma clave de negocio con distinto archivo (severidad alta).

    La clave de negocio incluye el CUPS, así que basta con las facturas candidatas del
    mismo CUPS. Si la clave coincide, el archivo debe ser distinto: el mismo PDF es la
    idempotencia de la ingesta, no una anomalía.
    """
    for otra in contexto.mismo_cups:
        if _misma_clave(otra, factura) and otra.archivo_hash != factura.archivo_hash:
            return Anomalia(
                "R3",
                "alta",
                f"Factura duplicada: la clave de negocio (CUPS {factura.cups_leido}, número "
                f"{factura.numero}, {factura.comercializadora}) ya existe con otro archivo "
                f"(hash {otra.archivo_hash[:12]}…)",
            )
    return None


def r4_periodo_solapado(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R4 «Periodo solapado»: otra factura del mismo CUPS con fechas que se solapan (alta).

    Solo cuenta si la clave de negocio es distinta: la misma clave con solape es un
    duplicado (R3), no un solape.
    """
    for otra in contexto.mismo_cups:
        if not _misma_clave(otra, factura) and _solapa(otra, factura):
            return Anomalia(
                "R4",
                "alta",
                f"Periodo solapado: la factura {otra.numero} de {otra.comercializadora} cubre "
                f"del {otra.fecha_inicio.isoformat()} al {otra.fecha_fin.isoformat()} y se pisa "
                f"con el periodo del {factura.fecha_inicio.isoformat()} al "
                f"{factura.fecha_fin.isoformat()} del CUPS {factura.cups_leido}",
            )
    return None


def r5_total_no_cuadra(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R5 «El total no cuadra»: potencia + energía + impuestos difieren del total (alta).

    Tolerancia de 0,05 €. Si falta algún concepto no se puede comprobar y no dispara:
    ese caso lo cubre R11 como revisión de extracción.
    """
    partes = [factura.importe_potencia, factura.importe_energia, factura.impuestos_otros]
    if (
        factura.importe_potencia is None
        or factura.importe_energia is None
        or factura.impuestos_otros is None
    ):
        return None
    suma = sum((_dinero(parte) for parte in partes if parte is not None), Decimal("0.00"))
    total = _dinero(factura.importe_total)
    diferencia = abs(suma - total)
    if diferencia > TOLERANCIA_TOTAL_EUR:
        return Anomalia(
            "R5",
            "alta",
            f"El total no cuadra: potencia + energía + impuestos suman {suma} € frente a un "
            f"total de {total} € (diferencia de {diferencia} €, tolerancia 0,05 €)",
        )
    return None


def r6_consumo_atipico(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R6 «Consumo atípico»: diario > 2× o < 0,3× la media de las últimas 6 (media).

    Con menos de 3 facturas de histórico no hay base de comparación y no dispara.
    """
    if len(contexto.historico) < 3:
        return None
    ultimas = contexto.historico[-6:]
    medias = [historica.consumo_kwh / historica.dias for historica in ultimas]
    media = sum(medias) / len(medias)
    diario = factura.consumo_kwh / factura.dias
    if media > 0 and (diario > 2 * media or diario < 0.3 * media):
        return Anomalia(
            "R6",
            "media",
            f"Consumo atípico: {diario:.1f} kWh/día frente a una media de {media:.1f} kWh/día "
            f"en las últimas {len(medias)} facturas",
        )
    return None


def r7_lecturas_estimadas_seguidas(
    factura: FacturaDatos, contexto: ContextoReglas
) -> Anomalia | None:
    """R7 «Lecturas estimadas seguidas»: esta y la anterior son estimadas (media).

    Sin factura anterior no hay «seguidas» y no dispara.
    """
    if not contexto.historico:
        return None
    anterior = contexto.historico[-1]
    if factura.lectura_estimada and anterior.lectura_estimada:
        return Anomalia(
            "R7",
            "media",
            f"Lecturas estimadas seguidas: esta factura y la anterior ({anterior.numero}, del "
            f"{anterior.fecha_fin.isoformat()}) son estimadas",
        )
    return None


def r8_potencia_distinta(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R8 «Potencia distinta de la contratada»: difiere del suministro (media).

    Tolerancia de 0,01 kW. Sin suministro o sin potencia en cualquiera de los dos no
    hay con qué comparar y no dispara.
    """
    if (
        contexto.suministro is None
        or factura.potencia_kw is None
        or contexto.suministro.potencia_kw is None
    ):
        return None
    contratada = _dinero(contexto.suministro.potencia_kw)
    facturada = _dinero(factura.potencia_kw)
    if abs(facturada - contratada) > TOLERANCIA_POTENCIA_KW:
        return Anomalia(
            "R8",
            "media",
            f"Potencia facturada {facturada} kW distinta de la contratada {contratada} kW "
            "(tolerancia 0,01 kW)",
        )
    return None


def r9_precio_fuera_de_rango(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R9 «Precio fuera de rango»: €/kWh de energía fuera de ±40 % de la mediana (baja).

    Sin mediana de la cartera, sin importe de energía o sin consumo (o con consumo no
    positivo) no hay precio que contrastar y no dispara.
    """
    if (
        contexto.mediana_precio_kwh is None
        or factura.importe_energia is None
        or factura.consumo_kwh <= 0
    ):
        return None
    precio = Decimal(str(factura.importe_energia)) / Decimal(str(factura.consumo_kwh))
    mediana = Decimal(str(contexto.mediana_precio_kwh))
    limite_inferior = mediana * (1 - MARGEN_PRECIO)
    limite_superior = mediana * (1 + MARGEN_PRECIO)
    if precio < limite_inferior or precio > limite_superior:
        return Anomalia(
            "R9",
            "baja",
            f"Precio de energía {precio:.4f} €/kWh fuera del rango ±40 % de la mediana de la "
            f"cartera ({mediana:.4f} €/kWh; límites {limite_inferior:.4f}–"
            f"{limite_superior:.4f} €/kWh)",
        )
    return None


def r10_suministro_sin_facturar(
    suministro: SuministroDatos,
    ultima_factura: FacturaDatos | None,
    dias: int = DIAS_SIN_FACTURAR,
) -> Anomalia | None:
    """R10 «Suministro sin facturar»: activo y sin factura en 60 días (media).

    Se ejecuta como tarea programada sobre toda la cartera, no factura a factura.
    """
    if suministro.estado != "activo":
        return None
    if ultima_factura is None:
        return Anomalia(
            "R10",
            "media",
            f"Suministro activo {suministro.cups} sin ninguna factura registrada "
            f"(límite {dias} días)",
        )
    dias_sin = (date.today() - ultima_factura.fecha_fin).days
    if dias_sin > dias:
        return Anomalia(
            "R10",
            "media",
            f"Suministro activo {suministro.cups} sin facturar {dias_sin} días: la última "
            f"factura es del {ultima_factura.fecha_fin.isoformat()} (límite {dias} días)",
        )
    return None


def r11_revision_extraccion(factura: FacturaDatos, contexto: ContextoReglas) -> Anomalia | None:
    """R11 «Revisión de extracción»: confianza < 0,85 o campos dudosos (media)."""
    if (
        factura.confianza is None or factura.confianza >= UMBRAL_CONFIANZA
    ) and not factura.campos_dudosos:
        return None
    motivos = []
    if factura.confianza is not None and factura.confianza < UMBRAL_CONFIANZA:
        motivos.append(f"confianza {factura.confianza:.2f} (umbral {UMBRAL_CONFIANZA})")
    if factura.campos_dudosos:
        motivos.append("campos dudosos: " + ", ".join(factura.campos_dudosos))
    return Anomalia("R11", "media", "Revisión de extracción: " + "; ".join(motivos))


_REGLAS_POR_FACTURA = (
    r1_cups_invalido,
    r2_cups_fuera_de_cartera,
    r3_factura_duplicada,
    r4_periodo_solapado,
    r5_total_no_cuadra,
    r6_consumo_atipico,
    r7_lecturas_estimadas_seguidas,
    r8_potencia_distinta,
    r9_precio_fuera_de_rango,
    r11_revision_extraccion,
)


def evaluar(factura: FacturaDatos, contexto: ContextoReglas) -> list[Anomalia]:
    """Ejecuta R1–R9 y R11 sobre una factura y devuelve todas las anomalías que disparan."""
    resultado: list[Anomalia] = []
    for regla in _REGLAS_POR_FACTURA:
        anomalia = regla(factura, contexto)
        if anomalia is not None:
            resultado.append(anomalia)
    return resultado
