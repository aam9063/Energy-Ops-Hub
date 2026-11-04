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

- [x] T1 `cd.yml` con jobs `image`, `deploy` y `apps-script` opcional
- [x] T2 smoke test que reintenta hasta 5 minutos contra `/health`
- [x] T3 `release.yml` que etiqueta la imagen con la versión semántica
- [x] T4 `tests/test_workflows.py`: YAML válido, permisos mínimos, disparadores correctos,
      environment `production`, smoke test presente y ningún secreto interpolado dentro de `run:`
- [x] T5 `pyyaml` como dependencia de desarrollo explícita (no transitiva)
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

- **T1–T3**: `.github/workflows/cd.yml` con los jobs `image` (GHCR etiquetada por SHA y `main`),
  `deploy` (environment `production`, deploy hook por secreto y smoke test que reintenta 30 veces
  cada 10 s) y `apps-script` opcional (`vars.DEPLOY_APPS_SCRIPT == 'true'`). `release.yml` etiqueta
  la imagen con `type=semver` (versión y mayor.menor).
- **T4**: `tests/test_workflows.py` con **20 tests** de política de entrega: YAML válido, permisos
  mínimos, CD solo desde `main` o manual, environment `production`, smoke test con reintentos,
  imágenes etiquetadas, release con semver, Apps Script opcional, `cancel-in-progress: false` y
  ningún secreto o input interpolado dentro de un `run:`.
- **T5**: `pyyaml` y `types-pyyaml` como dependencias de desarrollo explícitas. Nota: `yaml.safe_load`
  convierte la clave `on:` en el booleano `True` (YAML 1.1); el helper `disparadores()` lo maneja.
- **Verificación**: `uv run pytest` → **199 passed** (20 de workflows) · `uv run mypy app scripts tests
  evals` → 43 archivos sin errores · `ruff check` y `ruff format --check` limpios · cobertura **97 %**.
- **Lo que no se puede verificar aquí**: el primer despliegue real. Necesita que el humano elija
  plataforma, cree el environment `production` y cargue `DEPLOY_HOOK_URL` y `API_PUBLIC_URL`.

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.
- 2026-11-05 T1–T5 implementados y verificados; T6 pendiente de RDD y PR.

## Siguiente paso

T6: PR a `dev` y merge. Después, hito **v0.2.0** (merge `dev`→`main` y release, del humano) y la
feature 12.

## Git

- Rama: `ci/11-cd-despliegue`
- PR: (pendiente)

## Decisiones

- **El CD solo escucha `main`**: desplegar desde una rama de trabajo convierte cada push en un
  despliegue y multiplica las formas de romper producción.
- **`cancel-in-progress: false`** en el despliegue: cancelar un despliegue a medias deja el entorno
  en un estado que nadie pidió.
- **Secrets e inputs siempre por `env:`**, nunca interpolados en `run:`: es una regla de inyección de
  comandos y un test la pinnea.
- **El smoke test reintenta 30 veces cada 10 s** (5 minutos) porque la plataforma tarda en arrancar
  la versión nueva; fallar al primer intento daría falsos negativos.
- **El push de Apps Script está apagado por defecto** y se activa con una variable del repositorio:
  el `clasp push` requiere credenciales que no deben existir por defecto.

## RDD

- Riesgo: **alto** (workflows de entrega) · Lentes: **4R** · Resultado: **aprobado** · Lineage
  `review-f1b089d1a51bce47`, 6 archivos y 353 líneas.
- **La revisión se atascó en el transporte, no en el candidato**: el slot de la lente `risk` fue
  rechazado dos veces con `binding_mismatch` del relay (el revisor devolvía un subject distinto al de
  la binding). No consumió slot ni quemó autoridad. Se capturaron primero `resilience`,
  `readability` y `reliability`, y al tercer intento `risk` entró.
- **El acknowledge exige que el árbol coincida con el candidato revisado**: el primer intento se hizo
  desde otra rama (las correcciones de evals) y el proveedor lo rechazó con `not-current`. Se repitió
  desde `ci/11-cd-despliegue` y quemó la autoridad correctamente.
- Tres avisos informativos, ninguno bloqueante: `.github/workflows/cd.yml:17` (sugerencia),
  `cd.yml:90` (`clasp push` sin reintento) y `cd.yml:59` (el deploy hook sin reintento). Quedan como
  trabajo posterior; el smoke test ya cubre el síntoma principal.
