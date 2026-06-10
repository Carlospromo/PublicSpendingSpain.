"""Parser de DIR3: XLSX oficial de unidades AGE → DataFrame canónico.

SOLO raw → DataFrame (CLAUDE.md §2). Estructura verificada contra el fichero
real ``Listado Unidades AGE.xlsx`` (captura 2026-06-10, datos.gob.es E05251701):

- Hoja ``Unidades AGE V+T``: fila 1 en blanco, fila 2 cabecera, primera columna
  vacía. ~19.7k filas. Algunas filas llegan recortadas (celdas finales vacías).
- Columnas oficiales (ver hoja "Leyenda de campos" del propio fichero):
  C_ID_UD_ORGANICA, C_DNM_UD_ORGANICA, C_ID_NIVEL_ADMON, C_ID_TIPO_ENT_PUBLICA,
  N_NIVEL_JERARQUICO, C_ID_DEP_UD_SUPERIOR (+nombre), C_ID_DEP_UD_PRINCIPAL
  (+nombre), B_SW_DEP_EDP_PRINCIPAL, C_ID_DEP_EDP_PRINCIPAL (+nombre),
  C_ID_ESTADO, D_VIG_ALTA_OFICIAL, NIF_CIF.
- Fechas de alta como texto ``DD/MM/YY`` (a menudo vacías).
- La raíz del Estado ``EA9999999`` ("Administracion del Estado") se referencia
  como superior de los ministerios pero no tiene fila propia.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd

SHEET_UNIDADES = "Unidades AGE V+T"

# Raíz virtual del Estado: aparece como unidad superior de los ministerios pero
# no existe como fila en el fichero.
ROOT_ESTADO = "EA9999999"

N_COLS = 16  # ancho de la tabla en la hoja (incluida la primera columna vacía)

# Posición (0-based) → columna canónica.
_COLUMN_MAP: dict[int, str] = {
    1: "dir3_cod",
    2: "denominacion",
    3: "nivel_administracion",
    4: "tipo_entidad",
    5: "nivel_jerarquico",
    6: "dir3_padre_cod",
    7: "denominacion_padre",
    8: "dir3_raiz_cod",
    9: "denominacion_raiz",
    10: "es_edp",
    11: "edp_cod",
    12: "edp_denominacion",
    13: "estado",
    14: "fecha_alta",
    15: "nif",
}


def _parse_fecha(value: Any) -> date | None:
    """Convierte el texto oficial ``DD/MM/YY`` en ``date`` (o ``None``).

    El año viene con dos dígitos y ``%y`` pivota en 69 (59 → 2059), pero una
    fecha de creación oficial nunca es futura: si el año resultante supera el
    año actual, se corrige al siglo anterior (59 → 1959).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    parsed = datetime.strptime(str(value).strip(), "%d/%m/%y").date()
    if parsed.year > date.today().year:
        parsed = parsed.replace(year=parsed.year - 100)
    return parsed


def _clean(value: Any) -> str | None:
    """Normaliza celdas: cadenas sin espacios extremos; vacíos → None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_unidades_age(path: Path) -> pd.DataFrame:
    """Parsea el XLSX de unidades AGE a un DataFrame canónico.

    Sin pérdida de filas: toda fila con código DIR3 se conserva tal cual
    (incluidas anomalías de la fuente, p. ej. huérfanos); juzgar el dato es
    tarea de transform/quality, no del parser.
    """
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        sheet = workbook[SHEET_UNIDADES]
        # El fichero oficial declara mal sus dimensiones: hay que recalcular.
        sheet.reset_dimensions()
        records: list[dict[str, Any]] = []
        for raw in sheet.iter_rows(values_only=True):
            row = (tuple(raw) + (None,) * N_COLS)[:N_COLS]
            dir3_cod = _clean(row[1])
            # Descarta la fila en blanco inicial y la cabecera.
            if dir3_cod is None or dir3_cod == "C_ID_UD_ORGANICA":
                continue
            record: dict[str, Any] = {name: _clean(row[idx]) for idx, name in _COLUMN_MAP.items()}
            record["fecha_alta"] = _parse_fecha(row[14])
            records.append(record)
    finally:
        workbook.close()

    df = pd.DataFrame.from_records(records, columns=list(_COLUMN_MAP.values()))
    df["nivel_administracion"] = df["nivel_administracion"].astype("int64")
    df["nivel_jerarquico"] = df["nivel_jerarquico"].astype("int64")
    return df
