"""Métricas analíticas sobre el warehouse (Fase 5).

Funciones/consultas PURAS sobre las vistas del warehouse (CLAUDE.md §5, §6): sin
acoplamiento a scheduler ni a la API. La Fase 6 (API) y la Fase 7 (Dagster) se
limitarán a INVOCAR estas funciones; aquí no hay efectos colaterales más allá de
registrar vistas temporales de apoyo en la conexión que se recibe.

Cada métrica devuelve un ``MetricResult`` autoexplicativo (CLAUDE.md §9, pensando
en el frontal): el DataFrame del dato más metadatos de **nivel de agregación**,
**magnitudes y fuentes** usadas, **naturaleza** (exacta / aproximada /
indiciaria), **advertencias metodológicas**, **frescura** (última actualización y
periodo cubierto) y, cuando aplica, la **cobertura/fiabilidad de anclaje**
heredada de la Fase 4 (docs/cobertura_fuentes.md).

Principio de honestidad (CLAUDE.md §3): nunca se cruzan magnitudes no comparables
sin marcarlo como aproximación. El dato IGAE es ACUMULADO del ejercicio: se
compara entre periodos, jamás se suma. Las tres velocidades viven a distinta
profundidad de anclaje (servicio en IGAE/PLACSP/BDNS, sección en BOE/CdM), por lo
que un cruce solo es legítimo al nivel común y etiquetado como indiciario.

Las alertas (umbrales, anomalías) NO viven aquí: son la Fase 5/Prompt 13.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import gasto_estado.db as _db

SEEDS_DIR = Path(_db.__file__).parent / "seeds"

# --- Naturaleza de una métrica (marca inseparable, CLAUDE.md §3) -------------
EXACTA = "exacta"  # aritmética sobre magnitudes auditables comparables
APROXIMADA = "aproximada"  # importe de extracción falible (BOE/CdM) o anclaje parcial
INDICIARIA = "indiciaria"  # cruce de velocidades: NO es identidad contable

_PERIODO_RE = re.compile(r"^\d{4}-\d{2}$")


def _validar_periodo(periodo: str) -> str:
    if not _PERIODO_RE.match(periodo):
        raise ValueError(f"periodo debe ser 'YYYY-MM'; recibido {periodo!r}.")
    return periodo


@dataclass(frozen=True)
class MetricResult:
    """Resultado autoexplicativo de una métrica (contrato de salida, Fase 6).

    ``data`` es el DataFrame; el resto son metadatos para que la API/el frontal
    presenten la cifra con su contexto sin re-derivarlo.
    """

    metrica: str
    data: pd.DataFrame
    nivel: str
    naturaleza: str
    magnitudes: list[str]
    fuentes: list[str]
    frescura: dict[str, Any]
    advertencias: list[str] = field(default_factory=list)
    cobertura_anclaje: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialización JSON-friendly (la API la expondrá tal cual)."""
        d = asdict(self)
        d["data"] = self.data.to_dict(orient="records")
        return d


# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------

# Niveles de agregación de ejecución → (columnas-CÓDIGO, columnas-ETIQUETA).
# Se AGRUPA por código (clave estable); la etiqueta/denominación se agrega con
# max() para no PARTIR un código cuyo nombre no sea constante (p. ej. servicios
# derivados del Anexo I traen seccion_denominacion NULL). 'dg' es especial
# (requiere el crosswalk servicio↔DIR3) y se trata aparte.
_NIVEL_EJECUCION: dict[str, tuple[list[str], list[str]]] = {
    "AGE": ([], []),
    "seccion": (["seccion_cod"], ["seccion_denominacion"]),
    "servicio": (
        ["seccion_cod", "servicio_cod"],
        ["seccion_denominacion", "servicio_denominacion"],
    ),
    "programa": (["programa_cod"], []),
    "economica": (["economica_cod"], []),
    "capitulo": (["capitulo_cod"], []),
}
NIVELES_EJECUCION = (*_NIVEL_EJECUCION.keys(), "dg")

# Columnas-código de cada nivel (claves de emparejamiento interanual y orden).
_CODIGOS_DG = ["seccion_cod", "dg_dir3_cod"]


def _codigos_nivel(nivel: str) -> list[str]:
    return _CODIGOS_DG if nivel == "dg" else _NIVEL_EJECUCION[nivel][0]


# Prioridad del nivel orgánico al deduplicar el crosswalk a UN dir3 por servicio:
# la unidad operativa más específica gana (el servicio 01 "Subsecretaría y
# Servicios Generales" mapea a Ministerio+Subsecretaría → se queda Subsecretaría).
_PRIORIDAD_NIVEL_DG = (
    "DIRECCION_GENERAL",
    "SECRETARIA_ESTADO",
    "SUBSECRETARIA",
    "ORGANISMO",
    "MINISTERIO",
)
_DG_RESIDUAL = "(sin unidad DIR3 asignada)"


