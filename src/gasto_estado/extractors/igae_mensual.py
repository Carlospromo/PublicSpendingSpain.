"""Extractor de la ejecución presupuestaria mensual de la IGAE (Anexo I, AGE).

SOLO descarga (CLAUDE.md §2): el Anexo I se guarda inmutable en
``data/raw/igae_mensual/<YYYY-MM>/`` sin transformar. El reconocimiento de la
estructura del fichero está en ``docs/igae_anexo_i_estructura.md``; el parser
llega en la Fase 2 (Prompt 5).

Patrón de URL VERIFICADO (2026-06-11) con peticiones reales:
``…/Documents/MENSUAL%20<MES>%20<AÑO>%20ANEXO%20I.xlsx`` con el mes en
mayúsculas en español. Resuelve para 2019+; en ≤2018 el nombre lleva a veces
el sufijo " (EXCEL)" de forma inconsistente, así que para históricos antiguos
el camino fiable es scrapear la página del año
(``imejecucionpresupuesto<YYYY>.aspx``), que aquí se usa como fallback del
descubrimiento del último mes.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .base import DEFAULT_HEADERS, download_to_raw

FUENTE = "igae_mensual"

# Mes presupuestario en el formato del nombre de fichero IGAE (verificado:
# mayúsculas, en español, sin tildes en los meses que la llevan en castellano
# no aplica: ninguno de los nombres de mes lleva tilde en mayúsculas IGAE).
MESES_ES = {
    1: "ENERO",
    2: "FEBRERO",
    3: "MARZO",
    4: "ABRIL",
    5: "MAYO",
    6: "JUNIO",
    7: "JULIO",
    8: "AGOSTO",
    9: "SEPTIEMBRE",
    10: "OCTUBRE",
    11: "NOVIEMBRE",
    12: "DICIEMBRE",
}

_PERIODO_RE = re.compile(r"^(\d{4})-(\d{2})$")

# Meses hacia atrás que sondea el descubrimiento antes de rendirse (la IGAE
# publica con ~25-30 días de desfase; 14 cubre con holgura cualquier parón).
_MAX_LOOKBACK = 14


def _source_config() -> dict[str, Any]:
    from config import settings

    return settings.load_sources()["igae_mensual"]


def parse_periodo(periodo: str) -> tuple[int, int]:
    """Valida y descompone un periodo ``YYYY-MM`` → ``(año, mes)``."""
    m = _PERIODO_RE.match(periodo)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"Periodo inválido: {periodo!r} (formato esperado: YYYY-MM)")
    return int(m.group(1)), int(m.group(2))


def anexo_i_filename(periodo: str) -> str:
    """Nombre oficial del fichero para un periodo: ``MENSUAL ABRIL 2026 ANEXO I.xlsx``."""
    anio, mes = parse_periodo(periodo)
    return f"MENSUAL {MESES_ES[mes]} {anio} ANEXO I.xlsx"


def compose_anexo_i_url(periodo: str, *, documents_base: str | None = None) -> str:
    """Compone la URL del Anexo I de un periodo (espacios → %20)."""
    base = documents_base or _source_config()["url_documents"]
    return f"{base.rstrip('/')}/{quote(anexo_i_filename(periodo))}"


def _periodo_anterior(anio: int, mes: int) -> tuple[int, int]:
    return (anio, mes - 1) if mes > 1 else (anio - 1, 12)


def _scrape_index_periodos(index_url: str, *, timeout: float = 30.0) -> list[str]:
    """Fallback: extrae los periodos con Anexo I publicados en la página del año."""
    response = httpx.get(index_url, headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    meses_inv = {nombre: numero for numero, nombre in MESES_ES.items()}
    encontrados = re.findall(
        r"MENSUAL%20([A-Z]+)%20(\d{4})%20ANEXO%20I(?:%20%28EXCEL%29)?\.xlsx",
        response.text,
        re.IGNORECASE,
    )
    periodos = {
        f"{anio}-{meses_inv[mes.upper()]:02d}"
        for mes, anio in encontrados
        if mes.upper() in meses_inv
    }
    return sorted(periodos)


def discover_latest_periodo(*, today: date | None = None) -> str:
    """Descubre el último periodo con Anexo I publicado.

    Sondea el patrón de URL hacia atrás desde el mes corriente (la publicación
    llega ~25-30 días tras el cierre); si ningún sondeo resuelve, scrapea la
    página índice del año como fallback. Fail loud si tampoco hay nada.
    """
    cfg = _source_config()
    today = today or date.today()
    anio, mes = today.year, today.month
    for _ in range(_MAX_LOOKBACK):
        periodo = f"{anio}-{mes:02d}"
        url = compose_anexo_i_url(periodo, documents_base=cfg["url_documents"])
        response = httpx.head(url, headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True)
        if response.status_code == 200:
            return periodo
        anio, mes = _periodo_anterior(anio, mes)

    periodos = _scrape_index_periodos(cfg["url_index"])
    if periodos:
        return periodos[-1]
    raise RuntimeError(
        f"No se encontró ningún Anexo I publicado en los últimos {_MAX_LOOKBACK} "
        f"meses ni en la página índice ({cfg['url_index']})."
    )


def extract(
    *,
    periodo: str | None = None,
    raw_dir: Path | None = None,
) -> list[Path]:
    """Descarga el Anexo I del ``periodo`` dado (o del último disponible).

    Guarda en ``data/raw/igae_mensual/<YYYY-MM>/<nombre oficial>``; si la
    captura ya existe no se sobrescribe (inmutabilidad del raw).
    """
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    if periodo is None:
        periodo = discover_latest_periodo()
    else:
        parse_periodo(periodo)

    saved = download_to_raw(
        compose_anexo_i_url(periodo),
        fuente=FUENTE,
        filename=anexo_i_filename(periodo),
        raw_dir=raw_dir,
        subdir=periodo,
    )
    return [saved]
