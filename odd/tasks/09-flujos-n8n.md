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

- [ ] T1 `F1_facturas_email.json`: trigger de email, filtro de PDF, split de adjuntos, `POST /facturas`
  con `X-API-Key`, decisión por severidad alta y creación del ticket en la API
- [ ] T2 `F2_altas_paradas.json`: reloj de días laborables a las 8:30, `GET /altas?parada_dias=7`,
  corte si está vacío, agrupación por cliente y aviso
- [ ] T3 `F3_sync_hubspot.json`: reloj de 15 minutos, `POST /sync/hubspot` y aviso si hay errores
- [ ] T4 JSON sin credenciales, nombres descriptivos y notas adhesivas en los tres flujos
- [ ] T5 `tests/test_n8n_flows.py`: JSON válido, conexiones que apuntan a nodos existentes, sin
  campos de credenciales y endpoints esperados en cada flujo
- [ ] T6 verificación, evidencia, RDD (riesgo medio, una lente), PR y merge

## Criterios de aceptación

- Los tres flujos son JSON válido y el job `integrations` del CI sigue pasando (validación + ausencia
  de credenciales).
- El test nuevo falla si un flujo referencia un nodo inexistente, si aparece una credencial embebida
  o si un flujo pierde su endpoint.
- F1 crea el ticket **llamando a la API**, no con un nodo de HubSpot en n8n: la idempotencia vive en
  Python y está testeada.
- Las URLs de la API salen de una variable/credencial de n8n, nunca escritas en cada nodo.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.

## Siguiente paso

T1–T3: los tres flujos.

## Git

- Rama: `feat/09-flujos-n8n`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