def _ensure_dg_crosswalk(con: duckdb.DuckDBPyConnection) -> None:
    """Registra la vista temporal ``_cw_dg``: un DIR3 por (ejercicio,sección,servicio).

    El crosswalk seed (Fase 1) NO es 1:1 — el servicio 01 mapea a Ministerio y
    Subsecretaría a la vez. Sin deduplicar, el join a ejecución doble-contaría
    (~+3% de ORN). Se elige un único DIR3 por prioridad de nivel orgánico, de
    modo que la agregación a DG CONSERVE los totales de su sección padre.
    """
    crosswalk = pd.read_csv(
        SEEDS_DIR / "crosswalk_servicio_dir3.csv",
        dtype={"seccion_cod": str, "servicio_cod": str},
    )
    crosswalk = crosswalk[crosswalk["dir3_cod"].notna()][
        ["ejercicio", "seccion_cod", "servicio_cod", "dir3_cod"]
    ]
    con.register("_cw_raw", crosswalk)
    casos = " ".join(f"WHEN '{n}' THEN {i}" for i, n in enumerate(_PRIORIDAD_NIVEL_DG))
    # TEMP TABLE (materializada): evalúa el SELECT ya, para poder soltar _cw_raw
    # después sin romper una vista diferida. Funciona en conexión read-only.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _cw_dg AS
        WITH ranked AS (
            SELECT c.ejercicio, c.seccion_cod, c.servicio_cod, c.dir3_cod,
                   o.denominacion AS dg_denominacion,
                   coalesce(o.nivel_organico, 'OTRO') AS dg_nivel_organico,
                   row_number() OVER (
                       PARTITION BY c.ejercicio, c.seccion_cod, c.servicio_cod
                       ORDER BY CASE coalesce(o.nivel_organico, 'OTRO') {casos}
                                ELSE 99 END, c.dir3_cod
                   ) AS rn
            FROM _cw_raw c
            LEFT JOIN dim_organica o ON o.dir3_cod = c.dir3_cod
        )
        SELECT ejercicio, seccion_cod, servicio_cod, dir3_cod,
               dg_denominacion, dg_nivel_organico
        FROM ranked WHERE rn = 1
        """
    )
    con.unregister("_cw_raw")


def _frescura(con: duckdb.DuckDBPyConnection, tabla: str, fuentes: list[str]) -> dict[str, Any]:
    """Metadatos de frescura de un hecho: última captura y periodo cubierto."""
    row = con.execute(
        f"SELECT max(fecha_captura), min(periodo), max(periodo) FROM {tabla}"  # noqa: S608
    ).fetchone()
    ultima, pmin, pmax = row if row else (None, None, None)
    return {
        "fuentes": fuentes,
        "ultima_actualizacion": None if ultima is None else ultima.isoformat(),
        "periodo_cubierto": None if pmin is None else [pmin, pmax],
    }


def _es_prorroga(presupuesto: object) -> bool:
    return isinstance(presupuesto, str) and presupuesto.strip().upper().endswith("-P")


# ---------------------------------------------------------------------------
# PASO 1 — Ejecución presupuestaria (velocidad contable, IGAE)
# ---------------------------------------------------------------------------


def _ejecucion_agregada(
    con: duckdb.DuckDBPyConnection, periodos: list[str], nivel: str
) -> pd.DataFrame:
    """Suma de magnitudes IGAE (inicial/definitivo/ORN) por nivel y periodo.

    Base = ``v_ejecucion``. Para ``nivel='dg'`` se enlaza el crosswalk
    deduplicado y los servicios sin DIR3 caen en un bucket residual nombrado
    (no se descartan: así la suma a DG cuadra con la sección padre).
    """
    if nivel not in NIVELES_EJECUCION:
        raise ValueError(f"nivel desconocido {nivel!r}; usa uno de {NIVELES_EJECUCION}.")
    lista = ", ".join(f"'{_validar_periodo(p)}'" for p in periodos)
    magnitudes = (
        "sum(credito_inicial) AS credito_inicial, "
        "sum(credito_definitivo) AS credito_definitivo, "
        "sum(orn) AS orn"
    )
    if nivel == "dg":
        _ensure_dg_crosswalk(con)
        # Se agrupa por (sección, dir3): cada DG pertenece a una sección y el
        # residual es per-sección, de modo que las DG de una sección suman su
        # total (cuadre con la sección padre, verificable). Etiquetas con max().
        sql = f"""
            SELECT f.seccion_cod, cw.dir3_cod AS dg_dir3_cod,
                   max(f.seccion_denominacion) AS seccion_denominacion,
                   max(coalesce(cw.dg_denominacion, '{_DG_RESIDUAL}')) AS dg_denominacion,
                   max(coalesce(cw.dg_nivel_organico, 'residual')) AS dg_nivel_organico,
                   f.periodo, {magnitudes}
            FROM v_ejecucion f
            LEFT JOIN _cw_dg cw
              ON cw.ejercicio = f.ejercicio
             AND cw.seccion_cod = f.seccion_cod
             AND cw.servicio_cod = f.servicio_cod
            WHERE f.periodo IN ({lista})
            GROUP BY f.seccion_cod, cw.dir3_cod, f.periodo
        """
    else:
        codigos, etiquetas = _NIVEL_EJECUCION[nivel]
        sel_cod = (", ".join(codigos) + ", ") if codigos else ""
        sel_lab = "".join(f"max({e}) AS {e}, " for e in etiquetas)
        group = ", ".join([*codigos, "periodo"]) if codigos else "periodo"
        sql = f"""
            SELECT {sel_cod}{sel_lab}periodo, {magnitudes}
            FROM v_ejecucion
            WHERE periodo IN ({lista})
            GROUP BY {group}
        """
    return con.execute(sql).df()


def _advertencias_ejecucion(
    con: duckdb.DuckDBPyConnection, periodos: list[str], nivel: str
) -> list[str]:
    avisos = [
        "El dato IGAE es ACUMULADO del ejercicio a la fecha del periodo: "
        "compárese entre periodos, nunca se sume.",
    ]
    etiquetas = con.execute(
        "SELECT DISTINCT presupuesto FROM dim_periodo WHERE periodo IN ({})".format(
            ", ".join(f"'{_validar_periodo(p)}'" for p in periodos)
        )
    ).fetchall()
    if any(_es_prorroga(e[0]) for e in etiquetas):
        avisos.append(
            "Periodo en PRÓRROGA presupuestaria: el crédito inicial es el operativo "
            "(prorrogado), no el inicial legal de un PGE propio del ejercicio."
        )
    if nivel == "dg":
        avisos.append(
            "Nivel DG: solo los servicios con correspondencia DIR3 se atribuyen a una "
            "unidad nombrada; el resto (Deuda, Clases Pasivas, transferencias a entes/SS) "
            "queda en el bucket residual. La suma a DG cuadra con la sección padre."
        )
    return avisos


def _cobertura_dg(con: duckdb.DuckDBPyConnection, periodo: str) -> dict[str, Any]:
    """Qué fracción de la ORN del periodo se atribuye a una unidad DIR3 nombrada."""
    df = _ejecucion_agregada(con, [periodo], "dg")
    total = float(df["orn"].sum())
    nombrada = float(df.loc[df["dg_dir3_cod"].notna(), "orn"].sum())
    return {
        "magnitud": "orn",
        "atribuida_a_unidad_dir3": round(nombrada, 2),
        "residual_sin_dir3": round(total - nombrada, 2),
        "pct_atribuida": None if total == 0 else round(100 * nombrada / total, 1),
        "nota": "Residual = capítulos sin DG ministerial (deuda, pensiones, transferencias).",
    }


def grado_ejecucion(
    con: duckdb.DuckDBPyConnection, periodo: str, *, nivel: str = "AGE"
) -> MetricResult:
    """Grado de ejecución = ORN / crédito definitivo, a cualquier nivel.

    Métrica reina (CLAUDE.md §3). ``nivel`` ∈ {AGE, seccion, servicio, programa,
    economica, capitulo, dg}. El crédito definitivo es la base; la ORN, la
    obligación reconocida acumulada a esa fecha. Exacta.
    """
    periodo = _validar_periodo(periodo)
    df = _ejecucion_agregada(con, [periodo], nivel)
    df["modificaciones"] = df["credito_definitivo"] - df["credito_inicial"]
    df["pct_ejecucion"] = (df["orn"] / df["credito_definitivo"].replace(0, pd.NA)) * 100
    df = df.drop(columns="periodo").sort_values("orn", ascending=False, ignore_index=True)
    return MetricResult(
        metrica="grado_ejecucion",
        data=df,
        nivel=nivel,
        naturaleza=EXACTA,
        magnitudes=["credito_definitivo", "orn", "credito_inicial"],
        fuentes=["igae_anexo_i"],
        frescura=_frescura(con, "fact_ejecucion", ["igae_anexo_i"]),
        advertencias=_advertencias_ejecucion(con, [periodo], nivel),
        cobertura_anclaje=_cobertura_dg(con, periodo) if nivel == "dg" else None,
    )


def ritmo_ejecucion(
    con: duckdb.DuckDBPyConnection, ejercicio: int, *, nivel: str = "AGE"
) -> MetricResult:
    """Serie intra-anual del grado de ejecución (mes a mes de un mismo ejercicio).

    Compara periodos, NUNCA los suma (el acumulado ya incorpora los meses
    previos). El resultado es monótono no decreciente en ORN dentro del ejercicio
    (coherente con la regla R8 de la Fase 3).
    """
    periodos = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT periodo FROM fact_ejecucion WHERE ejercicio = ? "
            "AND fuente_cod = 'igae_anexo_i' ORDER BY periodo",
            [ejercicio],
        ).fetchall()
    ]
    if not periodos:
        df = pd.DataFrame()
    else:
        df = _ejecucion_agregada(con, periodos, nivel)
        df["pct_ejecucion"] = (df["orn"] / df["credito_definitivo"].replace(0, pd.NA)) * 100
        df = df.sort_values([*_codigos_nivel(nivel), "periodo"], ignore_index=True)
    return MetricResult(
        metrica="ritmo_ejecucion",
        data=df,
        nivel=nivel,
        naturaleza=EXACTA,
        magnitudes=["credito_definitivo", "orn"],
        fuentes=["igae_anexo_i"],
        frescura=_frescura(con, "fact_ejecucion", ["igae_anexo_i"]),
        advertencias=[
            f"Serie intra-anual del ejercicio {ejercicio}: cada periodo es el ACUMULADO "
            "a esa fecha. Se comparan los grados de ejecución, no se suman.",
        ],
    )


def comparativa_interanual(
    con: duckdb.DuckDBPyConnection, periodo: str, *, nivel: str = "AGE"
) -> MetricResult:
    """Grado de ejecución de un mes frente al MISMO mes del ejercicio anterior.

    La comparación honesta dada la estacionalidad del gasto público (abril vs
    abril, no abril vs diciembre). Empareja por las dimensiones del nivel. Si el
    mismo mes del año anterior no está cargado, las columnas previas quedan nulas
    con advertencia. La prórroga se señala (no es comparable como un PGE propio).
    """
    periodo = _validar_periodo(periodo)
    anio, mes = int(periodo[:4]), periodo[5:7]
    periodo_prev = f"{anio - 1}-{mes}"
    cargado_prev = bool(
        con.execute(
            "SELECT 1 FROM fact_ejecucion WHERE periodo = ? LIMIT 1", [periodo_prev]
        ).fetchone()
    )

    actual = _ejecucion_agregada(con, [periodo], nivel).drop(columns="periodo")
    actual["pct_ejecucion"] = (actual["orn"] / actual["credito_definitivo"].replace(0, pd.NA)) * 100
    claves = _codigos_nivel(nivel)
    avisos: list[str] = []
    if cargado_prev:
        prev = _ejecucion_agregada(con, [periodo_prev], nivel).drop(columns="periodo")
        prev["pct_ejecucion"] = (prev["orn"] / prev["credito_definitivo"].replace(0, pd.NA)) * 100
        if claves:
            df = actual.merge(prev, on=claves, how="outer", suffixes=("", "_prev"))
        else:  # nivel AGE: una fila por lado, sin clave → emparejado posicional.
            df = actual.merge(prev, how="cross", suffixes=("", "_prev"))
        df["delta_pct_ejecucion"] = df["pct_ejecucion"] - df["pct_ejecucion_prev"]
    else:
        df = actual
        avisos.append(
            f"El mismo mes del ejercicio anterior ({periodo_prev}) no está cargado: "
            "sin comparación interanual disponible."
        )
    etiquetas = dict(
        con.execute(
            "SELECT periodo, presupuesto FROM dim_periodo WHERE periodo IN (?, ?)",
            [periodo, periodo_prev],
        ).fetchall()
    )
    if _es_prorroga(etiquetas.get(periodo)) != _es_prorroga(etiquetas.get(periodo_prev)):
        avisos.append(
            f"ADVERTENCIA: uno de los ejercicios está en prórroga ({periodo}="
            f"{etiquetas.get(periodo)}, {periodo_prev}={etiquetas.get(periodo_prev)}). "
            "El crédito (inicial/definitivo) de un ejercicio prorrogado no es homogéneo "
            "con uno de PGE propio; el grado de ejecución comparado es solo orientativo."
        )
    return MetricResult(
        metrica="comparativa_interanual",
        data=df,
        nivel=nivel,
        naturaleza=EXACTA,
        magnitudes=["credito_definitivo", "orn", "pct_ejecucion"],
        fuentes=["igae_anexo_i"],
        frescura=_frescura(con, "fact_ejecucion", ["igae_anexo_i"]),
        advertencias=[
            f"Comparación mismo-mes: {periodo} frente a {periodo_prev}.",
            *avisos,
        ],
    )


def modificaciones_credito(
    con: duckdb.DuckDBPyConnection, periodo: str, *, nivel: str = "seccion"
) -> MetricResult:
    """Modificaciones de crédito DERIVADAS (definitivo − inicial), abs. y % s/inicial.

    El Anexo I no publica una columna de modificaciones explícita (Fase 3): se
    deriva. En valor absoluto y como porcentaje sobre el crédito inicial, por
    nivel orgánico. Las modificaciones netas pueden ser negativas.
    """
    periodo = _validar_periodo(periodo)
    df = _ejecucion_agregada(con, [periodo], nivel).drop(columns="periodo")
    df["modificaciones"] = df["credito_definitivo"] - df["credito_inicial"]
    df["modificaciones_pct"] = (
        df["modificaciones"] / df["credito_inicial"].replace(0, pd.NA)
    ) * 100
    df = df.sort_values("modificaciones", ascending=False, ignore_index=True)
    return MetricResult(
        metrica="modificaciones_credito",
        data=df,
        nivel=nivel,
        naturaleza=EXACTA,
        magnitudes=["credito_inicial", "credito_definitivo", "modificaciones (derivada)"],
        fuentes=["igae_anexo_i"],
        frescura=_frescura(con, "fact_ejecucion", ["igae_anexo_i"]),
        advertencias=[
            "Modificaciones DERIVADAS (crédito definitivo − inicial): el Anexo I no "
            "publica el desglose explícito de modificaciones. El neto puede ser negativo.",
            *_advertencias_ejecucion(con, [periodo], nivel)[1:],
        ],
    )


# ---------------------------------------------------------------------------
# PASO 2 — Compromisos jurídicos (PLACSP + BDNS)
# ---------------------------------------------------------------------------

# Niveles de las velocidades ya ancladas por DIR3 (el hecho trae el anclaje).
_NIVEL_COMPROMISO: dict[str, list[str]] = {
    "AGE": [],
    "seccion": ["seccion_cod"],
    "servicio": ["seccion_cod", "servicio_cod"],
    "dg": ["anclaje_dir3_cod"],
}


def _ventana_sql(
    periodo: str | None, ejercicio: int | None, alias: str = ""
) -> tuple[str, list[Any]]:
    """Filtro temporal por periodo exacto o por ejercicio completo."""
    col = f"{alias}." if alias else ""
    if periodo is not None:
        return f"{col}periodo = ?", [_validar_periodo(periodo)]
    if ejercicio is not None:
        return f"{col}ejercicio = ?", [ejercicio]
    return "1=1", []


def _cobertura_anclaje(
    con: duckdb.DuckDBPyConnection, tabla: str, magnitud: str, where: str, params: list[Any]
) -> dict[str, Any]:
    """Reparto del importe por tipo de anclaje (qué fracción es atribuible)."""
    rows = con.execute(
        f"SELECT anclaje_tipo, count(*) n, sum({magnitud}) imp "  # noqa: S608
        f"FROM {tabla} WHERE {where} GROUP BY anclaje_tipo",
        params,
    ).fetchall()
    por_tipo = {r[0]: {"n": r[1], "importe": float(r[2] or 0)} for r in rows}
    total = sum(v["importe"] for v in por_tipo.values())
    anclado = por_tipo.get("servicio", {}).get("importe", 0.0)
    return {
        "magnitud": magnitud,
        "por_tipo": por_tipo,
        "importe_total": round(total, 2),
        "pct_anclado_a_servicio": None if total == 0 else round(100 * anclado / total, 1),
        "nota": "Solo el anclaje 'servicio' atribuye a (sección, servicio); el resto "
        "(organica_sin_servicio, fuera_perimetro, sin_anclar) se cuenta pero no se imputa.",
    }


def _volumen_compromiso(
    con: duckdb.DuckDBPyConnection,
    *,
    metrica: str,
    tabla: str,
    fuente: str,
    magnitud: str,
    nivel: str,
    periodo: str | None,
    ejercicio: int | None,
) -> MetricResult:
    if nivel not in _NIVEL_COMPROMISO:
        raise ValueError(f"nivel {nivel!r} no soportado; usa {tuple(_NIVEL_COMPROMISO)}.")
    grano = "lote adjudicado" if fuente == "placsp" else "concesión"
    where, params = _ventana_sql(periodo, ejercicio)
    cols = _NIVEL_COMPROMISO[nivel]
    # A nivel sección/servicio/DG solo cuentan las filas ancladas a servicio
    # (las únicas con seccion/servicio informados); a AGE entra todo el importe.
    filtro = where
    if cols:
        filtro = f"({where}) AND anclaje_tipo = 'servicio'"
        if nivel == "dg":
            filtro = f"({where}) AND anclaje_dir3_cod IS NOT NULL"
    select_cols = (", ".join(cols) + ", ") if cols else ""
    group = ("GROUP BY " + ", ".join(cols)) if cols else ""
    df = con.execute(
        f"SELECT {select_cols}count(*) n, sum({magnitud}) importe "  # noqa: S608
        f"FROM {tabla} WHERE {filtro} {group}",
        params,
    ).df()
    if cols:
        df = df.sort_values("importe", ascending=False, ignore_index=True)
    return MetricResult(
        metrica=metrica,
        data=df,
        nivel=nivel,
        naturaleza=EXACTA,
        magnitudes=[magnitud],
        fuentes=[fuente],
        frescura=_frescura(con, tabla, [fuente]),
        advertencias=[
            f"Flujo acumulable por ventana temporal (grano = {grano}); no "
            "doble-cuenta (el importe es aditivo por fila).",
        ],
        cobertura_anclaje=_cobertura_anclaje(con, tabla, magnitud, where, params),
    )


def volumen_adjudicacion(
    con: duckdb.DuckDBPyConnection,
    *,
    periodo: str | None = None,
    ejercicio: int | None = None,
    nivel: str = "seccion",
) -> MetricResult:
    """Importe adjudicado (PLACSP) por nivel y ventana temporal.

    Grano = lote (``importe_adjudicacion`` es aditivo por fila, sin doble conteo;
    las magnitudes de licitación viven solo en la cabecera). Expone la cobertura
    de anclaje: qué fracción del importe se atribuye a un servicio.
    """
    return _volumen_compromiso(
        con,
        metrica="volumen_adjudicacion",
        tabla="fact_contratos",
        fuente="placsp",
        magnitud="importe_adjudicacion",
        nivel=nivel,
        periodo=periodo,
        ejercicio=ejercicio,
    )


def volumen_concesion(
    con: duckdb.DuckDBPyConnection,
    *,
    periodo: str | None = None,
    ejercicio: int | None = None,
    nivel: str = "seccion",
) -> MetricResult:
    """Importe concedido (BDNS) por nivel y ventana temporal (grano = concesión)."""
    return _volumen_compromiso(
        con,
        metrica="volumen_concesion",
        tabla="fact_subvenciones",
        fuente="bdns",
        magnitud="importe",
        nivel=nivel,
        periodo=periodo,
        ejercicio=ejercicio,
    )


def concentracion_adjudicatarios(
    con: duckdb.DuckDBPyConnection,
    *,
    nivel: str = "servicio",
    periodo: str | None = None,
    ejercicio: int | None = None,
    top_n: int = 5,
) -> MetricResult:
    """Concentración de adjudicatarios por órgano: cuota del top-N e índice HHI.

    HHI = Σ(cuota_i)² en puntos (0–10.000; >2.500 = muy concentrado). Solo
    alimenta el cálculo; el umbral/alerta es la Fase 5/Prompt 13. Se restringe a
    contratos anclados a un servicio con adjudicatario e importe identificados.
    """
    if nivel not in ("servicio", "seccion", "dg"):
        raise ValueError(f"nivel {nivel!r} no soportado para concentración.")
    organo = {
        "servicio": ["seccion_cod", "servicio_cod"],
        "seccion": ["seccion_cod"],
        "dg": ["anclaje_dir3_cod"],
    }[nivel]
    where, params = _ventana_sql(periodo, ejercicio)
    org = ", ".join(organo)
    df = con.execute(
        f"""
        WITH base AS (
            SELECT {org}, adjudicatario_id, sum(importe_adjudicacion) imp
            FROM fact_contratos
            WHERE ({where}) AND anclaje_tipo = 'servicio'
              AND adjudicatario_id IS NOT NULL AND importe_adjudicacion > 0
            GROUP BY {org}, adjudicatario_id
        ),
        tot AS (SELECT {org}, sum(imp) total, count(*) n_adj FROM base GROUP BY {org}),
        rk AS (
            SELECT b.*, t.total, t.n_adj,
                   row_number() OVER (PARTITION BY {", ".join(f"b.{c}" for c in organo)}
                                      ORDER BY b.imp DESC) rnk,
                   (b.imp / t.total) cuota
            FROM base b JOIN tot t USING ({org})
        )
        SELECT {org}, any_value(n_adj) n_adjudicatarios,
               round(100 * sum(CASE WHEN rnk <= {int(top_n)} THEN cuota ELSE 0 END), 1)
                   AS top_n_cuota_pct,
               round(10000 * sum(cuota * cuota), 0) AS hhi,
               round(any_value(total), 2) AS importe_total
        FROM rk GROUP BY {org}
        ORDER BY hhi DESC
        """,
        params,
    ).df()
    return MetricResult(
        metrica="concentracion_adjudicatarios",
        data=df,
        nivel=nivel,
        naturaleza=EXACTA,
        magnitudes=["importe_adjudicacion"],
        fuentes=["placsp"],
        frescura=_frescura(con, "fact_contratos", ["placsp"]),
        advertencias=[
            f"top_n = {top_n}. HHI en puntos (0–10.000). Solo contratos anclados a "
            "servicio con adjudicatario identificado; un órgano con poca contratación "
            "anclada arroja un HHI alto por construcción (pocos adjudicatarios), no "
            "necesariamente por captura.",
        ],
        cobertura_anclaje=_cobertura_anclaje(
            con, "fact_contratos", "importe_adjudicacion", where, params
        ),
    )


# ---------------------------------------------------------------------------
# PASO 3 — Decisiones políticas (BOE + CdM)
# ---------------------------------------------------------------------------

_DECISIONES = {
    "boe": ("fact_boe_disposiciones", "boe_sumario", "tipo_disposicion", "departamento"),
    "cdm": ("fact_acuerdos_cdm", "consejo_ministros", "tipo_acuerdo", "ministerio"),
}


def volumen_decisiones(
    con: duckdb.DuckDBPyConnection,
    fuente: str,
    *,
    periodo: str | None = None,
    ejercicio: int | None = None,
    nivel: str = "seccion",
) -> MetricResult:
    """Conteo y volumen de decisiones (BOE/CdM) por sección/ministerio y tipo.

    APROXIMADA: el importe de estas fuentes es de extracción falible. Por eso el
    importe NUNCA se agrega sin propagar la confianza: se desglosa en importe de
    confianza alta vs media y se cuenta lo que quedó sin importe. La columna de
    tipo (autorización, modificación de crédito, convenio…) permite filtrar.
    """
    if fuente not in _DECISIONES:
        raise ValueError(f"fuente {fuente!r} desconocida; usa 'boe' o 'cdm'.")
    tabla, fuente_cod, col_tipo, col_org = _DECISIONES[fuente]
    if nivel not in ("seccion", "ministerio"):
        raise ValueError(f"nivel {nivel!r} no soportado; usa 'seccion' o 'ministerio'.")
    grupo = "seccion_cod" if nivel == "seccion" else col_org
    where, params = _ventana_sql(periodo, ejercicio)
    df = con.execute(
        f"""
        SELECT {grupo} AS grupo, {col_tipo} AS tipo, count(*) AS n,
               sum(CASE WHEN importe_confianza='alta'  THEN importe ELSE 0 END) AS importe_alta,
               sum(CASE WHEN importe_confianza='media' THEN importe ELSE 0 END) AS importe_media,
               sum(CASE WHEN importe_confianza='sin_importe' THEN 1 ELSE 0 END) AS n_sin_importe
        FROM {tabla} WHERE {where}
        GROUP BY {grupo}, {col_tipo}
        ORDER BY n DESC
        """,  # noqa: S608
        params,
    ).df()
    return MetricResult(
        metrica="volumen_decisiones",
        data=df,
        nivel=nivel,
        naturaleza=APROXIMADA,
        magnitudes=["importe (confianza alta)", "importe (confianza media)", "conteo"],
        fuentes=[fuente_cod],
        frescura=_frescura(con, tabla, [fuente_cod]),
        advertencias=[
            "Importe de EXTRACCIÓN FALIBLE: se desglosa por confianza (alta = cuantía "
            "titular; media = cifra suelta) y se cuenta lo que quedó SIN importe. No se "
            "presenta un importe agregado único sin esta separación.",
            "Anclaje a SECCIÓN por ministerio proponente (no a servicio/DG): el texto "
            "no da el servicio (docs/cobertura_fuentes.md §4-5).",
        ],
    )


# ---------------------------------------------------------------------------
# PASO 4 — Cruce entre velocidades (INDICIARIO, con marca de aproximación)
# ---------------------------------------------------------------------------

_ADVERTENCIA_CRUCE = (
    "APROXIMACIÓN INDICIARIA — NO es una identidad contable. El compromiso jurídico "
    "(adjudicación) y la obligación reconocida (ORN) NO son subconjuntos: no todo lo "
    "adjudicado se ejecuta en el mismo periodo, hay IVA (la adjudicación suele ser con "
    "IVA, la ORN no), plurianualidad (un contrato se ejecuta en varios ejercicios) y "
    "contratos que no llegan a ORN. Se exponen AMBAS magnitudes por separado además del "
    "ratio; el ratio es un indicio de anticipación del gasto, no una conciliación."
)


def compromiso_vs_ejecucion(
    con: duckdb.DuckDBPyConnection, periodo: str, *, nivel: str = "seccion"
) -> MetricResult:
    """Adjudicación (PLACSP) frente a ejecución (ORN) por sección/servicio.

    El valor de ANTICIPACIÓN del proyecto: ilustra cómo el compromiso jurídico
    antecede a la obligación reconocida. Indiciaria (ver advertencia inseparable):
    expone adjudicado y ORN por separado y su ratio, nunca como cuadre contable.
    """
    periodo = _validar_periodo(periodo)
    if nivel not in ("seccion", "servicio"):
        raise ValueError(f"nivel {nivel!r} no soportado; usa 'seccion' o 'servicio'.")
    cols = _NIVEL_COMPROMISO[nivel]
    on = ", ".join(cols)
    ejercicio = int(periodo[:4])
    ejec = _ejecucion_agregada(con, [periodo], nivel)[[*cols, "orn"]]
    adj = con.execute(
        f"SELECT {on}, sum(importe_adjudicacion) adjudicado FROM fact_contratos "
        f"WHERE ejercicio = ? AND anclaje_tipo='servicio' GROUP BY {on}",
        [ejercicio],
    ).df()
    df = ejec.merge(adj, on=cols, how="outer")
    df["adjudicado"] = df["adjudicado"].fillna(0.0)
    df["orn"] = df["orn"].fillna(0.0)
    df["ratio_adjudicado_orn"] = df["adjudicado"] / df["orn"].replace(0, pd.NA)
    df = df.sort_values("orn", ascending=False, ignore_index=True)
    return MetricResult(
        metrica="compromiso_vs_ejecucion",
        data=df,
        nivel=nivel,
        naturaleza=INDICIARIA,
        magnitudes=["orn (igae)", "importe_adjudicacion (placsp)", "ratio"],
        fuentes=["igae_anexo_i", "placsp"],
        frescura={
            "igae_anexo_i": _frescura(con, "fact_ejecucion", ["igae_anexo_i"]),
            "placsp": _frescura(con, "fact_contratos", ["placsp"]),
        },
        advertencias=[
            _ADVERTENCIA_CRUCE,
            f"ORN acumulada al periodo {periodo}; adjudicación acumulada del ejercicio "
            f"{ejercicio}. Adjudicación solo de contratos anclados a servicio.",
        ],
        cobertura_anclaje=_cobertura_anclaje(
            con, "fact_contratos", "importe_adjudicacion", "ejercicio = ?", [ejercicio]
        ),
    )


def decisiones_vs_compromiso(
    con: duckdb.DuckDBPyConnection, *, ejercicio: int, nivel: str = "seccion"
) -> MetricResult:
    """Autorizaciones de gasto del Consejo (señal adelantada) vs adjudicación PLACSP.

    Indiciaria: el Consejo autoriza ANTES de que se adjudique; este cruce sugiere
    la magnitud de la decisión política frente al compromiso jurídico posterior.
    Expone ambas por separado; el importe del Consejo es de extracción falible
    (solo confianza alta+media) → doble marca de aproximación.
    """
    if nivel != "seccion":
        raise ValueError("decisiones_vs_compromiso solo se ancla a 'seccion'.")
    cdm = con.execute(
        """
        SELECT seccion_cod, sum(importe) autorizado_cdm,
               sum(CASE WHEN importe_confianza='alta' THEN importe ELSE 0 END) autorizado_cdm_alta
        FROM fact_acuerdos_cdm
        WHERE ejercicio = ? AND tipo_acuerdo='autorizacion_gasto' AND seccion_cod IS NOT NULL
        GROUP BY seccion_cod
        """,
        [ejercicio],
    ).df()
    adj = con.execute(
        "SELECT seccion_cod, sum(importe_adjudicacion) adjudicado FROM fact_contratos "
        "WHERE ejercicio = ? AND anclaje_tipo='servicio' GROUP BY seccion_cod",
        [ejercicio],
    ).df()
    df = cdm.merge(adj, on="seccion_cod", how="outer")
    for c in ("autorizado_cdm", "autorizado_cdm_alta", "adjudicado"):
        if c in df.columns:
            df[c] = df[c].fillna(0.0)
    return MetricResult(
        metrica="decisiones_vs_compromiso",
        data=df,
        nivel=nivel,
        naturaleza=INDICIARIA,
        magnitudes=["importe autorizado CdM (falible)", "importe_adjudicacion (placsp)"],
        fuentes=["consejo_ministros", "placsp"],
        frescura={
            "consejo_ministros": _frescura(con, "fact_acuerdos_cdm", ["consejo_ministros"]),
            "placsp": _frescura(con, "fact_contratos", ["placsp"]),
        },
        advertencias=[
            _ADVERTENCIA_CRUCE,
            "DOBLE aproximación: el importe del Consejo es de extracción falible (se "
            "expone también solo el de confianza alta) y la autorización política no se "
            "corresponde 1:1 con adjudicaciones concretas ni con su mismo periodo.",
        ],
    )
