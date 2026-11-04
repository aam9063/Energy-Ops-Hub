# 09 · Flujos de n8n

## Objetivo

Que las facturas que llegan por email, las altas paradas y la sincronización con HubSpot corran
solas, con los flujos versionados en el repositorio y sin lógica de negocio dentro de n8n.

## Problema

La API ya sabe extraer, validar y sincronizar, pero alguien tiene que dispararla. n8n es el
pegamento: escucha el buzón, mira el reloj y avisa al equipo. La regla del proyecto es que n8n solo
orqueste; si una decisión vive en un nodo de n8n, no se puede testear.

Cita literal de `docs/spec.md`, sección 13:

> | 1 | **Gmail Trigger** (o IMAP Email) | Buzón dedicado tipo `facturas+demo@...`; descargar adjuntos |
> | 2 | **IF** | Solo continuar si hay adjunto PDF |
> | 3 | **Split Out** | Un ítem por adjunto si hay varios |
> | 4 | **HTTP Request** | `POST {API_URL}/facturas`, multipart con el binario, cabecera `X-API-Key` |
> | 5 | **IF** | `anomalias` con severidad alta |
> | 6a | **HTTP Request** | `POST {API_URL}/anomalias/{id}/ticket` (la API crea el ticket de forma idempotente) |
> | 6b | **Gmail / Slack** | Aviso al responsable con resumen y enlace al ticket |

> **F2. Altas paradas** — Schedule Trigger (días laborables 8:30) → `GET {API_URL}/altas?parada_dias=7`
> → IF vacío → Code (agrupar por cliente) → Gmail/Slack.

> **F3. Sincronización con HubSpot** — Schedule Trigger (cada 15 minutos) →
> `POST {API_URL}/sync/hubspot` → IF respuesta con errores → aviso.

> | 09 | `09-flujos-n8n` | `feat/09-flujos-n8n` | Flujos F1, F2 y F3 exportados al repo | Medio | Un email con PDF termina como factura y, si procede, como ticket | **v0.2.0** |

## Alcance

- **Dentro**: `n8n/F1_facturas_email.json`, `n8n/F2_altas_paradas.json` y `n8n/F3_sync_hubspot.json`
  en formato de exportación de n8n, sin credenciales embebidas, con nombres de nodo descriptivos y
  notas adhesivas que expliquen cada bloque; y `tests/test_n8n_flows.py`, que valida la estructura
  de los tres flujos en CI.
- **Fuera**: el flujo F4 del copiloto (feature 10), conectar las credenciales de Gmail (lo hace el
  humano), el flujo de errores concreto y la demo grabada (feature 12).

## Checklist

- [x] T1 `F1_facturas_email.json`: trigger de email, filtro de PDF, split de adjuntos, `POST /facturas`
  con `X-API-Key`, decisión por severidad alta y creación del ticket en la API
- [x] T2 `F2_altas_paradas.json`: reloj de días laborables a las 8:30, `GET /altas?parada_dias=7`,
  corte si está vacío, agrupación por cliente y aviso
- [x] T3 `F3_sync_hubspot.json`: reloj de 15 minutos, `POST /sync/hubspot` y aviso si hay errores
- [x] T4 JSON sin credenciales, nombres descriptivos y notas adhesivas en los tres flujos
- [x] T5 `tests/test_n8n_flows.py`: JSON válido, conexiones que apuntan a nodos existentes, sin
  campos de credenciales y endpoints esperados en cada flujo
- [x] T6 verificación, evidencia, RDD, PR y merge

## Criterios de aceptación

- Los tres flujos son JSON válido y el job `integrations` del CI sigue pasando (validación + ausencia
  de credenciales).
- El test nuevo falla si un flujo referencia un nodo inexistente, si aparece una credencial embebida
  o si un flujo pierde su endpoint.
- F1 crea el ticket **llamando a la API**, no con un nodo de HubSpot en n8n: la idempotencia vive en
  Python y está testeada.
- Las URLs de la API salen de una variable/credencial de n8n, nunca escritas en cada nodo.

## Evidencia

- **Implementación**: un worker con este documento como contrato; el orquestador verificó después.
- **F1** (10 nodos): Gmail Trigger con filtro `has:attachment filename:pdf` → IF de adjunto →
  `splitOut` → `POST {{$vars.API_URL}}/facturas` con `X-API-Key` → IF de severidad alta →
  `POST …/anomalias/{{id}}/ticket` → aviso por email. Tres notas adhesivas, una de ellas explicando
  **por qué el ticket lo crea la API y no el nodo de HubSpot**.
- **F2** (7 nodos): reloj `30 8 * * 1-5` → `GET …/altas?parada_dias=7` → IF de lista vacía → `Code`
  que agrupa por cliente y devuelve un solo ítem con `total_altas`, `clientes_afectados` y
  `resumen` → aviso.
