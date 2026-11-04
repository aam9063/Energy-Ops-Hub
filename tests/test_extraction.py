"""Tests de la extracción con LLM (docs/spec.md, sección 17).

Todo sin red: el cliente de OpenAI se sustituye por un doble que devuelve respuestas
preparadas. Cubren la respuesta válida, la que no cumple el esquema (→ `ExtraccionInvalida`),
los metadatos de tokens, la protección frente a inyección de prompt y la creación perezosa
del cliente. Los PDFs son reales, generados con reportlab, para pasar por pdfplumber.
"""

import io
from types import SimpleNamespace
from typing import Any

import pytest
from app.config import settings
from app.schemas import FacturaExtraida
from app.services import extraction
from openai import OpenAIError
from pydantic import ValidationError
from reportlab.pdfgen.canvas import Canvas


def _pdf_bytes() -> bytes:
    """Un PDF mínimo pero válido: pdfplumber debe poder leerlo."""
    buffer = io.BytesIO()
    lienzo = Canvas(buffer)
    lienzo.drawString(72, 750, "Factura de prueba")
    lienzo.save()
    return buffer.getvalue()


PDF_BYTES = _pdf_bytes()


def _pdf_roto() -> bytes:
    """Bytes con firma de PDF pero contenido inservible para pdfplumber."""
    return b"%PDF-1.4 esto no es un pdf valido"


class _ResponsesFalsas:
    """Doble de `client.responses`: guarda los kwargs y devuelve lo preparado."""

    def __init__(self, respuesta: Any = None, error: Exception | None = None) -> None:
        self._respuesta = respuesta
        self._error = error
        self.kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._respuesta


class _ClienteFalso:
    """Doble de `openai.OpenAI`: solo implementa `responses.parse`."""

    def __init__(self, respuesta: Any = None, error: Exception | None = None) -> None:
        self.responses = _ResponsesFalsas(respuesta, error)


def _respuesta_valida(
    datos: FacturaExtraida | None = None,
    modelo: str = "gpt-4o-mini-test",
    tokens: tuple[int, int] = (1200, 180),
) -> SimpleNamespace:
    if datos is None:
        datos = _datos()
    return SimpleNamespace(
        output_parsed=datos,
        model=modelo,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


def _datos(**extra: Any) -> FacturaExtraida:
    valores: dict[str, Any] = {
        "cups": "ES0123456789012345ZX",
        "numero_factura": "F-2026-041",
        "comercializadora": "Voltia Energía",
        "fecha_emision": "2026-03-01",
        "fecha_inicio": "2026-02-01",
        "fecha_fin": "2026-02-28",
        "potencia_kw": 5.5,
        "consumo_kwh": 320.5,
        "importe_potencia": 30.25,
        "importe_energia": 45.1,
        "impuestos_otros": 15.87,
        "importe_total": 91.22,
        "lectura_estimada": False,
        "confianza": 0.95,
        "campos_dudosos": [],
    }
    valores.update(extra)
    return FacturaExtraida(**valores)


def _error_validacion() -> ValidationError:
    """Un ValidationError real de Pydantic, como el que lanza el SDK con salida inválida."""
    try:
        FacturaExtraida.model_validate({"cups": "ES0123456789012345ZX"})
    except ValidationError as exc:
        return exc
    raise AssertionError("El esquema debía rechazar una salida sin campos obligatorios")


def _instalar_cliente(monkeypatch: pytest.MonkeyPatch, cliente: _ClienteFalso) -> None:
    """Sustituye el cliente perezoso por el doble, sin tocar la red."""
    monkeypatch.setattr(extraction, "_obtener_cliente", lambda: cliente)


def test_respuesta_valida_devuelve_datos_y_metadatos(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(respuesta=_respuesta_valida())
    _instalar_cliente(monkeypatch, cliente)

    datos, meta = extraction.extraer_factura(PDF_BYTES)

    assert isinstance(datos, FacturaExtraida)
    assert datos.numero_factura == "F-2026-041"
    assert datos.confianza == 0.95
    assert meta["modelo"] == "gpt-4o-mini-test"
    assert meta["tokens_entrada"] == 1200
    assert meta["tokens_salida"] == 180


def test_pdf_viaja_como_input_file_en_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    cliente = _ClienteFalso(respuesta=_respuesta_valida())
    _instalar_cliente(monkeypatch, cliente)

    extraction.extraer_factura(PDF_BYTES)

    contenido = cliente.responses.kwargs["input"][0]["content"]
    fichero = next(b for b in contenido if b["type"] == "input_file")
    assert fichero["filename"] == "factura.pdf"
    esperado = "data:application/pdf;base64," + base64.standard_b64encode(PDF_BYTES).decode()
    assert fichero["file_data"] == esperado


def test_el_prompt_trata_el_documento_como_dato(monkeypatch: pytest.MonkeyPatch) -> None:
    """El prompt va junto al PDF y prohíbe seguir instrucciones del documento."""
    cliente = _ClienteFalso(respuesta=_respuesta_valida())
    _instalar_cliente(monkeypatch, cliente)

    extraction.extraer_factura(PDF_BYTES)

    assert cliente.responses.kwargs["text_format"] is FacturaExtraida
    contenido = cliente.responses.kwargs["input"][0]["content"]
    textos = [b["text"] for b in contenido if b["type"] == "input_text"]
    assert any("no una instrucción" in t for t in textos)
    assert any("inyección de prompt" in t for t in textos)
    assert any("No inventes ni calcules" in t for t in textos)


def test_salida_que_no_cumple_esquema_lanza_extraccion_invalida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _ClienteFalso(error=_error_validacion())
    _instalar_cliente(monkeypatch, cliente)

    with pytest.raises(extraction.ExtraccionInvalida):
        extraction.extraer_factura(PDF_BYTES)


def test_respuesta_sin_datos_estructurados_lanza_extraccion_invalida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el modelo se niega, el SDK devuelve `output_parsed=None`: error controlado."""
    respuesta = _respuesta_valida()
    respuesta.output_parsed = None
    cliente = _ClienteFalso(respuesta=respuesta)
    _instalar_cliente(monkeypatch, cliente)

    with pytest.raises(extraction.ExtraccionInvalida):
        extraction.extraer_factura(PDF_BYTES)


def test_pdf_ilegible_lanza_extraccion_invalida(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso(respuesta=_respuesta_valida())
    _instalar_cliente(monkeypatch, cliente)

    with pytest.raises(extraction.ExtraccionInvalida, match="No se ha podido leer"):
        extraction.extraer_factura(_pdf_roto())


def test_importar_no_crea_cliente_y_sin_api_key_falla_solo_al_usar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El módulo se importa sin `OPENAI_API_KEY`; el fallo llega al crear el cliente."""
    monkeypatch.setattr(extraction, "_cliente", None)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert extraction._cliente is None

    with pytest.raises(OpenAIError):  # el SDK pide la clave al crear el cliente, no antes
        extraction._obtener_cliente()


def test_un_periodo_invertido_es_una_extraccion_invalida() -> None:
    """`fecha_fin < fecha_inicio` no puede llegar a la base de datos como un 500."""
    datos = {
        "cups": "ES0021000000000001RK",
        "numero_factura": "F-1",
        "comercializadora": "Voltia Energía",
        "fecha_inicio": "2026-02-01",
        "fecha_fin": "2026-01-01",
        "consumo_kwh": 100.0,
        "importe_total": 30.0,
        "lectura_estimada": False,
        "confianza": 0.9,
    }

    with pytest.raises(ValidationError):
        FacturaExtraida.model_validate(datos)
