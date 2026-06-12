"""Compatibilidad: el anclaje orgánico vive ahora en ``anclaje_organico``.

El motor DIR3 → (sección, servicio) nació aquí acoplado a PLACSP; al
incorporar la BDNS (mismo problema, distinto punto de entrada) se movió a
``transform/anclaje_organico.py`` como módulo compartido. Este módulo re-exporta
los nombres históricos para no romper a los consumidores existentes; el código
nuevo debe importar de ``anclaje_organico`` directamente.
"""

import pandas as pd

from gasto_estado.transform.anclaje_organico import (
    ANCLA_FUERA_PERIMETRO,
    ANCLA_ORGANICA_SIN_SERVICIO,
    ANCLA_SERVICIO,
    ANCLA_SIN_ANCLAR,
    ANCLAJE_COLUMNS,
    ANCLAJE_TIPOS,
    SENAL_DIR3_ANCESTRO,
    SENAL_DIR3_DIRECTO,
    SENAL_DIR3_MALFORMADO,
    SENAL_DIR3_NO_AGE,
    SENAL_EJERCICIO_SIN_CROSSWALK,
    SENAL_ENTIDAD_INSTRUMENTAL,
    SENAL_SIN_DIR3,
    SENAL_SIN_SERVICIO_EN_CADENA,
    Anclador,
    anclar_contratos,
)
from gasto_estado.transform.anclaje_organico import (
    anclaje_stats as _anclaje_stats,
)

__all__ = [
    "ANCLA_FUERA_PERIMETRO",
    "ANCLA_ORGANICA_SIN_SERVICIO",
    "ANCLA_SERVICIO",
    "ANCLA_SIN_ANCLAR",
    "ANCLAJE_COLUMNS",
    "ANCLAJE_TIPOS",
    "SENAL_DIR3_ANCESTRO",
    "SENAL_DIR3_DIRECTO",
    "SENAL_DIR3_MALFORMADO",
    "SENAL_DIR3_NO_AGE",
    "SENAL_EJERCICIO_SIN_CROSSWALK",
    "SENAL_ENTIDAD_INSTRUMENTAL",
    "SENAL_SIN_DIR3",
    "SENAL_SIN_SERVICIO_EN_CADENA",
    "Anclador",
    "anclar_contratos",
    "anclaje_stats",
]


def anclaje_stats(contratos: pd.DataFrame) -> dict[str, float]:
    """Firma histórica (por expediente PLACSP) sobre el contador compartido."""
    stats = _anclaje_stats(contratos, unidad_col="expediente_id")
    stats["expedientes_total"] = stats.pop("unidades_total")
    return stats
