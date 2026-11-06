# 05 · Reglas de anomalías

## Objetivo

Que cada factura que entra se contrastе contra once reglas puras y testeables, y que las anomalías
queden guardadas, consultables y resolubles por la API.

## Problema

Una factura puede estar bien extraída y seguir siendo un problema: el total no cuadra, el consumo
se dispara, es un duplicado, la potencia no es la contratada o el CUPS no está en cartera. Javier
hoy lo detecta «a ojo». Las reglas convierten ese ojo en algo que se ejecuta siempre, igual y con
un motivo escrito.

Cita literal de `docs/spec.md`, sección 10:

> | ID | Regla | Severidad | Lógica |
> |---|---|---|---|
> | R1 | CUPS inválido | Alta | `cups_valido()` falla |
> | R2 | CUPS fuera de cartera | Media | El CUPS no existe en `suministros` |
> | R3 | Factura duplicada | Alta | Ya existe la misma clave de negocio con distinto archivo |
> | R4 | Periodo solapado | Alta | Otra factura del mismo CUPS con fechas que se solapan |
> | R5 | El total no cuadra | Alta | `potencia + energía + impuestos_otros` difiere del total en más de 0,05 € |
> | R6 | Consumo atípico | Media | Consumo diario medio > 2× o < 0,3× la media de los últimos 6 meses (mínimo 3 facturas de histórico) |
> | R7 | Lecturas estimadas seguidas | Media | Esta y la anterior tienen lectura estimada |
> | R8 | Potencia distinta de la contratada | Media | La potencia facturada difiere de la registrada en el suministro |
> | R9 | Precio fuera de rango | Baja | €/kWh de energía ±40 % de la mediana de la cartera para esa tarifa |
> | R10 | Suministro sin facturar | Media | Activo y sin factura en 60 días (se ejecuta como tarea programada, no por factura) |
> | R11 | Revisión de extracción | Media | Confianza baja o campos dudosos |

> Cada regla es una función pura que recibe la factura y el contexto (histórico y suministro) y
> devuelve `None` o una anomalía. Así se testean una a una.

> | 05 | `05-reglas-anomalias` | `feat/05-reglas-anomalias` | Reglas R1 a R11 | Medio | Cada regla con un test que la dispara y otro que no | |

## Alcance

- **Dentro**: `app/domain/rules.py` con las reglas como funciones puras y un tipo `Anomalia`;
  el contexto de evaluación (suministro e histórico); la evaluación de R1–R9 y R11 al ingerir una
  factura; R10 como tarea programada con su endpoint; la persistencia de anomalías sustituyendo la
  R11 que hoy vive dentro de la ingesta; `GET /anomalias` y `PATCH /anomalias/{id}`; y los tests.
- **Fuera**: crear tickets en HubSpot (feature 07), los flujos de n8n (09) y las métricas de
  detección (06).

## Checklist

- [x] T1 `app/domain/rules.py`: `Anomalia` y las reglas como funciones puras con su contexto
- [x] T2 R1–R9 y R11 evaluadas por factura con el histórico real del suministro
- [x] T3 R10 como tarea programada y `POST /tareas/sin-facturar`
- [x] T4 persistencia idempotente de las anomalías en la ingesta (una por regla y factura)
- [x] T5 `GET /anomalias` con filtros `estado`, `severidad`, `cups` y `PATCH /anomalias/{id}` para
  resolver o descartar con comentario
- [x] T6 tests: cada regla con un caso que dispara y otro que no, y la evaluación conjunta
- [x] T7 verificación, evidencia, RDD (riesgo medio, una lente), PR y merge

## Criterios de aceptación

- Cada una de las once reglas tiene un test que la dispara y otro que no.
- R3 y R4 no confunden un duplicado con un solape: R3 es la misma clave de negocio, R4 periodos
  que se pisan con distinto número.
- R6 y R7 no disparan sin histórico suficiente.
- R5 compara con tolerancia de 0,05 € y no dispara cuando falta algún concepto (lo cubre R11).
- La evaluación es pura: recibe datos, no toca la base de datos; el I/O queda en el servicio.
- Reprocesar una factura no duplica sus anomalías.

## Evidencia

- **Implementación**: un worker con este documento como contrato; el orquestador verificó después.
- **T1 pureza**: `app/domain/rules.py` (360 líneas) sin `Session`, `select` ni `httpx`; todo el
  I/O quedó en `app/services/rules.py` (261 líneas).
- **T2/T6 reglas**: `uv run pytest tests/test_rules.py` → **31 tests** puros. Cada regla tiene su
  caso que dispara y otro que no, más los bordes que fija la sección 10: R5 con desviación exacta
  de 0,05 € y con un concepto ausente; R6 con 2 facturas de histórico (no dispara) y con 3;
  R7 sin anterior; R8 con diferencia exacta de 0,01 kW; R9 justo en ±40 %; R10 a 59 y a 61 días;
  `evaluar()` devolviendo `{R1, R2, R5, R11}` para una factura mala y `[]` para una limpia.
