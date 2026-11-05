"""Estructura de los flujos de n8n exportados a `n8n/` (docs/spec.md, sección 13).

Los flujos viven como JSON de exportación real de n8n. El job `integrations` del CI
valida que sean JSON válido y que no lleven credenciales embebidas; estos tests pican
lo mismo desde pytest, sin red, y además comprueban nodos e identificadores únicos,
conexiones que apuntan a nodos existentes, ausencia de nodos huérfanos, los endpoints
esperados de cada flujo y que la URL de la API salga siempre de variables de n8n.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
DIR_N8N = RAIZ / "n8n"

FLUJOS = {
    "F1_facturas_email": DIR_N8N / "F1_facturas_email.json",
    "F2_altas_paradas": DIR_N8N / "F2_altas_paradas.json",
    "F3_sync_hubspot": DIR_N8N / "F3_sync_hubspot.json",
}

# Igual que el paso "Los flujos de n8n no llevan credenciales embebidas" del job
# `integrations` (.github/workflows/ci.yml): claves con pinta de secreto con valor
# literal de cadena (las expresiones de n8n empiezan por "=" y no son secretos).
PATRON_CLAVE_SECRETA = re.compile(r'"(apikey|api_key|token|password|secret)"\s*:\s*"')
PATRON_VALOR_SECRETO = re.compile(r"^[A-Za-z0-9+/=_.-]{40,}$")


@pytest.fixture(scope="module", params=list(FLUJOS.values()), ids=list(FLUJOS))
def flujo(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Un flujo de n8n exportado, parseado como JSON."""
    ruta: Path = request.param
    assert ruta.exists(), f"Falta el flujo exportado {ruta.name}"
    documento: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    return documento


def _cadenas(valor: Any) -> list[str]:
    """Todas las cadenas de un documento JSON, en cualquier nivel."""
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, dict):
        return [cadena for hijo in valor.values() for cadena in _cadenas(hijo)]
    if isinstance(valor, list):
        return [cadena for hijo in valor for cadena in _cadenas(hijo)]
    return []


def _pares_clave_valor(valor: Any) -> list[tuple[str, Any]]:
    """Todos los pares (clave, valor) de un documento JSON, en cualquier nivel."""
    if isinstance(valor, dict):
        pares = list(valor.items())
        for hijo in valor.values():
            pares.extend(_pares_clave_valor(hijo))
        return pares
    if isinstance(valor, list):
        return [par for hijo in valor for par in _pares_clave_valor(hijo)]
    return []


def _nodos_operativos(flujo: dict[str, Any]) -> list[dict[str, Any]]:
    """Los nodos que forman el flujo, sin contar las notas adhesivas del lienzo."""
    return [nodo for nodo in flujo["nodes"] if nodo["type"] != "n8n-nodes-base.stickyNote"]


def _nombres_conectados(flujo: dict[str, Any]) -> set[str]:
    """Nodos que aparecen en `connections`, como origen o como destino."""
    conectados: set[str] = set()
    for origen, salidas in flujo["connections"].items():
        conectados.add(origen)
        for tipo in salidas.values():
            for rama in tipo:
                for conexion in rama:
                    conectados.add(conexion["node"])
    return conectados


