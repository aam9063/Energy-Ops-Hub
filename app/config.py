"""Configuración de la aplicación, solo por variables de entorno (docs/spec.md, sección 18)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes cargados de `.env` y del entorno. Sin valores por defecto para secretos."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Base de datos. El contenedor de la API habla con el servicio `db`; en local, localhost.
    database_url: str = "postgresql+psycopg://ops:ops@localhost:5432/energy_ops"

    # Autenticación de la demo: cabecera X-API-Key. Vacío = API abierta (solo en local).
    api_key: str = ""

    # Extracción con LLM (feature 04). Proveedor OpenAI con Structured Outputs.
    openai_api_key: str = ""
    openai_model: str = ""

    # HubSpot (feature 07)
    hubspot_token: str = ""
    hs_pipeline_altas: str = ""
    hs_stage_pendiente: str = ""
    hs_ticket_pipeline: str = ""
    hs_ticket_stage_nuevo: str = ""
    # Fase de negocio en HubSpot → estado de suministro, escrita como JSON (p. ej.
    # HS_MAPA_ESTADOS='{"pendiente-doc":"pendiente","en-tramite":"en_tramite"}').
    hs_mapa_estados: dict[str, str] = {}

    # n8n
    n8n_encryption_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuración cacheada de este proceso."""
    return Settings()


settings = get_settings()
