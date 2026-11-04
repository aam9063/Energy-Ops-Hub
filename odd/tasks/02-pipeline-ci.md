# 02 · Pipeline de CI

## Objetivo

Que cada PR a `dev` o `main` pase por un único check obligatorio (`ci-ok`) que solo puede estar
en verde si el lint, los tipos, los tests con PostgreSQL real, la validación de los artefactos de
n8n y Apps Script, la detección de secretos y el build de la imagen han pasado.

## Problema

Sin CI, «merge cuando esté en verde» es una promesa sin respaldo, y la autorización permanente de
entrega del `AGENTS.md` §3 descansa sobre ella. Además, la protección de ramas necesita un check
concreto al que exigir.

Cita literal de `docs/spec.md`, sección 22:

> | 02 | `02-pipeline-ci` | `ci/02-pipeline-ci` | `ci.yml`, `dependabot.yml`, plantilla de PR y, tras el merge, protección de `main` y `dev` | Alto | CI en verde en su propio PR; `ci-ok` obligatorio en `dev` y `main` | |

## Alcance

- **Dentro**: `.github/workflows/ci.yml` (jobs `lint`, `test`, `integrations`, `secrets`, `docker`
  y el agregador `ci-ok`), `.github/dependabot.yml`, `.github/pull_request_template.md`, los tests
  de esquema que hacen falta para cumplir el umbral de cobertura del 75 %, y la protección de
  `main` y `dev` una vez que `ci-ok` haya corrido.
- **Fuera**: `cd.yml`, `release.yml` y `evals.yml` (features 11 y 06), y la elección de plataforma
  de despliegue.

## Checklist

- [x] T1 `ci.yml` con `lint`, `test`, `integrations`, `secrets`, `docker` y `ci-ok`
- [x] T2 `dependabot.yml` (uv, github-actions y docker, contra `dev`)
- [x] T3 `.github/pull_request_template.md` con ODD y RDD
- [x] T4 tests de esquema que cubren `app/models.py` y llevan la cobertura por encima del 75 %
- [x] T5 validación local: hooks de YAML, cobertura y `actionlint` si está disponible
- [ ] T6 push y CI en verde en el propio PR
- [ ] T7 squash merge a `dev`
- [ ] T8 protección de `main` y `dev` con `ci-ok` obligatorio, y verificación

## Criterios de aceptación

- El PR de esta feature tiene `ci-ok` en verde y es el único check exigido por la protección.
- `lint`, `test`, `integrations`, `secrets` y `docker` corren y fallan cuando deben.
- Los jobs de `n8n/` y `apps_script/` pasan en vacío mientras esas carpetas no existan.
- La cobertura no baja del 75 %; el umbral nunca se reduce para que un PR entre.
- `dev` y `main` rechazan un push directo y un merge sin `ci-ok`.

## Evidencia

- **T1** `push` de `.github/workflows/ci.yml` aceptado por GitHub: el token tiene el scope
  `workflow` (el `gh auth status` mostraba la caché anterior a `gh auth refresh`).
  `pre-commit run --all-files` → `check yaml ... Passed` sobre el workflow y `dependabot.yml`.
- **T4** Antes de esta feature la cobertura era del 50 % con `app/models.py` al 0 %, así que el
  umbral del 75 % habría fallado. Con `tests/test_schema.py`:
  `uv run pytest --cov=app` → `31 passed`, `TOTAL 157 5 97%`, `app/models.py 73 0 100%`.
- **T5** `uv run ruff check .` → `All checks passed!` · `uv run mypy app scripts tests` →
  `Success: no issues found in 15 source files` · `actionlint` **no está instalado** en la máquina,
  así que la validación estructural del workflow la hace GitHub al ejecutarlo (y `check-yaml` en
  local).

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1: escribir `ci.yml`.

## Git

- Rama: `ci/02-pipeline-ci`
- PR: (pendiente)

## Decisiones

- Versiones mayores de las acciones comprobadas con la API de GitHub el 2026-11-04 y fijadas por
  tag mayor: `actions/checkout@v7`, `astral-sh/setup-uv@v10`, `actions/upload-artifact@v7`,
  `docker/setup-buildx-action@v4`, `docker/build-push-action@v7`, `actions/setup-node@v7` y
  `gitleaks/gitleaks-action@v3`.
- El umbral de cobertura se cumple con tests reales de esquema, no bajándolo ni excluyendo
  `app/models.py` de la medición.
- Los tests de esquema escriben dentro de una transacción que se revierte, así que no dejan datos
  ni necesitan una base dedicada por test.
- Los jobs de n8n y Apps Script toleran que las carpetas no existan todavía: el CI se escribe una
  vez y no hay que tocarlo en cada feature.

## RDD

- (pendiente)
