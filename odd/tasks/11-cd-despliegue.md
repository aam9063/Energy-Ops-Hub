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
  secretos (lo hace el humano), y el primer despliegue real, que necesita lo anterior. **Hecho el
  2026-11-05**: plataforma Render, environment `production` con sus dos valores y primer despliegue
  verde; ver T6 en Evidencia.

## Checklist

- [x] T1 `cd.yml` con jobs `image`, `deploy` y `apps-script` opcional
- [x] T2 smoke test que reintenta hasta 5 minutos contra `/health`
- [x] T3 `release.yml` que etiqueta la imagen con la versión semántica
- [x] T4 `tests/test_workflows.py`: YAML válido, permisos mínimos, disparadores correctos,
      environment `production`, smoke test presente y ningún secreto interpolado dentro de `run:`
- [x] T5 `pyyaml` como dependencia de desarrollo explícita (no transitiva)
- [x] T6 verificación, evidencia, RDD (riesgo alto, 4 lentes), PR y merge

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
- **T6 · primer despliegue real (2026-11-05)**: plataforma **Render**, elegida por el humano.
  Servicio `energy-ops-hub` en Frankfurt desplegando la imagen
  `ghcr.io/aam9063/energy-ops-hub:main` desde GHCR (paquete público, sin credenciales de registro)
  contra un Postgres 16 gestionado en el mismo proyecto y la misma región, para que funcione la red
  interna. El contenedor arranca con `alembic upgrade head && uvicorn …` (spec §18), así que migra
  solo: no hubo que configurar Pre-Deploy Command ni comando de Docker.
- **T6 · environment `production`**: `DEPLOY_HOOK_URL` (secreto, lo cargó el humano con
  `gh secret set`) y `API_PUBLIC_URL` = `https://energy-ops-hub-main.onrender.com` (variable). Por
  spec §21.10, `DATABASE_URL`, `API_KEY`, `OPENAI_API_KEY` y las `HS_*` viven en las variables de
  entorno de Render, no en GitHub.
- **T6 · CD en verde**: `gh workflow run cd.yml` → run **42000252294**, con `image` publicando las
  etiquetas SHA y `main`, `deploy` lanzando el hook y pasando el smoke test contra `/health` en 4 s,
  y `apps-script` salteado por el gate `DEPLOY_APPS_SCRIPT`.
- **T6 · el disparador por push a `main` ya estaba probado**: el run **41915056309**, generado por el
  merge `dev`→`main` de la release v1.0.0, entró por el evento `push`, dejó `image` en verde y falló
  sólo en `deploy` por el `DEPLOY_HOOK_URL` vacío. Con el secreto cargado, los mismos jobs pasan. Un
  push directo a `main` no lo puede hacer un agente (AGENTS.md §3), así que la prueba del disparador
  se compone de esos dos runs.
- **T6 · smoke test manual previo**: `GET /health` → `{"status":"ok","database":"ok"}` con HTTP 200
  en tres llamadas seguidas (0,10–0,19 s), lo que confirma además la migración aplicada y la
  conexión por red interna.
- **Deuda conocida**: el plan Free de PostgreSQL en Render caduca a los 30 días. El servicio y la URL
  sobreviven, pero hay que recrear la base y volver a cargar `DATABASE_URL`.

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.
- 2026-11-05 T1–T5 implementados y verificados; T6 pendiente de RDD y PR.
- 2026-11-05 RDD aprobado (4 lentes) y PR mergeado; quedaba el despliegue real, que depende del
  humano.
- 2026-11-05 T6 cerrado: Render elegido, environment `production` cargado y CD en verde
  (run 42000252294). Feature completa.

## Siguiente paso

No queda trabajo de repo en esta feature. Lo pendiente es del humano y vive en la sección 22.1 de la
spec: credenciales de HubSpot, hoja de Google con `apps_script/Code.gs`, credenciales de Gmail en
n8n y la grabación de la demo con `docs/demo.md`. La release **v1.0.0** ya está publicada.

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
