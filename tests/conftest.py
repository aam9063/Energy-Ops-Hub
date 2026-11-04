"""Configuración común de los tests.

Los tests de integración usan el PostgreSQL de `docker compose` publicado en localhost. La
variable se fija antes de importar `app` porque el engine se construye al importar el módulo,
y así los tests no dependen del `.env` de cada desarrollador (que dentro de Docker usa `db`).
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ops:ops@localhost:5432/energy_ops")
# Los tests de la API no deben depender de si el entorno trae una clave: el middleware se
# prueba aparte, inyectando `Settings(api_key=...)` en `create_app` (tests/test_health.py).
os.environ["API_KEY"] = ""
