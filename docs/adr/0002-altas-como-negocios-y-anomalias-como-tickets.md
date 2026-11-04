# ADR 0002 · Altas como negocios y anomalías como tickets en HubSpot

- Estado: aceptado
- Fecha: 2026-11 (feature 07)
- Documento ODD: [odd/tasks/07-hubspot.md](../../odd/tasks/07-hubspot.md) · PR
  [#9](https://github.com/aam9063/Energy-Ops-Hub/pull/9)

## Contexto

El equipo de operaciones ya vive en HubSpot: ve negocios, mueve fases y gestiona tickets. Lo
natural sería crear objetos a medida («alta de suministro», «anomalía»), pero el **plan
gratuito de HubSpot no incluye objetos personalizados**. Quedaban dos caminos: inventar
convenciones sobre objetos existentes o dejar las altas y las anomalías solo en la base de datos
propia.

## Decisión

- **Un alta de suministro es un negocio (deal)** en el pipeline configurado por variables
  `HS_*`. El estado comercial lo mueve el equipo en HubSpot; los datos técnicos (CUPS, tarifa,
  potencia) son fuente de verdad de PostgreSQL y se sincronizan de vuelta con polling
  ([ADR 0003](0003-polling-incremental-en-lugar-de-webhooks.md)).
- **Una anomalía de severidad alta es un ticket** asociado a la empresa del cliente. Energy Ops
  la crea (de forma idempotente: si ya existe, devuelve el ID guardado); HubSpot gestiona su
  ciclo de vida.
- La idempotencia se apoya en IDs externos guardados en nuestra base de datos
  (`hubspot_deal_id`, `hubspot_ticket_id`) y en búsquedas por claves únicas antes de crear.

## Consecuencias

- Buenas: cero adopción nueva para el equipo (mira el CRM que ya usa), y el pipeline de altas da
  gratis fases, vistas y asignaciones.
- Costes: los objetos genéricos no permiten campos tan ricos como un objeto propio (los detalles
  técnicos viven en la API), y el mapeo pipeline/fases depende de variables de entorno que hay
  que configurar en cada entorno.
- Si el proyecto se mudara a un plan con objetos personalizados, esta decisión se revisaría; el
  cliente API está aislado en `app/services/hubspot.py` para que el cambio sea local.
