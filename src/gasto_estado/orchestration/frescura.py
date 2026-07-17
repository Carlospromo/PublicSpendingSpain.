"""Ledger de materialización: trazabilidad de frescura y operación.

Cada materialización de un asset registra aquí QUÉ se materializó, su partición,
cuántas filas y CUÁNDO. La API (``analytics.estructura.frescura_fuentes``) lee
este ledger para que la frescura que ve el frontal provenga del estado real de
materialización, no de una estimación — sin romper el contrato v1 (el campo
``materializado_en`` es una adición OPCIONAL).

Es un artefacto DERIVADO (como el warehouse): vive junto a él y puede publicarse
con el resultado de CI. Si no existe (camino ``gasto-estado build``, sin
Dagster), la API cae con elegancia a la frescura derivada del propio dato. La
reproducibilidad se mantiene: el ledger nunca es fuente de verdad, solo
trazabilidad operativa.
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


def _escribir(warehouse_path: Path, datos: dict[str, dict[str, Any]]) -> None:
    ruta = ledger_path(warehouse_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True)
    ruta.write_text(contenido, encoding="utf-8")


def registrar_intento(warehouse_path: Path, fuente_cod: str, *, particion: str | None) -> None:
    """Registra un intento antes de materializar, sin alterar el último éxito."""
    actual = leer(warehouse_path)
    entrada = actual.get(fuente_cod, {})
    entrada.update(
        {
            "particion": particion,
            "ultima_ejecucion_intentada": datetime.now(UTC).isoformat(),
            "estado_fuente": "en_ejecucion",
            "advertencia_o_error_activo": None,
        }
    )
    actual[fuente_cod] = entrada
    _escribir(warehouse_path, actual)


def registrar_fallo(
    warehouse_path: Path,
    fuente_cod: str,
    *,
    particion: str | None,
    diagnostico: str,
) -> None:
    """Conserva el último éxito y deja visible el fallo operativo activo."""
    actual = leer(warehouse_path)
    entrada = actual.get(fuente_cod, {})
    entrada.update(
        {
            "particion": particion,
            "ultima_ejecucion_intentada": datetime.now(UTC).isoformat(),
            "estado_fuente": "error",
            "advertencia_o_error_activo": diagnostico,
        }
    )
    actual[fuente_cod] = entrada
    _escribir(warehouse_path, actual)


def registrar(
    warehouse_path: Path,
    fuente_cod: str,
    *,
    particion: str | None,
    filas: int,
    captura_disponible: str | None = None,
) -> None:
    """Anota una materialización correcta, preservando compatibilidad con el ledger previo."""
    actual = leer(warehouse_path)
    ahora = datetime.now(UTC).isoformat()
    captura = captura_disponible or ahora
    actual[fuente_cod] = {
        "particion": particion,
        "filas": filas,
        "materializado_en": ahora,
        "ultima_captura_disponible": captura,
        "ultima_ejecucion_intentada": ahora,
        "ultima_ejecucion_correcta": ahora,
        "particion_cubierta": particion,
        "estado_fuente": "correcta",
        "advertencia_o_error_activo": None,
    }
    _escribir(warehouse_path, actual)
