"""Carga del registro histórico de equivalencias de secciones presupuestarias.

Modelo (``historico_secciones.csv``, editable a mano y versionado): una fila
por arista ``(ejercicio_origen, seccion_origen) → (ejercicio_destino,
seccion_destino)`` con ``tipo_cambio`` controlado. Las relaciones n:m de una
remodelación se expresan con varias filas. El objetivo es que una serie
temporal no se rompa cuando una sección cambia de código o de ministerio:
el consumidor sigue las aristas para encadenar ejercicios.

Cómo se alimenta: al publicarse un nuevo PGE/prórroga, diff de las secciones
del árbol PGE-ROM del ejercicio nuevo contra el anterior + el real decreto de
reestructuración correspondiente. La retrocarga de ejercicios pasados usa el
mismo formato (una tanda de filas por transición de ejercicio).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

HISTORICO_FILE = Path(__file__).parent / "historico_secciones.csv"

TIPOS_CAMBIO = ("continuidad_renombre", "fusion", "escision", "creacion", "supresion")


def load_historico(path: Path = HISTORICO_FILE) -> pd.DataFrame:
    """Carga y valida el histórico de equivalencias de secciones."""
    historico = pd.read_csv(path, dtype=str, comment="#")
    tipos_invalidos = set(historico["tipo_cambio"]) - set(TIPOS_CAMBIO)
    if tipos_invalidos:
        raise ValueError(f"tipo_cambio desconocido en historico_secciones.csv: {tipos_invalidos}")
    # Solo 'creacion' admite origen vacío (y 'supresion', destino vacío).
    sin_origen = historico["seccion_origen"].isna() & (historico["tipo_cambio"] != "creacion")
    sin_destino = historico["seccion_destino"].isna() & (historico["tipo_cambio"] != "supresion")
    if sin_origen.any() or sin_destino.any():
        raise ValueError("Filas con origen/destino vacío y tipo_cambio incompatible.")
    return historico
