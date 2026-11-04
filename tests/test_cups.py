"""Tests de validación de CUPS (docs/spec.md, sección 10).

Los dos CUPS válidos que se usan como referencia son reales y públicos:
ES0031102846140001AK0F y ES0021000000000001RK. Con ellos se fija la tabla de letras
de control, no solo la forma del código.
"""

import pytest
from app.domain.cups import cups_valido, letras_control, normalizar_cups


def test_letras_control_sobre_cups_reales() -> None:
    assert letras_control("0031102846140001") == "AK"
    assert letras_control("0021000000000001") == "RK"


@pytest.mark.parametrize(
    "cups",
    [
        "ES0031102846140001AK0F",  # con sufijo de frontera
        "ES0031102846140001AK",  # 20 caracteres
        "ES0021000000000001RK",
    ],
)
def test_cups_validos(cups: str) -> None:
    assert cups_valido(cups) is True


@pytest.mark.parametrize(
    "cups",
    [
        "es0021000000000001rk",  # minúsculas
        " ES0021 000000000001 RK ",  # espacios y espacios alrededor
        "ES 0031 1028461400 01 AK 0F",
    ],
)
def test_cups_se_normalizan_antes_de_validar(cups: str) -> None:
    assert cups_valido(cups) is True


@pytest.mark.parametrize(
    "cups",
    [
        "",
        "ES0031102846140001AA",  # letras de control incorrectas
        "ES0031102846140001AK0",  # sufijo incompleto
        "ES0031102846140001AKA1",  # sufijo con el orden cambiado
        "ES003110284614000AK",  # faltan dígitos
        "PT0031102846140001AK",  # país distinto de ES
        "ES0031102846140001",  # sin letras de control
    ],
)
def test_cups_invalidos(cups: str) -> None:
    assert cups_valido(cups) is False


def test_normalizar_cups_quita_espacios_y_pasa_a_mayusculas() -> None:
    assert normalizar_cups(" es0021 0000 0000 0001 rk ") == "ES0021000000000001RK"
    assert normalizar_cups("") == ""
    assert normalizar_cups(None) == ""  # type: ignore[arg-type]
