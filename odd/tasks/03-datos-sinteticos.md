# 03 · Datos sintéticos

## Objetivo

Generar con una semilla fija un conjunto de facturas en PDF que parezca real —tres
comercializadoras con maquetaciones distintas— junto con su verdad esperada, para poder medir la
extracción del LLM (feature 06) y probar las reglas de anomalías (feature 05) sin usar datos de
nadie.

## Problema

No hay forma de evaluar la extracción ni de demostrar la detección de anomalías sin un conjunto
etiquetado. Y con datos reales no se puede: son de terceros y no se pueden versionar.

Cita literal de `docs/spec.md`, secciones 8 y 22:

> No uses facturas reales de nadie. Genera las tuyas con `scripts/generate_invoices.py` y
> **reportlab**:
>
> - **3 comercializadoras ficticias** con maquetaciones diferentes: "Voltia Energía", "Luminar
>   Comercializadora" y "Ecoflux". Diferentes posiciones de campos, nombres de conceptos ("Término
>   de potencia" frente "Potencia contratada"), una con tabla y otra con texto corrido. Esto es lo
>   que justifica usar un LLM en vez de plantillas fijas.
> - **3 clientes** de sectores distintos y unos **40 suministros** con CUPS válidos (generados con
>   la función de la sección 10).
> - **~120 facturas** (unos 6 meses), de las que un 15 % llevan **anomalías inyectadas a
>   propósito**: duplicadas, total que no cuadra, consumo disparado, lecturas estimadas seguidas,
>   potencia distinta de la contratada, CUPS fuera de cartera.
> - Por cada PDF, un **JSON con los valores esperados** (ground truth) en `evals/dataset/`, que
>   usarás para medir la extracción.

> | 03 | `03-datos-sinteticos` | `feat/03-datos-sinteticos` | Generador de PDFs con 3 maquetaciones y ground truth | Medio | 120 facturas con un 15 % de anomalías inyectadas, regenerables con una semilla fija | |

## Alcance

- **Dentro**: `scripts/generate_invoices.py` (Python + reportlab), la dependencia en el grupo
  `dev`, el conjunto generado en `evals/dataset/` (con un JSON de verdad esperada por PDF; **no se
  versiona**, se regenera) y los tests del generador.
- **Fuera**: llamar al LLM (feature 04), las reglas R1–R11 (feature 05), `run_evals.py` (feature
  06) y las capturas o gráficos del README.

## Checklist

- [x] T1 dependencia `reportlab` en el grupo `dev` y esqueleto del generador determinista
- [x] T2 datos coherentes: 3 clientes y 40 suministros reutilizados de `scripts/seed.py`, 120
      facturas en 6 meses con estacionalidad e importes internamente coherentes
- [x] T3 tres maquetaciones realmente distintas (tabla, texto corrido y tabla con otro orden y
      otros nombres de concepto)
- [x] T4 inyección del 15 % de anomalías: duplicada, total que no cuadra, consumo disparado,
      lecturas estimadas seguidas, potencia distinta y CUPS fuera de cartera
- [x] T5 verdad esperada por PDF en `evals/dataset/*.json`, con la forma de `FacturaExtraida` más
      las anomalías esperadas
- [x] T6 CLI (`--semilla`, `--limite`, `--salida`) y regeneración byte a byte determinista
- [x] T7 tests: determinismo, coherencia de importes, CUPS válidos, proporción de anomalías y
      presencia de las seis clases
- [ ] T8 verificación, evidencia, RDD y PR

## Criterios de aceptación

- `uv run python -m scripts.generate_invoices` deja 120 PDFs y 120 JSON en `evals/dataset/`.
- Un 15 % de las facturas (18 de 120) lleva al menos una anomalía inyectada y está etiquetada.
- Dos ejecuciones con la misma semilla producen exactamente los mismos archivos.
- Los 40 CUPS pasan `cups_valido` y coinciden con los de `scripts/seed.py`.
- Los importes son internamente coherentes: potencia + energía + impuestos = total (salvo en las
  facturas donde el descuadre es justamente la anomalía).
- Ningún dato real: todos los NIF, CUPS y direcciones son ficticios.

## Evidencia

- **T1–T7 (implementación)** la hizo un worker con el documento como contrato. `reportlab 5.1.0`
  en el grupo `dev`; `scripts/generate_invoices.py` con tres renderizados distintos;
  `tests/test_generate_invoices.py`.
- **T2 datos**: `uv run python -m scripts.generate_invoices` → `120 facturas: 120 PDFs y 120 JSON
  en evals\dataset (0.36 MB)`. Comprobado por separado: 120+120 archivos, 364 KB en total, y los
  CUPS coinciden con los de `scripts/seed.py`.
- **T3 maquetaciones**: inspeccionado el texto extraído de un PDF de cada comercializadora con
  `pdfplumber` (instalado de forma transitoria, sin tocar el proyecto):
  - Ecoflux: tabla con `Potencia pico facturada`, `Cargo por energía` **antes** que
    `Cargo por potencia`, `Alquiler de contador`, `IMPORTE TOTAL` arriba y CUPS/periodo abajo.
  - Luminar: texto corrido, `potencia contratada`, `consumo de energía activa de 5.108,42 kWh`,
    `La lectura de este periodo ha sido de carácter real`.
  - Voltia: cabecera en líneas (`Número de factura`, `CUPS`, `Lectura: real`) y tabla de conceptos.
  Los tres formatos comparten datos pero no estructura, etiquetas ni orden.