class TestFormatoDeExportacion:
    def test_json_parsea_y_tiene_el_formato_de_exportacion(self, flujo: dict[str, Any]) -> None:
        for clave in ("name", "nodes", "connections", "settings", "pinData", "meta"):
            assert clave in flujo, f"Falta {clave} en la exportación"
        assert flujo["pinData"] == {}

    def test_nodos_con_id_y_name_unicos(self, flujo: dict[str, Any]) -> None:
        nodos = flujo["nodes"]
        assert nodos, "El flujo no tiene nodos"
        ids = [nodo["id"] for nodo in nodos]
        nombres = [nodo["name"] for nodo in nodos]
        assert len(ids) == len(set(ids)), "Hay nodos con `id` repetido"
        assert len(nombres) == len(set(nombres)), "Hay nodos con `name` repetido"
        for nodo in nodos:
            assert nodo["parameters"] is not None, f"{nodo['name']} sin parameters"
            assert nodo["typeVersion"] is not None, f"{nodo['name']} sin typeVersion"
            assert isinstance(nodo["position"], list), f"{nodo['name']} sin position"

    def test_conexiones_apuntan_a_nodos_existentes(self, flujo: dict[str, Any]) -> None:
        nombres = {nodo["name"] for nodo in flujo["nodes"]}
        for origen, salidas in flujo["connections"].items():
            assert origen in nombres, f"La conexión sale de {origen!r}, que no existe"
            for tipo, ramas in salidas.items():
                assert tipo == "main", f"Conexión de tipo inesperado {tipo!r}"
                for rama in ramas:
                    for conexion in rama:
                        destino = conexion["node"]
                        assert destino in nombres, (
                            f"La conexión {origen!r} → {destino!r} apunta a un nodo inexistente"
                        )

    def test_sin_nodos_huerfanos(self, flujo: dict[str, Any]) -> None:
        operativos = {nodo["name"] for nodo in _nodos_operativos(flujo)}
        conectados = _nombres_conectados(flujo)
        huerfanos = operativos - conectados
        assert not huerfanos, f"Nodos sin conexión: {sorted(huerfanos)}"

    def test_sin_credenciales_ni_valores_con_pinta_de_secreto(self, flujo: dict[str, Any]) -> None:
        for clave, _ in _pares_clave_valor(flujo):
            assert clave.lower() != "credentials", "Clave `credentials` embebida en el flujo"
        texto = json.dumps(flujo, ensure_ascii=False)
        assert not PATRON_CLAVE_SECRETA.search(texto), "Clave con pinta de secreto y valor literal"
        for cadena in _cadenas(flujo):
            if " " not in cadena and "\n" not in cadena:
                assert not PATRON_VALOR_SECRETO.match(cadena), (
                    f"Valor con pinta de secreto: {cadena[:16]}…"
                )

    def test_la_url_de_la_api_sale_de_variables_de_n8n(self, flujo: dict[str, Any]) -> None:
        peticiones = [
            nodo for nodo in flujo["nodes"] if nodo["type"] == "n8n-nodes-base.httpRequest"
        ]
        assert peticiones, "El flujo no llama a la API"
        for peticion in peticiones:
            url = peticion["parameters"]["url"]
            assert "$vars" in url, f"{peticion['name']}: la URL debe salir de $vars, no {url[:60]}"
            assert "API_URL" in url, f"{peticion['name']}: la URL debe usar API_URL, no {url[:60]}"
            assert "http://api:8000" in url, (
                f"{peticion['name']}: falta el fallback local para la edición Community, "
                "donde $vars no existe"
            )

    def test_ninguna_url_literal_apunta_fuera_de_la_maquina(self, flujo: dict[str, Any]) -> None:
        for cadena in _cadenas(flujo):
            if "http://" not in cadena and "https://" not in cadena:
                continue
            assert "api:8000" in cadena or "localhost" in cadena, (
                f"URL literal en el flujo: {cadena[:60]}"
            )


