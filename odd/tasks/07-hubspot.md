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

- [ ] T1 cliente HubSpot con httpx, timeout y reintento exponencial en 429/5xx
- [ ] T2 `buscar_uno` y `upsert_deal_alta` idempotentes por `cups` y por `hubspot_deal_id`
- [ ] T3 `crear_ticket_anomalia` idempotente por `energy_ops_id`, con asociación a la empresa
- [ ] T4 `POST /altas/lote` idempotente por CUPS, con resultado por fila y resumen
- [ ] T5 `POST /anomalias/{id}/ticket` (crea o devuelve el ticket) y guarda `hubspot_ticket_id`
- [ ] T6 `POST /sync/hubspot` incremental por `hs_lastmodifieddate`, actualizando `estado` y
  `estado_desde`, con marca de última sincronización correcta
- [ ] T7 auditoría en `eventos_sync` de cada operación con HubSpot, sin datos personales
- [ ] T8 tests con `respx`: dos upserts no duplican, 429 se reintenta, se asocia a la empresa,
  el sync no retrocede estados y un error de HubSpot no pierde la fila local
- [ ] T9 verificación, evidencia, RDD (riesgo alto, 4 lentes), PR y merge

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

- (pendiente)

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.

## Siguiente paso

T1: el cliente.

## Git

- Rama: `feat/07-hubspot`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
