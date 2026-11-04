"""Evaluación del sistema sobre el dataset sintético (docs/spec.md, secciones 8 y 16).

`evals.run_evals` recorre `evals/dataset/`, mide la precisión de la extracción campo a
campo, evalúa el sistema completo (extracción + reglas puras) contra las anomalías
inyectadas y escribe un informe en Markdown listo para el README.
"""
