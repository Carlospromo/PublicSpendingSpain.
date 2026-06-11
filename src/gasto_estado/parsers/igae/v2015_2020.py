"""Parser del Anexo I de la IGAE, vintage 2015–2020 en contenedor .xls (BIFF).

Decisión de vintage (Prompt 6), justificada con la inspección de ficheros
reales COMPLETOS (dic-2015, nov-2016, nov-2017, nov-2018, nov-2020):

- La **gramática interna es idéntica** a la del vintage 2021+ en todo el rango
  2015–2026: hoja resumen ``S5`` + hojas de sección ``SNN``, misma cabecera
  (``APLICACIÓN PGE`` + créditos iniciales/definitivos/ORN), misma celda
  compuesta de aplicación, mismos subtotales ``TOTAL SERVICIO`` y mismo ``-``
  para "sin dato". Los .xlsx de 2016–2020 parsean con ``v2021_plus`` SIN
  cambios y cuadran (verificado empíricamente).
- La única frontera real de vintage es el **contenedor**: BIFF/OLE2 ``.xls``
  desde 2015 hasta ~abril 2016, OOXML ``.xlsx`` desde ~noviembre 2016 (la
  transición ocurre DENTRO de 2016). openpyxl no lee BIFF: este módulo lee con
  ``xlrd`` y **reutiliza la gramática de** ``v2021_plus`` (clasificador de
  filas, descomposición de la aplicación, mapeo de importes y cuadre interno),
  sin modificarla (CLAUDE.md §2/§9).
- Particularidad de dominio del histórico: ``provincia_cod`` puede ser ``DT``
  (Diversos Territorios), admitido en el esquema canónico.

El DataFrame emitido es EXACTAMENTE el mismo canónico que el de 2021+ (mismas
columnas, misma clave natural con ``provincia_cod``, misma cobertura explícita
de magnitudes: solo crédito inicial, definitivo y ORN).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd
import xlrd

from gasto_estado.transform.text import normalize

from .v2021_plus import (
    APLICACION,
    DETALLE_COLUMNS,
    FUENTE,
    SUBTOTAL_SERVICIO,
    _check_cuadre,
    _sum_amount,
    _to_amount,
    classify_row,
    parse_aplicacion,
)

_SECTION_SHEET_RE = re.compile(r"^S\d{2}$")


def parse_anexo_i(
    path: Path,
    *,
    periodo: str,
    fecha_captura: date | None = None,
) -> pd.DataFrame:
    """Parsea un Anexo I en .xls (BIFF) al DataFrame canónico de detalle.

    Misma semántica que ``v2021_plus.parse_anexo_i``: solo filas APLICACION al
    detalle, cuadre aplicaciones↔TOTAL SERVICIO por servicio (``CuadreError``
    fail loud si descuadra) y ``-`` → nulo.
    """
    fecha_captura = fecha_captura or date.today()
    book = xlrd.open_workbook(str(path))
    registros: list[dict[str, object]] = []
    for sheet_name in book.sheet_names():
        if not _SECTION_SHEET_RE.match(sheet_name):
            continue
        registros.extend(
            _parse_section(
                book.sheet_by_name(sheet_name), periodo=periodo, fecha_captura=fecha_captura
            )
        )
    return pd.DataFrame(registros, columns=DETALLE_COLUMNS)


def _parse_section(
    sheet: xlrd.sheet.Sheet, *, periodo: str, fecha_captura: date
) -> list[dict[str, object]]:
    registros: list[dict[str, object]] = []
    acumulado = [0.0, 0.0, 0.0]
    servicio_denominacion: str | None = None
    n_aplicaciones = 0

    for i in range(sheet.nrows):
        valores = sheet.row_values(i)
        # xlrd devuelve '' para celdas vacías; se normaliza a None como openpyxl.
        fila = [None if v == "" else v for v in valores] + [None] * (5 - len(valores))
        col0, aplicacion_pge = fila[0], fila[1]
        magnitudes = (fila[2], fila[3], fila[4])
        tipo = classify_row(aplicacion_pge)

        if tipo == APLICACION:
            servicio_denominacion = normalize(str(col0)) if col0 is not None else None
            aplicacion = parse_aplicacion(str(aplicacion_pge))
            importes = [_to_amount(m) for m in magnitudes]
            for k, importe in enumerate(importes):
                acumulado[k] += importe if importe is not None else 0.0
            n_aplicaciones += 1
            registros.append(
                {
                    "periodo": periodo,
                    "fuente": FUENTE,
                    "fecha_captura": fecha_captura,
                    "seccion_cod": aplicacion.seccion_cod,
                    "servicio_cod": aplicacion.servicio_cod,
                    "servicio_denominacion": servicio_denominacion,
                    "programa_cod": aplicacion.programa_cod,
                    "provincia_cod": aplicacion.provincia_cod,
                    "economica_cod": aplicacion.economica_cod,
                    "aplicacion_denominacion": aplicacion.denominacion,
                    "credito_inicial": importes[0],
                    "credito_definitivo": importes[1],
                    "orn": importes[2],
                }
            )
        elif tipo == SUBTOTAL_SERVICIO:
            subtotal = [_sum_amount(m) for m in magnitudes]
            _check_cuadre(sheet.name, servicio_denominacion, acumulado, subtotal, n_aplicaciones)
            acumulado = [0.0, 0.0, 0.0]
            n_aplicaciones = 0

    return registros
