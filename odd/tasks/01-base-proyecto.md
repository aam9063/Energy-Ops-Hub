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

- [x] T1 pyproject con uv, estructura de paquetes, ruff/mypy/pytest
- [x] T2 config con pydantic-settings y `.env.example`
- [x] T3 validación de CUPS con tests (RED → GREEN)
- [x] T4 modelos SQLAlchemy, engine/sesión y migración inicial de Alembic
- [x] T5 FastAPI con middleware `X-API-Key` y `/health` contra la BD, con tests
- [x] T6 docker-compose, Dockerfile y `.dockerignore`
- [x] T7 `scripts/seed.py` con clientes y suministros de ejemplo
- [x] T8 pre-commit con ruff, hooks básicos y gitleaks
- [x] T9 verificación completa y evidencia
- [x] T10 RDD del candidato, PR a `dev`, merge y limpieza

## Criterios de aceptación

- `docker compose up` levanta PostgreSQL y la API, y la API aplica las migraciones al arrancar.
- `GET /health` responde `200` con la base de datos accesible y `503` cuando no lo está.
- `cups_valido` acepta CUPS correctos y rechaza letras de control incorrectas, espacios y
  minúsculas (se normalizan antes de validar).
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app` y `uv run pytest -q`
  en verde.
- `.env.example` lista las variables de la sección 18 sin valores.

## Evidencia

- **T1** `uv run ruff check .` → `All checks passed!` · `uv run mypy app` → `Success: no issues found in 8 source files` · `uv run ruff format --check .` → `18 files already formatted`.
- **T3** Primero en rojo: `uv run pytest tests/test_cups.py` → `ModuleNotFoundError: No module named 'app.domain.cups'`. Después: `15 passed`.
- **T3 · verificación de la tabla de letras**: la función de la spec reproduce dos CUPS
  públicos reales, `ES0031102846140001AK0F` (resto 90 → `AK`) y `ES0021000000000001RK`
  (resto 44 → `RK`). Fuentes consultadas el 2026-11-04: <https://nbxprocess.es/blog/como-validar-un-cups/>
  (estructura y cálculo con 529/23) y <https://es.wikipedia.org/wiki/C%C3%B3digo_Unificado_de_Punto_de_Suministro>
  (formato y campo de control).
- **T4** `DATABASE_URL=…@localhost… uv run alembic upgrade head` → `Running upgrade -> a6ae4c7bfd35,
  create initial schema` · `uv run alembic check` → `No new upgrade operations detected.` ·
  `\dt` → `alembic_version`, `anomalias`, `clientes`, `eventos_sync`, `facturas`, `suministros`.
- **T5** `uv run pytest` → `21 passed` (15 de CUPS + 6 de `/health` y del middleware).
- **T6** `docker compose build api` → `Image energy-ops-hub-api Built` ·
  `docker compose down -v && docker compose up -d` → `api`, `db` y `n8n` en `Up` ·
  `curl /health` → `{"status":"ok","database":"ok"}` con `HTTP 200` ·
  log del contenedor → `Running upgrade -> a6ae4c7bfd35` antes de `Application startup complete`.
- **T7** `uv run python -m scripts.seed` → `creados=43 actualizados=0`; segunda ejecución →
  `creados=0 actualizados=40`; en la base: 3 clientes, 40 suministros, 40 CUPS distintos
  (34 luz, 4 gas, 2 agua) y los 40 CUPS pasan `cups_valido`.
- **T8** `uv run pre-commit autoupdate` → pre-commit-hooks `v6.0.0`, ruff `v0.17.3`, gitleaks
  `v8.30.0` · `uv run pre-commit run --all-files` → los 8 hooks `Passed`.
- **T9** `uv run ruff check .` → `All checks passed!` · `uv run ruff format --check .` →
  `18 files already formatted` · `uv run mypy app scripts tests` → `Success: no issues found in
  14 source files` · `uv run pytest` → `21 passed`.

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.
- 2026-11-04 T1–T3 hechos: proyecto con uv, settings y validación de CUPS con tests.
- 2026-11-04 T4–T5 hechos: esquema completo con migración aplicada y `/health` con middleware.
- 2026-11-04 T6–T8 hechos: stack Docker de punta a punta, seed idempotente y pre-commit.
- 2026-11-04 T9 hecho: verificación completa desde un stack vacío.

## Siguiente paso

Feature 02 (`02-pipeline-ci`): `ci.yml` con el job agregador `ci-ok`, `dependabot.yml`, plantilla
de PR y, tras el merge, protección de `main` y `dev`. Antes de empezarla hace falta el scope
`workflow` del token de `gh`.

## Git

- Rama: `feat/01-base-proyecto`
- PR: #1 (`feat/01-base-proyecto` → `dev`)

## Decisiones

- Python 3.12 fijado en `pyproject.toml` con `requires-python = ">=3.12,<3.13"`; el intérprete
  del sistema es 3.14 y uv descarga el 3.12 del proyecto, así que el entorno es reproducible.
- El middleware `X-API-Key` se aplica a toda la API salvo `/health` y `/docs`: la demo necesita
  un sondeo sin credenciales para el smoke test del CD.
- Los modelos usan `TIMESTAMPTZ` con `server_default=func.now()`, igual que la sección 7.
- `docker-compose.yml` no redefine `command` en el servicio `api`: el `CMD` de la imagen aplica
  `alembic upgrade head` antes de arrancar uvicorn. Con el `command` de la sección 18 las
  migraciones no correrían y el criterio de aceptación no se cumpliría.
- El servicio `api` declara `DATABASE_URL` con host `db` y usa `env_file` opcional
  (`required: false`), así `docker compose up` funciona sin `.env` en la máquina.
- Los tests fijan `DATABASE_URL` a localhost en `tests/conftest.py` antes de importar `app`,
  porque el `.env` de cada desarrollador apunta a `db` (válido solo dentro de Docker).
- ruff 0.17 formatea código dentro de Markdown y reescribió `docs/spec.md`; se excluyeron
  `docs/` y `odd/` en `pyproject.toml` y los hooks de higiene tampoco tocan esas carpetas.
  La spec se versiona literal.
- `main` pasa a ser la rama por defecto del repositorio (pedido del humano), así que todo PR
  se abre con `--base dev` explícito. `docs/spec.md` y `AGENTS.md` quedaron actualizados.
- `.env.example` tiene un cambio pendiente de decisión (proveedor del LLM): el archivo local
  declara `OPENAI_API_KEY`/`OPENAI_MODEL` en lugar de las variables de Anthropic de la spec.
  Se resuelve al empezar la feature 04.

## RDD

- Riesgo: **medio** · Lente: `risk` (la que fija la tabla 19.4 para riesgo medio) · Resultado:
  **aprobado sin correcciones** · Lineage `review-b7c930d42723b98d`, 30 archivos y 2240 líneas
  revisadas sobre `dev`.
- Avisos informativos del revisor, ninguno bloqueante y ninguno reabre esta revisión. Quedan como
  trabajo posterior:
  - `R1-alembic-concurrency` (`Dockerfile:23`): con más de una réplica, `alembic upgrade head` en
    el arranque puede competir entre contenedores. En producción la migración va como paso previo
    del despliegue, no en el `CMD`.
  - `R1-predictable-api-key` (`docker-compose.yml:23`) y `R1-weak-db-creds` (`docker-compose.yml:6`):
    credenciales de relleno, válidas solo en local; la plataforma de despliegue usa las suyas.
  - `R1-n8n-weak-key` (`docker-compose.yml:34`): `N8N_ENCRYPTION_KEY` tiene un valor de relleno;
    en producción es un secreto real.
- Estos avisos se recogen también en la sección "Si esto fuera a producción" del README (feature 12).