class TestEndpointsPorFlujo:
    def test_f1_llama_a_facturas_y_al_ticket_de_anomalias(self) -> None:
        texto = FLUJOS["F1_facturas_email"].read_text(encoding="utf-8")
        assert "/facturas" in texto
        assert "/anomalias/" in texto
        assert "X-API-Key" in texto, "F1 debe autenticarse con X-API-Key"
        assert "$vars.API_URL" in texto

    def test_f1_decide_por_severidad_alta(self) -> None:
        texto = FLUJOS["F1_facturas_email"].read_text(encoding="utf-8")
        assert "severidad" in texto
        assert "'alta'" in texto or '"alta"' in texto

    def test_f2_consulta_altas_paradas_7_dias(self) -> None:
        texto = FLUJOS["F2_altas_paradas"].read_text(encoding="utf-8")
        assert "/altas?parada_dias=7" in texto
        assert "$vars.API_URL" in texto

    def test_f2_programa_dias_laborables_a_las_830(self) -> None:
        texto = FLUJOS["F2_altas_paradas"].read_text(encoding="utf-8")
        assert "30 8 * * 1-5" in texto

    def test_f2_agrupa_por_cliente_con_nodo_code(self) -> None:
        flujo = json.loads(FLUJOS["F2_altas_paradas"].read_text(encoding="utf-8"))
        codes = [n for n in flujo["nodes"] if n["type"] == "n8n-nodes-base.code"]
        assert len(codes) == 1, "F2 debe tener exactamente un nodo Code"
        codigo = codes[0]["parameters"]["jsCode"]
        assert "cliente" in codigo, "El Code debe agrupar por cliente"

    def test_f2_termina_solo_cuando_no_hay_altas_paradas(self) -> None:
        """Sin condicional: el Code emite cero ítems y el correo no corre (2026-11-05).

        El If usaba `$items('Consultar altas paradas').first().json.cups`, que devolvía vacío
        en n8n 2.46: el flujo se cortaba en silencio aunque hubiera altas paradas de 87 días.
        """
        flujo = json.loads(FLUJOS["F2_altas_paradas"].read_text(encoding="utf-8"))
        condicionales = [n for n in flujo["nodes"] if n["type"].endswith(".if")]
        assert not condicionales, (
            "F2 no necesita condicional: el Code corta el flujo cuando la lista viene vacía"
        )
        codigo = next(n for n in flujo["nodes"] if n["type"].endswith(".code"))["parameters"][
            "jsCode"
        ]
        assert "if (!items.length) return [];" in codigo, (
            "El Code debe terminar sin items cuando no hay altas paradas"
        )

    def test_ningun_flujo_usa_el_accesor_fragil_items(self) -> None:
        """`$items('nodo')` no es fiable: cortó F2 en silencio. Usar `$('nodo')` o el Code."""
        for ruta in FLUJOS.values():
            assert "$items(" not in ruta.read_text(encoding="utf-8"), (
                f"{ruta.name} usa $items(), que devolvió vacío en n8n 2.46"
            )

    def test_f3_sincroniza_hubspot_cada_15_minutos(self) -> None:
        texto = FLUJOS["F3_sync_hubspot"].read_text(encoding="utf-8")
        assert "/sync/hubspot" in texto
        assert "*/15 * * * *" in texto

    @pytest.mark.parametrize(
        ("clave", "tipo", "fragmento"),
        [
            ("F1_facturas_email", "gmailTrigger", "gmail"),
            ("F2_altas_paradas", "scheduleTrigger", "schedule"),
            ("F3_sync_hubspot", "scheduleTrigger", "schedule"),
            ("F1_facturas_email", "code", "code"),
            ("F1_facturas_email", "gmail", "gmail"),
            ("F2_altas_paradas", "gmail", "gmail"),
            ("F3_sync_hubspot", "gmail", "gmail"),
        ],
    )
    def test_tipos_de_nodo_esperados(self, clave: str, tipo: str, fragmento: str) -> None:
        flujo = json.loads(FLUJOS[clave].read_text(encoding="utf-8"))
        tipos = [nodo["type"] for nodo in flujo["nodes"]]
        assert any(tipo in t for t in tipos), f"{clave} no tiene ningún nodo {tipo!r}"


