"""Tests del generador de facturas sintéticas (docs/spec.md, sección 8).

Corren contra el generador real, sin mocks, y todo el estado temporal vive en el
directorio temporal de pytest: nunca escriben dentro del repositorio.
"""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from app.domain.cups import cups_valido
from scripts.generate_invoices import (
    CLASES_ANOMALIA,
    CLAVES_EXTRA,
    CLAVES_FACTURA_EXTRAIDA,
    LIMITE_DEFECTO,
    SEMILLA_DEFECTO,
    generar_dataset,
)
from scripts.seed import suministros_de_ejemplo


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Un dataset completo con la semilla por defecto, compartido por los tests del módulo."""
    salida = tmp_path_factory.mktemp("dataset-facturas")
    generar_dataset(semilla=SEMILLA_DEFECTO, limite=LIMITE_DEFECTO, salida=salida)
    return salida


def _cargas(salida: Path) -> list[dict[str, object]]:
    """Verdades esperadas del dataset, en orden determinista por nombre de archivo."""
    resultado: list[dict[str, object]] = []
    for ruta in sorted(salida.glob("*.json")):
        with open(ruta, encoding="utf-8") as fichero:
            resultado.append(json.load(fichero))
    return resultado


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_dos_ejecuciones_son_identicas_byte_a_byte(dataset: Path, tmp_path: Path) -> None:
    """La misma semilla en dos directorios distintos produce archivos exactamente iguales."""
    otra = tmp_path / "replica"
    generar_dataset(semilla=SEMILLA_DEFECTO, limite=LIMITE_DEFECTO, salida=otra)
    nombres = sorted(ruta.name for ruta in dataset.iterdir())
    assert nombres == sorted(ruta.name for ruta in otra.iterdir())
    for nombre in nombres:
        assert _sha256(dataset / nombre) == _sha256(otra / nombre)


def test_importes_coherentes_salvo_el_descuadre_inyectado(dataset: Path) -> None:
    """Potencia + energía + impuestos_otros = total en euros, salvo en la anomalía R5."""
    for carga in _cargas(dataset):
        if carga["tipo_anomalia"] == "total_no_cuadra":
            continue
        suma = round(
            float(str(carga["importe_potencia"]))
            + float(str(carga["importe_energia"]))
            + float(str(carga["impuestos_otros"])),
            2,
        )
        assert abs(suma - float(str(carga["importe_total"]))) < 0.005


def test_los_40_cups_de_seed_son_validos() -> None:
    for suministro in suministros_de_ejemplo():
        assert cups_valido(str(suministro["cups"])) is True


def test_los_cups_del_dataset_son_validos_y_de_cartera_salvo_los_inyectados(
    dataset: Path,
) -> None:
    cartera = {str(s["cups"]) for s in suministros_de_ejemplo()}
    for carga in _cargas(dataset):
        cups = str(carga["cups"])
        assert cups_valido(cups) is True
        if carga["tipo_anomalia"] != "cups_fuera_cartera":
            assert cups in cartera


def test_proporcion_exacta_de_anomalias_con_la_semilla_por_defecto(dataset: Path) -> None:
    cargas = _cargas(dataset)
    anomalas = [c for c in cargas if c["tipo_anomalia"] is not None]
    assert len(cargas) == 120
    assert len(anomalas) == 18


def test_presencia_de_las_seis_clases_de_anomalia(dataset: Path) -> None:
    tipos = Counter(
        str(c["tipo_anomalia"]) for c in _cargas(dataset) if c["tipo_anomalia"] is not None
    )
    assert set(tipos) == set(CLASES_ANOMALIA)
    assert set(tipos.values()) == {3}  # reparto equitativo con la semilla por defecto


def test_verdad_esperada_con_forma_de_factura_extraida(dataset: Path) -> None:
    """Cada JSON tiene las claves del esquema más `anomalias_esperadas` y `tipo_anomalia`."""
    reglas_validas = {f"R{i}" for i in range(1, 12)}
    for carga in _cargas(dataset):
        assert set(carga) == set(CLAVES_FACTURA_EXTRAIDA) | set(CLAVES_EXTRA)
        reglas = carga["anomalias_esperadas"]
        assert isinstance(reglas, list)
        assert all(isinstance(regla, str) and regla in reglas_validas for regla in reglas)
        if carga["tipo_anomalia"] is None:
            assert reglas == []
        else:
            assert reglas == [CLASES_ANOMALIA[str(carga["tipo_anomalia"])]]
        assert isinstance(carga["lectura_estimada"], bool)
        assert float(str(carga["confianza"])) == 1.0


def test_los_pdfs_caben_en_los_limites_del_hook(dataset: Path) -> None:
    """Ningún PDF supera los 800 KB del hook y el conjunto no pasa de 5 MB."""
    pdfs = list(dataset.glob("*.pdf"))
    assert len(pdfs) == LIMITE_DEFECTO
    assert all(ruta.stat().st_size < 800 * 1024 for ruta in pdfs)
    assert sum(ruta.stat().st_size for ruta in pdfs) < 5 * 1024 * 1024


def test_la_duplicada_es_el_mismo_documento_que_su_original(dataset: Path) -> None:
    """Una duplicada comparte clave de negocio, periodo y fecha de emisión: es el mismo papel."""
    cargas = _cargas(dataset)
    originales = {
        (str(c["cups"]), str(c["numero_factura"]), str(c["comercializadora"])): c
        for c in cargas
        if c["tipo_anomalia"] != "duplicada"
    }
    duplicadas = [c for c in cargas if c["tipo_anomalia"] == "duplicada"]
    assert len(duplicadas) == 3
    for duplicada in duplicadas:
        clave = (
            str(duplicada["cups"]),
            str(duplicada["numero_factura"]),
            str(duplicada["comercializadora"]),
        )
        original = originales[clave]
        assert duplicada["fecha_inicio"] == original["fecha_inicio"]
        assert duplicada["fecha_fin"] == original["fecha_fin"]
        assert duplicada["fecha_emision"] == original["fecha_emision"]
        assert duplicada["importe_total"] == original["importe_total"]
    # Y son archivos distintos: si compartieran bytes, el hash las haría idempotentes y R3 no
    # podría ver el duplicado.
    pdfs = {
        ruta.stem: hashlib.sha256(ruta.read_bytes()).hexdigest() for ruta in dataset.glob("*.pdf")
    }
    assert pdfs["lum-202605-004"] != pdfs["lum-202605-004-duplicada"]


def test_las_fechas_de_emision_son_plausibles(dataset: Path) -> None:
    """Toda factura se emite entre 2 y 6 días después de cerrar su periodo."""
    for carga in _cargas(dataset):
        fin = date.fromisoformat(str(carga["fecha_fin"]))
        emision = date.fromisoformat(str(carga["fecha_emision"]))
        assert 2 <= (emision - fin).days <= 6, carga["numero_factura"]
