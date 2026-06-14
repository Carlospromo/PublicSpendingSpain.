"""Ledger de materialización: trazabilidad de frescura real (Fase 7).

Cada materialización de un asset registra aquí QUÉ se materializó, su partición,
cuántas filas y CUÁNDO. La API (``analytics.estructura.frescura_fuentes``) lee
este ledger para que la frescura que ve el frontal provenga del estado real de
materialización, no de una estimación — sin romper el contrato v1 (el campo
``materializado_en`` es una adición OPCIONAL).

Es un artefacto DERIVADO (como el warehouse): vive junto a él y no se versiona.
Si no existe (camino ``gasto-estado build``, sin Dagster), la API cae con
elegancia a la frescura derivada del propio dato. La reproducibilidad se
mantiene: el ledger nunca es fuente de verdad, solo trazabilidad operativa.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def ledger_path(warehouse_path: Path) -> Path:
    """Ruta del ledger, junto al warehouse."""
    return warehouse_path.with_name("materializacion.json")


def leer(warehouse_path: Path) -> dict[str, dict[str, Any]]:
    """Lee el ledger (``{fuente_cod: {particion, filas, materializado_en}}``) o {}."""
    ruta = ledger_path(warehouse_path)
    if not ruta.exists():
        return {}
    try:
        datos: dict[str, dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8"))
        return datos
    except (json.JSONDecodeError, OSError):
        return {}


def registrar(
    warehouse_path: Path, fuente_cod: str, *, particion: str | None, filas: int
) -> None:
    """Anota la materialización de una fuente (sobrescribe su entrada anterior)."""
    ruta = ledger_path(warehouse_path)
    actual = leer(warehouse_path)
    actual[fuente_cod] = {
        "particion": particion,
        "filas": filas,
        "materializado_en": datetime.now(UTC).isoformat(),
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(actual, ensure_ascii=False, indent=2), encoding="utf-8")
