"""Detección de la época ("vintage") de maquetación del Anexo I de la IGAE.

Los Excel oficiales cambian de formato entre ejercicios (CLAUDE.md §2): hay una
familia de parsers, uno por vintage, con detección de formato. Aquí solo se
identifica el vintage; cada parser vive en su propio módulo.

Vintages conocidos (frontera VERIFICADA sobre ficheros reales completos):

- ``2021_plus`` (contenedor OOXML .xlsx): libro con hoja resumen ``S5`` y una
  hoja por sección ``S01``…; cabecera ``APLICACIÓN PGE`` + 3 magnitudes.
  Verificado en 2016-11, 2017-11, 2018-11, 2020-11 y 2026-03/04: los .xlsx
  históricos comparten EXACTAMENTE esta gramática, así que enrutan aquí.
- ``2015_2020_xls`` (contenedor BIFF/OLE2 .xls): misma gramática interna, otro
  contenedor. La IGAE publicó .xls desde 2015 hasta ~abril 2016; la transición
  a .xlsx ocurre DENTRO de 2016 (abril 2016 = .xls, noviembre 2016 = .xlsx).
  openpyxl no lee BIFF → parser propio sobre xlrd (``v2015_2020.py``).

La detección va por contenido (magic bytes + estructura de hojas), no por
extensión ni por año: es lo único robusto frente al zoo de nomenclaturas de la
fuente (sufijos "(EXCEL)", "PROVISIONAL", nombres sin año, dobles espacios).
"""

from __future__ import annotations

import re
from pathlib import Path

import openpyxl
import xlrd

VINTAGE_2021_PLUS = "2021_plus"
VINTAGE_2015_2020_XLS = "2015_2020_xls"

_SECTION_SHEET_RE = re.compile(r"^S\d{2}$")
_RESUMEN_SHEET = "S5"

_ZIP_MAGIC = b"PK\x03\x04"  # OOXML (.xlsx)
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # BIFF (.xls)


def _has_anexo_i_layout(sheets: set[str]) -> bool:
    return _RESUMEN_SHEET in sheets and any(_SECTION_SHEET_RE.match(s) for s in sheets)


def detect_vintage(path: Path) -> str:
    """Devuelve el identificador de vintage del Anexo I en ``path``.

    Fail loud (CLAUDE.md §2): si el contenedor o la maquetación no coinciden
    con ningún vintage conocido, se aborta en lugar de adivinar un parser.
    """
    with path.open("rb") as f:
        magic = f.read(8)

    if magic.startswith(_ZIP_MAGIC):
        workbook = openpyxl.load_workbook(path, read_only=True)
        try:
            sheets = set(workbook.sheetnames)
        finally:
            workbook.close()
        if _has_anexo_i_layout(sheets):
            return VINTAGE_2021_PLUS
    elif magic == _OLE2_MAGIC:
        book = xlrd.open_workbook(str(path))
        sheets = set(book.sheet_names())
        if _has_anexo_i_layout(sheets):
            return VINTAGE_2015_2020_XLS
    else:
        raise ValueError(
            f"Contenedor no reconocido en {path.name}: ni OOXML (.xlsx) ni BIFF (.xls)."
        )

    raise ValueError(
        f"No se reconoce el vintage del Anexo I en {path.name}: "
        f"hojas={sorted(sheets)[:8]}… (maquetación desconocida)"
    )