- **R3 frente a R4**: dos tests dedicados comprueban que con la misma clave de negocio y el mismo
  periodo **solo** dispara R3, y que con distinta clave y solape **solo** dispara R4.
- **T3/T5 endpoints**: `uv run pytest tests/test_anomalias_api.py` → **16 tests** contra PostgreSQL
  real: filtros y su 422 con `Literal`, `PATCH` resolviendo y descartando con comentario (404 si no
  existe, 422 si el estado no vale), R10 con `POST /tareas/sin-facturar` y su idempotencia, y las
  anomalías de la ingesta (R3, R5, R6) sin duplicarse al reprocesar.
- **T7 verificación del orquestador sobre el merge ya resuelto**: `uv run pytest -q` → **105 passed** ·
  `uv run ruff check .` → `All checks passed!` · `uv run mypy app scripts tests` →
  `Success: no issues found in 29 source files` · cobertura de `app/`: `TOTAL 623 4 99%`, con
  `domain/rules.py`, `services/rules.py`, `routers/anomalias.py` y `routers/tareas.py` al 100 %.
- **Merge con `dev`**: el squash de la 04 en `dev` provocó conflictos en `app/main.py`,
  `app/schemas.py` y `app/services/invoices.py` (contenido idéntico, historia distinta). Se resolvió
  quedándose con el lado de la rama —que es 04 + los cambios de la 05— y se comprobó que el diff
  contra `dev` es exactamente esta feature (10 archivos, 1846 líneas). `tests/conftest.py` no
  aparece en el diff: quedó idéntico al de `dev`.

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.
- 2026-11-04 T1–T6 implementados y verificados; T7 pendiente de RDD y PR.
- 2026-11-04 rama reconciliada con `dev` resolviendo los conflictos del squash de la 04.

## Siguiente paso

T7: RDD (riesgo medio, una lente), PR a `dev` y merge. Después, feature 06 (`06-evals`).

## Git

- Rama: `feat/05-reglas-anomalias` (apilada sobre `feat/04-extraccion-facturas`)
- PR: (pendiente)

## Decisiones

- **R3 en la ruta del duplicado**: la `UNIQUE` de clave de negocio impide insertar la copia, así que
  R3 solo puede dispararse reevaluando la factura **guardada** con la copia nueva como candidata
  (`candidatas_extra`). La reevaluación es idempotente, así que no duplica el resto de reglas.
- **R10 idempotente a mano**: cuelga del suministro, no de una factura, y `UNIQUE (factura_id,
  regla)` no protege filas con `factura_id` NULL (NULL ≠ NULL). El servicio garantiza «como mucho
  una R10 abierta por suministro», de modo que al resolverla puede volver a dispararse con
  trazabilidad.
- **R9 sin tarifa no dispara**: sin `tarifa_acceso` no hay mediana correcta que elegir, así que la
  regla se abstiene en lugar de inventar una referencia.
- **Comparaciones de dinero con `Decimal(str(x))`** en R5, R8 y R9: con `float`, los bordes exactos
  (0,05 €, ±40 %, 0,01 kW) eran inestables y daban falsos negativos.
- **Conocido y no resuelto aquí**: el PDF duplicado **no** deja su `archivo_hash`, porque no se
  inserta fila. Volver a subir el mismo duplicado cuesta otra llamada al LLM (R3 ya está abierta y
  no se duplica nada). Se deja anotado como siguiente paso: un registro de hashes vistos si el
  volumen de duplicados lo justifica.
- **`R10` usa `date.today()`** dentro de la función pura, que es lo que permite que el endpoint no
  reciba la fecha. Los tests usan fechas relativas a hoy; si algún día se quiere congelar el
  calendario, el parámetro ya existe (`dias`) y la fecha se puede inyectar.

## RDD

- Riesgo: **medio** · Lente: `reliability` · Resultado: **aprobado** · Lineage
  `review-2c0c28b3ee26dd65`, 10 archivos y 1932 líneas.
- **Primer intento mal acotado y descartado sin quemar autoridad**: al pasar `dev` como base, el
  proveedor resolvió al merge-base e incluyó la feature 04 ya revisada (21 archivos, 3289 líneas).
  Se rehizo sobre el commit exacto de `dev` (`87888e6`), y el candidato quedó en los 10 archivos de
  esta feature.
- Aviso informativo `R3-sug-cron-determinism`: el reloj entra en R10 con `date.today()`. Está
  documentado en `Decisiones` y la firma ya admite `dias`; si algún día se quiere congelar el
  calendario, la fecha se inyecta y el test no cambia de semántica.
