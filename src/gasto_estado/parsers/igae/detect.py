"""Detección de la época ("vintage") de maquetación del Anexo I de la IGAE.

Los Excel oficiales cambian de formato entre ejercicios (CLAUDE.md §2): hay una
familia de parsers, uno por vintage, con detección de formato. Aquí solo se
identifica el vintage; cada parser vive en su propio módulo.

Vintage ``2021_plus`` (verificado sobre ficheros 2019–2026): un libro con la
hoja resumen ``S5`` y una hoja por sección ``S01``…``S38``; las hojas de
sección llevan en la fila 1 la cabecera ``APLICACIÓN PGE`` + las tres
magnitudes (créditos iniciales, definitivos y ORN).
"""

from __future__ import annotations

import re
from pathlib import Path

import openpyxl

VINTAGE_2021_PLUS = "2021_plus"

_SECTION_SHEET_RE = re.compile(r"^S\d{2}$")
_RESUMEN_SHEET = "S5"


def detect_vintage(path: Path) -> str:
    """Devuelve el identificador de vintage del Anexo I en ``path``.

    Fail loud (CLAUDE.md §2): si la maquetación no coincide con ningún vintage
    conocido, se aborta en lugar de adivinar un parser.
    """
    workbook = openpyxl.load_workbook(path, read_only=True)
    try:
        sheets = set(workbook.sheetnames)
        section_sheets = {s for s in sheets if _SECTION_SHEET_RE.match(s)}
        if _RESUMEN_SHEET in sheets and section_sheets:
            return VINTAGE_2021_PLUS
    finally:
        workbook.close()
    raise ValueError(
        f"No se reconoce el vintage del Anexo I en {path.name}: "
        f"hojas={sorted(sheets)[:8]}… (¿formato ≤2018? aún no soportado)"
    )