class TestAdjuntosDeF1:
    """El trigger de Gmail entrega binarios, no un array `attachments` (2026-11-05).

    Con `downloadAttachments`, n8n 2.46.6 escribe cada adjunto en una propiedad binaria
    (`attachment_0`, `attachment_1`, …) y **no** crea un campo `attachments` en el JSON. El
    flujo original filtraba y dividía por ese campo, así que reventaba en el segundo nodo con
    cualquier correo, y el POST habría dado 422 por mandar `fichero` donde la API espera
    `archivo`. Estos tres tests pinan la forma real y el contrato del endpoint.
    """

    @staticmethod
    def _flujo() -> dict[str, Any]:
        documento: dict[str, Any] = json.loads(
            FLUJOS["F1_facturas_email"].read_text(encoding="utf-8")
        )
        return documento

    def test_el_filtro_mira_los_binarios_y_no_un_campo_attachments(self) -> None:
        texto = json.dumps(self._flujo(), ensure_ascii=False)
        assert "$json.attachments" not in texto, (
            "F1 vuelve a leer `attachments`, que el trigger de Gmail no entrega"
        )
        ifs = [n for n in self._flujo()["nodes"] if n["type"].endswith(".if")]
        assert ifs, "F1 perdió el nodo condicional"
        condicion = ifs[0]["parameters"]["conditions"]["conditions"][0]["leftValue"]
        assert "$binary" in condicion, f"El If debe mirar el binario, no {condicion!r}"

    def test_el_archivo_viaja_en_el_campo_que_espera_la_api(self) -> None:
        """El endpoint declara `archivo: UploadFile = File(...)`: otro nombre da 422."""
        for nodo in self._flujo()["nodes"]:
            if not nodo["type"].endswith("httpRequest"):
                continue
            if not str(nodo["parameters"].get("url", "")).endswith("/facturas"):
                continue
            parametros = nodo["parameters"]["bodyParameters"]["parameters"]
            binarios = [p for p in parametros if p.get("parameterType") == "formBinaryData"]
            assert binarios, f"{nodo['name']} no manda ningún archivo"
            assert binarios[0]["name"] == "archivo", (
                f"{nodo['name']} manda el archivo como {binarios[0]['name']!r}; "
                "la API espera 'archivo'"
            )
            return
        raise AssertionError("F1 no tiene el nodo que sube la factura")

    def test_el_trigger_descarga_los_adjuntos_donde_n8n_los_lee(self) -> None:
        """`downloadAttachments` va dentro de `options`; en la raíz n8n lo ignora."""
        triggers = [n for n in self._flujo()["nodes"] if n["type"].endswith("gmailTrigger")]
        assert triggers, "F1 perdió el trigger de Gmail"
        parametros = triggers[0]["parameters"]
        assert "downloadAttachments" not in parametros, (
            "`downloadAttachments` en la raíz de parameters no lo lee n8n: va dentro de `options`"
        )
        assert parametros["options"].get("downloadAttachments") is True, (
            "Sin `options.downloadAttachments` el trigger no descarga el adjunto "
            "y el If no ve binario"
        )

    def test_el_correo_se_marca_leido_despues_del_post(self) -> None:
        """n8n advierte que sin `markAsRead` el mismo correo puede reprocesarse.

        El trigger deduplica por `lastTimeChecked`, pero los datos estáticos se pierden al
        resetear un flujo: el paso es lo que garantiza que cada correo se trate una vez.
        """
        flujo = self._flujo()
        leidos = [n for n in flujo["nodes"] if n["parameters"].get("operation") == "markAsRead"]
        assert leidos, "F1 no marca el correo como leído después de procesarlo"
        leido = leidos[0]
        assert "Recibir emails con facturas" in leido["parameters"]["messageId"], (
            "El mensaje a marcar debe ser el del trigger"
        )
        origen = [
            nombre
            for nombre, salidas in flujo["connections"].items()
            if any(
                conexion["node"] == leido["name"] for rama in salidas["main"] for conexion in rama
            )
        ]
        assert any(
            "/facturas" in str(n["parameters"].get("url", ""))
            for n in flujo["nodes"]
            if n["name"] in origen
        ), f"El correo debe marcarse después del POST, no antes: viene de {origen}"
        assert leido.get("onError") == "continueRegularOutput", (
            "Un fallo al marcar no puede tumbar la ingesta: la API es idempotente"
        )

    def test_el_nodo_code_entrega_el_binario_como_data(self) -> None:
        codigo = None
        for nodo in self._flujo()["nodes"]:
            if nodo["type"].endswith(".code"):
                codigo = nodo["parameters"]["jsCode"]
        assert codigo, "F1 perdió el nodo Code que separa los adjuntos"
        assert "binary" in codigo, "El Code debe emitir el binario de cada adjunto"
        assert "data" in codigo, "El Code debe renombrar el binario a `data`, que lee el POST"
        for nodo in self._flujo()["nodes"]:
            for parametro in nodo["parameters"].get("bodyParameters", {}).get("parameters", []):
                if parametro.get("parameterType") == "formBinaryData":
                    assert parametro["inputDataFieldName"] == "data", (
                        "El POST debe leer la propiedad binaria que produce el Code"
                    )


@pytest.mark.parametrize("ruta", FLUJOS.values(), ids=lambda p: p.name)
def test_los_nodos_http_reintentan_y_avisan_del_fallo(ruta: Path) -> None:
    """Un fallo de red no puede detener el flujo en silencio (hallazgo R4 del RDD de la 09).

    Cada nodo HTTP reintenta, y cuando se agotan los intentos entrega el ítem por su salida de
    error, que tiene que estar conectada a un nodo existente (el aviso al responsable).
    """
    flujo = json.loads(ruta.read_text(encoding="utf-8"))
    nombres = {nodo["name"] for nodo in flujo["nodes"]}
    http = [nodo for nodo in flujo["nodes"] if nodo["type"].endswith("httpRequest")]
    assert http, f"{ruta.name} no tiene ningún nodo HTTP"

    for nodo in http:
        assert nodo.get("retryOnFail") is True, f"{nodo['name']} no reintenta"
        assert int(nodo.get("maxTries", 0)) >= 2, f"{nodo['name']} reintenta demasiado poco"
        assert nodo.get("onError") == "continueErrorOutput", (
            f"{nodo['name']} corta el flujo al fallar"
        )
        salidas = flujo["connections"][nodo["name"]]["main"]
        assert len(salidas) >= 2, f"{nodo['name']} no declara salida de error"
        assert salidas[1], f"{nodo['name']} no tiene rama de error conectada"
        for conexion in salidas[1]:
            assert conexion["node"] in nombres
