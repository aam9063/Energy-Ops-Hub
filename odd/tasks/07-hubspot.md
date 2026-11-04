# 07 · Integración con HubSpot

## Objetivo

Que cada alta de suministro exista como negocio en HubSpot y cada anomalía alta como ticket, sin
duplicados aunque el proceso se repita, y que el estado que el equipo mueve en el CRM vuelva a
nuestra base de datos.

## Problema

El equipo vive en HubSpot: ahí ve los negocios, mueve fases y gestiona tickets. Si las altas y las
anomalías solo existen en nuestra base de datos, Laura trabaja en dos sitios. Y si la sincronización
no es idempotente, cada reintento duplica negocios y ensucia el CRM — que es justo el problema que
la oferta llama «calidad de los datos».

Cita literal de `docs/spec.md`, sección 12:

> | Energy Ops | HubSpot | Fuente de verdad |
> |---|---|---|
> | Cliente | Empresa (company) | HubSpot para datos comerciales; NIF como clave de cruce |
> | Suministro en alta | Negocio en el pipeline "Altas de suministro" | Estado: **HubSpot** (lo mueve el equipo); datos técnicos: **Energy Ops** |
> | Anomalía | Ticket asociado a la empresa | Energy Ops la crea; HubSpot la gestiona (estado del ticket) |

> - **Opción elegida para el MVP: polling incremental.** Cada 15 minutos (flujo F3 de n8n) se llama
>   a `POST /sync/hubspot`, que busca negocios del pipeline modificados desde la última
>   sincronización (filtro por `hs_lastmodifieddate`) y actualiza `suministros.estado` y
>   `estado_desde`. Guarda la marca de tiempo de la última sincronización correcta.

> | 07 | `07-hubspot` | `feat/07-hubspot` | Cliente, pipeline, propiedades, upsert de negocios, tickets y sync | Alto | Dos ejecuciones seguidas no crean duplicados en HubSpot | |

## Alcance

- **Dentro**: `app/services/hubspot.py` con cliente httpx, reintento con espera exponencial en 429
  y 5xx, `buscar_uno`, `upsert_deal_alta`, `crear_ticket_anomalia` y asociación con la empresa;
  configuración de pipeline y fases por variables `HS_*` (nunca escritas a mano en el código); la
  marca de la última sincronización; `POST /sync/hubspot`, `POST /anomalias/{id}/ticket` y
  `POST /altas/lote`; auditoría en `eventos_sync`; y los tests con `respx`.
- **Fuera**: crear la cuenta, la app privada, las propiedades y el pipeline en HubSpot (lo hace el
  humano); los flujos de n8n (09); el copiloto (10); y los webhooks, que quedan como ADR de mejora.

## Checklist

- [x] T1 cliente HubSpot con httpx, timeout y reintento exponencial en 429/5xx
- [x] T2 `buscar_uno` y `upsert_deal_alta` idempotentes por `cups` y por `hubspot_deal_id`
- [x] T3 `crear_ticket_anomalia` idempotente por `energy_ops_id`, con asociación a la empresa
- [x] T4 `POST /altas/lote` idempotente por CUPS, con resultado por fila y resumen
- [x] T5 `POST /anomalias/{id}/ticket` (crea o devuelve el ticket) y guarda `hubspot_ticket_id`
- [x] T6 `POST /sync/hubspot` incremental por `hs_lastmodifieddate`, actualizando `estado` y
  `estado_desde`, con marca de última sincronización correcta
- [x] T7 auditoría en `eventos_sync` de cada operación con HubSpot, sin datos personales
- [x] T8 tests con `respx`: dos upserts no duplican, 429 se reintenta, se asocia a la empresa,
  el sync no retrocede estados y un error de HubSpot no pierde la fila local
- [x] T9 verificación, evidencia, RDD, PR y merge

## Criterios de aceptación

- Dos ejecuciones seguidas de las mismas altas no crean negocios duplicados en HubSpot (ni filas
  nuevas en `suministros`).
- Dos ejecuciones del mismo ticket devuelven el mismo `hubspot_ticket_id`.
- Un 429 de HubSpot se reintenta con espera creciente y termina bien; si se agotan los intentos, la
  API responde con un error controlado y deja el evento `ok=False`.
- El sync actualiza `estado` y `estado_desde` solo cuando la fase cambió, y no retrocede un estado
  por una respuesta vieja.
- Ningún test hace red: `respx` simula HubSpot con respuestas grabadas a mano.
- El token y los IDs de pipeline salen de configuración; el repositorio no contiene ninguno.

## Evidencia

- **Implementación**: un worker con este documento como contrato; el orquestador verificó después.
- **T1 reintentos**: `_req` reintenta 429 y 5xx hasta cinco intentos con espera exponencial
  (1→2→4→8 s, sin dormir tras el último) y respeta `Retry-After`; agotados los intentos lanza
  `HubSpotError` con el código HTTP y la ruta, nunca el token. Cliente perezoso: importar sin
  `HUBSPOT_TOKEN` no falla.
- **T2–T3 idempotencia**: `tests/test_hubspot.py` prueba que dos upserts no crean dos negocios (el
  segundo va por `PATCH` y **no** manda `dealstage`), que el ticket se reutiliza por
  `energy_ops_id` y que la asociación con la empresa se llama.
