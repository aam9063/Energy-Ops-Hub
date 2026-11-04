"""Tests unitarios de las reglas de anomalías (docs/spec.md, sección 10).

Las reglas son funciones puras: ningún test toca la base de datos ni la red. Cada regla
tiene un caso que la dispara y otro que no, más los bordes que fija la especificación:
la tolerancia de 0,05 € de R5 y los conceptos faltantes, el histórico mínimo de R6, R7 sin
anterior, la frontera entre R3 (misma clave) y R4 (solape con clave distinta), el ±40 % de
R9 justo en el borde y los 59/61 días de R10.
"""

from datetime import date, timedelta
from typing import Any

from app.domain.cups import letras_control
from app.domain.rules import (
    ContextoReglas,
    FacturaDatos,
    SuministroDatos,
    evaluar,
    r1_cups_invalido,
    r2_cups_fuera_de_cartera,
    r3_factura_duplicada,
    r4_periodo_solapado,
    r5_total_no_cuadra,
    r6_consumo_atipico,
    r7_lecturas_estimadas_seguidas,
    r8_potencia_distinta,
    r9_precio_fuera_de_rango,
    r10_suministro_sin_facturar,
    r11_revision_extraccion,
)

_DIGITOS = "0123456789012345"
CUPS_VALIDO = "ES" + _DIGITOS + letras_control(_DIGITOS)
CUPS_INVALIDO = "ES" + _DIGITOS + "XY"


def _factura(**extra: Any) -> FacturaDatos:
    """Factura limpia y cuadrada: es la base de los casos que no disparan."""
    valores: dict[str, Any] = {
        "id": 1,
        "cups_leido": CUPS_VALIDO,
        "numero": "F-001",
        "comercializadora": "Voltia",
        "fecha_inicio": date(2026, 2, 1),
        "fecha_fin": date(2026, 2, 28),
        "potencia_kw": 5.5,
        "consumo_kwh": 320.5,
        "importe_potencia": 30.25,
        "importe_energia": 45.1,
        "impuestos_otros": 15.87,
        "importe_total": 91.22,
        "lectura_estimada": False,
        "confianza": 0.95,
        "campos_dudosos": [],
        "archivo_hash": "hash-actual",
    }
    valores.update(extra)
    return FacturaDatos(**valores)


def _suministro(**extra: Any) -> SuministroDatos:
    """Suministro en cartera, activo y con la misma potencia que la factura base."""
    valores: dict[str, Any] = {
        "cups": CUPS_VALIDO,
        "estado": "activo",
        "potencia_kw": 5.5,
        "tarifa_acceso": "2.0TD",
    }
    valores.update(extra)
    return SuministroDatos(**valores)


def _contexto(**extra: Any) -> ContextoReglas:
    """Contexto neutro: en cartera, sin histórico y con mediana de 0,15 €/kWh.

    Con esa mediana, el precio de la factura base (45,10 € / 320,5 kWh ≈ 0,1407 €/kWh)
    cae dentro del rango ±40 % y R9 no dispara.
    """
    valores: dict[str, Any] = {
        "suministro": _suministro(),
        "historico": [],
        "mismo_cups": [],
        "mediana_precio_kwh": 0.15,
    }
    valores.update(extra)
    return ContextoReglas(**valores)


def _meses_historico(cuantas: int, consumo: float = 300.0) -> list[FacturaDatos]:
    """Facturas de 30 días con consumo diario de 10 kWh, una por mes hacia atrás."""
    meses = [
        (date(2025, 11, 1), date(2025, 11, 30)),
        (date(2025, 12, 1), date(2025, 12, 30)),
        (date(2026, 1, 1), date(2026, 1, 30)),
        (date(2025, 10, 1), date(2025, 10, 30)),
        (date(2025, 9, 1), date(2025, 9, 30)),
        (date(2025, 8, 1), date(2025, 8, 30)),
    ]
    return [
        _factura(
            id=i + 10,
            numero=f"F-2{i:02d}",
            archivo_hash=f"hash-hist-{i}",
            fecha_inicio=inicio,
            fecha_fin=fin,
            consumo_kwh=consumo,
        )
        for i, (inicio, fin) in enumerate(meses[:cuantas])
    ]


