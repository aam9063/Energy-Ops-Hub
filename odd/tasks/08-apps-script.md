# 08 · Altas masivas desde Google Sheets (Apps Script)

## Objetivo

Que Laura pegue cincuenta viviendas nuevas en una hoja, pulse un menú y sepa fila a fila qué está
mal antes de enviar nada, y que las altas válidas lleguen a la API en un solo lote idempotente.

## Problema

Hoy las filas llegan con el CUPS mal escrito o sin datos, y se entera semanas después, cuando la
solicitud se rechaza. La validación tiene que pasar **antes** del envío, en la herramienta que ya
usa, y sin que un error de una fila tumbe el resto del lote.

Cita literal de `docs/spec.md`, sección 11:

> Una hoja "Altas" con columnas fijas: `cliente_nif | cups | tipo | direccion | tarifa_acceso |
> potencia_kw | estado | mensaje`. En el menú aparece **Energy Ops** con tres opciones:
>
> 1. **Validar filas**: comprueba en la propia hoja formato de CUPS, campos obligatorios y duplicados,
>    y colorea en rojo las filas con error, con el motivo en `mensaje`.
> 2. **Enviar altas válidas**: manda a la API solo las filas validadas y sin enviar, y escribe el
>    resultado fila a fila.
> 3. **Actualizar estados**: trae de la API el estado actual de cada CUPS.
>
> Además, un **activador diario** genera la pestaña "Resumen" y envía un email con las altas paradas.

> | 08 | `08-apps-script-altas` | `feat/08-apps-script-altas` | Menú, validación, envío e informe diario; `POST /altas/lote` | Medio | Una hoja de 30 filas (5 erróneas) se procesa y se marca bien | |

## Alcance

- **Dentro**: `apps_script/Code.gs` (menú, validación en la hoja, envío por lote, actualización de
  estados e informe diario), `apps_script/appsscript.json`, un test de la lógica pura de CUPS que se
  pueda ejecutar con Node, y el paso del CI que lo ejecuta. El endpoint `POST /altas/lote` ya existe
  desde la feature 07.
- **Fuera**: crear la hoja, pegar el script, desplegarlo con `clasp` y exponer la API con un túnel
  (lo hace el humano); el `cd.yml` con `clasp push` (feature 11).

## Checklist

- [ ] T1 `Code.gs` con el menú **Energy Ops** y las tres acciones
- [ ] T2 `validarFilas`: CUPS con BigInt, duplicados en la hoja, campos obligatorios y tipo válido;
  una sola lectura y una sola escritura de la hoja, con los fondos en rojo y el motivo en `mensaje`
- [ ] T3 `enviarAltas`: solo filas `validada`, una sola llamada a `/altas/lote`, resultado por fila
- [ ] T4 `actualizarEstados` e `informeDiario` (pestaña `Resumen` y email con las altas paradas)
- [ ] T5 secretos en Script Properties (`API_URL`, `API_KEY`), nunca en el código
- [ ] T6 `appsscript.json` con los permisos mínimos y la zona horaria de Madrid
- [ ] T7 test de la lógica de CUPS ejecutable con `node`, y paso en el job `integrations` del CI
- [ ] T8 verificación, evidencia, RDD (riesgo medio, una lente), PR y merge

## Criterios de aceptación

- Una hoja de 30 filas con 5 erróneas (CUPS inválido, duplicado en la hoja, sin NIF, sin dirección y
  tipo inválido) queda marcada con su motivo y solo las 25 correctas se envían.
- La validación de CUPS en JavaScript coincide con `cups_valido` de Python en los casos de prueba,
  incluidos el sufijo opcional, los espacios y las minúsculas.
- El envío es idempotente: repetirlo no duplica altas.
- `node --check` y el test de Node pasan en CI; el resto del CI sigue igual.
- El código no contiene URL, clave ni NIF reales.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.

## Siguiente paso

T1: el menú y la validación.

## Git

- Rama: `feat/08-apps-script`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
