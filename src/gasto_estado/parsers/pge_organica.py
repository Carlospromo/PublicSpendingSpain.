"""Parser de la clasificación orgánica del PGE (resumen por servicios).

SOLO raw → DataFrame (CLAUDE.md §2). Estructura verificada contra el fichero
real ``N_25P_E_V_1_101_1_1_2_A_1.CSV`` (Serie verde del PGE-ROM, "Resumen
general por servicios y capítulos del presupuesto de gastos", presupuesto
prorrogado 2025-P vigente para 2026):

- CSV en ISO-8859-1 (latin-1) con separador ``;`` (a diferencia de DIR3, que
  es XLSX: aquí sí aplica la advertencia clásica de encoding).
- Cabecera documental en las primeras filas; la fila ``;PRESUPUESTO 2025-P;``
  identifica el presupuesto de origen.
- Filas de sección: columna ``Orgánica`` = ``NN`` (dos dígitos).
- Filas de servicio: columna ``Orgánica`` = ``NN.NN``; la denominación llega
  con un espacio inicial.
- El resto de filas (totales, capítulos) se ignoran.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

_SECCION_RE = re.compile(r"^\d{2}$")
_SERVICIO_RE = re.compile(r"^\d{2}\.\d{2}$")
_PRESUPUESTO_RE = re.compile(r"PRESUPUESTO\s+([0-9]{4}-?[A-Z]?)")


def parse_resumen_servicios(path: Path, *, ejercicio: int) -> pd.DataFrame:
    """Parsea el resumen por servicios a la tabla ``dim_seccion_servicio``.

    ``ejercicio`` es el año al que rige el presupuesto (en prórroga no coincide
    con el del presupuesto de origen, que se lee del propio fichero y se
    conserva en la columna ``presupuesto``).
    """
    secciones: dict[str, str] = {}
    servicios: list[tuple[str, str, str]] = []
    presupuesto: str | None = None

    with path.open(encoding="latin-1", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if len(row) < 2:
                continue
            organica = row[0].strip()
            explicacion = row[1].strip()
            if presupuesto is None and (m := _PRESUPUESTO_RE.search(";".join(row))):
                presupuesto = m.group(1)
            if _SECCION_RE.fullmatch(organica) and explicacion:
                secciones[organica] = explicacion
            elif _SERVICIO_RE.fullmatch(organica) and explicacion:
                seccion_cod, servicio_cod = organica.split(".")
                servicios.append((seccion_cod, servicio_cod, explicacion))

    if presupuesto is None:
        raise ValueError(f"No se encontró la fila 'PRESUPUESTO ...' en {path}")
    if not servicios:
        raise ValueError(f"No se encontraron servicios (NN.NN) en {path}")

    return pd.DataFrame(
        {
            "ejercicio": ejercicio,
            "presupuesto": presupuesto,
            "seccion_cod": [s[0] for s in servicios],
            "seccion_denominacion": [secciones.get(s[0]) for s in servicios],
            "servicio_cod": [s[1] for s in servicios],
            "servicio_denominacion": [s[2] for s in servicios],
        }
    )
