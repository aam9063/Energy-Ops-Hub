"""Evaluación de la extracción y de la detección de anomalías (docs/spec.md, sección 16).

Recorre `evals/dataset/*.pdf` con su JSON de verdad esperada (generado con
`scripts.generate_invoices`), mide la precisión de la extracción campo a campo con las
tolerancias de la sección 16, evalúa el sistema completo (extracción + reglas puras) contra
las anomalías inyectadas y escribe un informe en Markdown listo para pegar en el README.

Caché: `evals/cache/<sha256 del PDF>.json` guarda la salida del modelo y sus metadatos para
no repetir llamadas entre ejecuciones. `--sin-cache` la ignora al leer y no escribe en ella.

Anomalías: el contexto de las reglas (suministro, histórico y candidatos de R3/R4) se toma
de los JSON del dataset — la verdad esperada —, con la potencia y tarifa contratadas de
`scripts.seed.suministros_de_ejemplo()`. Una duplicada dispara R3 y, si la clave de negocio
extraída no coincide exactamente con la original, también R4: esa R4 se trata como
anomalía secundaria esperada de la duplicada y no cuenta como falsa alarma.

Uso:
    uv run python -m evals.run_evals --limite 30
    uv run python -m evals.run_evals --limite 2 --sin-cache
"""

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from app.config import settings
from app.domain.cups import normalizar_cups
from app.domain.rules import ContextoReglas, SuministroDatos, evaluar
from app.schemas import FacturaExtraida
from app.services.extraction import ExtraccionInvalida, extraer_factura
from app.services.rules import a_factura_de_extraccion
from scripts.seed import suministros_de_ejemplo

CARPETA_DATASET = Path("evals/dataset")
CARPETA_CACHE = Path("evals/cache")
SALIDA_DEFECTO = Path("evals/resultados.md")
SEMILLA_DEFECTO = 20261104

TOLERANCIA_IMPORTE_EUR = Decimal("0.01")
TOLERANCIA_KWH = Decimal("0.5")

REGLA_DUPLICADA = "R3"
REGLA_SOLAPADO = "R4"

CAMPOS = (
    "cups",
    "numero_factura",
    "comercializadora",
    "periodo",
    "consumo_kwh",
    "importe_total",
    "lectura_estimada",
)
ETIQUETAS_CAMPO: dict[str, str] = {
    "cups": "CUPS",
    "numero_factura": "Número de factura",
    "comercializadora": "Comercializadora",
    "periodo": "Periodo (inicio y fin)",
    "consumo_kwh": "Consumo kWh",
    "importe_total": "Importe total",
    "lectura_estimada": "Lectura estimada",
}
COMERCIALIZADORAS = ("Voltia Energía", "Luminar Comercializadora", "Ecoflux")

# Precio por millón de tokens (entrada, salida). La lista pública de OpenAI está en **dólares**
# (noviembre de 2026); aquí se usan como euros, que es una aproximación conservadora para
# comparar órdenes de magnitud, no una conversión de divisa. Los precios cambian: revisa la
# lista oficial o sobreescribe la tabla sin tocar código con EVALS_PRECIOS, por ejemplo:
# EVALS_PRECIOS='{"gpt-5.1": [1.25, 10.0]}'.
VAR_ENTORNO_PRECIOS = "EVALS_PRECIOS"
PRECIOS_EUR_POR_MILLON: dict[str, tuple[float, float]] = {
    "gpt-5.1": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}

AVISO_SIN_DATOS = "> Aviso: no hay datos (no se ha evaluado ninguna factura)."
AVISO_R4_SECUNDARIA = (
    "> Nota: una factura duplicada dispara R3 y, por diseño, puede disparar también R4 "
    "(su periodo coincide con el de la original y la clave de negocio no coincide "
    "exactamente). Esa R4 se trata como anomalía secundaria esperada de la duplicada y no "
    "cuenta como falsa alarma."
)


# --------------------------------------------------------------------------- dataset


@dataclass(frozen=True)
class RegistroDataset:
    """Una factura del dataset: su PDF, su verdad esperada y las anomalías previstas."""

    pdf: Path
    verdad: FacturaExtraida
    anomalias_esperadas: frozenset[str]
    tipo_anomalia: str | None
    archivo_hash: str


