# AGENTS.md · Energy Ops Hub

Contrato de trabajo para los agentes de este repositorio (gentle-shell / gentle-ai).
Léelo entero al empezar cada sesión.

## 1. Qué es este proyecto

Demo de portfolio de automatización de operaciones energéticas para carteras inmobiliarias:
facturas PDF → extracción con LLM → reglas de anomalías → PostgreSQL → HubSpot; altas masivas
desde Google Sheets con Apps Script; flujos de n8n; copiloto de solo lectura.

- La especificación completa está en `docs/spec.md` y es la fuente de verdad del producto
  y de la técnica.
- En git, permisos y proceso manda este archivo.
- El plan de features está en `docs/spec.md`, sección 22.

## 2. Flujo de trabajo obligatorio: ODD con RDD

- Aplica ODD a toda petición: Authorize, Explore, Resolve uncertainty, Classify,
  Track before the first write, Implement task by task, Close.
- Las features del plan (docs/spec.md, sección 22) están autorizadas. No pidas permiso para
  empezar la siguiente; avisa al empezarla y al terminarla.
- Trabajo sustancial: crea `odd/tasks/NN-slug.md` con la plantilla de docs/spec.md 19.3 ANTES
  del primer cambio de código. Actualiza Progreso, Evidencia y Siguiente paso tras cada tarea.
- Trabajo pequeño (docs/spec.md 19.2): sin documento ODD, pero con rama y PR igualmente.
- Tests primero para cualquier comportamiento de dominio (CUPS, reglas, altas, idempotencia,
  cliente de HubSpot).
- RDD activo. Al completar el checklist de la feature, lanza la revisión RDD sobre el candidato
  ANTES de abrir el PR. El nivel de riesgo se fija con la tabla de docs/spec.md 19.4.
  Anota el resultado y los hallazgos en la sección RDD del documento ODD y en el PR.
- Delega en subagentes cuando la exploración abarque 4 o más archivos o haya 2 o más escrituras
  no triviales. Cada traspaso apunta al documento ODD; no lo resume.
- Para retomar una sesión: lee este archivo, el documento ODD de la rama actual y
  `git log --oneline origin/dev..HEAD`, y continúa desde "Siguiente paso".
- Una aprobación RDD no autoriza la entrega. La entrega la autoriza la sección 3.

## 3. Autorización permanente de entrega

Esta sección ES la política de entrega del repositorio. Tienes autorización explícita y
permanente para hacer lo siguiente SIN PREGUNTAR:

- Crear ramas de trabajo desde `dev` según la convención de la sección 5.
- Hacer commits en ramas de trabajo.
- Hacer push de ramas de trabajo (sin force).
- Actualizar tu rama con `git merge origin/dev`.
- Abrir PRs contra `dev`.
- Hacer squash merge de tus PRs en `dev` cuando `ci-ok` esté en verde y, si el riesgo es medio
  o alto, RDD haya aprobado.
- Borrar la rama de trabajo tras el merge.
- Hacer merge en `dev` de PRs de Dependabot de parche o menor con el CI en verde.
- Al llegar a un hito (v0.1.0, v0.2.0, v1.0.0), abrir el PR de release `dev` → `main`
  y DETENERTE hasta que el humano lo mergee.

NUNCA, aunque parezca necesario:

- Push directo a `main` o a `dev` (salvo los pasos del bootstrap de la sección 9).
- Merge en `main`. Crear tags o releases.
- `git push --force` o `--force-with-lease`, rebase de ramas ya publicadas,
  `git reset --hard` sobre trabajo publicado o cualquier reescritura de historial.
- Borrar `main` o `dev`. Cambiar la protección de ramas o los ajustes del repo fuera del
  bootstrap y del cierre de la feature 02.
- `--no-verify`, desactivar o saltarse checks del CI, o bajar el umbral de cobertura para que
  un PR pase.
- Crear, leer, imprimir o modificar secretos (`.env`, secretos de GitHub). Commitear credenciales.
- Usar datos reales de personas o empresas. Llamar a HubSpot o al LLM con datos no sintéticos.
- Hacer merge de PRs de Dependabot de versión mayor.

## 4. Cuándo preguntar (y solo entonces)

- Una decisión de producto real que docs/spec.md no resuelve.
- Necesitas una credencial, una cuenta, un servicio de pago o que el humano haga algo fuera del
  repo (token de HubSpot, credenciales de Gmail en n8n, secretos de GitHub, plataforma de
  despliegue).
- El cambio necesario se sale del alcance de docs/spec.md.
- El CI falla 3 veces seguidas por la misma causa.
- Una acción de la lista NUNCA parece necesaria.

Haz una sola pregunta, concreta, con tu recomendación y las alternativas.
Mientras esperas, sigue con lo que no dependa de la respuesta.

## 5. Git

Ramas:
- `main`: releases. Solo PR desde `dev` (o `hotfix/*`). El merge lo hace el humano.
- `dev`: integración y rama por defecto. Solo por PR, con squash merge.
- Ramas de trabajo desde `dev`: `feat/NN-slug`, `fix/slug`, `chore/slug`, `docs/slug`,
  `test/slug`, `refactor/slug`, `ci/NN-slug`. Slug en minúsculas, con guiones y sin acentos.
- `hotfix/slug` solo desde `main` y solo si el humano lo pide.

