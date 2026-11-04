# 06 · Evaluación del LLM

## Objetivo

Medir con números la extracción y la detección de anomalías sobre el conjunto sintético, y dejar
esos números en el README: precisión por campo y por comercializadora, recall de anomalías, falsas
alarmas y coste medio por factura.

## Problema

Hasta ahora lo único cierto es que el esquema valida. Nadie sabe si el modelo lee bien el importe
total de Ecoflux o si confunde el consumo con la potencia. Sin medir, «funciona» es una opinión; y
la decisión de producto del umbral de confianza (0,85) tampoco tiene respaldo.

Cita literal de `docs/spec.md`, sección 16:

> 1. Recorre `evals/dataset/*.pdf` y su JSON esperado.
> 2. Llama a `extraer_factura` (y guarda la salida cruda en caché para no repetir llamadas).
> 3. Compara campo a campo: igualdad exacta en textos normalizados (CUPS, número), tolerancia de
>    0,01 en importes y 0,5 en kWh, igualdad en fechas.
> 4. Imprime una tabla de precisión por campo y por comercializadora, más el coste medio por
>    factura.
> 5. Comprueba cuántas anomalías inyectadas detecta el sistema completo (extracción + reglas) y
>    cuántas falsas alarmas da.

> | 06 | `06-evals` | `feat/06-evals` | `run_evals.py` y `evals.yml` | Medio | Tabla de precisión por campo y recall de anomalías en el README | **v0.1.0** |

## Alcance

- **Dentro**: `evals/run_evals.py` con la caché de extracciones, la comparación campo a campo con
  las tolerancias de la sección 16, el cálculo de recall y falsas alarmas de anomalías, la tabla en
  Markdown, el CLI (`--limite`, `--salida`, `--semilla`, `--sin-cache`) y `.github/workflows/evals.yml`
  manual con environment `evals`. Tests del comparador y del cálculo de métricas, sin red.
- **Fuera**: rellenar las tablas del README con números reales (necesita `OPENAI_API_KEY`, que la
  aporta el humano), el ADR del umbral de confianza (feature 12) y cualquier mejora del prompt que
  salga de los resultados: si la evaluación revela un campo flojo, se abre un `fix/` aparte.

## Checklist

- [ ] T1 caché de extracciones en `evals/cache/` indexada por hash del PDF, con `--sin-cache`
- [ ] T2 comparación campo a campo con las tolerancias de la sección 16 y normalización de textos
- [ ] T3 tabla de precisión por campo y por comercializadora, y coste medio por factura
- [ ] T4 recall de anomalías inyectadas, falsas alarmas y desglose por regla
- [ ] T5 CLI con `--limite`, `--salida` y salida a Markdown lista para el README
- [ ] T6 `evals.yml` manual con environment `evals`, límite por input y resultados en el resumen
- [ ] T7 tests del comparador y de las métricas con extracciones simuladas, sin red
- [ ] T8 verificación, evidencia, RDD (riesgo medio, una lente), PR y merge

## Criterios de aceptación

- `uv run python -m evals.run_evals --limite 2 --sin-cache` funciona con dos PDFs y escribe la tabla.
- Con caché, una segunda ejecución no vuelve a llamar al modelo: se comprueba por número de claves.
- La tabla trae precisión por campo (CUPS, número, periodo, consumo, importe total, lectura
  estimada), por comercializadora, recall de anomalías, falsas alarmas y coste medio.
- Los tests no hacen red y cubren: campo correcto, campo fuera de tolerancia, texto que difiere
  solo en espacios o mayúsculas, importe en el borde de 0,01 y kWh en el borde de 0,5.
- El workflow no se dispara solo: es `workflow_dispatch` y vive en el environment `evals`.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1: la caché y el recorrido del dataset.

## Git

- Rama: `feat/06-evals`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
