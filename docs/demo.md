# Guion de demo · Energy Ops Hub

Vídeo de 3 minutos para el README (se graba cuando el entorno local esté preparado). Estructura
de [docs/spec.md](spec.md), sección 24, ajustada a lo que el proyecto tiene construido hoy.

> Nota honesta: el guion original reservaba el minuto 2:20 al **copiloto**. El copiloto (feature
> 10) aún no está construido, así que ese tramo muestra la evaluación y la calidad. Cuando la
> feature 10 exista, se recupera su tramo.

## Guion

| Tiempo | Qué decir | Qué mostrar |
|---|---|---|
| **0:00 – 0:30** | «Laura gestiona los suministros de varios clientes inmobiliarios. Recibe decenas de facturas en PDF de comercializadoras distintas y las copia a mano; las altas nuevas llegan en un Excel con CUPS mal escritos y se enteran semanas después.» | El diagrama de arquitectura ([docs/arquitectura.md](arquitectura.md)) o el diagrama del README. |
| **0:30 – 1:15** | «Un flujo de n8n escucha el buzón y manda cada PDF a la API. El LLM lo convierte en un esquema fijo y once reglas en código detectan anomalías: duplicadas, totales que no cuadran, consumos disparados…» | Enviar un email con **2 facturas** (una duplicada o con el total manipulado). Ver el flujo **F1** ejecutarse en n8n y la respuesta de `POST /facturas` con la anomalía detectada. |
| **1:15 – 1:40** | «Las anomalías graves se convierten en tickets en HubSpot, asociados a la empresa, para que el equipo las gestione donde ya trabaja.» | El **ticket** en HubSpot, con la empresa asociada y el detalle de la regla que lo disparó. |
| **1:40 – 2:20** | «Para las altas, el equipo trabaja en una hoja de Google. El menú valida los CUPS antes de enviar nada, y las altas válidas se crean como negocios en HubSpot. Un flujo diario avisa de las paradas más de una semana.» | En la hoja «Altas»: **«Validar filas»** marca 2 filas en rojo con su motivo; **«Enviar altas válidas»** crea los negocios en HubSpot. (Si da tiempo: pestaña «Resumen» del informe diario.) |
| **2:20 – 2:45** | «Y lo medí: con 120 facturas etiquetadas, la extracción acierta el 100 % de los siete campos, detecta 18 de 18 anomalías inyectadas, con un coste medio de 0,0007 € por factura. Todo con 219 tests y revisión por feature.» | La tabla de [evals/resultados.md](../evals/resultados.md) y el badge de CI en verde del README. |
| **2:45 – 3:00** | «Lo que haría después: el copiloto de solo lectura para las preguntas de Ventas, gas y agua, y validación de consumos con Datadis.» | La sección «Limitaciones y siguientes pasos» del README. |

## Lista de comprobación previa a grabar

- [ ] `docker compose up -d` con API, PostgreSQL y n8n en verde; `/health` responde OK.
- [ ] `.env` con `OPENAI_API_KEY` válida (la extracción real necesita llamar al LLM).
- [ ] Datos de arranque cargados: `uv run python -m scripts.seed`.
- [ ] Dataset sintético presente: `uv run python -m scripts.generate_invoices` (los PDF no se
      versionan).
- [ ] Credenciales de Gmail conectadas en n8n para el flujo F1 y el flujo desactivado tras la
      toma (evita procesar correos reales del buzón).
- [ ] App privada de HubSpot con token y variables `HS_*` en `.env`; pipeline de altas y de
      tickets configurados.
- [ ] Hoja de Google con el script de `apps_script/Code.gs` pegado, el menú cargado y 30 filas
      de prueba (algunas con CUPS mal escritos).
- [ ] Cuenta desactivada o de prueba en la integración de email: nada de datos reales de
      personas o empresas en la grabación.
- [ ] Terminal lista con `evals/resultados.md` y el README abiertos para el tramo final.
- [ ] Ensayo cronometrado de una pasada completa antes de grabar.
