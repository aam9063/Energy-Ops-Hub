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

- [ ] T1 `ci.yml` con `lint`, `test`, `integrations`, `secrets`, `docker` y `ci-ok`
- [ ] T2 `dependabot.yml` (uv, github-actions y docker, contra `dev`)
- [ ] T3 `.github/pull_request_template.md` con ODD y RDD
- [ ] T4 tests de esquema que cubren `app/models.py` y llevan la cobertura por encima del 75 %
- [ ] T5 validación local: hooks de YAML, cobertura y `actionlint` si está disponible
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

- (pendiente)

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1: escribir `ci.yml`.

## Git

- Rama: `ci/02-pipeline-ci`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
