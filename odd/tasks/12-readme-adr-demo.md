# 12 · README, ADR y guion de demo

## Objetivo

Que alguien que no me conoce entienda en cinco minutos qué problema resuelve el proyecto, cómo está
construido, qué mide y qué le falta, y que pueda levantarlo con cinco comandos.

## Problema

El proyecto ya funciona, pero su valor no se ve sin un texto que empiece por el problema y termine en
números. Y las decisiones que tomé —por qué la lógica vive en Python y no en n8n, por qué se modeló
un alta como negocio y no como objeto propio— se pierden si no están escritas como ADR cortos.

Cita literal de `docs/spec.md`, secciones 23 y 24:

> ### Estructura del README
> ```markdown
> # Energy Ops Hub
> [![CI](...)](...)
> Automatización de operaciones energéticas para carteras inmobiliarias.
>
> ## El problema (30 segundos)
> ## Qué hace (con un GIF o vídeo de 3 minutos)
> ## Arquitectura (diagrama)
> ## Decisiones clave (enlaces a los ADR)
> ## Resultados (tabla de evaluación + métricas estimadas con supuestos)
> ## Cómo ejecutarlo (5 comandos)
> ## Cómo se ha construido (ODD + RDD, enlaces a odd/tasks/ y a los PRs)
> ## Limitaciones y siguientes pasos
> ## Si esto fuera a producción
> ```

> | 12 | `12-readme-adr-demo` | `docs/12-readme-adr-demo` | README final, ADR y guion de demo | Bajo | Lo entiende alguien que no te conoce | **v1.0.0** |

## Alcance

- **Dentro**: `README.md` completo con la estructura de la sección 23 y los números medidos,
  `docs/arquitectura.md`, los siete ADR de la sección 23 y `docs/demo.md` con el guion de tres
  minutos de la sección 24.
- **Fuera**: el vídeo de la demo (lo graba el humano), el despliegue real y las métricas de ahorro
  definitivas, que dependen de medir el proceso actual con datos reales.

## Números medidos que deben aparecer

Medidos con la clave real, `gpt-4.1-mini`, sobre las 120 facturas sintéticas:

| Campo | Precisión |
|---|---:|
| CUPS, número de factura, comercializadora, periodo, consumo, importe total y lectura estimada | **100 % cada uno** |

| Anomalías | Valor |
|---|---:|
| Recall (18 inyectadas) | **18/18 (100 %)** |
| Falsas alarmas | 10 (9 de R5 por ±1 € de ruido de extracción, 1 de R11 por confianza baja) |
| Coste medio por factura | **0,0007 €** |

Además: **199 tests** en verde, cobertura del 97 % sobre `app/`, CI con `ci-ok` obligatorio en `main`
y `dev`, y once features integradas con su documento ODD y su resultado RDD.

## Checklist

- [x] T1 `README.md` con la estructura de la sección 23 y los números medidos
- [x] T2 `docs/arquitectura.md` con el diagrama de la sección 4 y el reparto de responsabilidades
- [x] T3 los siete ADR de la sección 23 en `docs/adr/`
- [x] T4 `docs/demo.md` con el guion de tres minutos de la sección 24
- [x] T5 verificación (enlaces internos, comandos del README, números contra `evals/resultados.md`)
- [ ] T6 PR a `dev` y merge

## Criterios de aceptación

- El README abre con el problema del usuario, no con la tecnología.
- Los cinco comandos de arranque funcionan tal como están escritos.
- Los números del README coinciden con `evals/resultados.md` y con lo que dicen los tests.
- Cada decisión importante enlaza a un ADR de media página.
- Hay una sección honesta de limitaciones y otra de qué cambiaría en producción.
- No se afirma nada que el repositorio no pueda demostrar.

## Evidencia

- **T1 README**: reescrito con la estructura de la sección 23. Abre con el problema de Laura y no
  con la tecnología, y los números son los medidos: 7 campos al 100 %, recall 18/18, 10 falsas
  alarmas (9 de R5 por ruido de extracción y 1 de R11), 0,0007 € por factura, **219 tests** y
  cobertura del **97 %** sobre `app/`. Las métricas de ahorro van como estimaciones con supuestos
  explícitos (4 minutos por factura, 500 facturas/mes).
- **T2** `docs/arquitectura.md` con el diagrama Mermaid de la sección 4 y el reparto de
  responsabilidades (Python decide, n8n orquesta, Apps Script es la interfaz).
- **T3** los siete ADR de la sección 23 en `docs/adr/`, de media página cada uno.
- **T4** `docs/demo.md` con el guion de tres minutos y la lista de comprobación previa a grabar.
- **Verificación**: script propio sobre todos los `.md` nuevos → **0 enlaces internos rotos**; los
  cinco comandos de arranque son los que existen en el repo (`cp .env.example .env`,
  `docker compose up -d`, `uv sync`, `uv run alembic upgrade head`, `uv run python -m scripts.seed`);
  `uv run pytest -q` → 219 passed.
- **Nota de proceso**: el worker escribió estos archivos mientras la rama activa era la de las
  correcciones de evals, así que la documentación entró en el PR #13. Reescribir esa rama exigiría
  `--force`, prohibido por la política del repo: se declaró en un comentario del PR en lugar de
  esconderlo, y este documento viaja en su propia rama.

## Progreso

- 2026-11-05 documento creado antes del primer cambio.
- 2026-11-05 T1–T4 escritos y verificados; T5–T6 pendientes de PR y merge.

## Siguiente paso

T5–T6: PR a `dev` y merge. Con eso queda todo el plan de la sección 22 terminado y solo faltan los
hitos de release, que son del humano.

## Git

- Rama: `feat/12-readme-adr-demo`
- PR: (pendiente)

## Decisiones

- **Los números del README salen de `evals/resultados.md`**, no de una estimación: si alguien
  regenera el dataset los números pueden cambiar, y el README dice cómo medirlos.
- **El coste se presenta como estimación** con la letra pequeña (lista de OpenAI en dólares usada
  como euros), porque fingir una conversión de divisa sería peor que no dar la cifra.
- **Las métricas de ahorro son supuestos explícitos**, no promesas: el README dice cuántas horas
  ahorraría con un porcentaje de automatización y de dónde sale ese porcentaje.
- **Cada decisión importante enlaza a un ADR**: el README no reinventa la argumentación, la delega.

## RDD

- Riesgo: **bajo** (solo documentación) · Sin lentes: lectura estructural · El `assess` del
  candidato de las correcciones ya cubrió el código; aquí no cambia ni una línea ejecutable.
- Verificación estructural aplicada: todos los enlaces internos resuelven, los comandos existen, los
  números coinciden con `evals/resultados.md` y la suite sigue en 219 tests.
