"""Contratos offline de la fiabilidad operativa de Fase 2."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from gasto_estado.orchestration.manifiestos import (
    ManifiestoIncompletoError,
    crear_manifiesto,
    escribir_manifiesto,
    registrar_desde_archivos,
    sha256_archivo,
)


def _manifiesto() -> object:
    return crear_manifiesto(
        fuente="placsp",
        fecha_extraccion=datetime(2026, 7, 17, 6, tzinfo=UTC),
        desde="2026-07-10",
        hasta="2026-07-17",
        url_origen="https://example.test/placsp",
        sha256="a" * 64,
        commit_codigo="a" * 40,
        commit_warehouse="b" * 40,
        ubicacion_inmutable="archivo-institucional/captura-1",
    )


def test_sha256_archivo_y_manifiesto_idempotente(tmp_path: Path) -> None:
    captura = tmp_path / "captura.atom"
    captura.write_bytes(b"contenido verificable")
    assert sha256_archivo(captura) == sha256_archivo(captura)

    ruta_1 = registrar_desde_archivos(
        directorio=tmp_path / "manifiestos",
        fuente="placsp",
        fecha_extraccion=datetime(2026, 7, 17, 6, tzinfo=UTC),
        desde="2026-07-17",
        hasta="2026-07-17",
        url_origen="https://example.test/placsp",
        archivos=[captura],
        commit_codigo="a" * 40,
        commit_warehouse="b" * 40,
        ubicacion_inmutable="archivo-institucional/captura-1",
    )
    ruta_2 = registrar_desde_archivos(
        directorio=tmp_path / "manifiestos",
        fuente="placsp",
        fecha_extraccion=datetime(2026, 7, 17, 6, tzinfo=UTC),
        desde="2026-07-17",
        hasta="2026-07-17",
        url_origen="https://example.test/placsp",
        archivos=[captura],
        commit_codigo="a" * 40,
        commit_warehouse="b" * 40,
        ubicacion_inmutable="archivo-institucional/captura-1",
    )
    assert ruta_1 == ruta_2
    assert len(list((tmp_path / "manifiestos").rglob("*.json"))) == 1
    assert json.loads(ruta_1.read_text(encoding="utf-8"))["schema_version"] == 1


def test_manifiesto_incompleto_no_se_escribe(tmp_path: Path) -> None:
    with pytest.raises(ManifiestoIncompletoError, match="ubicacion_inmutable"):
        crear_manifiesto(
            fuente="bdns",
            fecha_extraccion=datetime(2026, 7, 17, 6, tzinfo=UTC),
            desde="2026-07-17",
            hasta="2026-07-17",
            url_origen="https://example.test/bdns",
            sha256="a" * 64,
            commit_codigo="a" * 40,
            commit_warehouse="b" * 40,
            ubicacion_inmutable="",
        )
    assert not list(tmp_path.rglob("*.json"))


def test_colision_de_manifiesto_distinto_falla(tmp_path: Path) -> None:
    primero = _manifiesto()
    assert hasattr(primero, "sha256")
    ruta = escribir_manifiesto(tmp_path, primero)  # type: ignore[arg-type]
    ruta.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ManifiestoIncompletoError, match="colisión"):
        escribir_manifiesto(tmp_path, primero)  # type: ignore[arg-type]


def test_clasificacion_de_fallos_requerida() -> None:
    from gasto_estado.orchestration.notifications import clasificar_fallo
    from gasto_estado.orchestration.pipeline import FormatoNoReconocidoError

    assert clasificar_fallo(TimeoutError("timeout")) == "fuente_no_disponible"
    assert clasificar_fallo(ValueError("respuesta vacía")) == "respuesta_vacia"
    assert clasificar_fallo(RuntimeError("validación contable fallida")) == "validacion_contable"
    assert clasificar_fallo(RuntimeError("error de carga")) == "error_carga"
    assert clasificar_fallo(RuntimeError("otro error")) == "error_publicacion"
    error_formato = FormatoNoReconocidoError.__new__(FormatoNoReconocidoError)
    assert clasificar_fallo(error_formato) == "formato_cambiado"


def test_no_crea_issue_duplicado(tmp_path: Path) -> None:
    from gasto_estado.orchestration.notifications import Incidencia, crear_issue_si_ci

    incidencia = Incidencia("placsp", "2026-07-17", "error_carga", "fallo de prueba")
    existente = subprocess.CompletedProcess(args=[], returncode=0, stdout="[{\"number\": 12}]")
    with (
        patch.dict(
            os.environ,
            {"GITHUB_ACTIONS": "true", "GASTO_ESTADO_CREAR_ISSUES": "1"},
            clear=False,
        ),
        patch(
            "gasto_estado.orchestration.notifications.subprocess.run",
            return_value=existente,
        ) as run,
    ):
        assert not crear_issue_si_ci(incidencia)
    assert run.call_count == 1


def test_ledger_operativo_preserva_ultimo_exito(tmp_path: Path) -> None:
    from gasto_estado.orchestration import frescura

    warehouse = tmp_path / "warehouse.duckdb"
    frescura.registrar(warehouse, "placsp", particion="2026-07-10", filas=3)
    frescura.registrar_fallo(
        warehouse, "placsp", particion="2026-07-17", diagnostico="fuente no disponible"
    )
    entrada = frescura.leer(warehouse)["placsp"]
    assert entrada["ultima_ejecucion_correcta"] is not None
    assert entrada["estado_fuente"] == "error"
    assert entrada["advertencia_o_error_activo"] == "fuente no disponible"