# R1 · CUPS inválido ------------------------------------------------------------


def test_r1_dispara_con_cups_invalido() -> None:
    anomalia = r1_cups_invalido(_factura(cups_leido=CUPS_INVALIDO), _contexto())

    assert anomalia is not None
    assert anomalia.regla == "R1"
    assert anomalia.severidad == "alta"
    assert CUPS_INVALIDO in anomalia.detalle


def test_r1_no_dispara_con_cups_valido() -> None:
    assert r1_cups_invalido(_factura(), _contexto()) is None


# R2 · CUPS fuera de cartera ----------------------------------------------------


def test_r2_dispara_cuando_el_cups_no_esta_en_cartera() -> None:
    anomalia = r2_cups_fuera_de_cartera(_factura(), _contexto(suministro=None))

    assert anomalia is not None
    assert anomalia.regla == "R2"
    assert anomalia.severidad == "media"
    assert CUPS_VALIDO in anomalia.detalle


def test_r2_no_dispara_con_suministro_en_cartera() -> None:
    assert r2_cups_fuera_de_cartera(_factura(), _contexto()) is None


# R3 · Factura duplicada --------------------------------------------------------


def test_r3_dispara_con_misma_clave_y_distinto_archivo() -> None:
    duplicada = _factura(id=2, archivo_hash="hash-otro-pdf")
    anomalia = r3_factura_duplicada(_factura(), _contexto(mismo_cups=[duplicada]))

    assert anomalia is not None
    assert anomalia.regla == "R3"
    assert anomalia.severidad == "alta"
    assert "F-001" in anomalia.detalle


def test_r3_no_dispara_con_el_mismo_archivo() -> None:
    misma = _factura(id=2, archivo_hash="hash-actual")
    assert r3_factura_duplicada(_factura(), _contexto(mismo_cups=[misma])) is None


# R4 · Periodo solapado ---------------------------------------------------------


def test_r4_dispara_con_clave_distinta_y_solape() -> None:
    solapada = _factura(
        id=2,
        numero="F-002",
        archivo_hash="hash-solape",
        fecha_inicio=date(2026, 2, 10),
        fecha_fin=date(2026, 3, 5),
    )
    anomalia = r4_periodo_solapado(_factura(), _contexto(mismo_cups=[solapada]))

    assert anomalia is not None
    assert anomalia.regla == "R4"
    assert anomalia.severidad == "alta"
    assert "F-002" in anomalia.detalle


def test_r4_no_dispara_sin_solape() -> None:
    posterior = _factura(
        id=2,
        numero="F-002",
        archivo_hash="hash-posterior",
        fecha_inicio=date(2026, 3, 1),
        fecha_fin=date(2026, 3, 31),
    )
    assert r4_periodo_solapado(_factura(), _contexto(mismo_cups=[posterior])) is None


# R3 frente a R4: la misma clave nunca es un solape -----------------------------


def test_r3_y_r4_no_se_confunden_con_misma_clave_y_solape() -> None:
    duplicada = _factura(
        id=2,
        archivo_hash="hash-otro-pdf",
        fecha_inicio=date(2026, 2, 10),
        fecha_fin=date(2026, 3, 5),
    )
    contexto = _contexto(mismo_cups=[duplicada])

    assert r3_factura_duplicada(_factura(), contexto) is not None
    assert r4_periodo_solapado(_factura(), contexto) is None


# R5 · El total no cuadra -------------------------------------------------------


def test_r5_dispara_cuando_el_total_no_cuadra() -> None:
    anomalia = r5_total_no_cuadra(_factura(importe_total=95.0), _contexto())

    assert anomalia is not None
    assert anomalia.regla == "R5"
    assert anomalia.severidad == "alta"
    assert "91.22" in anomalia.detalle
    assert "95.00" in anomalia.detalle


def test_r5_no_dispara_en_el_borde_de_0_05_euros() -> None:
    # 91,22 € de conceptos frente a 91,27 € de total: desviación exactamente 0,05 €.
    assert r5_total_no_cuadra(_factura(importe_total=91.27), _contexto()) is None


