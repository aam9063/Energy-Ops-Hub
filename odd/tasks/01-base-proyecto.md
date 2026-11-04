# 01 · Base del proyecto

## Objetivo

Dejar el repositorio en un estado en el que `docker compose up` levante la API y PostgreSQL, la
validación de CUPS esté testeada y `/health` responda comprobando la base de datos.

## Problema

Sin esta base, ninguna feature posterior se puede implementar ni testear. Es el esqueleto que
las otras doce usan: paquete `app/`, configuración por entorno, modelos y migraciones, imagen
Docker y arnés de tests.

Cita literal de `docs/spec.md`, sección 22:

> | 01 | `01-base-proyecto` | `feat/01-base-proyecto` | pyproject con uv, estructura, config, modelos, Alembic, Docker Compose, Dockerfile, seed, validación de CUPS, `/health` y pre-commit | Medio | `docker compose up` levanta todo; tests de CUPS y de `/health` en verde | |

## Alcance

- **Dentro**: `pyproject.toml` con uv, estructura de `app/` de la sección 6, `config.py`,
  `db.py`, `models.py` con las cinco tablas de la sección 7, Alembic con la migración inicial,
  `domain/cups.py` con sus tests, `main.py` con middleware `X-API-Key` y `/health`,
  `docker-compose.yml`, `Dockerfile`, `.dockerignore`, `.env.example`, `scripts/seed.py`,
  `.pre-commit-config.yaml`.
- **Fuera**: routers de negocio, reglas de anomalías (R1–R11), extracción con LLM, HubSpot,
  n8n, Apps Script y el generador de PDFs. Cada uno tiene su feature.

## Checklist

- [ ] T1 pyproject con uv, estructura de paquetes, ruff/mypy/pytest
- [ ] T2 config con pydantic-settings y `.env.example`
- [ ] T3 validación de CUPS con tests (RED → GREEN)
- [ ] T4 modelos SQLAlchemy, engine/sesión y migración inicial de Alembic
- [ ] T5 FastAPI con middleware `X-API-Key` y `/health` contra la BD, con tests
- [ ] T6 docker-compose, Dockerfile y `.dockerignore`
- [ ] T7 `scripts/seed.py` con clientes y suministros de ejemplo
- [ ] T8 pre-commit con ruff, hooks básicos y gitleaks
- [ ] T9 verificación completa y evidencia
- [ ] T10 RDD del candidato, PR a `dev`, merge y limpieza

## Criterios de aceptación

- `docker compose up` levanta PostgreSQL y la API, y la API aplica las migraciones al arrancar.
- `GET /health` responde `200` con la base de datos accesible y `503` cuando no lo está.
- `cups_valido` acepta CUPS correctos y rechaza letras de control incorrectas, espacios y
  minúsculas (se normalizan antes de validar).
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app` y `uv run pytest -q`
  en verde.
- `.env.example` lista las variables de la sección 18 sin valores.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1: `pyproject.toml` con uv y la estructura de `app/`.

## Git

- Rama: `feat/01-base-proyecto`
- PR: (pendiente)

## Decisiones

- Python 3.12 fijado en `pyproject.toml` con `requires-python = ">=3.12,<3.13"`; el intérprete
  del sistema es 3.14 y uv descarga el 3.12 del proyecto, así que el entorno es reproducible.
- El middleware `X-API-Key` se aplica a toda la API salvo `/health` y `/docs`: la demo necesita
  un sondeo sin credenciales para el smoke test del CD.
- Los modelos usan `TIMESTAMPTZ` con `server_default=func.now()`, igual que la sección 7.

## RDD

- (pendiente)