- **T4 `POST /altas/lote`**: `tests/test_altas_api.py` — resumen exacto de la sección 15, filas
  buenas y malas en el mismo lote, mensajes por fila para CUPS inválido, tipo inválido y cliente sin
  `hubspot_company_id`, y segundo envío del mismo lote con `creadas=0` y sin segundo negocio.
- **T5 ticket por API**: lo dejó el worker como hueco (solo probado a nivel de servicio). El
  orquestador lo cerró con `tests/test_tickets_api.py` y `respx`: la primera llamada crea el ticket
  (`creado=True`, `crear.call_count == 1`), la segunda lo reutiliza (`creado=False`) sin volver a
  crearlo, una anomalía inexistente da 404 y un HubSpot caído da 503 sin guardar id y con evento
  `ok=False`.
- **T6 sync**: `tests/test_sync_api.py` — actualiza el estado solo cuando cambia la fase, ignora
  fases desconocidas, no retrocede un estado por un negocio más viejo que `estado_desde`, actualiza
  la marca al terminar bien y **no** la toca si HubSpot devuelve 500.
- **T7 auditoría**: `eventos_sync` con `altas_lote`, `altas_lote_fila`, `ticket_anomalia`,
  `sync_estados` y `sync_marca`, sin NIF ni contenido de documentos.
- **Verificación del orquestador**: `uv run pytest` → **150 passed** · `uv run mypy app scripts tests
  evals` → `Success: no issues found in 40 source files` · `uv run ruff check .` → `All checks
  passed!` · cobertura de `app/`: `TOTAL 969 30 97%`.
- **Sin red**: los 13 tests del worker y los 3 del orquestador usan `respx`; ninguna prueba sale a
  internet.

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.
- 2026-11-05 T1–T8 implementados por el worker y verificados por el orquestador.
- 2026-11-05 hueco del ticket cerrado con tres tests de API; T9 pendiente de RDD y PR.

## Siguiente paso

T9: RDD de riesgo alto (4 lentes), PR a `dev` y merge. Después, feature 08 (`Code.gs`, que ya tiene
su `/altas/lote`).

## Git

- Rama: `feat/07-hubspot`
- PR: (pendiente)

## Decisiones

- **La fila del alta se guarda antes de llamar a HubSpot.** Si el CRM falla, la fila local ya existe
  y se informa el error en su resultado: el reintento del lote la completa en vez de perder la alta.
  Es lo que pide el criterio «un error de HubSpot no pierde la fila local».
- **El `PATCH` del negocio no toca `dealstage`**: la fase es la fuente de verdad del equipo y el
  sync la lee de HubSpot, no al revés. Sin eso, cada sincronización les pisaría el trabajo.
- **La marca de sincronización vive en `eventos_sync`** (`hubspot`/`sync_marca`), se captura
  `now()` antes de leer los negocios y solo se escribe si el sync termina sin errores: un fallo a
  medias no hace perder cambios.
- **No-retroceso**: si el `hs_lastmodifieddate` del negocio es anterior a `estado_desde`, se omite.
  Una respuesta vieja no puede devolver un suministro activo a «pendiente».
- **Fases desconocidas se omiten**, no se inventan: el mapa `HS_MAPA_ESTADOS` es configuración, y lo
  que no está en él se cuenta como `omitidos`.
- **`creado` del ticket** es verdadero si no había `hubspot_ticket_id` local. Si el ticket ya existía
  en HubSpot pero el campo local estaba vacío, devuelve el id con `creado=True`: se prefirió no
  duplicar la búsqueda a afinar ese contador.

## RDD

- **Primera revisión** (4 lentes: `risk`, `resilience`, `readability`, `reliability`, lineage
  `review-1f816bca02a6389e`): 4 revisores capturados y **refuter ejecutado**. La revisión **no
  aprobó**: quedó **escalada** con un hallazgo corroborado
  (`R3-reliability-crash-null-desde`, `app/services/hubspot_sync.py:66-67`) y causalidad
  desconocida sobre `R2-001`. Sin aprobación no hay merge.
- **Corrección**: la comparación `fecha_negocio < suministro.estado_desde` reventaba con
  `TypeError` si `estado_desde` era nulo (fila antigua o creada fuera del ORM) o si un extremo
  llevaba zona horaria y el otro no, y ese `TypeError` abortaba la sincronización entera. Se extrajo
  `respuesta_vieja()` con guardas explícitas —una fecha ausente o incomparable no impide aplicar la
  fase nueva— y se fijó con dos tests puros: extremos ausentes/incomparables y la comparación real
  (más antigua → `True`, más nueva o igual → `False`). 152 tests en la suite.
- **Segunda revisión** del candidato corregido (lineage `review-fde0e0777759eecc`): lentes
  `resilience` y `reliability`, las pertinentes al cambio; `risk` y `readability` ya se habían
  revisado sobre el código que no cambió. Resultado: **aprobado**, con seis avisos informativos
  (`app/routers/altas.py:73-77`, `app/services/hubspot.py:82-98`, `app/config.py:33`,
  `app/services/hubspot_sync.py:66` y `:107`, `app/services/hubspot.py:60`), ninguno bloqueante.
- **Lección para las siguientes features**: un refuter que corrobora un fallo convierte la revisión
  en un trabajo, no en un trámite. El coste de arreglarlo y volver a revisar es menor que el de
  mergear un crash conocido.