def test_r5_no_dispara_con_concepto_faltante() -> None:
    # Sin importe de energía no se puede comprobar: lo cubre R11, no R5.
    factura = _factura(importe_energia=None)
    assert r5_total_no_cuadra(factura, _contexto()) is None


# R6 · Consumo atípico ----------------------------------------------------------


def test_r6_dispara_con_consumo_diario_el_doble() -> None:
    # Histórico de 3 facturas a 10 kWh/día; la actual 630 kWh en 28 días ≈ 22,5 kWh/día.
    anomalia = r6_consumo_atipico(
        _factura(consumo_kwh=630.0), _contexto(historico=_meses_historico(3))
    )

    assert anomalia is not None
    assert anomalia.regla == "R6"
    assert anomalia.severidad == "media"


def test_r6_no_dispara_con_consumo_dentro_del_rango() -> None:
    # 320,5 kWh en 28 días ≈ 11,45 kWh/día, entre 0,3× y 2× los 10 kWh/día del histórico.
    assert r6_consumo_atipico(_factura(), _contexto(historico=_meses_historico(3))) is None


def test_r6_no_dispara_con_menos_de_3_facturas_de_historico() -> None:
    anomalia = r6_consumo_atipico(
        _factura(consumo_kwh=630.0), _contexto(historico=_meses_historico(2))
    )

    assert anomalia is None


# R7 · Lecturas estimadas seguidas ----------------------------------------------


def test_r7_dispara_con_dos_estimadas_seguidas() -> None:
    anterior = _factura(id=2, numero="F-100", archivo_hash="hash-100", lectura_estimada=True)
    anomalia = r7_lecturas_estimadas_seguidas(
        _factura(lectura_estimada=True), _contexto(historico=[anterior])
    )

    assert anomalia is not None
    assert anomalia.regla == "R7"
    assert anomalia.severidad == "media"


def test_r7_no_dispara_si_la_anterior_es_real() -> None:
    anterior = _factura(id=2, numero="F-100", archivo_hash="hash-100", lectura_estimada=False)
    anomalia = r7_lecturas_estimadas_seguidas(
        _factura(lectura_estimada=True), _contexto(historico=[anterior])
    )

    assert anomalia is None


def test_r7_no_dispara_sin_factura_anterior() -> None:
    anomalia = r7_lecturas_estimadas_seguidas(
        _factura(lectura_estimada=True), _contexto(historico=[])
    )

    assert anomalia is None


# R8 · Potencia distinta de la contratada ----------------------------------------


def test_r8_dispara_con_potencia_distinta_de_la_contratada() -> None:
    contexto = _contexto(suministro=_suministro(potencia_kw=7.5))
    anomalia = r8_potencia_distinta(_factura(), contexto)

    assert anomalia is not None
    assert anomalia.regla == "R8"
    assert anomalia.severidad == "media"
    assert "7.50" in anomalia.detalle


def test_r8_no_dispara_dentro_de_la_tolerancia() -> None:
    # 5,51 kW facturados frente a 5,50 kW contratados: diferencia de 0,01 kW, dentro.
    contexto = _contexto(suministro=_suministro(potencia_kw=5.51))
    assert r8_potencia_distinta(_factura(), contexto) is None


def test_r8_no_dispara_sin_suministro() -> None:
    assert r8_potencia_distinta(_factura(), _contexto(suministro=None)) is None


def test_r8_no_dispara_sin_potencia_facturada() -> None:
    assert r8_potencia_distinta(_factura(potencia_kw=None), _contexto()) is None


# R9 · Precio fuera de rango -----------------------------------------------------


def test_r9_dispara_por_encima_del_rango() -> None:
    # 90 € / 300 kWh = 0,30 €/kWh, muy por encima de 0,15 × 1,4 = 0,21.
    anomalia = r9_precio_fuera_de_rango(
        _factura(importe_energia=90.0, consumo_kwh=300.0), _contexto()
    )

    assert anomalia is not None
    assert anomalia.regla == "R9"
    assert anomalia.severidad == "baja"


