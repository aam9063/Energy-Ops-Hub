# 11 · CD y releases

## Objetivo

Que publicar en `main` construya la imagen en GHCR, lance el despliegue, compruebe con un smoke test
que la API responde, y que una release etiquete esa misma imagen con la versión semántica.

## Problema

Hoy el CI dice si el código está sano, pero nada lo pone en marcha: `main` es una rama con commits
verdes. Y una versión publicada sin una imagen etiquetada con ese número no se puede desplegar ni
volver atrás con precisión.

Cita literal de `docs/spec.md`, secciones 21.5 y 21.6:

> | `.github/workflows/cd.yml` | Push a `main`, manual | Imagen en GHCR, despliegue, smoke test y, opcionalmente, push de Apps Script con clasp | 11 |
> | `.github/workflows/release.yml` | Release publicada | Etiqueta la imagen con la versión semántica | 11 |

> - El despliegue usa un **deploy hook**, una URL secreta que ofrecen plataformas como Render o
>   Railway. Si eliges otra plataforma, el agente sustituye este paso por la acción oficial.
> - El smoke test reintenta durante 5 minutos porque la plataforma tarda en arrancar la versión
>   nueva.

> | 11 | `11-cd-despliegue` | `ci/11-cd-despliegue` | `cd.yml`, `release.yml`, despliegue y clasp opcional | Alto | Un push a `main` despliega y pasa el smoke test | |

## Alcance

- **Dentro**: `.github/workflows/cd.yml` (imagen en GHCR etiquetada por SHA y `main`, despliegue por
  deploy hook en el environment `production`, smoke test con reintentos y push opcional de Apps
  Script con clasp), `.github/workflows/release.yml` (etiquetas semver de la imagen) y
  `tests/test_workflows.py`, que valida en CI la política de entrega de los workflows.
- **Fuera**: elegir la plataforma, crear los environments `production` y `evals` y cargar sus
  secretos (lo hace el humano), y el primer despliegue real, que necesita lo anterior.

## Checklist

- [ ] T1 `cd.yml` con jobs `image`, `deploy` y `apps-script` opcional
- [ ] T2 smoke test que reintenta hasta 5 minutos contra `/health`
- [ ] T3 `release.yml` que etiqueta la imagen con la versión semántica
- [ ] T4 `tests/test_workflows.py`: YAML válido, permisos mínimos, disparadores correctos,
      environment `production`, smoke test presente y ningún secreto interpolado dentro de `run:`
- [ ] T5 `pyyaml` como dependencia de desarrollo explícita (no transitiva)
- [ ] T6 verificación, evidencia, RDD (riesgo alto, 4 lentes), PR y merge

## Criterios de aceptación

- El CD solo se dispara desde `main` (o a mano), nunca desde `dev` ni desde un PR.
- La imagen lleva el SHA y `main`; la release añade `X.Y.Z` y `X.Y`.
- El despliegue corre en el environment `production`, no en el repositorio a secas.
- El smoke test falla el job si `/health` no responde en cinco minutos.
- El push de Apps Script está apagado por defecto y se activa con una variable del repositorio.
- Ningún `run:` interpola `${{ secrets.* }}` ni `${{ inputs.* }}`: van por `env:`.
- `tests/test_workflows.py` falla si alguien quita el environment, el smoke test o los permisos
  mínimos, y pasa en el job `test` del CI.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.

## Siguiente paso

T1–T3: los dos workflows.

## Git

- Rama: `ci/11-cd-despliegue`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