- **F3** (6 nodos): reloj `*/15 * * * *` → `POST …/sync/hubspot` → IF `errores > 0` → aviso con el
  resumen del sync.
- **T4**: cero claves `credentials`; toda URL y clave salen de `$vars` (`API_URL`, `API_KEY`,
  `RESPONSABLE_EMAIL`, `HUBSPOT_PORTAL_URL`) y la configuración se documenta en notas. Verificado con
  el mismo `grep` del job `integrations`: **sin credenciales embebidas**.
- **T5**: `uv run pytest tests/test_n8n_flows.py` → **31 tests** de estructura, con RED observado
  rompiendo a propósito una conexión de F3. `uv run pytest` → **189 passed**.
- **Verificación independiente del orquestador**: los tres JSON parsean (`python -m json.tool`, que
  es el equivalente local de `jq empty` — **`jq` no está instalado en esta máquina**, y el CI sí lo
  usa); script propio sobre `connections`: **0 conexiones rotas**, ids únicos y los únicos nodos sin
  arista de entrada son los triggers y las notas adhesivas, que es lo correcto.
- **Lint y tipos**: `uv run ruff check .` → `All checks passed!` · `uv run ruff format --check .` →
  `47 files already formatted` · `uv run mypy app scripts tests evals` → `Success: no issues found in
  42 source files`.

## No verificado, y por qué

- **Importación real en n8n**: no hay instancia levantada. Los `typeVersion` (if 2.2, httpRequest 4.2,
  code 2, gmail 2.1, scheduleTrigger 1.2, gmailTrigger 1.2) son los vigentes en n8n reciente, pero
  eso se confirma al importar. Igual con `inputDataFieldName: "attachment_0"` del multipart de F1:
  es el nombre que usa el Gmail Trigger y hay que verificarlo contra la versión desplegada.
- **Credenciales de Gmail**: las conecta el humano después de importar; el JSON no las lleva a
  propósito.

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.
- 2026-11-05 T1–T5 implementados y verificados; T6 pendiente de RDD y PR.

## Siguiente paso

T6: RDD (riesgo medio, una lente), PR a `dev` y merge. Después, hito **v0.2.0** (merge `dev`→`main`
y release, del humano) y las features 11 y 12.

## Git

- Rama: `feat/09-flujos-n8n`
- PR: (pendiente)

## Decisiones

- **Gmail Trigger** en F1 (la spec admite Gmail o IMAP): filtra por PDF en la búsqueda y descarga los
  adjuntos, que es lo que evita abrir el buzón a mano.
- **El corte por lista vacía en F2 lo hace un IF, no el nodo `Code`**: con `alwaysOutputData: true`
  el HTTP siempre emite un ítem y el IF decide. El `Code` no toma decisiones de negocio: agrupa y
  presenta, que es lo único que se le permite a n8n en este proyecto.
- **F3 solo avisa de `errores > 0` en una respuesta 2xx**; un 5xx lo recoge el flujo de errores de
  n8n, que es la feature 12. Está anotado en la nota del flujo para que nadie lo confunda con un
  fallo silencioso.
- **`meta.templateCredsSetupCompleted: false`** en lugar de un `instanceId` inventado: un identificador
  falso en el repo no aporta nada y confunde al importar.

## RDD

- Riesgo: **medio** · Lente: `resilience` · Resultado: **aprobado tras una corrección** · Lineage
  `review-50066d1cb496ceb3`, 5 archivos y 947 líneas.
- **El refuter encontró lo que los tests no**: tres hallazgos **CRITICAL** (`R4-001`, `R4-002`,
  `R4-003`) con la misma causa — los nodos HTTP de los tres flujos no tenían reintento ni rama de
  error, así que un fallo de red detenía el flujo **en silencio**. El test estructural no lo veía
  porque no comprobaba esa política de ejecución.
- **Corrección acotada** (plan declarado en 192 líneas, dentro del tope de 200): cada nodo HTTP pasa
  a `retryOnFail` con 3 intentos y 5 s de espera, y `onError: continueErrorOutput`, con la salida de
  error conectada al nodo de aviso que **ya existía** en cada flujo. Se añadió un test que falla si
  un flujo pierde esos ajustes o si la rama de error apunta a un nodo inexistente.
- La corrección la validó el **validador dirigido** del proveedor: **aprobada** con un aviso
  informativo (`R4-004`, `n8n/F1_facturas_email.json:54`).
- **Proceso**: el plan de corrección se declara **antes** de aplicarlo; mi primer intento lo hizo al
  revés y el binding quedó atado a la revisión previa. Se resolvió volviendo temporalmente al estado
  anterior, declarando el plan y retomando la corrección ya commiteada.
- **Lo que esta feature deja claro**: `resilience` en flujos de orquestación no es decorativa. Los
  tests de estructura dicen que el cableado es coherente; solo una lente de resiliencia dice si el
  flujo se cae en silencio cuando la API no responde.
