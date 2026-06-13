"""Extractor de PLACSP — datos abiertos de contratación (sindicación 643).

SOLO descarga y escritura inmutable (CLAUDE.md §2). Dos modos sobre la misma
fuente, ambos verificados con descargas reales (2026-06-12):

- **anual**: el ZIP por año ``…/licitacionesPerfilesContratanteCompleto3_<AÑO>.zip``
  (histórico desde 2012 y también el año en curso). Es el camino de volcado
  masivo; cada ZIP contiene uno o varios ``.atom`` CODICE.
- **incremental**: el feed "cabecera"
  ``…/licitacionesPerfilesContratanteCompleto3.atom`` (último tramo, se renueva a
  diario) y, siguiendo ``atom:link@rel="next"``, las páginas anteriores hasta
  ``paginas`` o hasta agotar el feed. Cada fichero trae como máx. 500 entradas.

*Fail loud*: el portal devuelve un "soft-200" HTML para nombres inexistentes;
``download_to_raw`` con ``expected_magic`` (ZIP o ``<?xml``) aborta sin escribir
si el contenido no es el binario esperado, en vez de contaminar la capa raw.

El raw se guarda en ``data/raw/placsp/<fecha_captura>/643/{anual|incremental}/``.
A diferencia de IGAE (ficheros < 1,5 MB), una captura PLACSP pesa 10-160 MB y NO
se versiona: el git-scraping de CI la regenera (ver .gitignore). La detección de
formato CODICE y el parseo viven en ``parsers/placsp`` (separación de capas).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lxml import etree

from .base import XML_MAGIC, ZIP_MAGIC, SourceBlockedError, download_to_raw

FUENTE = "placsp"

# Espacio de nombres Atom (la paginación vive aquí; el cuerpo CODICE lo resuelve
# el parser). El "rel=next" apunta a la página inmediatamente anterior del feed.
_ATOM_NS = "http://www.w3.org/2005/Atom"

# Tope de seguridad de la paginación incremental: el histórico completo son
# miles de páginas (eso es trabajo del modo anual). El incremental cubre el
# tramo reciente; por defecto solo la cabecera.
_MAX_PAGINAS = 500


def _source_config() -> dict[str, Any]:
    from config import settings

    return settings.load_sources()["placsp"]


def _basename(url: str) -> str:
    """Nombre de fichero de una URL (estable: las páginas llevan timestamp)."""
    return Path(urlparse(url).path).name


def zip_url_anual(anio: int, *, patron: str | None = None) -> str:
    """URL del ZIP anual de la sindicación 643 para ``anio``."""
    patron = patron or _source_config()["url_zip_anual_patron"]
    return patron.format(anio=anio)


def _next_link(atom_path: Path) -> str | None:
    """Devuelve el ``href`` del ``atom:link@rel="next"`` de una página, o None."""
    root = etree.parse(str(atom_path)).getroot()
    for link in root.findall(f"{{{_ATOM_NS}}}link"):
        if link.get("rel") == "next":
            return link.get("href")
    return None


def extract(
    *,
    anio: int | None = None,
    paginas: int = 1,
    raw_dir: Path | None = None,
    capture_date: date | None = None,
) -> list[Path]:
    """Descarga la sindicación 643 de PLACSP a la capa raw (inmutable).

    - ``anio`` dado → modo anual: descarga el ZIP del año (histórico o en curso).
    - ``anio`` None → modo incremental: descarga la cabecera del feed y sigue
      ``rel="next"`` hasta ``paginas`` páginas (1 = solo la cabecera, el tramo
      diario) o hasta que el feed se agote.

    Devuelve las rutas guardadas. Las capturas existentes no se reescriben
    (idempotencia + inmutabilidad): los nombres de página llevan timestamp, así
    que reejecutar no vuelve a descargar lo ya capturado.
    """
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    capture_date = capture_date or date.today()
    cfg = _source_config()

    if anio is not None:
        anio_min = int(cfg.get("anio_minimo", 2012))
        if anio < anio_min or anio > capture_date.year:
            raise ValueError(
                f"Año fuera de rango para PLACSP: {anio} "
                f"(disponible {anio_min}-{capture_date.year})."
            )
        url = zip_url_anual(anio, patron=cfg["url_zip_anual_patron"])
        saved = download_to_raw(
            url,
            fuente=FUENTE,
            filename=_basename(url),
            raw_dir=raw_dir,
            subdir=f"{capture_date.isoformat()}/643/anual",
            expected_magic=ZIP_MAGIC,
        )
        return [saved]

    if paginas < 1:
        raise ValueError(f"paginas debe ser >= 1, recibido {paginas}")

    subdir = f"{capture_date.isoformat()}/643/incremental"
    pagina_url: str | None = cfg["url_atom_cabecera"]
    rutas: list[Path] = []
    for _ in range(min(paginas, _MAX_PAGINAS)):
        if pagina_url is None:
            break
        saved = download_to_raw(
            pagina_url,
            fuente=FUENTE,
            filename=_basename(pagina_url),
            raw_dir=raw_dir,
            subdir=subdir,
            expected_magic=XML_MAGIC,
        )
        rutas.append(saved)
        pagina_url = _next_link(saved)
    if not rutas:
        raise SourceBlockedError(
            f"PLACSP no devolvió ninguna página ATOM desde {cfg['url_atom_cabecera']}."
        )
    return rutas
