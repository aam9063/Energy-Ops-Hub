# ADR 0003 · Polling incremental en lugar de webhooks para el MVP

- Estado: aceptado
- Fecha: 2026-11 (feature 07)
- Documento ODD: [odd/tasks/07-hubspot.md](../../odd/tasks/07-hubspot.md) · PR
  [#9](https://github.com/aam9063/Energy-Ops-Hub/pull/9)

## Contexto

El estado de un alta lo mueve el equipo en HubSpot, y nuestra base de datos necesita enterarse.
Webhooks de HubSpot sería lo inmediato: latencia de segundos. Pero un webhook exige una URL
pública, firmas verificadas, reintentos y una cola de eventos: infraestructura que un MVP
autoalojado en local (API en Docker, n8n en Docker) no puede garantizar de forma fiable.

## Decisión

- **Polling incremental**: el flujo F3 de n8n llama cada **15 minutos** a `POST /sync/hubspot`,
  que busca negocios del pipeline modificados desde la última sincronización correcta (filtro
  por `hs_lastmodifieddate`) y actualiza `suministros.estado` y `estado_desde`.
- La marca de tiempo de la última sincronización se guarda en la base de datos, y cada
  sincronización deja rastro en `eventos_sync` para auditar qué entró y qué falló.

## Consecuencias

- Buenas: cero superficie pública expuesta, sin secretos de webhook, y si una tanda falla la
  siguiente la recupera sola (ventana incremental, no se pierde nada).
- Costes: hasta 15 minutos de desfase entre lo que ve el equipo en HubSpot y lo que dice la API;
  para el caso de uso (estados que cambian una vez al día) es aceptable.
- Criterio de revisión: si los estados empiezan a cambiar varias veces al día o la API se
  consume desde más herramientas, se pasa a webhooks; el cambio vive en el flujo F3 y en
  `app/services/hubspot_sync.py`, no en el resto del sistema.
