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
  `dev`, el conjunto generado en `evals/dataset/` con un JSON de verdad esperada por PDF, y los
  tests del generador.
- **Fuera**: llamar al LLM (feature 04), las reglas R1–R11 (feature 05), `run_evals.py` (feature
  06) y las capturas o gráficos del README.

## Checklist

- [ ] T1 dependencia `reportlab` en el grupo `dev` y esqueleto del generador determinista
- [ ] T2 datos coherentes: 3 clientes y 40 suministros reutilizados de `scripts/seed.py`, 120
      facturas en 6 meses con estacionalidad e importes internamente coherentes
- [ ] T3 tres maquetaciones realmente distintas (tabla, texto corrido y tabla con otro orden y
      otros nombres de concepto)
- [ ] T4 inyección del 15 % de anomalías: duplicada, total que no cuadra, consumo disparado,
      lecturas estimadas seguidas, potencia distinta y CUPS fuera de cartera
- [ ] T5 verdad esperada por PDF en `evals/dataset/*.json`, con la forma de `FacturaExtraida` más
      las anomalías esperadas
- [ ] T6 CLI (`--semilla`, `--limite`, `--salida`) y regeneración byte a byte determinista
- [ ] T7 tests: determinismo, coherencia de importes, CUPS válidos, proporción de anomalías y
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

- (pendiente)

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1–T7: implementación del generador y sus tests.

## Git

- Rama: `feat/03-datos-sinteticos`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
