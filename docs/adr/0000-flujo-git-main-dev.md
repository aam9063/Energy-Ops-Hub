# ADR 0000 · Flujo de git con `main` y `dev` y CI obligatorio

- Estado: aceptado
- Fecha: 2026-10 (feature 02)
- Documento ODD: [odd/tasks/02-pipeline-ci.md](../../odd/tasks/02-pipeline-ci.md) · PR
  [#2](https://github.com/aam9063/Energy-Ops-Hub/pull/2)

## Contexto

El proyecto se construye con agentes de IA que trabajan solos. Sin un flujo estricto, el historial
se convierte en una serie de commits directos sin verificación, y no hay forma de saber qué estado
de `dev` o `main` es fiable. Un merge a `main` equivale a publicar una release: tiene que ser una
decisión humana.

## Decisión

- `main` solo recibe PRs desde `dev` (o `hotfix/*` en caso extremo) y **el merge lo hace el
  humano**; es donde se etiquetan releases.
- `dev` es la rama de integración: solo entra por PR con **squash merge**, de modo que cada
  feature es un commit atómico y legible.
- Cada PR pasa por un único check agregador **`ci-ok`** que solo está en verde si pasan lint
  (ruff), tipos (mypy), tests con PostgreSQL real, validación de los artefactos de n8n y Apps
  Script, gitleaks y el build de la imagen. `ci-ok` es **obligatorio** en las protecciones de
  `main` y `dev`.
- Las ramas de trabajo (`feat/NN-slug`, `fix/`, `ci/`, …) se crean desde `dev` y se borran tras
  el merge. Los agentes tienen autorización permanente para ramas, commits, push y PRs; nunca
  para tocar `main`.

## Consecuencias

- Buenas: cualquier commit de `dev` es verificable y reversible; el historial de `dev` es un
  índice de features; la protección de ramas impide saltos de proceso incluso por accidente del
  propio agente.
- Costes: el ciclo por feature pasa por PR y CI aunque el cambio sea pequeño, y el squash merge
  pierde la granularidad de commits intermedios (queda en el PR).
- El merge a `main` sigue dependiendo de una persona: es deliberado, no una limitación.
