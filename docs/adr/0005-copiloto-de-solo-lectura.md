# ADR 0005 · Copiloto de solo lectura

- Estado: aceptado (decisión de diseño; **implementación pendiente**, feature 10 del plan)
- Fecha: 2026-11
- Especificación: [docs/spec.md](../spec.md), sección 14 (Módulo F)

## Contexto

El último dolor del día a día son las interrupciones: Ventas pregunta «¿cuánto pagó este
edificio el último trimestre?» o «¿por qué está parada el alta de tal vivienda?». Un agente con
acceso a la base de datos puede responder, pero un agente **con permisos de escritura** puede
resolver o descartar anomalías, tocar suministros o mover datos de HubSpot por una mala
interpretación del lenguaje natural. En un sistema donde la fuente de verdad técnica es una base
de datos compartida, un falso positivo del agente es un incidente de datos, no un error de chat.

## Decisión

- El copiloto (flujo F4 de n8n) será **de solo lectura**: sus herramientas son consultas
  (`GET /reportes/cliente/{nif}`, fichas de suministro, estados de altas y anomalías). Ninguna
  herramienta de escritura se le expone, ni siquiera «por comodidad».
- Las acciones que modifican estado (resolver una anomalía, lanzar una tarea) siguen siendo
  decisiones humanas desde la API o el CRM.
- El agente vive en el chat de n8n, la herramienta que ya se usa para los avisos, sin interfaz
  propia ([ADR 0006](0006-sin-interfaz-propia.md)).

## Consecuencias

- Buenas: el peor caso del copiloto es una respuesta errónea o incompleta, no un dato
  corrupto; no necesita permisos de escritura en la API ni en HubSpot; la auditoría de cambios
  queda intacta.
- Costes: el copiloto no puede «terminar» tareas, solo informar; si el equipo pide que actúe,
  se estudiará un permiso de escritura acotado con confirmación explícita, nunca implícito.
- Nota honesta: a fecha de este documento el flujo F4 **no está construido todavía**; esta
  decisión fija su diseño para la feature 10.
