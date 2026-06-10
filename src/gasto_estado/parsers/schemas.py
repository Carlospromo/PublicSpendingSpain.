"""Esquemas pandera de validación de entrada (raw → DataFrame canónico).

Un esquema por fuente. Validan el contrato del parser, no la coherencia
contable (eso vive en ``quality/checks.py``).
"""

from __future__ import annotations

import pandera.pandas as pa

# Estados oficiales de una unidad DIR3 (hoja "Catálogos de clasificación" del
# fichero oficial): Vigente, Extinguido, Anulado, Transitorio.
DIR3_ESTADOS = ("V", "E", "A", "T")

# Códigos DIR3: letra(s) + dígitos, p. ej. "E04921901", "EA0008567".
_DIR3_COD_REGEX = r"^[A-Z]{1,2}\d{7,8}$"

dir3_unidades_schema = pa.DataFrameSchema(
    {
        "dir3_cod": pa.Column(str, pa.Check.str_matches(_DIR3_COD_REGEX), unique=True),
        "denominacion": pa.Column(str),
        # 1 = Administración del Estado (único valor esperado en el listado AGE).
        "nivel_administracion": pa.Column("int64", pa.Check.isin(range(1, 6))),
        # Tipo de entidad: solo informado en unidades cabecera de entidad. El
        # catálogo completo vive en el Manual de Atributos DIR1014; no se
        # restringe aquí a una lista cerrada.
        "tipo_entidad": pa.Column(str, nullable=True),
        "nivel_jerarquico": pa.Column("int64", pa.Check.ge(0)),
        "dir3_padre_cod": pa.Column(str, pa.Check.str_matches(_DIR3_COD_REGEX)),
        "denominacion_padre": pa.Column(str, nullable=True),
        "dir3_raiz_cod": pa.Column(str, pa.Check.str_matches(_DIR3_COD_REGEX)),
        "denominacion_raiz": pa.Column(str, nullable=True),
        "es_edp": pa.Column(str, pa.Check.isin(["S", "N"]), nullable=True),
        "edp_cod": pa.Column(str, nullable=True),
        "edp_denominacion": pa.Column(str, nullable=True),
        "estado": pa.Column(str, pa.Check.isin(DIR3_ESTADOS)),
        "fecha_alta": pa.Column("object", nullable=True),  # datetime.date o None
        "nif": pa.Column(str, nullable=True),
    },
    strict=True,
    coerce=False,
)
