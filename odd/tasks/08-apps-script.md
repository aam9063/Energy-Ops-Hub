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

- [x] T1 `Code.gs` con el menú **Energy Ops** y las tres acciones
- [x] T2 `validarFilas`: CUPS con BigInt, duplicados en la hoja, campos obligatorios y tipo válido;
  una sola lectura y una sola escritura de la hoja, con los fondos en rojo y el motivo en `mensaje`
- [x] T3 `enviarAltas`: solo filas `validada`, una sola llamada a `/altas/lote`, resultado por fila
- [x] T4 `actualizarEstados` e `informeDiario` (pestaña `Resumen` y email con las altas paradas)
- [x] T5 secretos en Script Properties (`API_URL`, `API_KEY`), nunca en el código
- [x] T6 `appsscript.json` con los permisos mínimos y la zona horaria de Madrid
- [x] T7 test de la lógica de CUPS ejecutable con `node`, y paso en el job `integrations` del CI
- [x] T8 verificación, evidencia, RDD, PR y merge

## Criterios de aceptación

- Una hoja de 30 filas con 5 erróneas (CUPS inválido, duplicado en la hoja, sin NIF, sin dirección y
  tipo inválido) queda marcada con su motivo y solo las 25 correctas se envían.
- La validación de CUPS en JavaScript coincide con `cups_valido` de Python en los casos de prueba,
  incluidos el sufijo opcional, los espacios y las minúsculas.
- El envío es idempotente: repetirlo no duplica altas.
- `node --check` y el test de Node pasan en CI; el resto del CI sigue igual.
- El código no contiene URL, clave ni NIF reales.

## Evidencia

- **Implementación**: un worker con este documento como contrato; el orquestador verificó después.
- **T1–T2**: `apps_script/Code.gs` con el menú **Energy Ops**, `cupsValido_` con `BigInt` y
  `validarFilas()` con **una** lectura (`getDataRange().getValues()`), **una** escritura
  (`setValues`) y los fondos en un solo `setBackgrounds`; las filas ya `enviada` no se tocan.
- **T3–T4**: `enviarAltas()` en una sola llamada a `/altas/lote` con `muteHttpExceptions`, y
  `actualizarEstados()` + `informeDiario()` consumiendo el `GET /altas` real.
- **T5–T6**: secretos por `Script Properties` (`API_URL`, `API_KEY`), sin URL ni clave en el código;
  `appsscript.json` con `Europe/Madrid`, V8 y solo los scopes necesarios.
- **T7**: `node apps_script/test_cups.js` → **19/19 casos**, y paso nuevo en el job `integrations`
  del CI que lo ejecuta (tolerante a que el archivo no exista todavía). `node --check` sobre
  `Code.gs` copiado a `.js` → OK; el `.gs` directo falla por la extensión, que es justo el motivo
  del paso de copia que ya tenía el CI.
- **Hallazgo del worker que obligó a corregir el backend**: `POST /altas/lote` pedía `nif` y no
  aceptaba `fila`, mientras la sección 11 manda `cliente_nif` y `fila`; y **`GET /altas` no
  existía** aunque la sección 15 lo define y el script lo necesita. Con eso, el `Code.gs` de la spec
  habría recibido 422 en todas las filas. Se alineó la API a la spec: `FilaAlta` con
  `fila: int` y `cliente_nif` (alias `nif` aceptado por compatibilidad), `ResultadoFila.fila` como
  eco exacto —probado con un lote desordenado `[10, 5, 7, 3]`— y el endpoint `GET /altas` con
  `parada_dias`, `{cups, cliente, estado, dias_parada}` y orden por antigüedad.
- **Verificación del orquestador**: `uv run pytest` → **158 passed** · `uv run mypy app scripts
  tests evals` → `Success: no issues found in 41 source files` · `uv run ruff check .` → `All checks
  passed!` · cobertura de `app/`: `TOTAL 990 30 97%` · `node apps_script/test_cups.js` → `19/19`.
- **El script no compilaba en Apps Script (2026-11-05)**: al pegarlo en la hoja, el editor devolvió
  `ParseError: Unexpected token ILLEGAL, línea: 75`, que era `Number(BigInt(m[1]) % 529n)`. El
  runtime V8 de Apps Script incluye `BigInt()`, pero **el parser del editor no admite la sintaxis de
  literal** (`529n`): es una limitación documentada del editor, y no se ve en Node, que sí la acepta. Se sustituyó por `restoModulo_(digitos, 529)`, un módulo dígito a dígito que nunca
  sale del rango seguro de `Number`.
