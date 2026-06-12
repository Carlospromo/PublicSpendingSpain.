"""Anclaje orgánico de los contratos PLACSP a la espina presupuestaria.

El núcleo del valor (CLAUDE.md §2, §3): cada contrato se atribuye a un órgano de
contratación identificado (idealmente) por DIR3; aquí se enlaza con el servicio
presupuestario vía el crosswalk servicio↔DIR3 de la Fase 1 y ``dim_organica``.
El cruce analítico final es adjudicaciones (comprometido) vs ejecución (ORN)
bajo la misma espina orgánica.

Como en ``nivel_organico``, cada decisión queda etiquetada con su tipo de
anclaje y la señal que lo determinó (auditable; nada se descarta):

- ``servicio``: el DIR3 del órgano (o un ancestro de su cadena en
  ``dim_organica``) está en el crosswalk DEL EJERCICIO del contrato → hereda
  (seccion_cod, servicio_cod). Señales: ``dir3_directo`` / ``dir3_ancestro``
  (un órgano inferior — p. ej. una junta de contratación — ancla subiendo por
  sus padres).
- ``organica_sin_servicio``: el DIR3 existe en ``dim_organica`` pero no debe
  resolver a un servicio AGE. Señales: ``entidad_instrumental`` (la unidad — o
  un eslabón de su cadena — pertenece a un ente con presupuesto PROPIO:
  ``tipo_entidad`` distinto de MN, p. ej. ADIF=EE, Renfe=SM, AEAT=AT, OOAA=OA,
  autoridades portuarias=AP; anclar su gasto al servicio del ministerio
  inflaría el comprometido frente a una ORN que nunca lo contendrá),
  ``sin_servicio_en_cadena`` (estructura ministerial sin mapeo) o
  ``ejercicio_sin_crosswalk`` (el crosswalk aún no cubre ese ejercicio: un
  contrato de 2019 NO se fuerza contra la estructura de 2026).
- ``fuera_perimetro``: el DIR3 no es AGE (CCAA, local "L0#", universidades
  "U0#", otros entes fuera de dim_organica). El dataset 643 incluye TODO el
  sector público con perfil en PLACSP; se etiqueta, no se fuerza.
- ``sin_anclar``: el órgano no trae DIR3 (solo NIF u otro esquema), el código
  está malformado, o no se publica órgano. Contabilizado, nunca descartado.

Vigencia temporal: la fecha de referencia es ``fecha_adjudicacion`` (momento del
compromiso jurídico) y, en su defecto, ``fecha_actualizacion``; las versiones
SCD2 de ``dim_organica`` se filtran por esa fecha y el crosswalk por su
ejercicio.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

# Tipos de anclaje (enum cerrado, columna anclaje_tipo).
ANCLA_SERVICIO = "servicio"
ANCLA_ORGANICA_SIN_SERVICIO = "organica_sin_servicio"
ANCLA_FUERA_PERIMETRO = "fuera_perimetro"
ANCLA_SIN_ANCLAR = "sin_anclar"

ANCLAJE_TIPOS = (
    ANCLA_SERVICIO,
    ANCLA_ORGANICA_SIN_SERVICIO,
    ANCLA_FUERA_PERIMETRO,
    ANCLA_SIN_ANCLAR,
)

# Señales del anclaje (para auditoría, como nivel_organico_senal).
SENAL_DIR3_DIRECTO = "dir3_directo"
SENAL_DIR3_ANCESTRO = "dir3_ancestro"
SENAL_DIR3_NO_AGE = "dir3_no_age"
SENAL_SIN_DIR3 = "sin_dir3"
SENAL_DIR3_MALFORMADO = "dir3_malformado"
SENAL_SIN_SERVICIO_EN_CADENA = "sin_servicio_en_cadena"
SENAL_EJERCICIO_SIN_CROSSWALK = "ejercicio_sin_crosswalk"
SENAL_ENTIDAD_INSTRUMENTAL = "entidad_instrumental"

# Tipo de entidad DIR3 cuyo gasto SÍ vive en los servicios presupuestarios AGE
# (estructura ministerial). Cualquier otro tipo informado = presupuesto propio.
_TIPO_ENTIDAD_AGE = "MN"

_DIR3_RE = re.compile(r"^[A-Z]{1,2}\d{7,8}$")

# Tope de saltos al subir por la cadena de padres (el árbol AGE real tiene
# ~6 niveles; el tope corta posibles ciclos del dato bruto).
_MAX_ASCENSO = 12

ANCLAJE_COLUMNS = [
    "seccion_cod",
    "servicio_cod",
    "anclaje_dir3_cod",
    "anclaje_tipo",
    "anclaje_senal",
]


def _vigente_en(unidad: pd.Series, fecha: date | None) -> bool:
    """¿La versión SCD2 de la unidad estaba vigente en ``fecha``?

    Sin fecha de contrato se admite la versión abierta (fecha_fin nula): mejor
    anclar contra la estructura actual que perder el contrato.
    """
    fin = unidad["fecha_fin"]
    if fecha is None:
        return bool(pd.isna(fin))
    inicio = unidad["fecha_inicio"]
    empieza = pd.isna(inicio) or pd.Timestamp(inicio).date() <= fecha
    sigue = pd.isna(fin) or fecha <= pd.Timestamp(fin).date()
    return bool(empieza and sigue)


class Anclador:
    """Índices precalculados de dim_organica + crosswalk para anclar por fila."""

    def __init__(self, dim_organica: pd.DataFrame, crosswalk: pd.DataFrame) -> None:
        # dim_organica indexada por dir3_cod (puede haber varias versiones SCD2).
        self._versiones: dict[str, list[pd.Series]] = {}
        for _, fila in dim_organica.iterrows():
            self._versiones.setdefault(fila["dir3_cod"], []).append(fila)

        # Crosswalk: (ejercicio, dir3) -> (seccion, servicio). Solo pares con
        # dir3 asignado. Si un dir3 mapea a varios servicios (la correspondencia
        # no es 1:1) se toma el menor (seccion, servicio): determinista.
        con_dir3 = crosswalk[crosswalk["dir3_cod"].notna()]
        self._servicio_por_dir3: dict[tuple[int, str], tuple[str, str]] = {}
        for _, fila in con_dir3.sort_values(["seccion_cod", "servicio_cod"]).iterrows():
            clave = (int(fila["ejercicio"]), str(fila["dir3_cod"]))
            self._servicio_por_dir3.setdefault(
                clave, (str(fila["seccion_cod"]), str(fila["servicio_cod"]))
            )
        self._ejercicios = {ej for ej, _ in self._servicio_por_dir3}

    def _version_vigente(self, dir3_cod: str, fecha: date | None) -> pd.Series | None:
        for version in self._versiones.get(dir3_cod, []):
            if _vigente_en(version, fecha):
                return version
        return None

    def anclar(
        self, dir3_cod: object, fecha: date | None, ejercicio: int | None = None
    ) -> dict[str, object]:
        """Columnas de anclaje (ANCLAJE_COLUMNS) para un órgano de contratación.

        ``fecha`` filtra las versiones SCD2 de dim_organica; ``ejercicio`` elige
        el crosswalk (por defecto, el año de ``fecha``).
        """

        def out(
            tipo: str,
            senal: str,
            ancla: str | None = None,
            seccion: str | None = None,
            servicio: str | None = None,
        ) -> dict[str, object]:
            return {
                "seccion_cod": seccion,
                "servicio_cod": servicio,
                "anclaje_dir3_cod": ancla,
                "anclaje_tipo": tipo,
                "anclaje_senal": senal,
            }

        if dir3_cod is None or (isinstance(dir3_cod, float) and pd.isna(dir3_cod)):
            return out(ANCLA_SIN_ANCLAR, SENAL_SIN_DIR3)
        codigo = str(dir3_cod).strip().upper()
        if not _DIR3_RE.match(codigo):
            return out(ANCLA_SIN_ANCLAR, SENAL_DIR3_MALFORMADO)

        # Ejercicio presupuestario del contrato; sin fecha ni ejercicio, el
        # último cubierto por el crosswalk (estructura más reciente disponible).
        if ejercicio is None:
            ejercicio = fecha.year if fecha is not None else max(self._ejercicios, default=0)
        cubierto = ejercicio in self._ejercicios

        # Ascenso por la cadena de padres dentro de dim_organica (AGE): el
        # primer eslabón con servicio en el crosswalk del ejercicio gana.
        # "en_organica" distingue AGE de fuera-de-perímetro aunque la versión
        # SCD2 no esté vigente en la fecha (unidad extinguida/anacrónica).
        actual: str | None = codigo
        saltos = 0
        en_organica = codigo in self._versiones
        entidad_propia = False
        while actual is not None and saltos < _MAX_ASCENSO:
            servicio = self._servicio_por_dir3.get((ejercicio, actual))
            if servicio is not None:
                # El crosswalk es autoritativo (incluye overrides manuales):
                # si mapea la unidad, ancla aunque sea cabecera de ente.
                return out(
                    ANCLA_SERVICIO,
                    SENAL_DIR3_DIRECTO if actual == codigo else SENAL_DIR3_ANCESTRO,
                    ancla=actual,
                    seccion=servicio[0],
                    servicio=servicio[1],
                )
            version = self._version_vigente(actual, fecha)
            if version is None:
                break
            # Frontera de perímetro: una unidad de un ente con presupuesto
            # propio (tipo_entidad informado y != MN) no asciende al servicio
            # del ministerio — su gasto no aparecerá en la ORN de ese servicio.
            tipo = version.get("tipo_entidad")
            if not pd.isna(tipo) and tipo != _TIPO_ENTIDAD_AGE:
                entidad_propia = True
                break
            padre = version.get("dir3_padre_cod")
            actual = None if pd.isna(padre) or padre == actual else str(padre)
            saltos += 1

        if entidad_propia:
            return out(ANCLA_ORGANICA_SIN_SERVICIO, SENAL_ENTIDAD_INSTRUMENTAL, ancla=codigo)
        if en_organica:
            senal = SENAL_SIN_SERVICIO_EN_CADENA if cubierto else SENAL_EJERCICIO_SIN_CROSSWALK
            return out(ANCLA_ORGANICA_SIN_SERVICIO, senal, ancla=codigo)
        return out(ANCLA_FUERA_PERIMETRO, SENAL_DIR3_NO_AGE, ancla=codigo)


def anclar_contratos(
    contratos: pd.DataFrame,
    dim_organica: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Añade a ``contratos`` las columnas de anclaje orgánico (ANCLAJE_COLUMNS).

    ``contratos``: canónico PLACSP (placsp_adjudicacion_schema).
    ``dim_organica``: seed SCD2 de DIR3 (Fase 1), con fechas parseadas.
    ``crosswalk``: servicio↔DIR3 (Fase 1, CROSSWALK_COLUMNS), SCD por ejercicio.

    No se fuerza ningún anclaje dudoso: lo no resoluble queda etiquetado
    (``fuera_perimetro``/``sin_anclar``) y contabilizado (``anclaje_stats``).
    """
    anclador = Anclador(dim_organica, crosswalk)
    fechas = contratos["fecha_adjudicacion"].where(
        contratos["fecha_adjudicacion"].notna(), contratos["fecha_actualizacion"]
    )
    # El ejercicio del crosswalk es el del periodo del hecho: así el
    # comprometido anclado compara contra la ORN del MISMO ejercicio.
    ejercicios = contratos["periodo"].str.slice(0, 4).astype(int)
    anclajes = [
        anclador.anclar(dir3, fecha if isinstance(fecha, date) else None, ejercicio)
        for dir3, fecha, ejercicio in zip(
            contratos["organo_dir3_cod"], fechas, ejercicios, strict=True
        )
    ]
    resultado = contratos.copy()
    for col in ANCLAJE_COLUMNS:
        resultado[col] = pd.Series([a[col] for a in anclajes], index=resultado.index)
    return resultado


def anclaje_stats(contratos: pd.DataFrame) -> dict[str, float]:
    """Cobertura del anclaje por expediente (auditoría y tests).

    "Sin anclar contabilizado es información honesta": estas métricas son el
    contador. Se mide por expediente (no por fila-lote) para no sobreponderar
    los expedientes multi-lote.
    """
    por_exp = contratos.groupby("expediente_id")["anclaje_tipo"].first()
    total = len(por_exp)
    conteo = por_exp.value_counts()
    return {
        "expedientes_total": float(total),
        **{f"{tipo}_pct": float(conteo.get(tipo, 0)) / total * 100 for tipo in ANCLAJE_TIPOS},
    }
