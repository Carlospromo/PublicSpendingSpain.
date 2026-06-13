"""Estructura, catálogos y frescura del warehouse (capa analítica, lectura).

Funciones PURAS que la API de la Fase 6 expone sin reimplementar nada: navegación
del árbol orgánico con vigencia temporal, catálogos de dimensiones, y metadatos de
frescura/salud (objetivo 5 de CLAUDE.md §1: "siempre actualizado, y que se vea
hasta dónde"). Viven aquí —no en la API— para mantener la separación de capas
(§2): la API solo invoca.

Distinción servicio↔DG (CLAUDE.md §3): la unidad ESTABLE interanual es el
servicio presupuestario; la dirección general es su lectura NOMINAL vía el
crosswalk, que solo cubre el ejercicio del seed (2026). Fuera de ese ejercicio la
equivalencia DG es aproximada (estructura estable asumida) y se marca como tal en
cada servicio (``dg_equivalencia_aproximada``).
"""

from __future__ import annotations

from typing import Any

import duckdb

from gasto_estado.analytics import metrics

# Fuente de datos → hecho que la materializa (para la frescura por velocidad).
_FRESCURA_FUENTES: tuple[tuple[str, str], ...] = (
    ("igae_anexo_i", "fact_ejecucion"),
    ("placsp", "fact_contratos"),
    ("bdns", "fact_subvenciones"),
    ("boe_sumario", "fact_boe_disposiciones"),
    ("consejo_ministros", "fact_acuerdos_cdm"),
)


def _crosswalk_ejercicio(con: duckdb.DuckDBPyConnection) -> int:
    """Ejercicio que cubre el crosswalk DG (el del seed PGE; hoy 2026)."""
    metrics._ensure_dg_crosswalk(con)
    fila = con.execute("SELECT max(ejercicio) FROM _cw_dg").fetchone()
    return int(fila[0]) if fila and fila[0] is not None else 0


def ejercicios_disponibles(con: duckdb.DuckDBPyConnection) -> list[int]:
    """Ejercicios con ejecución cargada (descendente: el más reciente primero)."""
    return [
        int(r[0])
        for r in con.execute(
            "SELECT DISTINCT ejercicio FROM fact_ejecucion ORDER BY ejercicio DESC"
        ).fetchall()
    ]


def secciones(con: duckdb.DuckDBPyConnection, ejercicio: int) -> list[dict[str, Any]]:
    """Secciones (ministerios) con ejecución en el ejercicio, con su denominación."""
    filas = con.execute(
        """
        SELECT f.seccion_cod, max(ss.seccion_denominacion) AS denominacion,
               count(DISTINCT f.servicio_cod) AS n_servicios
        FROM fact_ejecucion f
        LEFT JOIN dim_seccion_servicio ss
          ON ss.ejercicio = f.ejercicio AND ss.seccion_cod = f.seccion_cod
         AND ss.servicio_cod = f.servicio_cod
        WHERE f.ejercicio = ?
        GROUP BY f.seccion_cod ORDER BY f.seccion_cod
        """,
        [ejercicio],
    ).fetchall()
    return [
        {"nivel": "seccion", "ejercicio": ejercicio, "seccion_cod": r[0],
         "denominacion": r[1], "n_servicios": int(r[2])}
        for r in filas
    ]


