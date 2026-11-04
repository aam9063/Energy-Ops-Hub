"""Cliente de la API de HubSpot (docs/spec.md, sección 12).

Toda la interacción con el CRM vive aquí, tras una interfaz pequeña, para que la
idempotencia —buscar antes de crear— esté en un solo sitio y testeada. El cliente HTTP se
crea de forma perezosa: importar el módulo sin `HUBSPOT_TOKEN` no puede fallar. Los
errores se traducen a `HubSpotError`, que solo contiene el código HTTP, nunca el token.
"""

import time
from datetime import datetime
from typing import Any, Protocol

import httpx

from app.config import settings

BASE_URL = "https://api.hubapi.com"
_INTENTOS = 5
_ESPERA_INICIAL = 1.0


class SuministroAlta(Protocol):
    """Lo que el cliente necesita de un suministro para gestionar su negocio."""

    id: int
    cups: str
    tipo: str
    direccion: str
    hubspot_deal_id: str | None


class AnomaliaTicket(Protocol):
    """Lo que el cliente necesita de una anomalía para gestionar su ticket."""

    id: int
    regla: str
    severidad: str
    detalle: str


class HubSpotError(Exception):
    """Fallo de la API de HubSpot, reintentos agotados o token ausente.

    Es un fallo del proveedor (o de la configuración), no del dato local: la API lo
    traduce a 503 para que n8n reintente. El mensaje lleva el código HTTP y la ruta,
    nunca el token de la app privada.
    """

    def __init__(self, mensaje: str, codigo: int = 0) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class HubSpot:
    """Cliente httpx de HubSpot con reintento y espera exponencial en 429 y 5xx."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        self._http: httpx.Client | None = None

    def _cliente_http(self) -> httpx.Client:
        """Crea el cliente a la primera llamada, no al construir el objeto ni al importar."""
        if self._http is None:
            token = self._token if self._token is not None else settings.hubspot_token
            if not token:
                raise HubSpotError("HUBSPOT_TOKEN no está configurada")
            self._http = httpx.Client(
                base_url=BASE_URL,
                timeout=30,
                headers={"Authorization": f"Bearer {token}"},
            )
        return self._http

    @staticmethod
    def _espera(respuesta: httpx.Response, espera: float) -> float:
        """Segundos a dormir antes del siguiente intento: `Retry-After` si viene."""
        cabecera = respuesta.headers.get("Retry-After")
        if cabecera is not None:
            try:
                return float(cabecera)
            except ValueError:
                pass  # HTTP-date u otro formato raro: vale la espera exponencial
        return espera

    def _req(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        """Petición con reintento en 429 y 5xx; agotados los intentos, `HubSpotError`."""
        espera = _ESPERA_INICIAL
        ultimo: int | None = None
        for intento in range(_INTENTOS):
            respuesta = self._cliente_http().request(method, url, **kw)
            if respuesta.status_code == 429 or respuesta.status_code >= 500:
                ultimo = respuesta.status_code  # temporal: esperar y reintentar
                if intento < _INTENTOS - 1:  # tras el último intento no hay nada que esperar
                    time.sleep(self._espera(respuesta, espera))
                    espera *= 2
                continue
            try:
                respuesta.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HubSpotError(
                    f"HubSpot respondió HTTP {respuesta.status_code} en {method} {url}",
                    codigo=respuesta.status_code,
                ) from exc
            return respuesta.json() if respuesta.content else {}
        raise HubSpotError(
            f"HubSpot no respondió bien tras {_INTENTOS} intentos (último HTTP {ultimo})",
            codigo=ultimo or 0,
        )

    def buscar_uno(self, objeto: str, propiedad: str, valor: str) -> dict[str, Any] | None:
        """Primer objeto que cumple `propiedad == valor`, o None si no hay ninguno."""
        cuerpo = {
            "filterGroups": [
                {"filters": [{"propertyName": propiedad, "operator": "EQ", "value": valor}]}
            ],
            "limit": 1,
        }
        resultado = self._req("POST", f"/crm/v3/objects/{objeto}/search", json=cuerpo)
        encontrados = resultado.get("results") or []
        return encontrados[0] if encontrados else None

    def upsert_deal_alta(self, suministro: SuministroAlta, company_id: str) -> str:
        """Crea el negocio del alta, o lo actualiza si ya existía, y devuelve su id.

        Idempotente por `hubspot_deal_id` guardado en el suministro y por `cups` en
        HubSpot. El negocio existente se actualiza con PATCH sin tocar `dealstage`: la
        fase la mueve el equipo en el CRM (fuente de verdad del estado).
        """
        propiedades: dict[str, Any] = {
            "dealname": f"Alta {suministro.tipo} · {suministro.direccion}",
            "pipeline": settings.hs_pipeline_altas,
            "cups": suministro.cups,
            "tipo_suministro": suministro.tipo,
            "direccion_suministro": suministro.direccion,
            "energy_ops_id": str(suministro.id),
        }
        existente: dict[str, Any] | None = None
        if suministro.hubspot_deal_id:
            existente = {"id": suministro.hubspot_deal_id}
        else:
            existente = self.buscar_uno("deals", "cups", suministro.cups)
        if existente is not None:
            self._req(
                "PATCH",
                f"/crm/v3/objects/deals/{existente['id']}",
                json={"properties": propiedades},
            )
            return str(existente["id"])
        propiedades["dealstage"] = settings.hs_stage_pendiente
        deal = self._req("POST", "/crm/v3/objects/deals", json={"properties": propiedades})
        self._req(
            "PUT",
            f"/crm/v4/objects/deals/{deal['id']}/associations/default/companies/{company_id}",
        )
        return str(deal["id"])

    def crear_ticket_anomalia(
        self, anomalia: AnomaliaTicket, cups: str, company_id: str | None
    ) -> str:
        """Crea el ticket de la anomalía, o devuelve el que ya existía, y da su id.

        Idempotente por `energy_ops_id` (el id de la anomalía en Energy Ops). El ticket
        se asocia a la empresa del cliente si se conoce.
        """
        existente = self.buscar_uno("tickets", "energy_ops_id", str(anomalia.id))
        if existente is not None:
            return str(existente["id"])
        ticket = self._req(
            "POST",
            "/crm/v3/objects/tickets",
            json={
                "properties": {
                    "subject": f"[{anomalia.severidad.upper()}] {anomalia.regla} · {cups}",
                    "content": anomalia.detalle,
                    "hs_pipeline": settings.hs_ticket_pipeline,
                    "hs_pipeline_stage": settings.hs_ticket_stage_nuevo,
                    "cups": cups,
                    "regla_anomalia": anomalia.regla,
                    "energy_ops_id": str(anomalia.id),
                }
            },
        )
        if company_id:
            self._req(
                "PUT",
                f"/crm/v4/objects/tickets/{ticket['id']}/associations/default/companies/"
                f"{company_id}",
            )
        return str(ticket["id"])

    def negocios_modificados_desde(self, desde: datetime | None) -> list[dict[str, Any]]:
        """Negocios modificados desde la marca anterior, paginando hasta el final.

        Filtra por `hs_lastmodifieddate` con GTE (sin filtro la primera sincronización) y
        pide solo las propiedades que la sincronización usa.
        """
        filtros = (
            [
                {
                    "propertyName": "hs_lastmodifieddate",
                    "operator": "GTE",
                    "value": desde.isoformat(),
                }
            ]
            if desde is not None
            else []
        )
        negocios: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            cuerpo: dict[str, Any] = {
                "properties": ["cups", "dealstage", "hs_lastmodifieddate"],
                "limit": 100,
            }
            if filtros:
                cuerpo["filterGroups"] = [{"filters": filtros}]
            if after is not None:
                cuerpo["after"] = after
            pagina = self._req("POST", "/crm/v3/objects/deals/search", json=cuerpo)
            negocios.extend(pagina.get("results") or [])
            after = (pagina.get("paging") or {}).get("next", {}).get("after")
            if not after:
                return negocios


# Cliente compartido, creado de forma perezosa: None hasta la primera llamada real.
_cliente: HubSpot | None = None


def obtener_cliente() -> HubSpot:
    """Devuelve el cliente compartido de HubSpot, creado a la primera llamada."""
    global _cliente
    if _cliente is None:
        _cliente = HubSpot()
    return _cliente
