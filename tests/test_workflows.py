"""Política de entrega de los workflows (docs/spec.md, sección 21).

El job `integrations` del CI comprueba que los JSON de n8n y los `.gs` son válidos. Estos tests
hacen lo mismo con los workflows de GitHub Actions: que el YAML parsee y, sobre todo, que la
política de entrega no se rompa por descuido — permisos mínimos, CD solo desde `main`, environment
de producción, smoke test y secretos siempre por `env:`.

`yaml.safe_load` interpreta la clave `on:` como el booleano `True` (YAML 1.1), así que los
disparadores se leen con un ayudante que acepta las dos formas.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

DIR_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
NOMBRES = sorted(ruta.name for ruta in DIR_WORKFLOWS.glob("*.yml"))
CD = "cd.yml"
RELEASE = "release.yml"


def cargar(nombre: str) -> dict[str, Any]:
    datos = yaml.safe_load((DIR_WORKFLOWS / nombre).read_text(encoding="utf-8"))
    assert isinstance(datos, dict)
    return datos


def disparadores(flujo: dict[str, Any]) -> dict[str, Any]:
    """Devuelve el bloque `on:` salvando la conversión de YAML 1.1 (`on` → `True`)."""
    valor: Any = flujo.get("on")
    if valor is None:
        valor = next((v for clave, v in flujo.items() if clave is True), None)
    assert isinstance(valor, dict), "el workflow no declara disparadores"
    return valor


def texto(nombre: str) -> str:
    return (DIR_WORKFLOWS / nombre).read_text(encoding="utf-8")


def test_hay_workflows_para_validar() -> None:
    assert CD in NOMBRES
    assert RELEASE in NOMBRES


@pytest.mark.parametrize("nombre", NOMBRES)
def test_el_yaml_parsea_y_declara_permisos(nombre: str) -> None:
    flujo = cargar(nombre)
    assert "jobs" in flujo, f"{nombre} no declara jobs"
    assert flujo["jobs"], f"{nombre} no tiene ningún job"
    assert flujo.get("permissions") == {"contents": "read"}, (
        f"{nombre} debe declarar permisos mínimos a nivel de workflow"
    )


@pytest.mark.parametrize("nombre", NOMBRES)
def test_ningun_run_interpola_secretos_ni_inputs(nombre: str) -> None:
    """Los secretos e inputs van por `env:`, nunca dentro del script (inyección de comandos)."""
    flujo = cargar(nombre)
    for nombre_job, job in flujo["jobs"].items():
        for paso in job.get("steps", []):
            guion = paso.get("run")
            if not guion:
                continue
            assert "${{ secrets." not in guion, f"{nombre}:{nombre_job} interpola un secreto en run"
            assert "${{ inputs." not in guion, f"{nombre}:{nombre_job} interpola un input en run"


@pytest.mark.parametrize("nombre", NOMBRES)
def test_ningun_workflow_lleva_credenciales_escritas(nombre: str) -> None:
    contenido = texto(nombre)
    for patron in (r"sk-[A-Za-z0-9]{8,}", r"ghp_[A-Za-z0-9]{8,}", r"pat-[A-Za-z0-9]{8,}"):
        assert not re.search(patron, contenido), f"{nombre} parece llevar una credencial literal"


def test_el_cd_solo_se_dispara_desde_main_o_a_mano() -> None:
    eventos = disparadores(cargar(CD))
    assert set(eventos) == {"push", "workflow_dispatch"}, "el CD solo debe escuchar push y manual"
    assert eventos["push"]["branches"] == ["main"], "el CD no puede desplegar desde otra rama"


def test_el_despliegue_usa_el_environment_de_produccion() -> None:
    jobs = cargar(CD)["jobs"]
    entorno = jobs["deploy"]["environment"]
    nombre = entorno["name"] if isinstance(entorno, dict) else entorno
    assert nombre == "production"


def test_el_smoke_test_reintenta_contra_health() -> None:
    pasos = cargar(CD)["jobs"]["deploy"]["steps"]
    smoke = [paso for paso in pasos if "/health" in (paso.get("run") or "")]
    assert smoke, "el despliegue no comprueba /health"
    guion = smoke[0]["run"]
    assert "seq 1" in guion, "el smoke test debe reintentar, no fallar al primer intento"
    assert "sleep" in guion, "el smoke test debe esperar entre intentos"
    assert smoke[0].get("env", {}).get("API_PUBLIC_URL") == "${{ vars.API_PUBLIC_URL }}"


def test_la_imagen_se_publica_con_sha_y_con_main() -> None:
    pasos = cargar(CD)["jobs"]["image"]["steps"]
    meta = next(paso for paso in pasos if "metadata-action" in str(paso.get("uses", "")))
    etiquetas = meta["with"]["tags"]
    assert "type=sha" in etiquetas
    assert "type=raw,value=main" in etiquetas
    publicar = next(paso for paso in pasos if "build-push-action" in str(paso.get("uses", "")))
    assert publicar["with"]["push"] is True


def test_la_release_etiqueta_con_semver() -> None:
    flujo = cargar(RELEASE)
    assert "release" in disparadores(flujo)
    pasos = flujo["jobs"]["tag-image"]["steps"]
    meta = next(paso for paso in pasos if "metadata-action" in str(paso.get("uses", "")))
    etiquetas = meta["with"]["tags"]
    assert "type=semver,pattern={{version}}" in etiquetas
    assert "type=semver,pattern={{major}}.{{minor}}" in etiquetas


def test_el_push_de_apps_script_esta_apagado_por_defecto() -> None:
    job = cargar(CD)["jobs"]["apps-script"]
    assert "DEPLOY_APPS_SCRIPT" in str(job.get("if")), "el push de Apps Script debe ser opcional"
    assert job["environment"] == "production"


def test_el_cd_no_cancela_un_despliegue_a_medias() -> None:
    concurrencia = cargar(CD)["concurrency"]
    assert concurrencia["cancel-in-progress"] is False