def _sha256(ruta: Path) -> str:
    """Hash SHA-256 del contenido del archivo (id de caché y `archivo_hash` de las reglas)."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def cargar_registros(dataset: Path, limite: int | None) -> list[RegistroDataset]:
    """Carga los pares PDF + JSON del dataset, en orden determinista y con `--limite`.

    Un JSON sin su PDF se ignora con un aviso: no hay factura que extraer.
    """
    registros: list[RegistroDataset] = []
    for ruta_json in sorted(dataset.glob("*.json")):
        ruta_pdf = ruta_json.with_suffix(".pdf")
        if not ruta_pdf.exists():
            print(f"Aviso: {ruta_json.name} no tiene PDF; se ignora", file=sys.stderr)
            continue
        carga = json.loads(ruta_json.read_text(encoding="utf-8"))
        esperadas = carga.get("anomalias_esperadas") or []
        registros.append(
            RegistroDataset(
                pdf=ruta_pdf,
                verdad=FacturaExtraida.model_validate(carga),
                anomalias_esperadas=frozenset(str(regla) for regla in esperadas),
                tipo_anomalia=carga.get("tipo_anomalia"),
                archivo_hash=_sha256(ruta_pdf),
            )
        )
    # La ingesta es cronológica: un duplicado llega *después* de la factura que duplica. El
    # dataset se ordena alfabéticamente y «…-duplicada.pdf» cae antes que «….pdf», así que se
    # empuja al final para que R3 lo vea contra su original ya procesado.
    registros.sort(key=lambda registro: "-duplicada" in registro.pdf.name)
    if limite is not None:
        registros = registros[:limite]
    return registros


# ----------------------------------------------------------------------------- caché


def cargar_de_cache(
    cache: Path, archivo_hash: str
) -> tuple[FacturaExtraida, dict[str, object]] | None:
    """Lee la extracción en caché para el hash dado; `None` si no existe o está corrupta."""
    ruta = cache / f"{archivo_hash}.json"
    if not ruta.exists():
        return None
    try:
        carga = json.loads(ruta.read_text(encoding="utf-8"))
        return FacturaExtraida.model_validate(carga["datos"]), dict(carga["meta"])
    except (json.JSONDecodeError, KeyError, TypeError):
        print(f"Aviso: caché corrupta en {ruta.name}; se vuelve a extraer", file=sys.stderr)
        return None


def guardar_en_cache(
    cache: Path, archivo_hash: str, datos: FacturaExtraida, meta: dict[str, object]
) -> None:
    """Guarda la salida del modelo y sus metadatos, indexados por el hash del PDF."""
    cache.mkdir(parents=True, exist_ok=True)
    carga = {"datos": datos.model_dump(mode="json"), "meta": meta}
    ruta = cache / f"{archivo_hash}.json"
    ruta.write_text(json.dumps(carga, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------- comparación


def normalizar_texto(texto: str) -> str:
    """Colapsa espacios, recorta extremos e ignora mayúsculas y acentos no relevantes."""
    return re.sub(r"\s+", " ", texto or "").strip().casefold()


def _dentro_de_tolerancia(esperado: float, extraido: float, tolerancia: str) -> bool:
    """True si la diferencia es menor o igual que la tolerancia, sin sorpresas de float."""
    diferencia = abs(Decimal(str(esperado)) - Decimal(str(extraido)))
    return diferencia <= Decimal(tolerancia)


def comparar_campo(campo: str, esperado: FacturaExtraida, extraido: FacturaExtraida) -> bool:
    """Compara un campo entre la verdad esperada y la extracción (tolerancias sección 16).

    Textos normalizados (CUPS con `normalizar_cups`; número y comercializadora sin espacios
    sobrantes y sin distinguir mayúsculas), fechas exactas, importes con tolerancia de 0,01 €
    y consumo con tolerancia de 0,5 kWh. El periodo es correcto solo si coinciden inicio y fin.
    """
    if campo == "cups":
        return normalizar_cups(esperado.cups) == normalizar_cups(extraido.cups)
    if campo == "numero_factura":
        return normalizar_texto(esperado.numero_factura) == normalizar_texto(
            extraido.numero_factura
        )
    if campo == "comercializadora":
        # La factura dice «Voltia Energía, S.L.» y la cartera «Voltia Energía»: la forma
        # jurídica y los acentos no identifican al proveedor, así que no cuentan como error.
        return comercializadora_canonica(esperado.comercializadora) == comercializadora_canonica(
            extraido.comercializadora
        )
    if campo == "periodo":
        return esperado.fecha_inicio == extraido.fecha_inicio and (
            esperado.fecha_fin == extraido.fecha_fin
        )
    if campo == "consumo_kwh":
        return _dentro_de_tolerancia(esperado.consumo_kwh, extraido.consumo_kwh, "0.5")
    if campo == "importe_total":
        return _dentro_de_tolerancia(esperado.importe_total, extraido.importe_total, "0.01")
    if campo == "lectura_estimada":
        return esperado.lectura_estimada == extraido.lectura_estimada
    raise ValueError(f"Campo desconocido: {campo}")


# ------------------------------------------------------------------------- precisión


def precision_por_campo(comparaciones: list[dict[str, bool]]) -> dict[str, tuple[int, int]]:
    """(correctos, evaluados) por campo; evaluados 0 si no hay comparaciones."""
    return {
        campo: (sum(1 for c in comparaciones if c[campo]), len(comparaciones)) for campo in CAMPOS
    }


def comercializadora_canonica(nombre: str) -> str:
    """Mapea el nombre leído a una de las tres comercializadoras del dataset.

    Empieza por coincidencia exacta (sin mayúsculas) y cae al primer token ("Voltia",
    "Luminar", "Ecoflux"); un nombre no reconocido se respeta tal cual.
    """
    clave = normalizar_texto(nombre)
    for canonica in COMERCIALIZADORAS:
        if canonica.casefold() == clave:
            return canonica
    for canonica in COMERCIALIZADORAS:
        if clave.startswith(canonica.casefold().split()[0]):
            return canonica
    return nombre.strip()


def precision_por_comercializadora(
    comparaciones: list[tuple[str, dict[str, bool]]],
) -> tuple[dict[str, int], dict[str, dict[str, tuple[int, int]]]]:
    """Agrupa las comparaciones por comercializadora (según la verdad esperada).

    Devuelve (facturas por comercializadora, precisión por campo y comercializadora);
    solo aparecen las tres canónicas y, si las hubiera, los nombres no reconocidos.
    """
    facturas: dict[str, int] = {}
    grupos: dict[str, list[dict[str, bool]]] = {}
    for nombre, comparacion in comparaciones:
        canonica = comercializadora_canonica(nombre)
        facturas[canonica] = facturas.get(canonica, 0) + 1
        grupos.setdefault(canonica, []).append(comparacion)
    return facturas, {nombre: precision_por_campo(comp) for nombre, comp in grupos.items()}


# ------------------------------------------------------------------------- anomalías


@dataclass
class MetricasAnomalias:
    """Recall de anomalías inyectadas, falsas alarmas y desglose por regla."""

    esperadas: int = 0
    detectadas: int = 0
    falsas_alarmas: int = 0
    secundarias_r4: int = 0
    desglose: dict[str, dict[str, int]] = field(default_factory=dict)


def suministros_de_cartera() -> dict[str, SuministroDatos]:
    """Suministros de `scripts.seed` como contexto de las reglas, indexados por CUPS.

    El estado se fija en «activo»: las reglas por factura no lo usan (R10 es una tarea
    programada fuera de las evals) y la potencia y tarifa contratadas sí son necesarias
    para R8 y la mediana de R9.
    """
    cartera: dict[str, SuministroDatos] = {}
    for fila in suministros_de_ejemplo():
        potencia = cast("float | None", fila.get("potencia_kw"))
        tarifa = fila.get("tarifa_acceso")
        cartera[normalizar_cups(str(fila["cups"]))] = SuministroDatos(
            cups=normalizar_cups(str(fila["cups"])),
            estado="activo",
            potencia_kw=float(potencia) if potencia is not None else None,
            tarifa_acceso=str(tarifa) if tarifa is not None else None,
        )
    return cartera


def _mediana_precio(
    precios_por_tarifa: dict[str, list[tuple[int, float]]],
    tarifa: str | None,
    indice: int,
) -> float | None:
    """Mediana de €/kWh de la tarifa excluyendo la propia factura (como `mediana_precio_kwh`)."""
    if tarifa is None:
        return None
    precios = [
        precio
        for indice_precio, precio in precios_por_tarifa.get(tarifa, [])
        if indice_precio != indice
    ]
    if not precios:
        return None
    return statistics.median(precios)


def _con_comercializadora_canonica(datos: FacturaExtraida) -> FacturaExtraida:
    """Copia la extracción con el nombre del proveedor en su forma canónica."""
    return datos.model_copy(
        update={"comercializadora": comercializadora_canonica(datos.comercializadora)}
    )


def precio_del_modelo(
    modelo: str, precios: dict[str, tuple[float, float]]
) -> tuple[float, float] | None:
    """Precio del modelo por id exacto o, si no, por el id base sin la fecha de versión.

    La API responde con `gpt-4.1-mini-2025-04-14` aunque se pida `gpt-4.1-mini`, y la tabla
    de precios está por nombre comercial.
    """
    if modelo in precios:
        return precios[modelo]
    return precios.get(re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", modelo))


def evaluar_anomalias(
    registros: list[RegistroDataset],
    extracciones: list[FacturaExtraida | None],
    suministros: dict[str, SuministroDatos],
) -> MetricasAnomalias:
    """Evalúa el sistema completo (extracción + reglas puras) contra lo esperado.

    Por cada factura con extracción válida se construye el contexto con la verdad esperada
    de las facturas anteriores del mismo CUPS (histórico de R6/R7 y candidatos de R3/R4) y
    el suministro de la cartera; después se ejecutan R1–R9 y R11. Una R4 sobre una factura
    cuya anomalía esperada es R3 (una duplicada) cuenta como secundaria esperada: no es
    acierto del recall ni falsa alarma.
    """
    precios_por_tarifa: dict[str, list[tuple[int, float]]] = {}
    for indice, registro in enumerate(registros):
        suministro = suministros.get(normalizar_cups(registro.verdad.cups))
        if (
            suministro is None
            or suministro.tarifa_acceso is None
            or registro.verdad.importe_energia is None
            or registro.verdad.consumo_kwh <= 0
        ):
            continue
        precio = registro.verdad.importe_energia / registro.verdad.consumo_kwh
        precios_por_tarifa.setdefault(suministro.tarifa_acceso, []).append((indice, precio))

    metricas = MetricasAnomalias()

    def _cuenta(regla: str, clave: str) -> None:
        desglose = metricas.desglose.setdefault(
            regla, {"esperadas": 0, "detectadas": 0, "falsas": 0}
        )
        desglose[clave] += 1

    for indice, (registro, extraccion) in enumerate(zip(registros, extracciones, strict=True)):
        esperadas = registro.anomalias_esperadas
        metricas.esperadas += len(esperadas)
        for regla in esperadas:
            _cuenta(regla, "esperadas")
        if extraccion is None:
            continue

        cups = normalizar_cups(registro.verdad.cups)
        suministro = suministros.get(cups)
        anteriores = [
            a_factura_de_extraccion(
                _con_comercializadora_canonica(anterior.verdad), anterior.archivo_hash
            )
            for posicion, anterior in enumerate(registros[:indice])
            if posicion != indice and normalizar_cups(anterior.verdad.cups) == cups
        ]
        contexto = ContextoReglas(
            suministro=suministro,
            historico=list(anteriores),
            mismo_cups=list(anteriores),
            mediana_precio_kwh=(
                _mediana_precio(precios_por_tarifa, suministro.tarifa_acceso, indice)
                if suministro is not None
                else None
            ),
        )
        factura = a_factura_de_extraccion(
            _con_comercializadora_canonica(extraccion), registro.archivo_hash
        )
        obtenidas = {anomalia.regla for anomalia in evaluar(factura, contexto)}

        if (
            REGLA_DUPLICADA in esperadas
            and REGLA_SOLAPADO in obtenidas
            and REGLA_SOLAPADO not in esperadas
        ):
            obtenidas.discard(REGLA_SOLAPADO)
            metricas.secundarias_r4 += 1

        aciertos = esperadas & obtenidas
        falsas = obtenidas - esperadas
        metricas.detectadas += len(aciertos)
        metricas.falsas_alarmas += len(falsas)
        for regla in aciertos:
            _cuenta(regla, "detectadas")
        for regla in falsas:
            _cuenta(regla, "falsas")
    return metricas


# ------------------------------------------------------------------------------ coste


def tabla_de_precios() -> dict[str, tuple[float, float]]:
    """Precios por millón de tokens (entrada, salida) en euros, sobreescribibles por entorno."""
    precios = dict(PRECIOS_EUR_POR_MILLON)
    crudo = os.environ.get(VAR_ENTORNO_PRECIOS)
    if not crudo:
        return precios
    try:
        sobrecarga: dict[str, list[float]] = json.loads(crudo)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{VAR_ENTORNO_PRECIOS} debe ser un JSON {{modelo: [entrada, salida]}}"
        ) from exc
    for modelo, par in sobrecarga.items():
        precios[modelo] = (float(par[0]), float(par[1]))
    return precios


def coste_de_factura(
    modelo: str,
    tokens_entrada: float,
    tokens_salida: float,
    precios: dict[str, tuple[float, float]],
) -> float | None:
    """Coste estimado de una llamada con la tabla de precios; `None` si el modelo no está."""
    precio = precio_del_modelo(modelo, precios)
    if precio is None:
        return None
    return (tokens_entrada / 1_000_000) * precio[0] + (tokens_salida / 1_000_000) * precio[1]


# ---------------------------------------------------------------------------- informe


@dataclass
class ResultadosEvals:
    """Todo lo que el informe necesita, ya calculado."""

    fecha: str
    evaluadas: int
    total_dataset: int
    limitado: bool
    errores: int
    precision_campo: dict[str, tuple[int, int]]
    facturas_por_comercializadora: dict[str, int]
    precision_comercializadora: dict[str, dict[str, tuple[int, int]]]
    tokens_medios: tuple[float, float] | None
    modelo: str | None
    coste_medio: float | None
    coste_calculado: bool
    anomalias: MetricasAnomalias


def _pct(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{100 * valor:.1f}".replace(".", ",") + " %"


def _ratio(cuenta: tuple[int, int]) -> float | None:
    correctos, evaluados = cuenta
    return correctos / evaluados if evaluados else None


def _eur(valor: float) -> str:
    return f"{valor:.4f}".replace(".", ",") + " €"


def _orden_regla(regla: str) -> tuple[int, str]:
    """Ordena R1…R11 por número; cualquier otra etiqueta va al final."""
    return (int(regla[1:]), regla) if regla[1:].isdigit() else (99, regla)


def generar_informe(resultados: ResultadosEvals) -> str:
    """Informe en Markdown con tablas listas para pegar en el README.

    Nunca inventa métricas: si no hay datos, la tabla va vacía con un aviso; si el modelo
    no está en la tabla de precios, se informan los tokens y se dice que no hay coste.
    """
    r = resultados
    lineas: list[str] = ["# Evaluación del LLM · Energy Ops Hub", ""]
    lineas.append(f"Fecha de la evaluación: {r.fecha}")
    alcance = f"{r.evaluadas} de {r.total_dataset} facturas del dataset"
    if r.limitado:
        alcance += " (limitado con `--limite`)"
    lineas.append(f"Facturas evaluadas: {alcance}")
    if r.errores:
        lineas.append(f"Extracciones con error (excluidas de las métricas): {r.errores}")

    lineas += [
        "",
        "## Precisión por campo",
        "",
        "| Campo | Correctos | Evaluados | Precisión |",
        "|---|---:|---:|---:|",
    ]
    if r.evaluadas == 0:
        lineas.append(AVISO_SIN_DATOS)
    else:
        for campo in CAMPOS:
            correctos, evaluados = r.precision_campo[campo]
            lineas.append(
                f"| {ETIQUETAS_CAMPO[campo]} | {correctos} | {evaluados} | "
                f"{_pct(_ratio(r.precision_campo[campo]))} |"
            )

    lineas += [
        "",
        "## Precisión por comercializadora",
        "",
        "| Comercializadora | Facturas | " + " | ".join(ETIQUETAS_CAMPO[c] for c in CAMPOS) + " |",
        "|---|---:|" + "---:|" * len(CAMPOS),
    ]
    if r.evaluadas == 0:
        lineas.append(AVISO_SIN_DATOS)
    else:
        nombres = [c for c in COMERCIALIZADORAS if c in r.facturas_por_comercializadora]
        nombres += sorted(set(r.facturas_por_comercializadora) - set(COMERCIALIZADORAS))
        for nombre in nombres:
            precision = r.precision_comercializadora.get(nombre, {})
            celdas = " | ".join(_pct(_ratio(precision.get(campo, (0, 0)))) for campo in CAMPOS)
            lineas.append(f"| {nombre} | {r.facturas_por_comercializadora[nombre]} | {celdas} |")

    lineas += [
        "",
        "## Coste por factura",
        "",
        "> Estimación con la tabla de precios "
        "(lista en USD usada como EUR). No es una conversión de divisa.",
        "",
    ]
    if r.evaluadas == 0 or r.tokens_medios is None:
        lineas.append(AVISO_SIN_DATOS)
    else:
        tokens_entrada, tokens_salida = r.tokens_medios
        lineas.append(f"- Modelo: {r.modelo}")
        lineas.append(
            f"- Tokens medios por factura: {tokens_entrada:.0f} de entrada / "
            f"{tokens_salida:.0f} de salida"
        )
        if r.coste_calculado and r.coste_medio is not None:
            lineas.append(f"- Coste medio por factura: {_eur(r.coste_medio)}")
        else:
            lineas.append(
                f"- Coste medio por factura: no calculado — el modelo «{r.modelo}» no está "
                f"en la tabla de precios. Se pueden añadir precios con la variable "
                f"{VAR_ENTORNO_PRECIOS} sin tocar código."
            )

    a = r.anomalias
    recall = _pct(a.detectadas / a.esperadas) if a.esperadas else "—"
    lineas += [
        "",
        "## Detección de anomalías",
        "",
        "| Detección de anomalías | Valor |",
        "|---|---:|",
    ]
    if r.evaluadas == 0:
        lineas.append(AVISO_SIN_DATOS)
    else:
        lineas += [
            f"| Anomalías esperadas (inyectadas) | {a.esperadas} |",
            f"| Detectadas (recall) | {a.detectadas}/{a.esperadas} ({recall}) |",
            f"| Falsas alarmas | {a.falsas_alarmas} |",
            f"| R4 secundarias sobre duplicadas (no cuentan como falsa alarma) "
            f"| {a.secundarias_r4} |",
        ]
        lineas += [
            "",
            "### Desglose por regla",
            "",
            "| Regla | Esperadas | Detectadas | Falsas alarmas |",
            "|---|---:|---:|---:|",
        ]
        for regla in sorted(a.desglose, key=_orden_regla):
            cuenta = a.desglose[regla]
            lineas.append(
                f"| {regla} | {cuenta['esperadas']} | {cuenta['detectadas']} | {cuenta['falsas']} |"
            )
        lineas += ["", AVISO_R4_SECUNDARIA]
    return "\n".join(lineas) + "\n"


# ------------------------------------------------------------------------------- CLI


def main(
    argv: list[str] | None = None,
    *,
    dataset: Path = CARPETA_DATASET,
    cache: Path = CARPETA_CACHE,
    salida: Path = SALIDA_DEFECTO,
) -> int:
    """Punto de entrada de `uv run python -m evals.run_evals`. Devuelve el código de salida."""
    parser = argparse.ArgumentParser(
        description="Evalúa la extracción y las anomalías sobre el dataset sintético."
    )
    parser.add_argument("--limite", type=int, default=None, help="Número máximo de facturas")
    parser.add_argument(
        "--salida",
        type=Path,
        default=None,
        help="Informe Markdown (por defecto evals/resultados.md)",
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=SEMILLA_DEFECTO,
        help="Semilla del dataset; solo se usa para sugerir el comando de generación",
    )
    parser.add_argument(
        "--sin-cache", action="store_true", help="Ignora la caché al leer y no escribe en ella"
    )
    args = parser.parse_args(argv)
    ruta_salida = args.salida if args.salida is not None else salida

    if not any(dataset.glob("*.pdf")):
        print(
            f"No hay facturas en {dataset}. Genera primero el dataset con:\n"
            f"    uv run python -m scripts.generate_invoices --semilla {args.semilla}",
            file=sys.stderr,
        )
        return 1

    total_dataset = len(list(dataset.glob("*.pdf")))
    registros = cargar_registros(dataset, args.limite)

    extracciones: list[FacturaExtraida | None] = []
    metas: list[dict[str, object]] = []
    errores = 0
    for registro in registros:
        en_cache = None if args.sin_cache else cargar_de_cache(cache, registro.archivo_hash)
        if en_cache is not None:
            datos, meta = en_cache
        else:
            if not settings.openai_api_key:
                print(
                    "OPENAI_API_KEY no está configurada: no se puede llamar al modelo. "
                    "Define la clave (o rellena .env) y vuelve a ejecutar; las extracciones "
                    "ya guardadas en caché se reutilizan sin clave.",
                    file=sys.stderr,
                )
                return 1
            try:
                datos, meta = extraer_factura(registro.pdf.read_bytes())
            except ExtraccionInvalida as exc:
                print(f"Extracción inválida para {registro.pdf.name}: {exc}", file=sys.stderr)
                errores += 1
                extracciones.append(None)
                metas.append({})
                continue
            if not args.sin_cache:
                guardar_en_cache(cache, registro.archivo_hash, datos, meta)
        extracciones.append(datos)
        metas.append(meta)

    evaluadas = sum(1 for datos in extracciones if datos is not None)
    comparaciones: list[tuple[str, dict[str, bool]]] = []
    for registro, extraccion in zip(registros, extracciones, strict=True):
        if extraccion is None:
            continue
        comparaciones.append(
            (
                registro.verdad.comercializadora,
                {campo: comparar_campo(campo, registro.verdad, extraccion) for campo in CAMPOS},
            )
        )
    facturas_por_comercializadora, precision_comercializadora = precision_por_comercializadora(
        comparaciones
    )

    metricas = evaluar_anomalias(registros, extracciones, suministros_de_cartera())

    tokens_medios: tuple[float, float] | None = None
    modelo: str | None = None
    coste_medio: float | None = None
    coste_calculado = False
    if metas:
        modelo = str(metas[0].get("modelo"))
        entradas = [float(str(meta.get("tokens_entrada", 0))) for meta in metas]
        salidas = [float(str(meta.get("tokens_salida", 0))) for meta in metas]
        tokens_medios = (statistics.fmean(entradas), statistics.fmean(salidas))
        precios = tabla_de_precios()
        if precio_del_modelo(modelo, precios) is not None:
            costes: list[float] = []
            for tokens_entrada, tokens_salida in zip(entradas, salidas, strict=True):
                coste = coste_de_factura(modelo, tokens_entrada, tokens_salida, precios)
                if coste is None:  # no debería pasar: el modelo está en la tabla
                    break
                costes.append(coste)
            if len(costes) == len(entradas) and costes:
                coste_medio = statistics.fmean(costes)
                coste_calculado = True

    informe = generar_informe(
        ResultadosEvals(
            fecha=date.today().isoformat(),
            evaluadas=evaluadas,
            total_dataset=total_dataset,
            limitado=args.limite is not None,
            errores=errores,
            precision_campo=precision_por_campo([c for _, c in comparaciones]),
            facturas_por_comercializadora=facturas_por_comercializadora,
            precision_comercializadora=precision_comercializadora,
            tokens_medios=tokens_medios,
            modelo=modelo,
            coste_medio=coste_medio,
            coste_calculado=coste_calculado,
            anomalias=metricas,
        )
    )
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(informe, encoding="utf-8")

    print(f"Facturas evaluadas: {evaluadas}/{total_dataset}")
    print(
        f"Recall de anomalías: {metricas.detectadas}/{metricas.esperadas} · "
        f"Falsas alarmas: {metricas.falsas_alarmas} · "
        f"R4 secundarias (duplicadas): {metricas.secundarias_r4}"
    )
    print(f"Informe escrito en {ruta_salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
