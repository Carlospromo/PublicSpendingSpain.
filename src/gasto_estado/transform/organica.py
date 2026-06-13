"""Construcción de la dimensión orgánica base (``dim_organica``) desde DIR3.

SCD tipo 2 sobre la jerarquía orgánica (CLAUDE.md §3): cada fila es una unidad
DIR3 con vigencia temporal (``fecha_inicio``, ``fecha_fin``). El ministerio
padre llega directamente del fichero oficial (``C_ID_DEP_UD_PRINCIPAL`` = raíz
de la entidad: ministerio o Presidencia del Gobierno).

``seccion_cod`` y ``servicio_cod`` se emiten a null POR DISEÑO: el enganche con
la clasificación presupuestaria no se materializa en esta dimensión, sino que el
crosswalk servicio↔DIR3 (``seeds/crosswalk_servicio_dir3.csv``) se aplica en
tiempo de anclaje (``transform/anclaje_organico.py``). Por eso ``dim_organica``
no es FK de los hechos (ver ``db/modelo.sql``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from gasto_estado.transform.nivel_organico import classify

# Columnas de la dimensión, en el orden canónico (CLAUDE.md §8).
DIM_COLUMNS = [
    "seccion_cod",  # null por diseño: el crosswalk servicio↔DIR3 se aplica al anclar
    "servicio_cod",  # null por diseño: ídem (ver docstring del módulo)
    "dir3_cod",
    "denominacion",
    "dir3_padre_cod",
    "ministerio_dir3_cod",
    "ministerio_denominacion",
    "nivel_jerarquico",
    "nivel_organico",
    "nivel_organico_senal",
    "tipo_entidad",
    "estado",
    "fecha_inicio",
    "fecha_fin",
]

# Estados DIR3 que se consideran vigentes (sin fecha_fin).
_ESTADOS_VIGENTES = ("V", "T")


def build_dim_organica(unidades: pd.DataFrame, *, capture_date: date) -> pd.DataFrame:
    """Construye ``dim_organica`` (SCD tipo 2) desde el DataFrame canónico DIR3.

    - ``fecha_inicio``: fecha de alta oficial; si la fuente no la informa (el
      ~82% de las filas), la fecha de captura del snapshot ("primera vez vista").
    - ``fecha_fin``: null para unidades vigentes/transitorias; fecha de captura
      para extinguidas/anuladas (el snapshot ya no las considera vivas).
    - ``seccion_cod``/``servicio_cod``: null por diseño (el crosswalk servicio↔
      DIR3 se aplica al anclar, no se materializa aquí; ver docstring del módulo).
    """
    clasificacion = [
        classify(denominacion, nivel)
        for denominacion, nivel in zip(
            unidades["denominacion"], unidades["nivel_jerarquico"], strict=True
        )
    ]
    dim = pd.DataFrame(
        {
            "seccion_cod": pd.Series([None] * len(unidades), dtype="object"),
            "servicio_cod": pd.Series([None] * len(unidades), dtype="object"),
            "dir3_cod": unidades["dir3_cod"],
            "denominacion": unidades["denominacion"],
            "dir3_padre_cod": unidades["dir3_padre_cod"],
            "ministerio_dir3_cod": unidades["dir3_raiz_cod"],
            "ministerio_denominacion": unidades["denominacion_raiz"],
            "nivel_jerarquico": unidades["nivel_jerarquico"],
            "nivel_organico": pd.Series(
                [nivel for nivel, _ in clasificacion], index=unidades.index
            ),
            "nivel_organico_senal": pd.Series(
                [senal for _, senal in clasificacion], index=unidades.index
            ),
            # Tipo de entidad pública DIR3 (MN=estructura ministerial; OA/AT/
            # EE/SM/AP/…=ente con presupuesto propio). Es la frontera de
            # perímetro presupuestario que usa el anclaje PLACSP.
            "tipo_entidad": unidades["tipo_entidad"],
            "estado": unidades["estado"],
            "fecha_inicio": unidades["fecha_alta"].map(
                lambda alta: alta if alta is not None else capture_date
            ),
            "fecha_fin": unidades["estado"].map(
                lambda estado: None if estado in _ESTADOS_VIGENTES else capture_date
            ),
        },
        columns=DIM_COLUMNS,
    )
    return dim.sort_values(["ministerio_dir3_cod", "nivel_jerarquico", "dir3_cod"]).reset_index(
        drop=True
    )


def write_seed(dim: pd.DataFrame, path: Path) -> None:
    """Materializa la dimensión como seed CSV versionado (git-diffable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dim.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
