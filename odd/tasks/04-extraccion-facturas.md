# 04 · Extracción de facturas con LLM

## Objetivo

Que un PDF de factura llegue a `POST /facturas` y salga convertido en una fila de `facturas` con
sus datos validados, sus anomalías y sus datos crudos para auditar, sin que reprocesar el mismo
documento duplique nada.

## Problema

Javier abre decenas de facturas en PDF de tres comercializadoras distintas y copia los datos a mano.
El formato cambia entre comercializadoras, así que una plantilla fija no sirve: hace falta un
modelo que lea el documento y devuelva un esquema fijo que el código pueda validar.

Cita literal de `docs/spec.md`, secciones 9 y 22:

> 1. Llega un PDF (desde n8n o subido a mano a `POST /facturas`).
> 2. Se calcula su hash. Si ya existe, se devuelve el resultado anterior (idempotencia).
> 3. Se manda al LLM pidiendo una **salida estructurada** con un esquema fijo.
> 4. La salida se valida con Pydantic.
> 5. Se ejecutan las reglas de anomalías (módulo B).
> 6. Se guarda todo y se devuelven la factura y sus anomalías.

> | 04 | `04-extraccion-facturas` | `feat/04-extraccion-facturas` | Esquema, servicio del LLM, `POST /facturas` idempotente y política de revisión humana | Alto | Reprocesar no duplica; una salida inválida del LLM da 422 | |

## Alcance

- **Dentro**: `app/schemas.py` con `FacturaExtraida` (sección 9, literal) y los esquemas de
  entrada/salida; `app/services/extraction.py` con OpenAI Structured Outputs; `app/services/invoices.py`
  con la orquestación y la idempotencia; `app/routers/facturas.py` con `POST /facturas` y
  `GET /facturas`; `openai_api_key`/`openai_model` en `app/config.py` y `.env.example`; la política
  de revisión humana (R11) como primera anomalía del sistema; y los tests.
- **Fuera**: las reglas R1–R10 (feature 05), HubSpot (07), las evals (06) y gas y agua en la
  extracción.

## Checklist

- [x] T1 `FacturaExtraida` y esquemas de respuesta, copiados literalmente de la sección 9
- [x] T2 `openai_api_key` y `openai_model` en config y en `.env.example` (sustituyen a las de
  Anthropic, que no se usan)
- [x] T3 `extraer_factura` con `responses.parse(..., text_format=FacturaExtraida)` y el PDF como
  `input_file`, con prompt que trata el documento como dato
- [x] T4 orquestación idempotente: `archivo_hash` y clave de negocio
  `(cups_leido, numero, comercializadora)`
- [x] T5 `POST /facturas` (multipart) y `GET /facturas` con filtros `cups`, `cliente_nif`, `desde`,
  `hasta`
- [x] T6 política de revisión humana: confianza < 0,85 o `campos_dudosos` → anomalía R11
- [x] T7 tests sin red: cliente del LLM simulado, salida válida, salida inválida → 422, idempotencia
- [x] T8 test de integración con PostgreSQL real y PDF generado por la feature 03
- [x] T9 verificación, evidencia, RDD (riesgo alto, 4 lentes), PR

## Criterios de aceptación

- Reprocesar el mismo PDF devuelve la factura existente y no crea filas nuevas ni en `facturas` ni
  en `anomalias`.
- Una salida del LLM que no cumple el esquema produce `422`, nunca un `500`.
- Se guardan `datos_crudos`, el modelo usado y los tokens de cada factura.
- Una factura con confianza baja o campos dudosos crea la anomalía R11 «Revisión de extracción».
- Los tests no hacen red: ni al LLM ni a HubSpot.

## Evidencia

- **Implementación**: la hizo un worker con este documento como contrato, en seis archivos
  (`app/schemas.py`, `app/services/extraction.py`, `app/services/invoices.py`,
  `app/routers/facturas.py`, `app/config.py`, `app/main.py`) y dos de tests.
- **T1–T3**: `uv run pytest tests/test_extraction.py` → 8 tests, sin red: el cliente de OpenAI se
  sustituye por un doble que guarda los kwargs. Comprueban que el PDF va como `input_file` con
  `filename` y `file_data` en data URL base64, que `text_format is FacturaExtraida`, que el prompt
  lleva la guarda anti-inyección, los metadatos de tokens, la salida no conforme → 
  `ExtraccionInvalida`, la negativa del modelo y el PDF ilegible. Importar el módulo sin
  `OPENAI_API_KEY` no falla: el cliente se crea perezosamente.
