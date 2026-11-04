"""Tests de las evals (docs/spec.md, sección 16).

Todo sin red: `extraer_factura` se sustituye por un doble y el dataset y la caché viven en
el directorio temporal de pytest; los tests nunca escriben dentro de `evals/`. Cubren el
comparador campo a campo con las tolerancias de la sección 16, el cálculo de precisión, la
caché de extracciones (con y sin `--sin-cache`), las métricas de anomalías con extracciones
simuladas —incluida la R4 secundaria sobre una duplicada— y el comportamiento del CLI sin
dataset y sin clave del modelo.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.config import settings
from app.domain.rules import SuministroDatos
from app.schemas import FacturaExtraida
from evals import run_evals
from evals.run_evals import (
    AVISO_SIN_DATOS,
    CAMPOS,
    MetricasAnomalias,
    RegistroDataset,
    ResultadosEvals,
    comercializadora_canonica,
    comparar_campo,
    coste_de_factura,
    evaluar_anomalias,
    generar_informe,
    main,
    normalizar_texto,
    precio_del_modelo,
    precision_por_campo,
    precision_por_comercializadora,
    suministros_de_cartera,
    tabla_de_precios,
)
from scripts.seed import cups_ejemplo, suministros_de_ejemplo

CUPS = cups_ejemplo(0)
OTRO_CUPS = cups_ejemplo(1)


# --------------------------------------------------------------------------- dobles


class _ExtraccionFalsa:
    """Doble de `extraer_factura`: devuelve la salida preparada para cada slug de PDF.

    Los PDFs del dataset de prueba son `pdf:<slug>`, así que el doble sabe qué factura
    toca. Cuenta las llamadas para verificar la caché.
    """

    def __init__(
        self,
        salidas: dict[str, FacturaExtraida],
        modelo: str = "modelo-test",
        tokens: tuple[int, int] = (1000, 200),
    ) -> None:
        self.salidas = salidas
        self.modelo = modelo
        self.tokens = tokens
        self.llamadas = 0

    def __call__(self, pdf_bytes: bytes) -> tuple[FacturaExtraida, dict[str, object]]:
        self.llamadas += 1
        slug = pdf_bytes.decode().removeprefix("pdf:")
        meta: dict[str, object] = {
            "modelo": self.modelo,
            "tokens_entrada": self.tokens[0],
            "tokens_salida": self.tokens[1],
        }
        return self.salidas[slug], meta


def _factura(**extra: Any) -> FacturaExtraida:
    """Una `FacturaExtraida` de ejemplo, con overrides puntuales por test."""
    valores: dict[str, Any] = {
        "cups": CUPS,
        "numero_factura": "VOL-202601-000",
        "comercializadora": "Voltia Energía",
        "fecha_emision": "2026-02-03",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-01-31",
        "potencia_kw": 4.6,
        "consumo_kwh": 100.0,
        "importe_potencia": 10.0,
        "importe_energia": 20.0,
        "impuestos_otros": 3.0,
        "importe_total": 33.0,
        "lectura_estimada": False,
        "confianza": 1.0,
        "campos_dudosos": [],
    }
    valores.update(extra)
    return FacturaExtraida(**valores)


def _escribir_registro(
    dataset: Path,
    slug: str,
    verdad: FacturaExtraida,
    esperadas: list[str],
    tipo: str | None = None,
) -> None:
    """Escribe un par PDF + JSON del dataset de prueba en el directorio temporal."""
    dataset.mkdir(parents=True, exist_ok=True)
    (dataset / f"{slug}.pdf").write_bytes(f"pdf:{slug}".encode())
    carga = verdad.model_dump(mode="json")
    carga["anomalias_esperadas"] = esperadas
    carga["tipo_anomalia"] = tipo
    (dataset / f"{slug}.json").write_text(json.dumps(carga), encoding="utf-8")


def _hash_de(slug: str) -> str:
    return hashlib.sha256(f"pdf:{slug}".encode()).hexdigest()


# ----------------------------------------------------------------------- comparador


def test_comparar_campo_igual_en_todos_los_campos() -> None:
    esperado = _factura()
    extraido = _factura()
    for campo in CAMPOS:
        assert comparar_campo(campo, esperado, extraido) is True


def test_comparar_campo_texto_ignora_espacios_y_mayusculas() -> None:
    esperado = _factura(comercializadora="Voltia Energía", numero_factura="VOL-202601-000")
    extraido = _factura(comercializadora="  voltia energía  ", numero_factura="vol-202601-000")
    assert comparar_campo("comercializadora", esperado, extraido) is True
    assert comparar_campo("numero_factura", esperado, extraido) is True


def test_comparar_campo_cups_ignora_espacios_y_minusculas() -> None:
    esperado = _factura(cups="ES0031000000000000TR")
    extraido = _factura(cups="es 0031 0000 0000 0000 tr")
    assert comparar_campo("cups", esperado, extraido) is True


def test_comparar_campo_importe_en_el_borde_de_la_tolerancia() -> None:
    esperado = _factura(importe_total=33.0)
    assert comparar_campo("importe_total", esperado, _factura(importe_total=33.01)) is True
    assert comparar_campo("importe_total", esperado, _factura(importe_total=32.99)) is True
    assert comparar_campo("importe_total", esperado, _factura(importe_total=33.02)) is False


def test_comparar_campo_consumo_en_el_borde_de_la_tolerancia() -> None:
    esperado = _factura(consumo_kwh=100.0)
    assert comparar_campo("consumo_kwh", esperado, _factura(consumo_kwh=100.5)) is True
    assert comparar_campo("consumo_kwh", esperado, _factura(consumo_kwh=99.5)) is True
    assert comparar_campo("consumo_kwh", esperado, _factura(consumo_kwh=100.6)) is False


def test_comparar_campo_periodo_y_lectura_son_exactos() -> None:
    esperado = _factura(fecha_fin="2026-01-31", lectura_estimada=False)
    assert comparar_campo("periodo", esperado, _factura()) is True
    assert comparar_campo("periodo", esperado, _factura(fecha_fin="2026-01-30")) is False
    assert comparar_campo("lectura_estimada", esperado, _factura()) is True
    assert comparar_campo("lectura_estimada", esperado, _factura(lectura_estimada=True)) is False


def test_comparar_campo_desconocido_falla() -> None:
    with pytest.raises(ValueError, match="desconocido"):
        comparar_campo("no_existe", _factura(), _factura())


def test_normalizar_texto_colapsa_espacios_internos() -> None:
    assert normalizar_texto("  Voltia    Energía ") == "voltia energía"


# ----------------------------------------------------------------------- precisión


def test_precision_por_campo_cuenta_correctos_sobre_evaluados() -> None:
    comparaciones = [
        dict.fromkeys(CAMPOS, True),
        {**dict.fromkeys(CAMPOS, True), "importe_total": False},
        {**dict.fromkeys(CAMPOS, True), "cups": False},
    ]
    precision = precision_por_campo(comparaciones)
    assert precision["importe_total"] == (2, 3)
    assert precision["cups"] == (2, 3)
    assert precision["consumo_kwh"] == (3, 3)


def test_precision_por_campo_sin_datos() -> None:
    precision = precision_por_campo([])
    assert all(cuenta == (0, 0) for cuenta in precision.values())


def test_precision_por_comercializadora_agrupa_por_la_verdad_esperada() -> None:
    comparaciones = [
        ("Voltia Energía", dict.fromkeys(CAMPOS, True)),
        ("voltia energia", dict.fromkeys(CAMPOS, False)),
        ("Ecoflux", dict.fromkeys(CAMPOS, True)),
    ]
    facturas, precision = precision_por_comercializadora(comparaciones)
    assert facturas == {"Voltia Energía": 2, "Ecoflux": 1}
    assert precision["Voltia Energía"]["cups"] == (1, 2)
    assert precision["Ecoflux"]["cups"] == (1, 1)


def test_comercializadora_canonica_reconoce_las_tres() -> None:
    assert comercializadora_canonica("Voltia Energía") == "Voltia Energía"
    assert comercializadora_canonica("luminar comercializadora") == "Luminar Comercializadora"
    assert comercializadora_canonica("Ecoflux") == "Ecoflux"


# --------------------------------------------------------------------------- caché


def test_dos_ejecuciones_con_cache_caliente_no_llaman_dos_veces_al_modelo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "dataset"
    cache = tmp_path / "cache"
    salidas = {
        "factura-a": _factura(cups=CUPS, numero_factura="factura-a"),
        "factura-b": _factura(cups=OTRO_CUPS, numero_factura="factura-b"),
    }
    for slug, verdad in salidas.items():
        _escribir_registro(dataset, slug, verdad, [])
    doble = _ExtraccionFalsa(salidas)
    monkeypatch.setattr(run_evals, "extraer_factura", doble)
    monkeypatch.setattr(settings, "openai_api_key", "clave-de-prueba")

    salida = tmp_path / "resultados.md"
    assert main(["--salida", str(salida)], dataset=dataset, cache=cache) == 0
    assert doble.llamadas == 2
    # La caché queda indexada por el hash de cada PDF.
    assert sorted(ruta.name for ruta in cache.glob("*.json")) == sorted(
        f"{_hash_de(slug)}.json" for slug in salidas
    )

    assert main(["--salida", str(salida)], dataset=dataset, cache=cache) == 0
    assert doble.llamadas == 2  # segunda ejecución: cero llamadas nuevas
    informe = salida.read_text(encoding="utf-8")
    assert "100,0 %" in informe  # la caché sirvió los mismos datos: precisión completa


def test_sin_cache_no_lee_ni_escribe_la_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "dataset"
    cache = tmp_path / "cache"
    cache.mkdir()
    salidas = {"factura-a": _factura(consumo_kwh=100.0)}
    _escribir_registro(dataset, "factura-a", salidas["factura-a"], [])

    # Caché envenenada: si se leyera, la precisión de consumo sería 0 %; con --sin-cache
    # no se lee y las métricas salen del modelo.
    veneno = {
        "datos": _factura(consumo_kwh=999.0).model_dump(mode="json"),
        "meta": {"modelo": "veneno", "tokens_entrada": 1, "tokens_salida": 1},
    }
    ruta_veneno = cache / f"{_hash_de('factura-a')}.json"
    ruta_veneno.write_text(json.dumps(veneno), encoding="utf-8")

    doble = _ExtraccionFalsa(salidas)
    monkeypatch.setattr(run_evals, "extraer_factura", doble)
    monkeypatch.setattr(settings, "openai_api_key", "clave-de-prueba")
    salida = tmp_path / "resultados.md"

    assert main(["--salida", str(salida), "--sin-cache"], dataset=dataset, cache=cache) == 0
    assert doble.llamadas == 1  # el modelo sí se llama
    assert ruta_veneno.read_text(encoding="utf-8") == json.dumps(veneno)  # y no se escribe
    informe = salida.read_text(encoding="utf-8")
    assert "| Consumo kWh | 1 | 1 | 100,0 % |" in informe  # métricas del modelo, no de la caché


# -------------------------------------------------------- métricas de anomalías


def _registro(slug: str, verdad: FacturaExtraida, esperadas: list[str]) -> RegistroDataset:
    return RegistroDataset(
        pdf=Path(f"{slug}.pdf"),
        verdad=verdad,
        anomalias_esperadas=frozenset(esperadas),
        tipo_anomalia=None,
        archivo_hash=hashlib.sha256(slug.encode()).hexdigest(),
    )


def _mes(mes: int) -> tuple[str, str]:
    finales = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31}
    return f"2026-{mes:02d}-01", f"2026-{mes:02d}-{finales[mes]}"


def _cartera() -> dict[str, SuministroDatos]:
    return {
        CUPS: SuministroDatos(cups=CUPS, estado="activo", potencia_kw=4.6, tarifa_acceso="2.0TD")
    }


def test_metricas_anomalias_con_extracciones_simuladas() -> None:
    """Un acierto, un fallo, una falsa alarma y una R4 secundaria de una duplicada.

    Esperado: R6 y una de las dos R3 se detectan (recall 2/3); la confianza baja de la
    factura limpia es la única falsa alarma (R11); la R4 de la duplicada con clave
    distinta es secundaria esperada y no cuenta como falsa alarma.
    """
    registros: list[RegistroDataset] = []
    extracciones: list[FacturaExtraida | None] = []

    # Cuatro meses limpios (r0–r3): histórico suficiente para R6.
    for mes in (1, 2, 3, 4):
        inicio, fin = _mes(mes)
        verdad = _factura(
            numero_factura=f"VOL-2026{mes:02d}-000", fecha_inicio=inicio, fecha_fin=fin
        )
        registros.append(_registro(f"mes-{mes}", verdad, []))
        extracciones.append(verdad)

    # r4: consumo disparado esperado (R6) y bien detectado.
    inicio, fin = _mes(5)
    registros.append(
        _registro(
            "mes-5",
            _factura(numero_factura="VOL-202605-000", fecha_inicio=inicio, fecha_fin=fin),
            ["R6"],
        )
    )
    extracciones.append(
        _factura(
            numero_factura="VOL-202605-000",
            fecha_inicio=inicio,
            fecha_fin=fin,
            consumo_kwh=650.0,
            importe_energia=130.0,
            importe_total=143.0,
        )
    )

    # r5: duplicada de r0 (mes 6, datos de enero) con clave igual: dispara R3, acierto.
    duplicada = _factura(
        numero_factura="VOL-202601-000", fecha_inicio="2026-01-01", fecha_fin="2026-01-31"
    )
    registros.append(_registro("duplicada", duplicada, ["R3"]))
    extracciones.append(duplicada)

    # r6: otra duplicada de r0 pero el modelo lee otro número: la clave no coincide y el
    # sistema dispara R4 (secundaria esperada) en lugar de R3 (fallo de recall).
    registros.append(_registro("duplicada-r4", duplicada, ["R3"]))
    extracciones.append(
        _factura(numero_factura="VOL-202601-0XX", fecha_inicio="2026-01-01", fecha_fin="2026-01-31")
    )

    # r7: factura limpia con confianza baja leída por el modelo: falsa alarma (R11).
    inicio, fin = _mes(7)
    registros.append(
        _registro(
            "mes-7",
            _factura(numero_factura="VOL-202607-000", fecha_inicio=inicio, fecha_fin=fin),
            [],
        )
    )
    extracciones.append(
        _factura(numero_factura="VOL-202607-000", fecha_inicio=inicio, fecha_fin=fin, confianza=0.5)
    )

    metricas = evaluar_anomalias(registros, extracciones, _cartera())

    assert metricas.esperadas == 3  # R6 + R3 + R3
    assert metricas.detectadas == 2  # R6 y la R3 de la duplicada con clave igual
    assert metricas.falsas_alarmas == 1  # solo la R11 de confianza baja
    assert metricas.secundarias_r4 == 1  # la R4 de la duplicada, sin contar como falsa
    assert metricas.desglose["R6"] == {"esperadas": 1, "detectadas": 1, "falsas": 0}
    assert metricas.desglose["R3"] == {"esperadas": 2, "detectadas": 1, "falsas": 0}
    assert metricas.desglose["R11"] == {"esperadas": 0, "detectadas": 0, "falsas": 1}
    # La R4 secundaria no entra en el desglose (ni esperada ni falsa): se informa aparte.
    assert "R4" not in metricas.desglose


def test_metricas_anomalias_sin_extraccion_valida_cuenta_esperadas() -> None:
    """Una extracción con error mantiene el conteo de esperadas y no añade nada más."""
    metricas = evaluar_anomalias([_registro("mes-1", _factura(), ["R6"])], [None], _cartera())
    assert metricas.esperadas == 1
    assert metricas.detectadas == 0
    assert metricas.falsas_alarmas == 0


def test_suministros_de_cartera_tiene_potencia_y_tarifa() -> None:
    cartera = suministros_de_cartera()
    assert len(cartera) == len(suministros_de_ejemplo())
    ejemplo = cartera[CUPS]
    assert ejemplo.potencia_kw is not None
    assert ejemplo.tarifa_acceso == "2.0TD"


# -------------------------------------------------------------------------- coste


def test_coste_de_factura_con_modelo_en_la_tabla() -> None:
    coste = coste_de_factura("modelo-x", 1_000_000, 1_000_000, {"modelo-x": (2.0, 10.0)})
    assert coste == pytest.approx(12.0)


def test_coste_de_factura_modelo_fuera_de_la_tabla() -> None:
    assert coste_de_factura("desconocido", 1000, 200, {"modelo-x": (2.0, 10.0)}) is None


def test_tabla_de_precios_se_sobreescribe_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALS_PRECIOS", '{"modelo-y": [0.5, 1.5]}')
    precios = tabla_de_precios()
    assert precios["modelo-y"] == (0.5, 1.5)
    assert "gpt-4o-mini" in precios  # la tabla base sigue disponible

    monkeypatch.setenv("EVALS_PRECIOS", "no es json")
    with pytest.raises(ValueError, match="EVALS_PRECIOS"):
        tabla_de_precios()


# ----------------------------------------------------------------------- informe


def _resultados(**extra: Any) -> ResultadosEvals:
    valores: dict[str, Any] = {
        "fecha": "2026-11-05",
        "evaluadas": 1,
        "total_dataset": 1,
        "limitado": False,
        "errores": 0,
        "precision_campo": dict.fromkeys(CAMPOS, (1, 1)),
        "facturas_por_comercializadora": {"Voltia Energía": 1},
        "precision_comercializadora": {"Voltia Energía": dict.fromkeys(CAMPOS, (1, 1))},
        "tokens_medios": (1000.0, 200.0),
        "modelo": "modelo-test",
        "coste_medio": None,
        "coste_calculado": False,
        "anomalias": MetricasAnomalias(),
    }
    valores.update(extra)
    return ResultadosEvals(**valores)


def test_informe_avisa_cuando_el_modelo_no_esta_en_la_tabla_de_precios() -> None:
    informe = generar_informe(_resultados())
    assert "no calculado" in informe
    assert "modelo-test" in informe
    assert "Tokens medios por factura: 1000 de entrada / 200 de salida" in informe


def test_informe_sin_datos_va_vacio_con_aviso() -> None:
    informe = generar_informe(
        _resultados(
            evaluadas=0,
            precision_campo=dict.fromkeys(CAMPOS, (0, 0)),
            facturas_por_comercializadora={},
            precision_comercializadora={},
            tokens_medios=None,
            modelo=None,
        )
    )
    # El aviso aparece en precisión por campo, por comercializadora, coste y anomalías.
    assert informe.count(AVISO_SIN_DATOS) == 4
    assert "| Anomalías esperadas (inyectadas) |" not in informe


def test_informe_trae_recall_falsas_alarmas_y_nota_de_r4() -> None:
    informe = generar_informe(
        _resultados(
            anomalias=MetricasAnomalias(
                esperadas=4,
                detectadas=3,
                falsas_alarmas=1,
                secundarias_r4=1,
                desglose={"R3": {"esperadas": 2, "detectadas": 1, "falsas": 0}},
            )
        )
    )
    assert "| Detectadas (recall) | 3/4 (75,0 %) |" in informe
    assert "| Falsas alarmas | 1 |" in informe
    assert "no cuentan como falsa alarma" in informe
    assert run_evals.AVISO_R4_SECUNDARIA in informe


# --------------------------------------------------------------------------- CLI


def test_sin_dataset_explica_como_generarlo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = main(["--semilla", "12345"], dataset=tmp_path / "vacio", cache=tmp_path / "cache")
    assert codigo == 1
    assert "uv run python -m scripts.generate_invoices --semilla 12345" in capsys.readouterr().err


def test_sin_clave_y_sin_cache_falla_con_mensaje_claro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = tmp_path / "dataset"
    _escribir_registro(dataset, "factura-a", _factura(), [])
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    codigo = main(
        ["--sin-cache", "--salida", str(tmp_path / "resultados.md")],
        dataset=dataset,
        cache=tmp_path / "cache",
    )
    assert codigo == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_ejecucion_completa_escribe_el_informe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "dataset"
    verdad = _factura()
    _escribir_registro(dataset, "factura-a", verdad, [])
    doble = _ExtraccionFalsa({"factura-a": verdad}, modelo="gpt-4o-mini", tokens=(500, 100))
    monkeypatch.setattr(run_evals, "extraer_factura", doble)
    monkeypatch.setattr(settings, "openai_api_key", "clave-de-prueba")
    salida = tmp_path / "informes" / "resultados.md"

    assert main(["--salida", str(salida)], dataset=dataset, cache=tmp_path / "cache") == 0
    informe = salida.read_text(encoding="utf-8")
    assert "Facturas evaluadas: 1 de 1 facturas del dataset" in informe
    assert "| CUPS | 1 | 1 | 100,0 % |" in informe
    assert "- Coste medio por factura: 0,0001 €" in informe  # (500·0.15 + 100·0.6) / 1M
    assert "| Detectadas (recall) | 0/0 (—) |" in informe


@pytest.mark.parametrize(
    ("esperado", "extraido", "coincide"),
    [
        ("Voltia Energía", "Voltia Energía, S.L.", True),
        ("Luminar Comercializadora", "Luminar Comercializadora, S.A.", True),
        ("Ecoflux", "ECOFLUX", True),
        ("Voltia Energía", "Voltia Energia", True),
        ("Voltia Energía", "Luminar Comercializadora", False),
    ],
)
def test_la_comercializadora_se_compara_sin_forma_juridica(
    esperado: str, extraido: str, coincide: bool
) -> None:
    """«Voltia Energía, S.L.» y «Voltia Energía» son la misma comercializadora.

    La factura lleva la forma jurídica y la cartera no; comparar el texto crudo hacía que la
    extracción pareciera fallar al 80 % cuando estaba leyendo bien.
    """
    verdad = _factura(comercializadora=esperado)
    extraccion = _factura(comercializadora=extraido)

    assert comparar_campo("comercializadora", verdad, extraccion) is coincide


def test_el_precio_se_encuentra_por_el_id_con_fecha() -> None:
    """La API devuelve `gpt-4.1-mini-2025-04-14`; la tabla de precios está por nombre."""
    precios = run_evals.tabla_de_precios()

    assert precio_del_modelo("gpt-4.1-mini-2025-04-14", precios) == precios["gpt-4.1-mini"]
    assert precio_del_modelo("modelo-inexistente", precios) is None