- **T4 anomalías**: 18 de 120 (15,0 %), tres de cada clase: `duplicada`, `total_no_cuadra`,
  `consumo_disparado`, `lecturas_estimadas_seguidas`, `potencia_distinta`, `cups_fuera_cartera`.
  Comprobado contra los JSON: 3 claves de negocio duplicadas, 0 CUPS inválidos, 3 fuera de cartera
  y **0 descuadres no etiquetados**.
- **T5 verdad esperada**: los 120 JSON tienen exactamente las 15 claves de `FacturaExtraida` más
  `anomalias_esperadas` y `tipo_anomalia`; `confianza` 1.0 y `campos_dudosos` vacío (extracción
  ideal, que es el techo contra el que se mide la feature 06).
- **T6 determinismo**: dos ejecuciones en directorios distintos dan **los 240 archivos idénticos
  byte a byte** (SHA-256 comparado por archivo).
- **T7 tests**: `uv run pytest` → `42 passed` (10 del generador, 31 previos). `uv run ruff check .`
  → `All checks passed!` · `uv run mypy app scripts tests` → `Success: no issues found in 17 source
  files` · cobertura de `app/` sin cambios: 97 %.
- **Defecto encontrado en la verificación del orquestador y corregido**: la factura `duplicada`
  copiaba clave de negocio, periodo, consumo y precios del original pero **no** su
  `fecha_emision`, así que tres «duplicados de mayo» aparecían emitidos en agosto, septiembre y
  octubre (retrasos de 66, 95 y 125 días). Corregido en `_aplicar_anomalia`; ahora el retraso de
  emisión es de 2 a 6 días en las 120 facturas y hay dos tests que lo fijan
  (`test_la_duplicada_es_el_mismo_documento_que_su_original`,
  `test_las_fechas_de_emision_son_plausibles`).
- **Dataset fuera de git**: tras la decisión, el árbol de trabajo lo conserva pero `git ls-files
  evals/` no devuelve nada; el candidato de revisión baja de 245 archivos y 12 542 líneas a 6
  archivos y ~1 150 líneas. Como la generación es determinista, el dataset es reproducible sin
  versionarlo.

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.
- 2026-11-04 T1–T7 implementados por el worker y verificados por el orquestador; dataset de
  120 PDFs y 120 JSON commiteado.
- 2026-11-04 defecto de la fecha de emisión de las duplicadas corregido y fijado con tests.

## Siguiente paso

T8: RDD de la feature (una lente, riesgo medio), PR a `dev` y merge. Después, feature 04
(`04-extraccion-facturas`), que debe generar el dataset antes de medir nada.

## Git

- Rama: `feat/03-datos-sinteticos`
- PR: (pendiente)

## Decisiones

- **Agua fuera del dataset**: los dos suministros de agua de `seed.py` no generan facturas; las
  tres maquetaciones son las tres comercializadoras que fija la spec y las facturas son de luz y
  gas.
- **Selección de suministros**: 4 de gas + 10 en 3.0TD + 6 viviendas 2.0TD muestreadas con la
  semilla, para llegar a 20 suministros × 6 meses = 120 facturas exactas y estables.
- **`impuestos_otros` incluye el IVA**, como describe la sección 9, de modo que
  `potencia + energía + impuestos_otros = total` es lo que comprueba R5.
- **`potencia_kw` de la verdad esperada = la impresa en el PDF** (la facturada). R8 se detecta
  comparando contra la potencia del suministro en la base de datos, no contra el propio PDF.
- **Solo se etiqueta la anomalía primaria**. Una duplicada también dispara R4 (periodo solapado)
  por diseño; la feature 06 lo tratará como regla secundaria esperada y no como falsa alarma.
- **Fechas fijas** (periodos de mayo a octubre de 2026, emisión 2–6 días después del cierre, tope
  04/11/2026): el generador nunca usa `datetime.now()`, que es lo que lo hace determinista.
- **`explicit_package_bases = true` en mypy**: `scripts/` es un namespace package sin
  `__init__.py`, y sin esa opción mypy resuelve `scripts/seed.py` como `seed` y `scripts.seed` a la
  vez y aborta en cualquier invocación.
- **`canvas.rl_config.invariant = 1`** fija la fecha de creación y el ID interno del PDF; es lo que
  permite que dos ejecuciones den archivos idénticos byte a byte.
- **El dataset no se versiona** (decisión del humano, 2026-11-04). Son 240 archivos generados de
  696 KB: la primera revisión RDD de esta feature **no se pudo ni crear** porque excedía el
  presupuesto de contexto del revisor (`lens_context_budget_exceeded`). Al ser determinista, el
  dataset es un producto de build: `evals/dataset/` está en `.gitignore` y quien lo necesita lo
  regenera con `uv run python -m scripts.generate_invoices`. La feature 06 lo genera antes de
  medir y la feature 12 lo documenta en el README.

## RDD

- (pendiente)
