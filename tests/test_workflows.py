"""Validaciones estáticas offline de los workflows operativos."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = ("monthly.yml", "weekly.yml", "health_check.yml")
SHA = "@[0-9a-f]{40}"


def test_workflows_operativos_son_yaml_y_fijan_actions() -> None:
    raiz = Path(__file__).parents[1] / ".github" / "workflows"
    for nombre in WORKFLOWS:
        contenido = (raiz / nombre).read_text(encoding="utf-8")
        assert yaml.safe_load(contenido) is not None
        assert "workflow_dispatch" in contenido
        assert "concurrency:" in contenido
        assert "actions/checkout@" in contenido
        assert "astral-sh/setup-uv@" in contenido
        import re

        assert re.search(f"actions/checkout{SHA}", contenido)
        assert re.search(f"astral-sh/setup-uv{SHA}", contenido)


def test_permisos_operativos_minimos() -> None:
    raiz = Path(__file__).parents[1] / ".github" / "workflows"
    mensual = (raiz / "monthly.yml").read_text(encoding="utf-8")
    semanal = (raiz / "weekly.yml").read_text(encoding="utf-8")
    salud = (raiz / "health_check.yml").read_text(encoding="utf-8")
    assert "contents: write" in mensual and "issues: write" in mensual
    assert "contents: write" in semanal and "issues: write" in semanal
    assert "contents: read" in salud and "issues: write" in salud
    assert "contents: write" not in salud
