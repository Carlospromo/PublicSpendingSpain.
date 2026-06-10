"""Configuración central del proyecto: rutas, perímetro y catálogo de fuentes.

Sin lógica de negocio: solo constantes y carga de ``config/sources.yaml``.
"""

from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SOURCES_FILE = CONFIG_DIR / "sources.yaml"

DATA_DIR = PROJECT_ROOT / "data"
# Capa raw: INMUTABLE. Estructura: data/raw/<fuente>/<fecha_captura>/<fichero>
RAW_DIR = DATA_DIR / "raw"
# Almacén analítico (DuckDB + Parquet)
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

# ---------------------------------------------------------------------------
# Perímetro (v1): AGE + organismos estatales. Sin CCAA ni entidades locales.
# ---------------------------------------------------------------------------

PERIMETRO_V1 = (
    "AGE",
    "organismos_estatales",
)

# ---------------------------------------------------------------------------
# Catálogo de fuentes
# ---------------------------------------------------------------------------


def load_sources(path: Path = SOURCES_FILE) -> dict[str, dict[str, Any]]:
    """Carga el catálogo de fuentes desde ``config/sources.yaml``."""
    with path.open(encoding="utf-8") as f:
        sources: dict[str, dict[str, Any]] = yaml.safe_load(f)
    return sources
