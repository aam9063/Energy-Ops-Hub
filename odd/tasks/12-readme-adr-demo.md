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

- [ ] T1 `README.md` con la estructura de la sección 23 y los números medidos
- [ ] T2 `docs/arquitectura.md` con el diagrama de la sección 4 y el reparto de responsabilidades
- [ ] T3 los siete ADR de la sección 23 en `docs/adr/`
- [ ] T4 `docs/demo.md` con el guion de tres minutos de la sección 24
- [ ] T5 verificación (enlaces internos, comandos del README, números contra `evals/resultados.md`)
- [ ] T6 PR a `dev` y merge

## Criterios de aceptación

- El README abre con el problema del usuario, no con la tecnología.
- Los cinco comandos de arranque funcionan tal como están escritos.
- Los números del README coinciden con `evals/resultados.md` y con lo que dicen los tests.
- Cada decisión importante enlaza a un ADR de media página.
- Hay una sección honesta de limitaciones y otra de qué cambiaría en producción.
- No se afirma nada que el repositorio no pueda demostrar.

## Evidencia

- (pendiente)

## Progreso

- 2026-11-05 documento creado antes del primer cambio.

## Siguiente paso

T1–T4: los textos.

## Git

- Rama: `feat/12-readme-adr-demo`
- PR: (pendiente)

## Decisiones

- (pendiente)

## RDD

- (pendiente)
