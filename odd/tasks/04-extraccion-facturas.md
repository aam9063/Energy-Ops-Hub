# 04 · Extracción de facturas con LLM

## Objetivo

Que un PDF de factura llegue a `POST /facturas` y salga convertido en una fila de `facturas` con
sus datos validados, sus anomalías y sus datos crudos para auditar, sin que reprocesar el mismo
documento duplique nada.

## Problema

Laura abre decenas de facturas en PDF de tres comercializadoras distintas y copia los datos a mano.
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

- [ ] T1 `FacturaExtraida` y esquemas de respuesta, copiados literalmente de la sección 9
- [ ] T2 `openai_api_key` y `openai_model` en config y en `.env.example` (sustituyen a las de
  Anthropic, que no se usan)
- [ ] T3 `extraer_factura` con `responses.parse(..., text_format=FacturaExtraida)` y el PDF como
  `input_file`, con prompt que trata el documento como dato
- [ ] T4 orquestación idempotente: `archivo_hash` y clave de negocio
  `(cups_leido, numero, comercializadora)`
- [ ] T5 `POST /facturas` (multipart) y `GET /facturas` con filtros `cups`, `cliente_nif`, `desde`,
  `hasta`
- [ ] T6 política de revisión humana: confianza < 0,85 o `campos_dudosos` → anomalía R11
- [ ] T7 tests sin red: cliente del LLM simulado, salida válida, salida inválida → 422, idempotencia
- [ ] T8 test de integración con PostgreSQL real y PDF generado por la feature 03
- [ ] T9 verificación, evidencia, RDD (riesgo alto, 4 lentes), PR

## Criterios de aceptación

- Reprocesar el mismo PDF devuelve la factura existente y no crea filas nuevas ni en `facturas` ni
  en `anomalias`.
- Una salida del LLM que no cumple el esquema produce `422`, nunca un `500`.
- Se guardan `datos_crudos`, el modelo usado y los tokens de cada factura.
- Una factura con confianza baja o campos dudosos crea la anomalía R11 «Revisión de extracción».
- Los tests no hacen red: ni al LLM ni a HubSpot.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-04 documento creado antes del primer cambio de código.

## Siguiente paso

T1: esquemas.

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
  el campo de reserva si el modelo falla.

## RDD

- (pendiente)
