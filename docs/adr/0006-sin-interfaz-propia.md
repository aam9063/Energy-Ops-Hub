# ADR 0006 · Sin interfaz propia

- Estado: aceptado
- Fecha: 2026-11 (features 08 y 09)
- Documentos ODD: [odd/tasks/08-apps-script.md](../../odd/tasks/08-apps-script.md) (PR
  [#10](https://github.com/aam9063/Energy-Ops-Hub/pull/10)) y
  [odd/tasks/09-flujos-n8n.md](../../odd/tasks/09-flujos-n8n.md) (PR
  [#11](https://github.com/aam9063/Energy-Ops-Hub/pull/11))

## Contexto

Una aplicación así «debería» tener una web: formularios de altas, listado de anomalías,
dashboards. Pero los usuarios de este problema no van a abrir una herramienta nueva: Laura ya
trabaja en Google Sheets (donde le llegan los Excel de altas), en HubSpot (donde mueve fases y
tickets) y en el email (donde llegan las facturas y las preguntas). Cada interfaz nueva es
fricción de adopción y una superficie más que mantener.

## Decisión

- **No se construye ninguna interfaz web propia.** La automatización vive dentro de las
  herramientas que el equipo ya usa:
  - **Google Sheets + Apps Script** como interfaz de las altas masivas: menú «Energy Ops» con
    validación, envío y actualización de estados, directamente en la hoja donde trabaja el
    equipo ([ADR 0001](0001-logica-en-python-orquestacion-en-n8n.md): la validación real vive en
    la API).
  - **HubSpot** como interfaz comercial: negocios de altas y tickets de anomalías.
  - **Email y chat de n8n** como canales de aviso y, en el futuro, del copiloto de solo lectura
    ([ADR 0005](0005-copiloto-de-solo-lectura.md)).
- La única «interfaz técnica» es la documentación automática de la API (`/docs` de FastAPI), para
  desarrollo y demo.

## Consecuencias

- Buenas: adopción casi nula (el usuario no cambia de herramienta), menos superficie que
  testear y mantener, y la demo se entiende sin explicar un producto nuevo.
- Costes: las capacidades quedan limitadas a lo que cada herramienta permite (por ejemplo, el
  coloreado de errores en la hoja es Apps Script, no la API), y un dashboard de anomalías «de
  verdad» no existe: se consulta por API o se mira en HubSpot.
- Si algún día el volumen lo justifica, un panel se construiría sobre los endpoints de reportes
  existentes, sin tocar el dominio.