def test_r9_dispara_por_debajo_del_rango() -> None:
    # 12 € / 300 kWh = 0,04 €/kWh, muy por debajo de 0,15 × 0,6 = 0,09.
    anomalia = r9_precio_fuera_de_rango(
        _factura(importe_energia=12.0, consumo_kwh=300.0), _contexto()
    )

    assert anomalia is not None
    assert anomalia.regla == "R9"


def test_r9_no_dispara_en_el_borde_superior_del_40_por_ciento() -> None:
    # 63 € / 300 kWh = 0,21 €/kWh, exactamente el límite superior (0,15 × 1,4).
    anomalia = r9_precio_fuera_de_rango(
        _factura(importe_energia=63.0, consumo_kwh=300.0), _contexto()
    )

    assert anomalia is None


def test_r9_no_dispara_en_el_borde_inferior_del_40_por_ciento() -> None:
    # 27 € / 300 kWh = 0,09 €/kWh, exactamente el límite inferior (0,15 × 0,6).
    anomalia = r9_precio_fuera_de_rango(
        _factura(importe_energia=27.0, consumo_kwh=300.0), _contexto()
    )

    assert anomalia is None


def test_r9_no_dispara_sin_mediana_de_cartera() -> None:
    anomalia = r9_precio_fuera_de_rango(
        _factura(importe_energia=90.0, consumo_kwh=300.0),
        _contexto(mediana_precio_kwh=None),
    )

    assert anomalia is None


def test_r9_no_dispara_sin_importe_de_energia() -> None:
    anomalia = r9_precio_fuera_de_rango(_factura(importe_energia=None), _contexto())

    assert anomalia is None


# R10 · Suministro sin facturar ---------------------------------------------------


def test_r10_dispara_con_61_dias_sin_facturar() -> None:
    ultima = _factura(fecha_fin=date.today() - timedelta(days=61))
    anomalia = r10_suministro_sin_facturar(_suministro(), ultima)

    assert anomalia is not None
    assert anomalia.regla == "R10"
    assert anomalia.severidad == "media"
    assert "61" in anomalia.detalle


def test_r10_no_dispara_con_59_dias_sin_facturar() -> None:
    ultima = _factura(fecha_fin=date.today() - timedelta(days=59))
    assert r10_suministro_sin_facturar(_suministro(), ultima) is None


def test_r10_dispara_sin_ninguna_factura_registrada() -> None:
    anomalia = r10_suministro_sin_facturar(_suministro(), None)

    assert anomalia is not None
    assert anomalia.regla == "R10"


def test_r10_no_dispara_si_el_suministro_no_esta_activo() -> None:
    anomalia = r10_suministro_sin_facturar(_suministro(estado="baja"), None)

    assert anomalia is None


# R11 · Revisión de extracción -----------------------------------------------------


def test_r11_dispara_con_confianza_baja_y_campos_dudosos() -> None:
    anomalia = r11_revision_extraccion(
        _factura(confianza=0.5, campos_dudosos=["importe_total"]), _contexto()
    )

    assert anomalia is not None
    assert anomalia.regla == "R11"
    assert anomalia.severidad == "media"
    assert "confianza 0.50" in anomalia.detalle
    assert "importe_total" in anomalia.detalle


def test_r11_no_dispara_con_extraccion_limpia() -> None:
    assert r11_revision_extraccion(_factura(), _contexto()) is None


def test_r11_dispara_solo_con_campos_dudosos() -> None:
    anomalia = r11_revision_extraccion(
        _factura(confianza=0.95, campos_dudosos=["potencia_kw"]), _contexto()
    )

    assert anomalia is not None
    assert anomalia.regla == "R11"


# Evaluación conjunta --------------------------------------------------------------


def test_evaluar_devuelve_varias_anomalias_para_una_factura_mala() -> None:
    factura = _factura(
        cups_leido=CUPS_INVALIDO,
        importe_total=999.0,
        confianza=0.4,
        campos_dudosos=["importe_total"],
    )
    reglas = {a.regla for a in evaluar(factura, _contexto(suministro=None))}

    assert reglas == {"R1", "R2", "R5", "R11"}


def test_evaluar_devuelve_vacio_con_una_factura_limpia() -> None:
    assert evaluar(_factura(), _contexto()) == []
