# ADR 0001 · Lógica de negocio en Python, orquestación en n8n

- Estado: aceptado
- Fecha: 2026-11 (features 05 y 09)
- Documentos ODD: [odd/tasks/05-reglas-anomalias.md](../../odd/tasks/05-reglas-anomalias.md) (PR
  [#6](https://github.com/aam9063/Energy-Ops-Hub/pull/6)) y
  [odd/tasks/09-flujos-n8n.md](../../odd/tasks/09-flujos-n8n.md) (PR
  [#11](https://github.com/aam9063/Energy-Ops-Hub/pull/11))

## Contexto

n8n permite poner lógica en nodos *Code* o en expresiones: es cómodo empezar, y un flujo «que
hace todo» es la tentación habitual. Pero una regla dentro de un nodo de n8n no tiene tests,
no participa de la cobertura, no se puede reutilizar desde la API o desde Apps Script y solo se
verifica ejecutando el flujo a mano.

## Decisión

- **Toda la lógica de negocio vive en Python** (FastAPI): validación de CUPS, reglas de
  anomalías R1–R11, idempotencia, upserts de HubSpot y reportes. Las reglas son **funciones
  puras** en `app/domain/` sin I/O, testeadas una a una.
- **n8n solo orquesta**: disparadores (email, horarios), llamadas HTTP a la API, avisos y, en el
  futuro, el agente copiloto. Los tres flujos versionados (`n8n/F1…F3.json`) no contienen
  decisiones de negocio; el CI valida su estructura en cada PR.

## Consecuencias

- Buenas: las reglas se testean con pytest (cada una con un test que la dispara y otro que no),
  la misma lógica sirve a n8n, a Apps Script vía API y a la evaluación automática, y cambiar una
  regla no obliga a retocar un flujo.
- Costes: hay un salto de red más (n8n → API) y el flujo de n8n a veces parece «solo un
  pasacables»; es el precio de tener la lógica testable y única.
- Si un día un flujo necesita una decisión local (por ejemplo, agrupar avisos), se mantiene como
  presentación, nunca como regla de negocio.
