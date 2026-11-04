# 05 · Reglas de anomalías

## Objetivo

Que cada factura que entra se contrastе contra once reglas puras y testeables, y que las anomalías
queden guardadas, consultables y resolubles por la API.

## Problema

Una factura puede estar bien extraída y seguir siendo un problema: el total no cuadra, el consumo
se dispara, es un duplicado, la potencia no es la contratada o el CUPS no está en cartera. Laura
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

- [ ] T1 `app/domain/rules.py`: `Anomalia` y las reglas como funciones puras con su contexto
- [ ] T2 R1–R9 y R11 evaluadas por factura con el histórico real del suministro
- [ ] T3 R10 como tarea programada y `POST /tareas/sin-facturar`
- [ ] T4 persistencia idempotente de las anomalías en la ingesta (una por regla y factura)
- [ ] T5 `GET /anomalias` con filtros `estado`, `severidad`, `cups` y `PATCH /anomalias/{id}` para
  resolver o descartar con comentario
- [ ] T6 tests: cada regla con un caso que dispara y otro que no, y la evaluación conjunta
- [ ] T7 verificación, evidencia, RDD (riesgo medio, una lente), PR y merge

## Criterios de aceptación

- Cada una de las once reglas tiene un test que la dispara y otro que no.
- R3 y R4 no confunden un duplicado con un solape: R3 es la misma clave de negocio, R4 periodos
  que se pisan con distinto número.
- R6 y R7 no disparan sin histórico suficiente.
- R5 compara con tolerancia de 0,05 € y no dispara cuando falta algún concepto (lo cubre R11).
- La evaluación es pura: recibe datos, no toca la base de datos; el I/O queda en el servicio.
- Reprocesar una factura no duplica sus anomalías.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1: `app/domain/rules.py`.

## Git

- Rama: `feat/05-reglas-anomalias` (apilada sobre `feat/04-extraccion-facturas`)
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