- **El fallo quedó cubierto por un test que sí corre en Node**: `apps_script/test_cups.js` falla si
  `Code.gs` vuelve a usar un literal BigInt (ignorando comentarios) y añade dos casos de precisión:
  `ES9999999999999999SA` es válido y `ES9999999999999999SG` no, porque la misma cuenta con `Number`
  daría `SG`. `node apps_script/test_cups.js` → `21/21`, y `app/domain/cups.py` coincide en los
  cuatro CUPS de control.
- **Sin otras construcciones en riesgo**: `Code.gs` no usa `?.`, `??`, `.at(`, `flatMap`,
  `replaceAll`, `fromEntries`, `padStart` ni `structuredClone`, así que no queda sintaxis que el
  parser del editor pueda rechazar.

## Progreso

- 2026-11-05 documento creado antes del primer cambio de código.
- 2026-11-05 T1–T7 implementados por el worker; la alineación del contrato de altas y el endpoint
  `GET /altas` entraron en la misma entrega. Falta T8.
- 2026-11-05 primer uso real en una hoja de Google: el script no compilaba por un literal BigInt.
  Corregido y fijado con un test que corre en Node.

## Siguiente paso

T8: RDD (riesgo medio, una lente), PR a `dev` y merge. Después, feature 09: los flujos de n8n, cuyo
F2 ya puede usar `GET /altas`.

## Git

- Rama: `feat/08-apps-script`
- PR: (pendiente)

## Decisiones

- **Manda la spec**: cuando el worker detectó que la API pedía `nif` y no aceptaba `fila`, se cambió
  el backend, no el script. El script de la sección 11 es el contrato con el usuario.
- **El alias `nif` se conserva** con `AliasChoices` para no romper a quien ya lo usara, pero el campo
  canónico y documentado es `cliente_nif`; un test pinnea el alias para que no se caiga por descuido.
- **`ResultadoFila.fila` es eco exacto**, no la posición en el lote: la hoja necesita saber dónde
  escribir y un lote desordenado no puede confundirla.
- **`GET /altas` sin `parada_dias` devuelve todas las altas en trámite**, y con el filtro aplica
  «más de N días» de forma estricta. Es lo que usan la opción 3 del menú y el informe diario, y
  también el flujo F2 de n8n.
- **El Apps Script no inventa endpoints**: si la API falla, avisa con el código HTTP y no toca los
  datos de la hoja. Preferible un mensaje claro a un estado inventado.

## RDD

- Riesgo: **alto** (el proveedor detectó el shell nuevo del CI) · Lentes: **4R** · Resultado:
  **aprobado** · Lineage `review-c945787518a9706d`, 9 archivos y 737 líneas.
- El candidato ya venía corregido de dos hallazgos propios: el contrato de `POST /altas/lote` y la
  falta de `GET /altas`. Esta revisión miró el conjunto ya alineado con la spec.
- Cinco avisos informativos, ninguno bloqueante: tres sobre `app/routers/altas.py:144-177` y
  `app/schemas.py:118-122` (validación y forma del lote), uno en `apps_script/Code.gs:173` y otro en
  `app/routers/altas.py:144-176` sobre el endpoint nuevo. Quedan como trabajo posterior.
- **Lección de proceso**: el worker paró dos veces antes de escribir una línea, porque la lista de
  superficies es autoridad en su contrato y yo la había dejado desactualizada y luego con prosa
  dentro del bloque. Parar fue lo correcto; la corrección era mía.
- **Segunda revisión, del arreglo del BigInt (2026-11-05)**: riesgo **medio** (cambio ejecutable en
  `apps_script/Code.gs`), lente `reliability`, 6 archivos y 127 líneas, lineage
  `review-19a79f17b42e0a2d`. Resultado: **aprobado** y autoridad quemada.
- **Defecto de proceso, anotado a propósito**: el commit del arreglo (`c999039`, PR #19) se mergeó
  en `dev` **antes** de pasar esta revisión, aunque el cuerpo del PR declaraba riesgo medio y la
  lente. La revisión se lanzó después, sobre el mismo candidato, y aprobó. Para un cambio de dominio
  eso no es aceptable como rutina: el orden correcto es revisión, luego merge. Sí funcionó como red
  de seguridad, que es mejor que nada.
