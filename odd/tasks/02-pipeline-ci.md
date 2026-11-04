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
- [x] T6 push y CI en verde en el propio PR
- [x] T7 squash merge a `dev`
- [x] T8 protección de `main` y `dev` con `ci-ok` obligatorio, y verificación

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
- **T6** Primer intento del PR: `lint` y `test` fallaban en 2–3 s con
  `Unable to resolve action astral-sh/setup-uv@v10, unable to find version v10`. El proyecto solo
  publica tags mayores hasta `v7` (comprobado con la API). Corregido en `fix(ci)`; segundo run:
  `lint`, `test`, `integrations`, `secrets`, `docker` y `ci-ok` en `pass`.
- **T7** `gh pr merge 2 --squash` → `b2466cb ci: add GitHub Actions pipeline with aggregated ci-ok
  check (#2)` en `dev`, rama borrada.
- **T8** Protección aplicada con `gh api` sobre `dev` y `main`, y leída de vuelta:
  `{"checks":["ci-ok"],"strict":true,"admins":true,"linear":true,"force":false,"delete":false}`
  en `dev` y lo mismo con `linear: false` en `main`. Prueba real: un commit vacío empujado a `dev`
  fue rechazado con `Changes must be made through a pull request` y
  `Required status check "ci-ok" is expected`; el commit de prueba se descartó con
  `git reset --soft origin/dev` y el árbol quedó limpio.

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.
- 2026-11-04 T1–T5 hechos: workflow, Dependabot, plantilla de PR y tests de esquema (97 % de
  cobertura).
- 2026-11-04 T6 hecho: dos corridas del CI, el segundo intento en verde tras corregir la versión
  de `setup-uv`.
- 2026-11-04 T7–T8 hechos: PR #2 mergeado y ramas protegidas, con la protección probada.

## Siguiente paso

Feature 03 (`03-datos-sinteticos`): generador de 120 PDFs con tres maquetaciones, anomalías
inyectadas y ground truth para las evals.

## Git

- Rama: `ci/02-pipeline-ci`
- PR: #2 (`ci/02-pipeline-ci` → `dev`)

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

- Riesgo: **alto** · Lentes: **4R** (`risk`, `resilience`, `readability`, `reliability`) ·
  Resultado: **aprobado** · Lineage `review-5482413e3f709b30`, 5 archivos y 403 líneas sobre `dev`.
- El revisor de `reliability` marcó un hallazgo **crítico** en `tests/test_schema.py:93-97`
  (el test del `archivo_hash` no aislaría la restricción que dice probar). El **refuter lo refutó**
  y quedó como no bloqueante: el segundo insert comparte `numero` distinto, así que la única
  restricción que puede violar es `archivo_hash`.
- Avisos informativos, ninguno bloqueante y ninguno reabre esta revisión. Quedan como trabajo
  posterior:
  - `R2-001` (`odd/tasks/02-pipeline-ci.md`): legibilidad de este documento.
  - `R3-002` (`.github/workflows/ci.yml`, paso `upload-artifact`): el artefacto de cobertura se
    sube con `if: always()`, incluso cuando el job falla antes de generarlo.
  - `R4-001` (`.github/workflows/ci.yml`, job `docker`): caché `gha` compartida con el build de CD;
    conviene separar `scope` cuando exista `cd.yml`.
  - `R4-002` (`.github/workflows/ci.yml`, sintaxis de Apps Script): el bucle `node --check` copia a
    `/tmp`; con nombres repetidos entre carpetas habría colisión.
  - `R4-003` (`.github/workflows/ci.yml`, `concurrency`): `cancel-in-progress` cancela ejecuciones
    del mismo `ref`; en `dev` puede dejar un run anterior a medias (es lo que se quiere, pero
    conviene saberlo).
- El merge incorpora este mismo registro; el código revisado no cambió después de la aprobación.