def servicios(
    con: duckdb.DuckDBPyConnection, ejercicio: int, seccion_cod: str
) -> list[dict[str, Any]]:
    """Servicios de una sección, con su DG nominal (vía crosswalk) y la marca de vigencia."""
    cw_ej = _crosswalk_ejercicio(con)
    aproximada = ejercicio != cw_ej
    filas = con.execute(
        """
        SELECT f.servicio_cod, max(ss.servicio_denominacion) AS denominacion,
               any_value(cw.dir3_cod) AS dir3_cod,
               any_value(cw.dg_denominacion) AS dg_denominacion,
               any_value(cw.dg_nivel_organico) AS dg_nivel_organico
        FROM fact_ejecucion f
        LEFT JOIN dim_seccion_servicio ss
          ON ss.ejercicio = f.ejercicio AND ss.seccion_cod = f.seccion_cod
         AND ss.servicio_cod = f.servicio_cod
        LEFT JOIN (SELECT DISTINCT seccion_cod, servicio_cod, dir3_cod,
                          dg_denominacion, dg_nivel_organico FROM _cw_dg) cw
          ON cw.seccion_cod = f.seccion_cod AND cw.servicio_cod = f.servicio_cod
        WHERE f.ejercicio = ? AND f.seccion_cod = ?
        GROUP BY f.servicio_cod ORDER BY f.servicio_cod
        """,
        [ejercicio, seccion_cod],
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in filas:
        tiene_dg = r[2] is not None
        out.append({
            "nivel": "servicio", "ejercicio": ejercicio, "seccion_cod": seccion_cod,
            "servicio_cod": r[0], "denominacion": r[1],
            "dg_dir3_cod": r[2], "dg_denominacion": r[3], "dg_nivel_organico": r[4],
            "dg_equivalencia_aproximada": bool(tiene_dg and aproximada),
            "dg_nota": (
                None if not tiene_dg else
                (f"Equivalencia DG nominal según la estructura {cw_ej}; aproximada para "
                 f"el ejercicio {ejercicio}." if aproximada else
                 f"Equivalencia DG según la estructura vigente {cw_ej}.")
            ),
        })
    return out


def catalogo_programas(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    filas = con.execute(
        "SELECT programa_cod, area_gasto_cod, politica_cod, grupo_programas_cod, denominacion "
        "FROM dim_programa ORDER BY programa_cod"
    ).fetchall()
    return [
        {"programa_cod": r[0], "area_gasto_cod": r[1], "politica_cod": r[2],
         "grupo_programas_cod": r[3], "denominacion": r[4]}
        for r in filas
    ]


def catalogo_economicas(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    filas = con.execute(
        "SELECT economica_cod, nivel, capitulo_cod, denominacion, denominacion_origen "
        "FROM dim_economica ORDER BY economica_cod"
    ).fetchall()
    return [
        {"economica_cod": r[0], "nivel": r[1], "capitulo_cod": r[2],
         "denominacion": r[3], "denominacion_origen": r[4]}
        for r in filas
    ]


def catalogo_fuentes(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Fuentes con su velocidad y periodicidad (las tres velocidades de §3)."""
    filas = con.execute(
        "SELECT fuente_cod, denominacion, velocidad, periodicidad, fase "
        "FROM dim_fuente ORDER BY fase, fuente_cod"
    ).fetchall()
    return [
        {"fuente_cod": r[0], "denominacion": r[1], "velocidad": r[2],
         "periodicidad": r[3], "fase": int(r[4])}
        for r in filas
    ]


def frescura_fuentes(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Por fuente: último periodo/captura cargado y rango cubierto (objetivo 5).

    Permite al frontal mostrar "IGAE a abril 2026, PLACSP a anteayer, …" sin
    adivinar. Las fuentes sin datos cargados se reportan vacías, no se omiten.
    """
    velocidades = {f["fuente_cod"]: f for f in catalogo_fuentes(con)}
    out: list[dict[str, Any]] = []
    for fuente, tabla in _FRESCURA_FUENTES:
        filtro = " WHERE fuente_cod = ?" if tabla == "fact_ejecucion" else ""
        params = [fuente] if filtro else []
        fila = con.execute(
            f"SELECT count(*), max(fecha_captura), min(periodo), max(periodo) FROM {tabla}{filtro}",  # noqa: S608
            params,
        ).fetchone()
        n, ultima, pmin, pmax = (fila if fila else (0, None, None, None))
        meta = velocidades.get(fuente, {})
        out.append({
            "fuente_cod": fuente,
            "velocidad": meta.get("velocidad"),
            "periodicidad": meta.get("periodicidad"),
            "n_filas": int(n or 0),
            "ultima_actualizacion": None if ultima is None else ultima.isoformat(),
            "periodo_cubierto": None if pmin is None else [pmin, pmax],
        })
    return out


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    fila = con.execute(sql).fetchone()
    return fila[0] if fila is not None else None


def salud(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Salud básica del warehouse: accesible, nº de periodos/secciones, última captura."""
    n_periodos = _scalar(
        con, "SELECT count(DISTINCT periodo) FROM fact_ejecucion WHERE fuente_cod='igae_anexo_i'"
    )
    ejercicios = ejercicios_disponibles(con)
    ultima_global = _scalar(
        con,
        """
        SELECT max(c) FROM (
            SELECT max(fecha_captura) c FROM fact_ejecucion
            UNION ALL SELECT max(fecha_captura) FROM fact_contratos
            UNION ALL SELECT max(fecha_captura) FROM fact_subvenciones
            UNION ALL SELECT max(fecha_captura) FROM fact_boe_disposiciones
            UNION ALL SELECT max(fecha_captura) FROM fact_acuerdos_cdm
        )
        """,
    )
    return {
        "accesible": True,
        "ejercicios": ejercicios,
        "n_periodos_igae": int(n_periodos or 0),
        "ultima_actualizacion": None if ultima_global is None else ultima_global.isoformat(),
        "perimetro": "AGE + organismos estatales (sin CCAA ni entes locales)",
        "cobertura_dg_nota": "Las métricas/alertas a nivel dirección general cubren la "
        "porción del gasto con anclaje DIR3 (~27% de la ORN); el resto se observa a nivel "
        "sección.",
    }
