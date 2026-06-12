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

# Códigos DIR3: letra(s) + dígitos, p. ej. "E04921901", "EA0008567".
_DIR3_COD_REGEX = r"^[A-Z]{1,2}\d{7,8}$"

# ---------------------------------------------------------------------------
# PLACSP — adjudicaciones (sindicación 643, CODICE 2.x)
#
# GRANO: una fila por (expediente, lote adjudicado); los expedientes sin
# adjudicación emiten una fila cabecera con resultado/importe nulos (ver
# docs/placsp_estructura.md §4). `es_cabecera_expediente` marca exactamente una
# fila por expediente: las magnitudes de licitación (presupuesto_*) solo van en
# ella, para que sumen sin doble conteo. El importe_adjudicacion es aditivo en
# todas las filas.
#
# El dato bruto es ruidoso (CLAUDE.md §9: la robustez está en la normalización
# y el anclaje, no en el campo bruto): el órgano puede identificarse por DIR3 o
# solo por NIF (organo_dir3_cod nulo), los códigos de estado/resultado son de
# listas oficiales que evolucionan (no se cierran aquí a un enum), y TODA
# ausencia es nulo explícito, nunca cero.
# ---------------------------------------------------------------------------

placsp_adjudicacion_schema = pa.DataFrameSchema(
    {
        "periodo": pa.Column(str, pa.Check.str_matches(r"^\d{4}-\d{2}$")),
        "fuente": pa.Column(str, pa.Check.equal_to("placsp")),
        "fecha_captura": pa.Column("object"),  # datetime.date
        # Id numérico de plataforma: la clave estable de la licitación
        # (VERIFICADO; el expediente_id se repite entre órganos distintos).
        "licitacion_id": pa.Column(str),
        "expediente_id": pa.Column(str, nullable=True),
        "entry_id": pa.Column(str),
        "es_cabecera_expediente": pa.Column(bool),
        "lote_id": pa.Column(str),
        "organo_id": pa.Column(str, nullable=True),
        "organo_id_esquema": pa.Column(str, nullable=True),  # DIR3 | NIF | otros
        "organo_dir3_cod": pa.Column(str, pa.Check.str_matches(_DIR3_COD_REGEX), nullable=True),
        "organo_denominacion": pa.Column(str, nullable=True),
        "organo_tipo_cod": pa.Column(str, nullable=True),
        "tipo_contrato_cod": pa.Column(str, nullable=True),
        "subtipo_contrato_cod": pa.Column(str, nullable=True),
        "procedimiento_cod": pa.Column(str, nullable=True),
        "cpv_cod": pa.Column(str, nullable=True),
        "estado_cod": pa.Column(str, nullable=True),  # PUB|EV|ADJ|RES|ANUL|PRE|BAJA…
        "resultado_cod": pa.Column(str, nullable=True),  # 8/9=adjudicado, 3=desierto…
        "presupuesto_sin_iva": pa.Column(float, nullable=True),
        "presupuesto_con_iva": pa.Column(float, nullable=True),
        "valor_estimado": pa.Column(float, nullable=True),
        "importe_adjudicacion": pa.Column(float, nullable=True),
        "num_ofertas": pa.Column(str, nullable=True),
        "adjudicatario_id": pa.Column(str, nullable=True),
        "adjudicatario_id_esquema": pa.Column(str, nullable=True),
        "adjudicatario_nombre": pa.Column(str, nullable=True),
        "adjudicatario_es_pyme": pa.Column("object", nullable=True),  # bool o None
        "fecha_adjudicacion": pa.Column("object", nullable=True),  # datetime.date
        "fecha_formalizacion": pa.Column("object", nullable=True),
        "fecha_actualizacion": pa.Column("object", nullable=True),
    },
    strict=True,
    coerce=False,
    # Clave natural del hecho: la foto vigente de cada lote de la licitación.
    unique=["licitacion_id", "lote_id"],
)

# Estados oficiales de una unidad DIR3 (hoja "Catálogos de clasificación" del
# fichero oficial): Vigente, Extinguido, Anulado, Transitorio.
DIR3_ESTADOS = ("V", "E", "A", "T")

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
