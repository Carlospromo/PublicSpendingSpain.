"""Extractor de DIR3 (Directorio Común de Unidades Orgánicas y Oficinas).

SOLO descarga: deja los XLSX oficiales en ``data/raw/dir3/<fecha_captura>/`` sin
transformar. Las URLs y los nombres de fichero viven en ``config/sources.yaml``
(entrada ``dir3``), no incrustados aquí.

Fuente verificada (2026-06): dataset nacional datos.gob.es E05251701; ficheros
servidos por el PAe en formato XLSX. El host de descargas está tras un WAF que
puede rechazar peticiones automatizadas; en ese caso ``download_to_raw`` lanza
``SourceBlockedError`` indicando que se aporte el fichero a mano.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from config import settings

from .base import download_to_raw

FUENTE = "dir3"


def _dir3_files() -> list[dict[str, Any]]:
    """Lista de distribuciones DIR3 declaradas en config/sources.yaml."""
    sources = settings.load_sources()
    files: list[dict[str, Any]] = sources["dir3"].get("files", [])
    if not files:
        raise ValueError("La entrada 'dir3' de sources.yaml no declara 'files'.")
    return files


def extract(
    *,
    raw_dir: Path | None = None,
    capture_date: date | None = None,
) -> list[Path]:
    """Descarga todas las distribuciones DIR3 a la capa raw.

    Devuelve las rutas de los ficheros guardados. Propaga ``SourceBlockedError``
    (fail loud) si el WAF impide la descarga, para que el usuario aporte el
    fichero manualmente en lugar de continuar con datos corruptos.
    """
    raw_dir = raw_dir or settings.RAW_DIR
    saved: list[Path] = []
    for entry in _dir3_files():
        saved.append(
            download_to_raw(
                entry["url"],
                fuente=FUENTE,
                filename=entry["filename"],
                raw_dir=raw_dir,
                capture_date=capture_date,
            )
        )
    return saved
