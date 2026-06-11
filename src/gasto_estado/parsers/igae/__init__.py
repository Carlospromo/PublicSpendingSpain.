"""Parsers del Anexo I de la IGAE: detección de vintage y despacho.

Punto de entrada invocable que toma el raw de un periodo y devuelve el
DataFrame canónico, eligiendo el parser según el vintage detectado (CLAUDE.md
§2: familia de parsers por época, no un parser único). Ambos vintages emiten
el MISMO contrato canónico (columnas, clave natural y cobertura de magnitudes).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .detect import VINTAGE_2015_2020_XLS, VINTAGE_2021_PLUS, detect_vintage
from .v2015_2020 import parse_anexo_i as _parse_2015_2020
from .v2021_plus import parse_anexo_i as _parse_2021_plus

_PARSERS = {
    VINTAGE_2021_PLUS: _parse_2021_plus,
    VINTAGE_2015_2020_XLS: _parse_2015_2020,
}


def parse_anexo_i(path: Path, *, periodo: str, fecha_captura: date | None = None) -> pd.DataFrame:
    """Detecta el vintage del Anexo I en ``path`` y lo parsea a canónico."""
    vintage = detect_vintage(path)
    return _PARSERS[vintage](path, periodo=periodo, fecha_captura=fecha_captura)


def parse_periodo(
    periodo: str,
    *,
    raw_dir: Path | None = None,
    fecha_captura: date | None = None,
) -> pd.DataFrame:
    """Localiza el raw del Anexo I de un ``periodo`` y lo parsea a canónico.

    Busca en ``<raw_dir>/igae_mensual/<periodo>/`` el fichero del Anexo I
    (descargado por el extractor). Fail loud si no hay exactamente uno.
    """
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    periodo_dir = raw_dir / "igae_mensual" / periodo
    # El nombre oficial varía con la época: '... ANEXO I.xlsx', con sufijo
    # ' (EXCEL)', 'PROVISIONAL', o contenedor .xls — el glob los admite todos.
    candidatos = sorted(periodo_dir.glob("*ANEXO I*.xls*"))
    if len(candidatos) != 1:
        raise FileNotFoundError(
            f"Se esperaba 1 Anexo I en {periodo_dir}, encontrados {len(candidatos)}. "
            "¿Descargaste el periodo con 'extract --source igae --periodo'?"
        )
    return parse_anexo_i(candidatos[0], periodo=periodo, fecha_captura=fecha_captura)