Commits (Conventional Commits, en inglés, en imperativo, asunto de 72 caracteres como máximo):
- `<type>(<scope>): <subject>`, con un cuerpo opcional que explica el porqué y el pie
  `Refs: odd/tasks/NN-slug.md`.
- Tipos: feat, fix, test, refactor, docs, chore, ci, build, perf.
- Scopes: api, db, domain, extraction, rules, hubspot, sheets, n8n, copilot, evals, data, ci, cd,
  deps, docs, odd.
- Un commit por unidad de trabajo (una tarea del checklist ODD), con
  `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q`
  en verde antes de hacerlo.
- Prohibido: wip, mensajes vagos, mezclar tareas, `--no-verify`.

Ciclo de cada feature:
1. `git switch dev && git pull --ff-only origin dev && git switch -c feat/NN-slug`
2. Commit del documento ODD: `docs(odd): track feature NN <título>`.
3. Tarea a tarea: test, código, verificación local, commit y push.
4. Si dev ha avanzado: `git fetch origin && git merge origin/dev`, y push.
5. Revisión RDD y anotación del resultado; commit y push.
6. `gh pr create --base dev` con título en formato Conventional Commit y la plantilla
   de `.github/pull_request_template.md` rellenada.
7. `gh pr checks --watch --fail-fast`. Si falla: `gh run view --log-failed`, corregir,
   push y repetir.
8. `gh pr merge --squash --delete-branch`, y después `git switch dev && git pull --ff-only origin dev`.
9. Resumen al humano: PR mergeado, resultado RDD y siguiente feature.

Release (al llegar a un hito):
- `gh pr create --base main --head dev --title "release: vX.Y.Z"` con la lista de PRs incluidos.
- Detente. El humano hace el merge (con merge commit) y publica la release.

## 6. Definición de terminado (cada feature)

- [ ] Todos los checkboxes del documento ODD marcados y con evidencia.
- [ ] Criterios de aceptación verificados, con el comando y su salida en Evidencia.
- [ ] ruff, ruff format, mypy y pytest en verde en local.
- [ ] RDD aprobado y anotado (riesgo medio o alto) o lectura estructural (riesgo bajo).
- [ ] PR mergeado en `dev` con `ci-ok` en verde y la rama borrada.
- [ ] Documento ODD con Progreso final y Siguiente paso apuntando a la próxima feature.
- [ ] `.env.example`, README y ADR actualizados si cambió algo visible o una decisión.

## 7. Estándares de código

- Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx, pytest, respx.
- Tipado en `app/` (mypy sin errores). ruff para lint y formato.
- Lógica de negocio en `app/domain/`: funciones puras, sin I/O. El I/O vive en `app/services/`.
  n8n solo orquesta: ninguna regla de negocio dentro de n8n.
- Idempotencia siempre: facturas por hash y clave de negocio, altas por CUPS y HubSpot por IDs
  externos guardados en nuestra base de datos.
- Los tests no usan red: respx para httpx y LLM simulado. Postgres real en los tests de
  integración (Docker Compose en local, servicio en el CI).
- Configuración solo por variables de entorno (pydantic-settings). Cada variable nueva se añade a
  `.env.example` sin valor.
- Logging estructurado con `request_id` y sin contenido de facturas.
- Nombres de dominio en español, como en docs/spec.md (`extraer_factura`, `cups_valido`).
  Infraestructura y utilidades pueden ir en inglés, pero con coherencia dentro de cada módulo.
- Datos 100 % sintéticos.

## 8. APIs externas

Antes de escribir código contra HubSpot, el SDK del LLM, nodos de n8n, clasp o una acción de
GitHub, consulta su documentación oficial actual. Anota en Evidencia del documento ODD qué
consultaste y la versión o fecha. Si la documentación contradice docs/spec.md, sigue la
documentación y registra la diferencia en Decisiones.

## 9. Bootstrap (solo una vez, feature 00)

La carpeta de trabajo contiene `proyecto-energy-ops-hub.md`. El remoto ya existe en GitHub.

1. `git init -b main`
2. `git remote add origin <URL que te da el humano>` y `git fetch origin`
3. Si el remoto ya tiene `main` (repo creado con README o licencia): `git pull origin main`
4. `mkdir -p docs odd/tasks && mv proyecto-energy-ops-hub.md docs/spec.md && touch odd/tasks/.gitkeep`
5. Crea `AGENTS.md` copiando el bloque entre `BEGIN AGENTS.md` y `END AGENTS.md` de
   docs/spec.md, sección 25, sin las líneas de valla.
6. Crea un README mínimo (nombre, una frase, "en construcción, ver docs/spec.md"),
   `.gitignore` y `.gitattributes` (docs/spec.md 20.8).
7. `git add -A && git commit -m "chore: initial commit"` y `git push -u origin main`
8. `git switch -c dev && git push -u origin dev`
9. `gh repo edit --default-branch dev --delete-branch-on-merge --enable-squash-merge --enable-merge-commit --enable-rebase-merge=false`
10. Comprueba que RDD está activo (`/gentle:review-mode status`) e informa al humano.
11. Continúa con la feature 01.

Al cerrar la feature 02, cuando `ci-ok` ya haya corrido una vez, aplica la protección de ramas
de docs/spec.md 20.7. Si tu token no tiene permisos de administración, pide al humano que lo haga.

## 10. Idioma

- Conversación con el humano, documentos ODD, README y ADR: español.
- Commits, títulos de PR y mensajes de log: inglés.
- Slugs de rama: español sin acentos (`feat/04-extraccion-facturas`).
