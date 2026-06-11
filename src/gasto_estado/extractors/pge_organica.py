"""Extractor de la clasificación orgánica del PGE (SEPG, árbol PGE-ROM).

SOLO descarga: deja el CSV oficial en ``data/raw/pge_organica/<fecha>/`` sin
transformar. La URL vive en ``config/sources.yaml`` (entrada ``pge_organica``).

Fuente verificada (2026-06): Serie verde del PGE-ROM del presupuesto prorrogado
("Prórroga del Presupuesto para 2026" en SEPG; árbol ``PGE2025Prorroga``). El
documento "Resumen general por servicios y capítulos" enumera las 37 secciones
y todos sus servicios presupuestarios con denominación oficial. Host alcanzable
sin WAF (a diferencia del de DIR3).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .base import download_to_raw

FUENTE = "pge_organica"

# El CSV oficial empieza exactamente así (verificado); si llega HTML de error,
# download_to_raw falla en alto en lugar de contaminar la capa raw.
CSV_MAGIC = b";PRESUPUESTOS"


def _source_config() -> dict[str, Any]:
    from config import settings

    sources = settings.load_sources()
    cfg: dict[str, Any] = sources["pge_organica"]
    if not cfg.get("url_resumen_servicios"):
        raise ValueError("'pge_organica' en sources.yaml no declara 'url_resumen_servicios'.")
    return cfg


def extract(
    *,
    raw_dir: Path | None = None,
    capture_date: date | None = None,
) -> list[Path]:
    """Descarga el resumen por servicios del PGE vigente a la capa raw."""
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    cfg = _source_config()
    url: str = cfg["url_resumen_servicios"]
    saved = download_to_raw(
        url,
        fuente=FUENTE,
        filename=url.rsplit("/", 1)[-1],
        raw_dir=raw_dir,
        capture_date=capture_date,
        expected_magic=CSV_MAGIC,
    )
    return [saved]