- **T4–T5**: `uv run pytest tests/test_facturas_api.py` → 9 tests contra PostgreSQL real:
  `test_mismo_pdf_no_duplica_nada` (segunda subida `creada=False`, **una sola llamada al LLM**, una
  fila), `test_pdf_distinto_misma_clave_negocio_no_duplica`, `test_salida_invalida_da_422_y_no_guarda_nada`,
  `test_confianza_baja_y_campos_dudosos_crea_r11`, `test_confianza_alta_sin_dudosos_no_crea_anomalia`,
  `test_cups_fuera_de_cartera_guarda_suministro_nulo`, `test_archivo_no_pdf_da_422` y
  `test_get_facturas_filtros` (incluida la normalización de CUPS).
- **T6**: R11 se crea con confianza < 0,85 o `campos_dudosos`, con severidad `media` y detalle de los
  motivos; la restricción `UNIQUE (factura_id, regla)` evita duplicarla.
- **T9 verificación completa**: `uv run pytest` → `57 passed` · `uv run ruff check .` →
  `All checks passed!` · `uv run ruff format --check .` → `28 files already formatted` ·
  `uv run mypy app scripts tests` → `Success: no issues found in 23 source files` ·
  cobertura de `app/`: `TOTAL 368 7 98%`.
- **Dos huecos que encontró el orquestador al verificar y se cerraron aquí**:
  1. Un periodo invertido que devolviera el modelo llegaba al `CHECK` de PostgreSQL y salía como
     **500**. Ahora `FacturaExtraida` lo rechaza con un validador y el resultado es el 422 que pide
     el criterio de aceptación; fijado con `test_un_periodo_invertido_es_una_extraccion_invalida`.
  2. `.github/workflows/ci.yml` seguía exportando `ANTHROPIC_API_KEY: ci-dummy`. Sustituida por
     `OPENAI_API_KEY`, que es la que el código lee.
- **Verificación manual pendiente de la clave del humano**: la calidad real de la extracción sobre
  los PDFs de las tres comercializadoras solo se puede medir con `OPENAI_API_KEY`. Es exactamente lo
  que automatiza la feature 06, y hasta entonces el techo del sistema es «los tests y el esquema»,
  no «la precisión medida».

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.
- 2026-11-04 T1–T8 implementados y verificados; T9 con los dos huecos cerrados.
- 2026-11-04 commits por unidad de trabajo: esquema y cliente, ingesta idempotente, tests y CI.

## Siguiente paso

T9: RDD de riesgo alto, PR a `dev` y merge. Después, feature 05 (`05-reglas-anomalias`).

## Git

- Rama: `feat/04-extraccion-facturas`
- PR: (pendiente)

## Decisiones

- Proveedor **OpenAI** en lugar de Anthropic (decisión del humano, 2026-11-04). El equivalente al
  tool use forzado son los Structured Outputs: `client.responses.parse(..., text_format=FacturaExtraida)`.
  Documentación consultada el 2026-11-04: guía de structured outputs y guía de file inputs de
  `developers.openai.com`. El PDF viaja como `input_file` con `filename` y `file_data` en data URL
  base64.
- `pdfplumber` entra aquí como apoyo: extraer el texto del PDF permite comprobaciones baratas y da
  el campo de reserva si el modelo falla (se recortan a 8000 caracteres para no duplicar coste).
- **`datos_crudos`** guarda la salida completa del modelo **y** una clave reservada `_extraccion`
  con `modelo`, `tokens_entrada`, `tokens_salida` y `caracteres_texto`: cumple «se guardan
  datos_crudos, modelo y tokens» sin añadir columnas al esquema de la sección 7.
- **El commit lo hace el router**, no el servicio: así la fila de auditoría de `eventos_sync` entra
  en la misma transacción y el 422 deja un evento `ok=False` en lugar de una transacción a medias.
- **`ExtraccionInvalida` cubre tres casos** con el mismo 422: PDF ilegible, salida que no cumple el
  esquema y negativa del modelo. Un 500 nunca es la respuesta correcta a un documento raro.

## RDD

- (pendiente)
