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

- [x] T1 caché de extracciones en `evals/cache/` indexada por hash del PDF, con `--sin-cache`
- [x] T2 comparación campo a campo con las tolerancias de la sección 16 y normalización de textos
- [x] T3 tabla de precisión por campo y por comercializadora, y coste medio por factura
- [x] T4 recall de anomalías inyectadas, falsas alarmas y desglose por regla
- [x] T5 CLI con `--limite`, `--salida` y salida a Markdown lista para el README
- [x] T6 `evals.yml` manual con environment `evals`, límite por input y resultados en el resumen
- [x] T7 tests del comparador y de las métricas con extracciones simuladas, sin red
- [x] T8 verificación, evidencia, RDD (riesgo medio, una lente), PR y merge

## Criterios de aceptación

- `uv run python -m evals.run_evals --limite 2 --sin-cache` funciona con dos PDFs y escribe la tabla.
- Con caché, una segunda ejecución no vuelve a llamar al modelo: se comprueba por número de claves.
- La tabla trae precisión por campo (CUPS, número, periodo, consumo, importe total, lectura
  estimada), por comercializadora, recall de anomalías, falsas alarmas y coste medio.
- Los tests no hacen red y cubren: campo correcto, campo fuera de tolerancia, texto que difiere
  solo en espacios o mayúsculas, importe en el borde de 0,01 y kWh en el borde de 0,5.
- El workflow no se dispara solo: es `workflow_dispatch` y vive en el environment `evals`.

## Evidencia

- **Implementación**: un worker con este documento como contrato; el orquestador verificó después.
- **T1–T5**: `evals/run_evals.py` con caché `evals/cache/<sha256>.json`, comparador con las
  tolerancias de la sección 16, precisión por campo y por comercializadora, coste medio y métricas
  de anomalías; CLI `--limite/--salida/--semilla/--sin-cache`.
- **T7 tests**: `uv run pytest tests/test_run_evals.py` → **26 tests** sin red: bordes exactos de
  0,01 € y 0,5 kWh, textos que difieren solo en espacios o mayúsculas, caché caliente que no llama
  al modelo, `--sin-cache` sobre una caché envenenada, y las cuatro ramas de anomalías (acierto,
  fallo de recall, falsa alarma y R4 secundaria sobre una duplicada).
- **Suite completa**: `uv run pytest` → **134 passed** · `uv run mypy app scripts tests evals` →
  `Success: no issues found in 32 source files` · `uv run ruff check .` → `All checks passed!` ·
  cobertura de `app/`: `TOTAL 634 4 99%`.
- **Comportamiento sin clave** (esta máquina no tiene `OPENAI_API_KEY`):
  `uv run python -m evals.run_evals --limite 2 --sin-cache` → `exit 1` con el mensaje
  «OPENAI_API_KEY no está configurada…». Es el comportamiento correcto: sin clave no se inventan
  métricas. Lo que ya está en caché se reutiliza sin clave.
- **Sin dataset**: exit 1 con el comando exacto para generarlo.
- **Dos correcciones del orquestador sobre el informe del worker**:
  1. La tabla de precios declaraba «euros» cuando la lista pública de OpenAI está en dólares. Se
     corrigió el comentario y el informe añade la nota «lista en USD usada como EUR; no es una
     conversión de divisa». Mejor un número honesto con letra pequeña que un euro falso.
  2. `evals.yml` usaba `upload-artifact@v4` mientras el resto del CI usa acciones más nuevas; se
     alineó a `v7`.

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.
- 2026-11-05 T1–T7 implementados por el worker y verificados por el orquestador; T8 pendiente.

## Siguiente paso

T8: RDD (riesgo medio, una lente), PR a `dev` y merge. Después, hito **v0.1.0**: los números
reales exigen `OPENAI_API_KEY` y el merge `dev`→`main` es del humano.

## Git

- Rama: `feat/06-evals`
- PR: (pendiente)

## Decisiones

- **La caché guarda la salida completa del modelo**, no solo los campos: así se puede reevaluar el
  comparador sin volver a pagar, que es el motivo por el que la sección 16 la pide.
- **El dataset no se versiona** (decisión de la feature 03), así que un clon nuevo empieza
  generándolo; el mensaje de error ya lo dice con el comando exacto.
- **Precios**: la lista pública de OpenAI está en dólares y se usa como euros, etiquetado en el
  informe; `EVALS_PRECIOS` permite sobreescribir la tabla sin tocar código.
- **Candidatos e histórico solo hacia atrás** en el contexto de las reglas: refleja la ingesta
  cronológica real y evita que una duplicada dispare una R3 falsa contra su original.
- **R4 sobre una duplicada** se cuenta aparte (`secundarias_r4`) y no como falsa alarma, que es lo
  que decidió la feature 05 al inyectar los datos.

## RDD

- (pendiente)
