"""Esquemas pandera de validación de entrada (raw → DataFrame canónico).

Un esquema por fuente. Validan el contrato del parser, no la coherencia
contable (eso vive en ``quality/checks.py``).
"""

from __future__ import annotations

import pandera.pandas as pa

# ---------------------------------------------------------------------------
# IGAE — Anexo I mensual (detalle por aplicación presupuestaria)
#
# COBERTURA DE MAGNITUDES: el Anexo I cubre crédito inicial, crédito definitivo
# y ORN. NO trae comprometido ni pagos (llegarán de Cuadros/Anexo II en un
# prompt posterior): por eso esas columnas NO existen aquí, en lugar de
# rellenarse con ceros/nulos silenciosos. La Fase 3 no debe validar
# "pagos ≤ ORN" sobre esta fuente.
#
# Las magnitudes son nullable: el texto "-" del fichero (sin dato) se mapea a
# nulo, que es distinto de 0.
# ---------------------------------------------------------------------------

igae_anexo_i_schema = pa.DataFrameSchema(
    {
        "periodo": pa.Column(str, pa.Check.str_matches(r"^\d{4}-\d{2}$")),
        "fuente": pa.Column(str, pa.Check.equal_to("igae_anexo_i")),
        "fecha_captura": pa.Column("object"),  # datetime.date
        "seccion_cod": pa.Column(str, pa.Check.str_matches(r"^\d{2}$")),
        "servicio_cod": pa.Column(str, pa.Check.str_matches(r"^\d{2}$")),
        "servicio_denominacion": pa.Column(str, nullable=True),
        # Grupo de programa (4 car.); el 5º opcional es la territorialización
        # de Defensa (p. ej. 121M2). Charset incluye Ñ (programa 46ÑF).
        "programa_cod": pa.Column(str, pa.Check.str_matches(r"^[0-9A-ZÑ]{4,5}$")),
        # Desglose territorial: 2 dígitos cuando existe, nulo cuando no.
        # 'DT' = Diversos Territorios (visto en el histórico, p. ej. 2016-11).
        "provincia_cod": pa.Column(str, pa.Check.str_matches(r"^\d{2}$|^DT$"), nullable=True),
        # Económica al nivel que trae el fichero: concepto (3), subconcepto (5)
        # o partida (7 dígitos).
        "economica_cod": pa.Column(str, pa.Check.str_matches(r"^\d{3}$|^\d{5}$|^\d{7}$")),
        "aplicacion_denominacion": pa.Column(str),
        "credito_inicial": pa.Column(float, nullable=True),
        "credito_definitivo": pa.Column(float, nullable=True),
        "orn": pa.Column(float, nullable=True),
    },
    strict=True,
    coerce=False,
)

# Estados oficiales de una unidad DIR3 (hoja "Catálogos de clasificación" del
# fichero oficial): Vigente, Extinguido, Anulado, Transitorio.
DIR3_ESTADOS = ("V", "E", "A", "T")

# Códigos DIR3: letra(s) + dígitos, p. ej. "E04921901", "EA0008567".
_DIR3_COD_REGEX = r"^[A-Z]{1,2}\d{7,8}$"

dim_seccion_servicio_schema = pa.DataFrameSchema(
    {
        "ejercicio": pa.Column("int64", pa.Check.ge(2000)),
        # Etiqueta oficial del presupuesto de origen ("2025-P" = prórroga del
        # PGE 2025; en prórroga no coincide con el ejercicio que rige).
        "presupuesto": pa.Column(str),
        "seccion_cod": pa.Column(str, pa.Check.str_matches(r"^\d{2}$")),
        "seccion_denominacion": pa.Column(str),
        "servicio_cod": pa.Column(str, pa.Check.str_matches(r"^\d{2}$")),
        "servicio_denominacion": pa.Column(str),
    },
    strict=True,
    coerce=False,
    # Un servicio es único dentro de su sección y ejercicio.
    unique=["ejercicio", "seccion_cod", "servicio_cod"],
)

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
