# ADR 0004 · LLM para extraer, código para validar

- Estado: aceptado
- Fecha: 2026-11 (features 04, 05 y 06)
- Documentos ODD: [odd/tasks/04-extraccion-facturas.md](../../odd/tasks/04-extraccion-facturas.md)
  (PR [#5](https://github.com/aam9063/Energy-Ops-Hub/pull/5)),
  [odd/tasks/05-reglas-anomalias.md](../../odd/tasks/05-reglas-anomalias.md) (PR
  [#6](https://github.com/aam9063/Energy-Ops-Hub/pull/6)) y
  [odd/tasks/06-evals.md](../../odd/tasks/06-evals.md) (PR
  [#8](https://github.com/aam9063/Energy-Ops-Hub/pull/8))

## Contexto

Cada comercializadora maqueta su factura distinto, así que una plantilla fija no sirve y un LLM
es la herramienta adecuada para leer el PDF. Pero un LLM también se equivoca: puede confundir el
consumo con la potencia, arrastrar un dígito del total o alucinar un campo que no está en el
documento. Confiarle también la validación sería construir sobre una base no determinista.

## Decisión

- **El LLM solo extrae**, con salida estructurada (`FacturaExtraida` vía OpenAI Structured
  Outputs) y una **confianza global** declarada en la salida.
- **El código valida y decide**: el esquema de Pydantic rechaza salidas malformadas, las reglas
  R1–R11 (funciones puras, testeables) contrastan la factura contra el suministro y el
  histórico, y una regla específica (**R11**) marca para **revisión humana** toda extracción
  con confianza por debajo de **0,85** o con campos dudosos.
- La evaluación ([evals/resultados.md](../../evals/resultados.md)) mide ambas capas por
  separado: precisión por campo y recall/falsas alarmas del sistema completo.

## Consecuencias

- Buenas: la exactitud es medible y reproducible; un error del LLM no corrompe la base de datos
  (el esquema y las reglas lo interceptan) y toda extracción queda con sus datos crudos para
  auditar.
- Costes: la revisión humana añade trabajo (en la evaluación actual, 10 de 120 facturas quedan
  marcadas), y el umbral de 0,85 es una decisión de producto que habrá que calibrar con datos
  reales.
- El umbral de 0,85 no es permanente: es el punto de partida medido sobre el dataset sintético y
  se ajustará con negocio cuando haya facturas reales.
