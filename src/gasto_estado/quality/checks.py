"""Validaciones de coherencia contable sobre el warehouse (CLAUDE.md §7).

Motor consciente de COBERTURA: cada regla declara qué magnitudes necesita y el
motor consulta qué magnitudes aportan las fuentes cargadas de cada periodo
(columna ``cobertura`` del hecho, docs/modelo_datos.md §1b). Si falta una
magnitud, la regla sale SKIPPED con motivo explícito — nunca PASS sobre nulos
ni FAIL espurio. Las reglas pendientes de la Fase 4 (R5, identidad explícita de
R4) ya están implementadas: se activan solas cuando una fuente declare la
magnitud en su cobertura.

Complementa, sin duplicar, el cuadre interno aplicaciones↔SUBTOTAL_SERVICIO de
los parsers: aquel valida el fichero contra sus propios totales impresos en el
momento del parseo; esto valida el warehouse ya poblado (capa de exposición,
ancla orgánica, niveles de agregación, continuidad entre periodos).

Niveles de agregación y vinculación jurídica: los créditos vinculan por bolsas
(art. 43 Ley 47/2003), no por aplicación. Empíricamente (8 periodos reales,
2015–2026) ORN > definitivo ocurre en cientos de aplicaciones por periodo y
existe un definitivo negativo oficial (−20.000 €, 2017-11, 18.05.322L.22000):
ambos son legítimos a nivel aplicación y violaciones reales a nivel servicio.
Por eso R3 y el signo del definitivo se validan de servicio hacia arriba.

Catálogo de reglas y tolerancias: docs/validaciones.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

import duckdb

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"

# ---------------------------------------------------------------------------
# Tolerancias de redondeo, escaladas por nivel de agregación.
#
# Base: el cuadre interno del parser admite 0,5 € por servicio
# (TOLERANCIA_CUADRE en parsers/igae/v2021_plus.py: importes oficiales con 2
# decimales; el redondeo acumula con el nº de aplicaciones). Al agregar, el
# error potencial crece con el nº de sumandos: una sección agrega ~decenas de
# servicios (×10) y la AGE ~37 secciones (×10). Sobre magnitudes de 10^11 €,
# 50 € son 5e-10 relativo: holgura de redondeo, jamás un descuadre real.
# ---------------------------------------------------------------------------
TOLERANCIA_SERVICIO = 0.5
TOLERANCIA_SECCION = 5.0
TOLERANCIA_AGE = 50.0

# Magnitudes del modelo (columnas de fact_ejecucion) y motivo de pendencia de
# las que ninguna fuente cargada cubre todavía.
MAGNITUDES = (
    "credito_inicial",
    "credito_definitivo",
    "modificaciones",
    "comprometido",
    "orn",
    "pagos",
)
# Estas magnitudes no las publica el Anexo I; llegarán de IGAE Cuadros/Anexo II
# (reservados en dim_fuente como igae_cuadros/igae_anexo_ii, aún sin incorporar).
MOTIVO_PENDIENTE = {
    "pagos": "magnitud pagos no disponible en el Anexo I (requiere IGAE Cuadros/Anexo II)",
    "comprometido": (
        "magnitud comprometido no disponible en el Anexo I (requiere IGAE Cuadros/Anexo II)"
    ),
    "modificaciones": (
        "el Anexo I no publica modificaciones explícitas; magnitud no disponible "
        "en esta fuente (requiere IGAE Cuadros/Anexo II)"
    ),
}

# Máximo de descuadres detallados por resultado (el resto se cuenta).
MAX_DESCUADRES = 20


@dataclass(frozen=True)
class CheckResult:
    """Resultado de una regla sobre un periodo y un ámbito (nivel/sub-check)."""

    regla: str  # 'R1'..'R8'
    nombre: str
    periodo: str
    ambito: str
    estado: str  # PASS | FAIL | SKIPPED
    detalle: str = ""
    descuadres: list[dict[str, object]] = field(default_factory=list)


class CoherenceError(RuntimeError):
    """Un periodo recién cargado no pasa los checks: la carga se revierte.

    Política fail-loud de CLAUDE.md §2: nunca se deja visible como confiable
    un dato que no cuadra.
    """

    def __init__(self, periodo: str, fallos: list[CheckResult]) -> None:
        self.periodo = periodo
        self.fallos = fallos
        reglas = ", ".join(f"{f.regla} ({f.ambito}): {f.detalle}" for f in fallos)
        super().__init__(
            f"El periodo {periodo} no pasa las validaciones contables; carga revertida. {reglas}"
        )


_CheckFn = Callable[[duckdb.DuckDBPyConnection, str, frozenset[str]], list[CheckResult]]


@dataclass(frozen=True)
class Regla:
    cod: str
    nombre: str
    # Magnitudes imprescindibles para ejecutar la regla. Si alguna no está en
    # la cobertura del periodo, la regla entera sale SKIPPED. Las reglas con
    # sub-checks por magnitud declaran () y gestionan el detalle internamente.
    requiere: tuple[str, ...]
    fn: _CheckFn


REGLAS: list[Regla] = []


def _regla(cod: str, nombre: str, requiere: tuple[str, ...] = ()) -> Callable[[_CheckFn], _CheckFn]:
    def registrar(fn: _CheckFn) -> _CheckFn:
        REGLAS.append(Regla(cod, nombre, requiere, fn))
        return fn

    return registrar


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _filas(
    con: duckdb.DuckDBPyConnection, sql: str, params: list[object]
) -> list[dict[str, object]]:
    res = con.execute(sql, params)
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, fila, strict=True)) for fila in res.fetchall()]


def _resultado_descuadres(
    regla: Regla, periodo: str, ambito: str, descuadres: list[dict[str, object]], ok_detalle: str
) -> CheckResult:
    if not descuadres:
        return CheckResult(regla.cod, regla.nombre, periodo, ambito, PASS, ok_detalle)
    muestra = "; ".join(", ".join(f"{k}={v}" for k, v in fila.items()) for fila in descuadres[:3])
    extra = f" … (+{len(descuadres) - 3} más)" if len(descuadres) > 3 else ""
    return CheckResult(
        regla.cod,
        regla.nombre,
        periodo,
        ambito,
        FAIL,
        f"{len(descuadres)} descuadre(s): {muestra}{extra}",
        descuadres[:MAX_DESCUADRES],
    )


def _magnitudes_cubiertas(con: duckdb.DuckDBPyConnection, periodo: str) -> frozenset[str]:
    """Unión de las coberturas declaradas por las fuentes cargadas del periodo."""
    filas = con.execute(
        "SELECT DISTINCT cobertura FROM fact_ejecucion WHERE periodo = ?", [periodo]
    ).fetchall()
    cubiertas: set[str] = set()
    for (cobertura,) in filas:
        cubiertas.update(cobertura.split(","))
    return frozenset(cubiertas)


def _motivo_skip(faltan: Sequence[str]) -> str:
    return "; ".join(
        MOTIVO_PENDIENTE.get(m, f"magnitud {m} no cubierta por las fuentes cargadas del periodo")
        for m in faltan
    )


# ---------------------------------------------------------------------------
# R1/R2 — cuadre de agregación a través de la capa de exposición
#
# El warehouse no almacena los totales impresos del fichero (ese cuadre vive en
# el parser). Aquí el "total" independiente es fact_ejecucion agregado directo,
# y la "suma de las partes" es la misma agregación A TRAVÉS de v_ejecucion
# (joins con todas las dimensiones): detecta pérdida o duplicación de filas en
# la capa de exposición — exactamente lo que consumirá el frontal.
# ---------------------------------------------------------------------------


def _sql_cuadre_exposicion(mags: Sequence[str], grupo: str | None) -> str:
    sumas = ", ".join(f"sum({m}) AS {m}" for m in mags)
    difs = ", ".join(f"coalesce(v.{m}, 0) - coalesce(d.{m}, 0) AS dif_{m}" for m in mags)
    if grupo:
        return f"""
            WITH vista AS (
                SELECT {grupo}, count(*) AS n, {sumas} FROM v_ejecucion WHERE periodo = ? GROUP BY 1
            ), directo AS (
                SELECT {grupo}, count(*) AS n, {sumas}
                FROM fact_ejecucion WHERE periodo = ? GROUP BY 1
            )
            SELECT coalesce(v.{grupo}, d.{grupo}) AS {grupo},
                   coalesce(v.n, 0) - coalesce(d.n, 0) AS dif_filas, {difs}
            FROM vista v FULL JOIN directo d USING ({grupo})
        """
    return f"""
        WITH vista AS (SELECT count(*) AS n, {sumas} FROM v_ejecucion WHERE periodo = ?),
             directo AS (SELECT count(*) AS n, {sumas} FROM fact_ejecucion WHERE periodo = ?)
        SELECT v.n - d.n AS dif_filas, {difs} FROM vista v, directo d
    """


def _cuadre_exposicion(
    con: duckdb.DuckDBPyConnection,
    periodo: str,
    disponibles: frozenset[str],
    grupo: str | None,
    tolerancia: float,
) -> list[dict[str, object]]:
    mags = [m for m in MAGNITUDES if m in disponibles]
    filas = _filas(con, _sql_cuadre_exposicion(mags, grupo), [periodo, periodo])
    return [
        f
        for f in filas
        if f["dif_filas"] != 0 or any(abs(float(f[f"dif_{m}"])) > tolerancia for m in mags)  # type: ignore[arg-type]
    ]


@_regla("R1", "Σ(servicios) de una sección == total de la sección")
def _check_r1(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    regla = next(r for r in REGLAS if r.cod == "R1")
    descuadres = _cuadre_exposicion(con, periodo, disponibles, "seccion_cod", TOLERANCIA_SECCION)
    return [
        _resultado_descuadres(
            regla,
            periodo,
            "sección (todas las provincias, vía v_ejecucion)",
            descuadres,
            "agregación por sección idéntica en fact_ejecucion y en la capa de exposición",
        )
    ]


@_regla("R2", "Σ(secciones) == total AGE")
def _check_r2(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    regla = next(r for r in REGLAS if r.cod == "R2")
    descuadres = _cuadre_exposicion(con, periodo, disponibles, None, TOLERANCIA_AGE)
    return [
        _resultado_descuadres(
            regla,
            periodo,
            "total AGE (vía v_ejecucion)",
            descuadres,
            "total AGE idéntico en fact_ejecucion y en la capa de exposición",
        )
    ]


# ---------------------------------------------------------------------------
# R3 — ORN ≤ crédito definitivo, por nivel de bolsa hacia arriba
# ---------------------------------------------------------------------------

_NIVELES_R3 = (
    ("servicio", "seccion_cod, servicio_cod", TOLERANCIA_SERVICIO),
    ("sección", "seccion_cod", TOLERANCIA_SECCION),
    ("AGE", None, TOLERANCIA_AGE),
)


@_regla("R3", "ORN ≤ crédito definitivo", requiere=("orn", "credito_definitivo"))
def _check_r3(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    """Comparación con propagación de NULL, nunca contra ceros falsos: una
    bolsa cuyo definitivo está íntegramente sin publicar ('-' → NULL; caso
    real: servicio 50 MRR en 2026) NO es comparable y se cuenta como nota
    informativa, no como descuadre (CLAUDE.md §8: NULL ≠ 0)."""
    regla = next(r for r in REGLAS if r.cod == "R3")
    resultados = []
    for nivel, grupo, tol in _NIVELES_R3:
        select = f"{grupo}, " if grupo else ""
        group_by = f"GROUP BY {grupo}" if grupo else ""
        descuadres = _filas(
            con,
            f"""
            SELECT {select} round(sum(orn), 2) AS orn,
                   round(sum(credito_definitivo), 2) AS definitivo
            FROM fact_ejecucion WHERE periodo = ? {group_by}
            HAVING sum(orn) > sum(credito_definitivo) + {tol}
            """,
            [periodo],
        )
        no_comparables = con.execute(
            f"""
            SELECT count(*) FROM (
                SELECT 1 FROM fact_ejecucion WHERE periodo = ? {group_by or "GROUP BY 1=1"}
                HAVING sum(orn) IS NOT NULL AND sum(credito_definitivo) IS NULL
            )
            """,
            [periodo],
        ).fetchone()[0]  # type: ignore[index]
        notas = []
        if nivel == "servicio":
            notas.append("a nivel aplicación la vinculación jurídica permite ORN > definitivo")
        if no_comparables:
            notas.append(
                f"{no_comparables} grupo(s) con ORN sin definitivo publicado: no comparables"
            )
        nota = f" ({'; '.join(notas)})" if notas else ""
        resultados.append(
            _resultado_descuadres(
                regla, periodo, nivel, descuadres, f"ORN ≤ definitivo en cada {nivel}{nota}"
            )
        )
    return resultados


# ---------------------------------------------------------------------------
# R4 — crédito definitivo == inicial + modificaciones netas
# ---------------------------------------------------------------------------


@_regla(
    "R4",
    "definitivo == inicial + modificaciones (derivada)",
    requiere=("credito_inicial", "credito_definitivo"),
)
def _check_r4_derivada(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    """Parte verificable hoy: la derivada ``modificaciones = definitivo − inicial``.

    Con solo inicial y definitivo la identidad la satisface la derivada por
    construcción (tautología): lo comprobable es su dominio — calculable en
    toda sección — y se reporta el neto AGE como información. El signo puede
    ser negativo (bajas); el suelo de la bolsa lo vigila R7.
    """
    regla = next(r for r in REGLAS if r.cod == "R4" and "derivada" in r.nombre)
    neto, negativas = con.execute(
        """
        WITH s AS (
            SELECT seccion_cod,
                   coalesce(sum(credito_definitivo), 0) - coalesce(sum(credito_inicial), 0) AS m
            FROM fact_ejecucion WHERE periodo = ? GROUP BY 1
        )
        SELECT round(sum(m), 2), count(*) FILTER (m < 0) FROM s
        """,
        [periodo],
    ).fetchone()  # type: ignore[misc]
    return [
        CheckResult(
            regla.cod,
            regla.nombre,
            periodo,
            "derivada (definitivo − inicial)",
            PASS,
            f"modificaciones netas derivadas AGE: {neto:+,.2f} €; "
            f"{negativas} sección(es) con neto negativo (admitido)",
        )
    ]


@_regla(
    "R4",
    "definitivo == inicial + modificaciones (explícitas)",
    requiere=("credito_inicial", "credito_definitivo", "modificaciones"),
)
def _check_r4_explicita(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    """Identidad contable real, activable cuando una fuente cubra modificaciones."""
    regla = next(r for r in REGLAS if r.cod == "R4" and "explícitas" in r.nombre)
    descuadres = _filas(
        con,
        f"""
        SELECT seccion_cod, servicio_cod,
               round(coalesce(sum(credito_definitivo), 0)
                     - coalesce(sum(credito_inicial), 0)
                     - coalesce(sum(modificaciones), 0), 2) AS dif
        FROM fact_ejecucion WHERE periodo = ? AND cobertura LIKE '%modificaciones%'
        GROUP BY 1, 2
        HAVING abs(coalesce(sum(credito_definitivo), 0) - coalesce(sum(credito_inicial), 0)
                   - coalesce(sum(modificaciones), 0)) > {TOLERANCIA_SERVICIO}
        """,
        [periodo],
    )
    return [
        _resultado_descuadres(
            regla, periodo, "servicio", descuadres, "definitivo == inicial + modificaciones"
        )
    ]


# ---------------------------------------------------------------------------
# R5 — pagos ≤ ORN (Fase 4)
# ---------------------------------------------------------------------------


@_regla("R5", "pagos ≤ ORN", requiere=("pagos", "orn"))
def _check_r5(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    regla = next(r for r in REGLAS if r.cod == "R5")
    # Propagación de NULL como en R3: pagos sin ORN publicada no es comparable.
    descuadres = _filas(
        con,
        f"""
        SELECT seccion_cod, servicio_cod, round(sum(pagos), 2) AS pagos,
               round(sum(orn), 2) AS orn
        FROM fact_ejecucion WHERE periodo = ? AND cobertura LIKE '%pagos%'
        GROUP BY 1, 2
        HAVING sum(pagos) > sum(orn) + {TOLERANCIA_SERVICIO}
        """,
        [periodo],
    )
    return [
        _resultado_descuadres(regla, periodo, "servicio", descuadres, "pagos ≤ ORN por servicio")
    ]


# ---------------------------------------------------------------------------
# R6 — sin anclas orgánicas huérfanas (red de seguridad a posteriori)
# ---------------------------------------------------------------------------


@_regla("R6", "sin secciones/servicios huérfanos en el ancla orgánica")
def _check_r6(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    """La carga ya lo previene (OrphanOrganicError); aquí se revalida sobre el
    warehouse por si el dato llegó por otra vía o el esquema perdió la FK."""
    regla = next(r for r in REGLAS if r.cod == "R6")
    descuadres = _filas(
        con,
        """
        SELECT f.ejercicio, f.seccion_cod, f.servicio_cod, count(*) AS filas
        FROM fact_ejecucion f
        LEFT JOIN dim_seccion_servicio d
            ON d.ejercicio = f.ejercicio
           AND d.seccion_cod = f.seccion_cod
           AND d.servicio_cod = f.servicio_cod
        WHERE f.periodo = ? AND d.servicio_denominacion IS NULL
        GROUP BY 1, 2, 3
        """,
        [periodo],
    )
    return [
        _resultado_descuadres(
            regla,
            periodo,
            "ancla (ejercicio, sección, servicio)",
            descuadres,
            "todas las filas anclan a una entrada vigente de dim_seccion_servicio",
        )
    ]


# ---------------------------------------------------------------------------
# R7 — signos: importes no negativos donde corresponde
# ---------------------------------------------------------------------------


@_regla("R7", "signos: importes no negativos donde corresponde")
def _check_r7(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    """Sub-checks por magnitud disponible; las modificaciones derivadas pueden
    ser negativas (no se valida su signo). El definitivo se valida a nivel
    servicio: a nivel aplicación existe negativo oficial legítimo
    (redistribución dentro de la bolsa; caso real 2017-11, −20.000 €)."""
    regla = next(r for r in REGLAS if r.cod == "R7")
    sub_checks: list[tuple[str, str, str]] = [
        (
            "credito_inicial",
            "crédito inicial ≥ 0 (aplicación)",
            """
            SELECT seccion_cod, servicio_cod, programa_cod, economica_cod, provincia_cod,
                   credito_inicial AS importe
            FROM fact_ejecucion WHERE periodo = ? AND credito_inicial < 0
            """,
        ),
        (
            "orn",
            "ORN ≥ 0 (aplicación)",
            """
            SELECT seccion_cod, servicio_cod, programa_cod, economica_cod, provincia_cod,
                   orn AS importe
            FROM fact_ejecucion WHERE periodo = ? AND orn < 0
            """,
        ),
        (
            "credito_definitivo",
            "crédito definitivo ≥ 0 (servicio = bolsa)",
            f"""
            SELECT seccion_cod, servicio_cod, round(sum(credito_definitivo), 2) AS importe
            FROM fact_ejecucion WHERE periodo = ? GROUP BY 1, 2
            HAVING sum(credito_definitivo) < -{TOLERANCIA_SERVICIO}
            """,
        ),
    ]
    resultados = []
    for magnitud, ambito, sql in sub_checks:
        if magnitud not in disponibles:
            resultados.append(
                CheckResult(
                    regla.cod, regla.nombre, periodo, ambito, SKIPPED, _motivo_skip([magnitud])
                )
            )
            continue
        descuadres = _filas(con, sql, [periodo])
        resultados.append(
            _resultado_descuadres(regla, periodo, ambito, descuadres, "sin importes negativos")
        )
    return resultados


# ---------------------------------------------------------------------------
# R8 — continuidad temporal intra-ejercicio (el Anexo I es acumulado)
# ---------------------------------------------------------------------------


@_regla("R8", "continuidad intra-ejercicio del acumulado")
def _check_r8(
    con: duckdb.DuckDBPyConnection, periodo: str, disponibles: frozenset[str]
) -> list[CheckResult]:
    """Contra el periodo cargado inmediatamente anterior del mismo ejercicio:
    la ORN acumulada por servicio no decrece, el crédito inicial no cambia y
    ningún servicio con acumulado desaparece. Un FAIL es una anomalía a
    revisar (puede ser revisión oficial: queda documentada en el diff git del
    raw y se decide caso a caso)."""
    regla = next(r for r in REGLAS if r.cod == "R8")
    ejercicio = int(periodo[:4])
    anterior = con.execute(
        "SELECT max(periodo) FROM fact_ejecucion WHERE ejercicio = ? AND periodo < ?",
        [ejercicio, periodo],
    ).fetchone()[0]  # type: ignore[index]
    ambito = "servicio (vs periodo anterior del ejercicio)"
    if anterior is None:
        return [
            CheckResult(
                regla.cod,
                regla.nombre,
                periodo,
                ambito,
                SKIPPED,
                f"primer periodo cargado del ejercicio {ejercicio}: nada que contrastar",
            )
        ]
    usar_orn = "orn" in disponibles
    usar_ini = "credito_inicial" in disponibles
    if not (usar_orn or usar_ini):
        return [
            CheckResult(
                regla.cod,
                regla.nombre,
                periodo,
                ambito,
                SKIPPED,
                _motivo_skip(["orn", "credito_inicial"]),
            )
        ]
    condiciones = ["cur.seccion_cod IS NULL"]  # servicio con acumulado que desaparece
    if usar_orn:
        condiciones.append(f"coalesce(pre.orn, 0) - coalesce(cur.orn, 0) > {TOLERANCIA_SERVICIO}")
    if usar_ini:
        condiciones.append(
            "(pre.inicial IS NOT NULL AND cur.inicial IS NOT NULL "
            f"AND abs(pre.inicial - cur.inicial) > {TOLERANCIA_SERVICIO})"
        )
    descuadres = _filas(
        con,
        f"""
        WITH pre AS (
            SELECT seccion_cod, servicio_cod, sum(orn) AS orn, sum(credito_inicial) AS inicial
            FROM fact_ejecucion WHERE periodo = ? GROUP BY 1, 2
        ), cur AS (
            SELECT seccion_cod, servicio_cod, sum(orn) AS orn, sum(credito_inicial) AS inicial
            FROM fact_ejecucion WHERE periodo = ? GROUP BY 1, 2
        )
        SELECT coalesce(pre.seccion_cod, cur.seccion_cod) AS seccion_cod,
               coalesce(pre.servicio_cod, cur.servicio_cod) AS servicio_cod,
               round(pre.orn, 2) AS orn_anterior, round(cur.orn, 2) AS orn_actual,
               round(pre.inicial, 2) AS inicial_anterior, round(cur.inicial, 2) AS inicial_actual
        FROM pre FULL JOIN cur USING (seccion_cod, servicio_cod)
        WHERE {" OR ".join(condiciones)}
        """,
        [anterior, periodo],
    )
    return [
        _resultado_descuadres(
            regla,
            periodo,
            f"{ambito[:-1]}: {anterior})",
            descuadres,
            f"acumulado coherente con {anterior} (ORN no decrece, inicial constante)",
        )
    ]


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------


def periodos_cargados(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [
        fila[0]
        for fila in con.execute(
            "SELECT DISTINCT periodo FROM fact_ejecucion ORDER BY periodo"
        ).fetchall()
    ]


def run_checks(
    con: duckdb.DuckDBPyConnection, periodos: Sequence[str] | None = None
) -> list[CheckResult]:
    """Ejecuta todas las reglas sobre los ``periodos`` (o todos los cargados)."""
    if periodos is None:
        periodos = periodos_cargados(con)
    else:
        cargados = set(periodos_cargados(con))
        desconocidos = [p for p in periodos if p not in cargados]
        if desconocidos:
            raise ValueError(f"Periodo(s) sin cargar en el warehouse: {', '.join(desconocidos)}")
    resultados: list[CheckResult] = []
    for periodo in periodos:
        disponibles = _magnitudes_cubiertas(con, periodo)
        for regla in REGLAS:
            faltan = sorted(set(regla.requiere) - disponibles)
            if faltan:
                resultados.append(
                    CheckResult(
                        regla.cod, regla.nombre, periodo, "periodo", SKIPPED, _motivo_skip(faltan)
                    )
                )
            else:
                resultados.extend(regla.fn(con, periodo, disponibles))
    return resultados


# ---------------------------------------------------------------------------
# Informes
# ---------------------------------------------------------------------------


def resumen(resultados: Sequence[CheckResult]) -> dict[str, int]:
    return {estado: sum(r.estado == estado for r in resultados) for estado in (PASS, FAIL, SKIPPED)}


def render_consola(resultados: Sequence[CheckResult], echo: Callable[[str], None]) -> None:
    for r in resultados:
        echo(f"{r.estado:<7} {r.regla:<3} {r.periodo}  {r.ambito} — {r.detalle}")
    contadores = resumen(resultados)
    echo(
        f"Resumen: {contadores[PASS]} PASS, {contadores[SKIPPED]} SKIPPED, {contadores[FAIL]} FAIL"
    )


def a_json(resultados: Sequence[CheckResult]) -> str:
    return json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=2)
