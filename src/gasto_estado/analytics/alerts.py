"""Motor de alertas analíticas sobre el warehouse (Fase 5).

Análogo a ``quality/checks.py`` pero ANALÍTICO, no contable: en vez de validar
coherencia (PASS/FAIL), interpreta las métricas del Prompt 12 y señala hipótesis
para revisión humana (CLAUDE.md §5). Construye SOBRE ``analytics/metrics.py`` sin
recalcular: una alerta es interpretación de una métrica, no una métrica nueva.

Principio rector: **una alerta es una hipótesis señalada para un analista
(Carlos), no un veredicto de irregularidad.** Por eso ninguna alerta afirma
intención ni ilegalidad — describe una anomalía estadística o un patrón, con su
cifra, su umbral, su contexto comparativo, su confianza y su naturaleza (exacta /
aproximada / indiciaria, heredada de la métrica base). Funciones PURAS sobre el
warehouse, sin acoplamiento a API ni scheduler (Fase 6 las expone, Fase 7 las
dispara).

Cobertura declarada (CLAUDE.md §3, docs/cobertura_fuentes.md): las alertas a
nivel DG cubren la porción del gasto gestionada por direcciones generales con
anclaje DIR3 (~27% de la ORN; el resto —Deuda, Clases Pasivas, transferencias a
entes/SS— no es una DG ministerial). El **ámbito y su cobertura viajan con cada
alerta**; ninguna sugiere vigilar la totalidad del gasto.

Ámbito orgánico de las alertas IGAE: el **servicio presupuestario**, que es la
clave estable interanual y se corresponde con la unidad gestora (dirección
general / secretaría de Estado / subsecretaría). Se etiqueta con su unidad DIR3 y
nivel orgánico cuando el crosswalk (2026) lo resuelve. La comparación de ritmo es
SIEMPRE contra la propia norma histórica del servicio para el mismo mes (nunca
una media entre servicios distintos, que no son comparables).
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import duckdb

from gasto_estado.analytics import metrics

# Estados (como en checks.py): una regla produce ALERTAs o sale SKIPPED.
ALERTA = "ALERTA"
SKIPPED = "SKIPPED"

# Severidad graduada (nunca binaria). Orden de presentación: destacada primero.
DESTACADA = "destacada"
A_REVISAR = "a_revisar"
INFORMATIVA = "informativa"
_ORDEN_SEVERIDAD = {DESTACADA: 0, A_REVISAR: 1, INFORMATIVA: 2}

# Confianza de la señal (no de la métrica: de la alerta, dado histórico/anclaje).
CONF_ALTA = "alta"
CONF_MEDIA = "media"
CONF_BAJA = "baja"

# --- Parámetros de las reglas (calibrados sobre los 8 periodos reales) -------
# Ritmo: nº mínimo de mismos-meses históricos para evaluar una desviación.
RITMO_MIN_HIST = 3
# Suelo de escala robusta en puntos porcentuales: el grado same-month de un
# servicio oscila varios puntos de forma natural; sin suelo, un MAD≈0 (servicio
# muy estable con n=3) dispararía z enormes ante variaciones triviales.
RITMO_PISO_PP = 8.0
RITMO_Z_MIN = 3.0  # z robusta mínima para señalar
RITMO_GAP_MIN_PP = 15.0  # materialidad: salto mínimo en puntos de grado
RITMO_IMPORTE_MIN = 1_000_000.0  # crédito definitivo mínimo (ignora unidades ínfimas)
RITMO_Z_DESTACADA = 6.0
RITMO_GAP_DESTACADA_PP = 50.0

# Modificaciones: outlier de la modificación relativa frente al CONJUNTO de
# secciones del periodo (permitido para modificaciones, CLAUDE.md/Prompt 13),
# con suelo de escala (la mayoría de secciones modifican ~0% → MAD≈0 dispararía
# z enormes) y suelo de materialidad absoluto y relativo.
MOD_PISO_PCT = 8.0
# La materialidad (relativa Y absoluta) selecciona lo atípico frente al conjunto
# (casi todas las secciones modifican ~0%); la z robusta acompaña como contexto.
MOD_PCT_MIN = 15.0  # |modificación| sobre inicial, en %
MOD_IMPORTE_MIN = 100_000_000.0  # € de modificación absoluta
MOD_PCT_DESTACADA = 40.0
MOD_EUR_DESTACADA = 1_000_000_000.0

# Concentración: umbral contextual de HHI y suelos de muestra.
CONC_HHI_MIN = 2500.0  # estándar de "mercado concentrado"
CONC_HHI_DESTACADA = 5000.0
CONC_IMPORTE_MIN = 100_000.0
CONC_MIN_ADJUDICATARIOS = 2  # con 1 solo adjudicatario la señal es estructural, no patrón

# Anticipación compromiso→ORN: ratio adjudicado/ORN alto = ejecución por venir.
ANTIC_RATIO_MIN = 1.0  # adjudicado supera a la ORN ya reconocida
ANTIC_IMPORTE_MIN = 5_000_000.0
ANTIC_RATIO_DESTACADA = 3.0

MAX_EVIDENCIAS = 8


@dataclass(frozen=True)
class Alerta:
    """Una hipótesis señalada para revisión humana (o un SKIPPED motivado).

    Autoexplicativa (CLAUDE.md §9): explica por qué saltó, con cifra observada,
    referencia/umbral, contexto, severidad, confianza, naturaleza heredada,
    cobertura del ámbito y evidencias. NUNCA afirma irregularidad ni intención.
    """

    tipo: str
    estado: str  # ALERTA | SKIPPED
    periodo: str
    ambito: dict[str, Any]
    naturaleza: str  # exacta | aproximada | indiciaria (heredada de la métrica)
    severidad: str | None = None
    confianza: str | None = None
    valor_observado: float | None = None
    referencia: dict[str, Any] = field(default_factory=dict)
    contexto: str = ""
    cobertura: dict[str, Any] = field(default_factory=dict)
    evidencias: list[dict[str, Any]] = field(default_factory=list)
    magnitudes: dict[str, Any] = field(default_factory=dict)  # cruces: ambas por separado
    motivo: str | None = None  # solo SKIPPED


def _skip(tipo: str, periodo: str, motivo: str, ambito: dict[str, Any] | None = None) -> Alerta:
    return Alerta(
        tipo=tipo, estado=SKIPPED, periodo=periodo, ambito=ambito or {"nivel": "AGE"},
        naturaleza=metrics.EXACTA, motivo=motivo,
    )


# ---------------------------------------------------------------------------
# Utilidades compartidas
# ---------------------------------------------------------------------------


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> Any:
    """Primer valor de la primera fila (o None): evita indexar un fetchone() None."""
    fila = con.execute(sql, params).fetchone()
    return fila[0] if fila is not None else None


def _es_prorroga(con: duckdb.DuckDBPyConnection, periodo: str) -> bool:
    etiqueta = _scalar(con, "SELECT presupuesto FROM dim_periodo WHERE periodo = ?", [periodo])
    return isinstance(etiqueta, str) and etiqueta.upper().endswith("-P")


def _mismos_meses_anteriores(con: duckdb.DuckDBPyConnection, periodo: str) -> list[str]:
    """Periodos IGAE cargados del MISMO mes y año anterior (orden ascendente)."""
    mes = periodo[5:7]
    anio = int(periodo[:4])
    return [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT periodo FROM fact_ejecucion "
            "WHERE fuente_cod='igae_anexo_i' AND substr(periodo,6,2)=? AND substr(periodo,1,4) < ? "
            "ORDER BY periodo",
            [mes, str(anio)],
        ).fetchall()
    ]


def _num(valor: object) -> float:
    """Coerción numérica NaN-safe de un valor de DataFrame (Any) a float; nulo → NaN."""
    if valor is None:
        return float("nan")
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def _num0(valor: object) -> float:
    """Como ``_num`` pero nulo/NaN → 0.0 (para sumandos donde el vacío es cero)."""
    x = _num(valor)
    return 0.0 if x != x else x


def _grado_servicio(
    con: duckdb.DuckDBPyConnection, periodo: str
) -> dict[tuple[str, str], dict[str, float]]:
    """{(seccion,servicio): {pct, definitivo, orn}} del grado de ejecución (reusa la métrica)."""
    df = metrics.grado_ejecucion(con, periodo, nivel="servicio").data
    out: dict[tuple[str, str], dict[str, float]] = {}
    for fila in df.to_dict("records"):
        out[(str(fila["seccion_cod"]), str(fila["servicio_cod"]))] = {
            "pct": _num(fila["pct_ejecucion"]),
            "definitivo": _num0(fila["credito_definitivo"]),
            "orn": _num0(fila["orn"]),
        }
    return out


def _etiquetas_dg(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], dict[str, str]]:
    """{(seccion,servicio): {dir3, nivel_organico, denominacion}} del crosswalk DG (2026)."""
    metrics._ensure_dg_crosswalk(con)
    out: dict[tuple[str, str], dict[str, str]] = {}
    for r in con.execute(
        "SELECT seccion_cod, servicio_cod, dir3_cod, dg_nivel_organico, dg_denominacion FROM _cw_dg"
    ).fetchall():
        out[(r[0], r[1])] = {"dir3_cod": r[2], "nivel_organico": r[3], "denominacion": r[4]}
    return out


def _denominacion_servicio(
    con: duckdb.DuckDBPyConnection, ejercicio: int, seccion: str, servicio: str
) -> str | None:
    fila = con.execute(
        "SELECT servicio_denominacion FROM dim_seccion_servicio "
        "WHERE ejercicio=? AND seccion_cod=? AND servicio_cod=?",
        [ejercicio, seccion, servicio],
    ).fetchone()
    return fila[0] if fila else None


def _ambito_servicio(
    con: duckdb.DuckDBPyConnection,
    periodo: str,
    seccion: str,
    servicio: str,
    dg: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    ejercicio = int(periodo[:4])
    etiqueta = dg.get((seccion, servicio))
    return {
        "nivel": "servicio",
        "seccion_cod": seccion,
        "servicio_cod": servicio,
        "denominacion": _denominacion_servicio(con, ejercicio, seccion, servicio)
        or (etiqueta or {}).get("denominacion"),
        "dir3_cod": (etiqueta or {}).get("dir3_cod"),
        "nivel_organico": (etiqueta or {}).get("nivel_organico"),
    }


def _cobertura_servicio(
    con: duckdb.DuckDBPyConnection, periodo: str, definitivo: float, dir3_cod: str | None
) -> dict[str, Any]:
    """Qué fracción del crédito AGE del periodo representa este servicio + si es DG con DIR3."""
    total = _scalar(
        con, "SELECT sum(credito_definitivo) FROM fact_ejecucion WHERE periodo=?", [periodo]
    )
    pct = None if not total else round(100 * definitivo / float(total), 2)
    return {
        "magnitud": "credito_definitivo",
        "pct_del_credito_age": pct,
        "unidad_dir3": dir3_cod is not None,
        "nota": "Ámbito = un servicio presupuestario; cubre solo su porción del gasto, "
        "no la totalidad. La identidad DG/DIR3 está disponible cuando el anclaje la resuelve.",
    }


# ---------------------------------------------------------------------------
# Paso 2 — Desviación de ritmo de ejecución (IGAE, servicio≈DG)
# ---------------------------------------------------------------------------


def alertas_ritmo(con: duckdb.DuckDBPyConnection, periodo: str) -> list[Alerta]:
    """Señala servicios cuyo grado de ejecución se desvía de SU norma histórica mismo-mes.

    Método: para cada servicio, mediana y MAD de su grado de ejecución en los
    mismos meses de años anteriores (banda robusta, con suelo de escala para no
    sobre-reaccionar a una historia casi constante). Se señala si la desviación
    robusta supera el umbral Y el salto en puntos es material. Sobre- y
    sub-ejecución son ambas señalables. Histórico insuficiente (ver
    ``RITMO_MIN_HIST`` mismos-meses) → SKIPPED, no falsa alarma.
    """
    historicos = _mismos_meses_anteriores(con, periodo)
    if len(historicos) < RITMO_MIN_HIST:
        return [
            _skip(
                "ritmo_ejecucion", periodo,
                f"histórico insuficiente: {len(historicos)} mismo(s)-mes anterior(es) cargado(s) "
                f"(se requieren {RITMO_MIN_HIST}); no se puede establecer la norma del servicio.",
            )
        ]
    series = {p: _grado_servicio(con, p) for p in historicos}
    actual = _grado_servicio(con, periodo)
    dg = _etiquetas_dg(con)
    prorroga = _es_prorroga(con, periodo)
    alertas: list[Alerta] = []
    evaluados = 0
    for clave, datos in actual.items():
        valores = [series[p][clave]["pct"] for p in historicos
                   if clave in series[p] and series[p][clave]["pct"] == series[p][clave]["pct"]]
        if len(valores) < RITMO_MIN_HIST or datos["pct"] != datos["pct"]:
            continue
        if datos["definitivo"] < RITMO_IMPORTE_MIN:
            continue
        evaluados += 1
        mediana = statistics.median(valores)
        mad = statistics.median([abs(v - mediana) for v in valores])
        escala = max(1.4826 * mad, RITMO_PISO_PP)
        gap = datos["pct"] - mediana
        z = gap / escala
        if abs(z) < RITMO_Z_MIN or abs(gap) < RITMO_GAP_MIN_PP:
            continue
        seccion, servicio = clave
        destacada = abs(z) >= RITMO_Z_DESTACADA or abs(gap) >= RITMO_GAP_DESTACADA_PP
        confianza = CONF_ALTA
        notas_prorroga = ""
        if prorroga:
            confianza = CONF_MEDIA
            notas_prorroga = (
                " La norma histórica se construyó con ejercicios no prorrogados; en prórroga "
                "(2025-P) el crédito no es homogéneo, lo que resta comparabilidad."
            )
        sentido = "sobre-ejecución" if gap > 0 else "sub-ejecución"
        ambito = _ambito_servicio(con, periodo, seccion, servicio, dg)
        alertas.append(
            Alerta(
                tipo="ritmo_ejecucion", estado=ALERTA, periodo=periodo, ambito=ambito,
                naturaleza=metrics.EXACTA, severidad=DESTACADA if destacada else A_REVISAR,
                confianza=confianza, valor_observado=round(datos["pct"], 1),
                referencia={
                    "norma_mismo_mes_mediana_pct": round(mediana, 1),
                    "banda_robusta_pp": round(escala, 1),
                    "z_robusta": round(z, 1),
                    "salto_pp": round(gap, 1),
                    "n_historico": len(valores),
                    "umbral_z": RITMO_Z_MIN,
                    "umbral_salto_pp": RITMO_GAP_MIN_PP,
                },
                contexto=(
                    f"Grado de ejecución {datos['pct']:.0f}% frente a su mediana de "
                    f"{mediana:.0f}% en los mismos meses de {len(valores)} años anteriores "
                    f"({sentido}, {abs(gap):.0f} pp; z robusta {z:.1f}). Es una desviación "
                    f"respecto al patrón propio del servicio, no un juicio sobre su causa."
                    + notas_prorroga
                ),
                cobertura=_cobertura_servicio(
                    con, periodo, datos["definitivo"], ambito["dir3_cod"]
                ),
                evidencias=[
                    {"tipo": "serie_historica", "mismo_mes": historicos,
                     "grados_pct": [round(v, 1) for v in valores]},
                    {"tipo": "aplicaciones",
                     "ref": f"v_ejecucion periodo={periodo} seccion_cod={seccion} "
                            f"servicio_cod={servicio}"},
                ],
            )
        )
    if evaluados == 0:
        return [
            _skip(
                "ritmo_ejecucion", periodo,
                "ningún servicio con histórico mismo-mes suficiente y crédito material.",
            )
        ]
    return alertas


# ---------------------------------------------------------------------------
# Paso 3 — Modificaciones de crédito atípicas (IGAE)
# ---------------------------------------------------------------------------


def alertas_modificaciones(con: duckdb.DuckDBPyConnection, periodo: str) -> list[Alerta]:
    """Señala secciones con modificaciones (definitivo−inicial) atípicas vs el conjunto.

    Las modificaciones son DERIVADAS (el Anexo I no las publica explícitas) y una
    grande NO es irregular per se (puede ser un suplemento de crédito legal): la
    alerta la enmarca como "inusual respecto al patrón del periodo". Outlier
    robusto de la modificación relativa frente al conjunto de secciones, con suelo
    de materialidad absoluto y relativo.
    """
    df = metrics.modificaciones_credito(con, periodo, nivel="seccion").data
    pct = [_num(x) for x in df["modificaciones_pct"]]
    pct = [v for v in pct if v == v and abs(v) != float("inf")]
    if len(pct) < 5:
        return [_skip("modificacion_atipica", periodo,
                      "muy pocas secciones para un conjunto de referencia.")]
    mediana = statistics.median(pct)
    mad = statistics.median([abs(v - mediana) for v in pct])
    escala = max(1.4826 * mad, MOD_PISO_PCT)  # suelo: evita z hipersensible con MAD≈0
    prorroga = _es_prorroga(con, periodo)
    total = _scalar(
        con, "SELECT sum(credito_definitivo) FROM fact_ejecucion WHERE periodo=?", [periodo]
    )
    total_f = float(total) if total else 0.0
    alertas: list[Alerta] = []
    for fila in df.to_dict("records"):
        mp = _num(fila["modificaciones_pct"])
        mod = _num0(fila["modificaciones"])
        if mp != mp or abs(mp) < MOD_PCT_MIN or abs(mod) < MOD_IMPORTE_MIN:
            continue
        z = (mp - mediana) / escala
        destacada = abs(mp) >= MOD_PCT_DESTACADA or abs(mod) >= MOD_EUR_DESTACADA
        signo = "ampliación" if mod > 0 else "minoración"
        seccion = str(fila["seccion_cod"])
        alertas.append(
            Alerta(
                tipo="modificacion_atipica", estado=ALERTA, periodo=periodo,
                ambito={"nivel": "seccion", "seccion_cod": seccion,
                        "denominacion": fila.get("seccion_denominacion")},
                naturaleza=metrics.EXACTA,
                severidad=DESTACADA if destacada else A_REVISAR,
                confianza=CONF_MEDIA if prorroga else CONF_ALTA,
                valor_observado=round(mp, 1),
                referencia={
                    "modificacion_eur": round(mod, 2),
                    "mediana_conjunto_pct": round(mediana, 1),
                    "banda_robusta_pp": round(escala, 1),
                    "z_robusta": round(z, 1),
                    "umbral_pct": MOD_PCT_MIN, "umbral_eur": MOD_IMPORTE_MIN,
                },
                contexto=(
                    f"Modificación neta derivada de {mod:+,.0f} € ({mp:+.1f}% sobre el crédito "
                    f"inicial): {signo} inusual frente a la mediana de {mediana:.1f}% del "
                    f"conjunto de secciones del periodo (z robusta {z:.1f}). Una modificación "
                    f"grande puede ser perfectamente legal (p. ej. un suplemento de crédito); "
                    f"esto solo marca que se aparta del patrón."
                    + (" En prórroga el comportamiento difiere." if prorroga else "")
                ),
                cobertura={
                    "magnitud": "credito_definitivo",
                    "pct_del_credito_age": None if not total_f else round(
                        100 * _num0(fila["credito_definitivo"]) / total_f, 2),
                    "nota": "Modificaciones DERIVADAS (definitivo − inicial); el Anexo I no las "
                    "publica explícitas.",
                },
                evidencias=[{"tipo": "aplicaciones",
                             "ref": f"v_ejecucion periodo={periodo} seccion_cod={seccion}"}],
            )
        )
    return alertas or [_skip("modificacion_atipica", periodo,
                             "sin secciones fuera del patrón del conjunto.")]


# ---------------------------------------------------------------------------
# Paso 4 — Concentración de adjudicatarios (PLACSP)
# ---------------------------------------------------------------------------


def alertas_concentracion(
    con: duckdb.DuckDBPyConnection, periodo: str, *, ejercicio: int | None = None
) -> list[Alerta]:
    """Señala órganos con concentración de adjudicatarios anómala (HHI alto).

    Sobre ``concentracion_adjudicatarios``. NO interpreta concentración como
    amaño: puede haber un único proveedor legítimo de un suministro especializado.
    Se describe como patrón a revisar. Propaga la tasa de anclaje del ámbito: una
    alerta sobre un órgano con gran parte del importe sin anclar es débil y lo dice.
    """
    ej = ejercicio if ejercicio is not None else int(periodo[:4])
    res = metrics.concentracion_adjudicatarios(con, nivel="servicio", ejercicio=ej)
    df = res.data
    cob = res.cobertura_anclaje or {}
    pct_anclado = cob.get("pct_anclado_a_servicio")
    if df.empty:
        return [_skip("concentracion_adjudicatarios", periodo,
                      f"sin contratación anclada a servicio en el ejercicio {ej}.")]
    alertas: list[Alerta] = []
    for fila in df.to_dict("records"):
        hhi = _num0(fila["hhi"])
        n_adj = int(_num0(fila["n_adjudicatarios"]))
        importe = _num0(fila["importe_total"])
        if hhi < CONC_HHI_MIN or importe < CONC_IMPORTE_MIN:
            continue
        if n_adj < CONC_MIN_ADJUDICATARIOS:
            # Un único adjudicatario es estructural, no un patrón de concentración;
            # se reporta como informativa, sin sugerir nada.
            severidad, conf = INFORMATIVA, CONF_BAJA
        else:
            severidad = DESTACADA if hhi >= CONC_HHI_DESTACADA else A_REVISAR
            conf = CONF_ALTA if (pct_anclado or 0) >= 60 else CONF_BAJA
        anclaje_debil = (pct_anclado is not None and pct_anclado < 60)
        seccion = str(fila["seccion_cod"])
        servicio = str(fila["servicio_cod"])
        alertas.append(
            Alerta(
                tipo="concentracion_adjudicatarios", estado=ALERTA, periodo=periodo,
                ambito={"nivel": "servicio", "seccion_cod": seccion, "servicio_cod": servicio},
                naturaleza=metrics.EXACTA, severidad=severidad, confianza=conf,
                valor_observado=hhi,
                referencia={
                    "hhi": hhi, "top_n_cuota_pct": _num0(fila["top_n_cuota_pct"]),
                    "n_adjudicatarios": n_adj, "importe_total_eur": importe,
                    "umbral_hhi": CONC_HHI_MIN,
                },
                contexto=(
                    f"HHI {hhi:.0f} (≥{CONC_HHI_MIN:.0f} = concentrado) con "
                    f"{n_adj} adjudicatario(s) e importe {importe:,.0f} €. Patrón de "
                    f"concentración a revisar; no implica amaño (puede existir un único "
                    f"proveedor legítimo)."
                    + (" Anclaje del ámbito débil: señal poco fiable." if anclaje_debil else "")
                ),
                cobertura={
                    "magnitud": "importe_adjudicacion",
                    "pct_anclado_a_servicio": pct_anclado,
                    "nota": "Concentración calculada solo sobre contratos anclados a servicio "
                    "con adjudicatario identificado.",
                },
                evidencias=[{"tipo": "contratos",
                             "ref": f"v_contratos ejercicio={ej} seccion_cod={seccion} "
                             f"servicio_cod={servicio} anclaje_tipo=servicio"}],
            )
        )
    return alertas or [_skip("concentracion_adjudicatarios", periodo,
                             "sin órganos por encima del umbral de concentración material.")]


# ---------------------------------------------------------------------------
# Paso 5 — Anticipación compromiso → ORN (cruce INDICIARIO)
# ---------------------------------------------------------------------------


def alertas_anticipacion(con: duckdb.DuckDBPyConnection, periodo: str) -> list[Alerta]:
    """Señala servicios con compromiso (PLACSP) alto frente a la ORN ya reconocida.

    El valor de anticipación del proyecto: el compromiso jurídico precede en meses
    a la obligación reconocida. INDICIARIA por construcción (no es identidad
    contable: IVA, plurianualidad, contratos que no llegan a ORN) — se exponen
    AMBAS magnitudes por separado, nunca solo el ratio.
    """
    res = metrics.compromiso_vs_ejecucion(con, periodo, nivel="servicio")
    df = res.data
    cob = res.cobertura_anclaje or {}
    alertas: list[Alerta] = []
    for fila in df.to_dict("records"):
        adjudicado = _num0(fila["adjudicado"])
        orn = _num0(fila["orn"])
        ratio = adjudicado / orn if orn > 0 else float("inf") if adjudicado > 0 else 0.0
        if adjudicado < ANTIC_IMPORTE_MIN or ratio < ANTIC_RATIO_MIN:
            continue
        destacada = ratio >= ANTIC_RATIO_DESTACADA or orn == 0
        seccion = str(fila["seccion_cod"])
        servicio = str(fila["servicio_cod"])
        alertas.append(
            Alerta(
                tipo="anticipacion_compromiso", estado=ALERTA, periodo=periodo,
                ambito={"nivel": "servicio", "seccion_cod": seccion, "servicio_cod": servicio},
                naturaleza=metrics.INDICIARIA,
                severidad=DESTACADA if destacada else A_REVISAR, confianza=CONF_BAJA,
                valor_observado=round(ratio, 2) if ratio != float("inf") else None,
                referencia={"umbral_ratio": ANTIC_RATIO_MIN,
                            "umbral_importe_eur": ANTIC_IMPORTE_MIN},
                contexto=(
                    f"Compromiso adjudicado en PLACSP ({adjudicado:,.0f} €) elevado frente a la "
                    f"ORN reconocida ({orn:,.0f} €) en el ejercicio: indicio de ejecución por "
                    f"venir, NO una conciliación contable (hay IVA, plurianualidad y contratos "
                    f"que no llegan a ORN). Se muestran ambas magnitudes por separado."
                ),
                cobertura={"magnitud": "importe_adjudicacion",
                           "pct_anclado_a_servicio": cob.get("pct_anclado_a_servicio")},
                magnitudes={"orn_igae_eur": round(orn, 2),
                            "adjudicado_placsp_eur": round(adjudicado, 2),
                            "ratio_adjudicado_orn": None if ratio == float("inf")
                            else round(ratio, 2)},
                evidencias=[{"tipo": "contratos",
                             "ref": f"v_contratos ejercicio={periodo[:4]} seccion_cod={seccion} "
                             f"servicio_cod={servicio}"},
                            {"tipo": "ejecucion",
                             "ref": f"v_ejecucion periodo={periodo} seccion_cod={seccion} "
                             f"servicio_cod={servicio}"}],
            )
        )
    if not alertas:
        return [_skip("anticipacion_compromiso", periodo,
                      "sin servicios con compromiso material por encima de la ORN.")]
    return alertas


# ---------------------------------------------------------------------------
# Motor + informe
# ---------------------------------------------------------------------------

_REGLAS: tuple[Callable[[duckdb.DuckDBPyConnection, str], list[Alerta]], ...] = (
    alertas_ritmo,
    alertas_modificaciones,
    alertas_concentracion,
    alertas_anticipacion,
)


def periodos_igae(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [
        r[0] for r in con.execute(
            "SELECT DISTINCT periodo FROM fact_ejecucion WHERE fuente_cod='igae_anexo_i' "
            "ORDER BY periodo"
        ).fetchall()
    ]


def run_alerts(
    con: duckdb.DuckDBPyConnection, periodos: Sequence[str] | None = None
) -> list[Alerta]:
    """Ejecuta todas las reglas de alerta sobre los ``periodos`` (o todos los IGAE)."""
    if periodos is None:
        periodos = periodos_igae(con)
    resultados: list[Alerta] = []
    for periodo in periodos:
        for regla in _REGLAS:
            resultados.extend(regla(con, periodo))
    return resultados


def _cobertura_global(con: duckdb.DuckDBPyConnection, periodo: str) -> dict[str, Any]:
    """Encabezado de cobertura: qué fracción de la ORN se vigila a nivel DG vs solo sección.

    Consistente con el etiquetado de las alertas: un servicio se considera
    vigilable a nivel DG si resuelve a una unidad DIR3 por el crosswalk
    (mapeado por sección+servicio, estructura 2026 estable). Los ejercicios sin
    crosswalk propio reutilizan esa estructura para servicios de código estable.
    """
    metrics._ensure_dg_crosswalk(con)
    fila = con.execute(
        """
        WITH e AS (
            SELECT f.seccion_cod, f.servicio_cod, sum(f.orn) AS orn
            FROM fact_ejecucion f WHERE f.periodo = ? GROUP BY 1, 2
        )
        SELECT sum(e.orn) AS total,
               sum(CASE WHEN cw.dir3_cod IS NOT NULL THEN e.orn ELSE 0 END) AS con_dir3
        FROM e LEFT JOIN (SELECT DISTINCT seccion_cod, servicio_cod, dir3_cod FROM _cw_dg) cw
          ON cw.seccion_cod = e.seccion_cod AND cw.servicio_cod = e.servicio_cod
        """,
        [periodo],
    ).fetchone()
    total = float(fila[0]) if fila and fila[0] else 0.0
    con_dir3 = float(fila[1]) if fila and fila[1] else 0.0
    return {
        "periodo": periodo,
        "pct_orn_vigilable_a_nivel_dg": None if total == 0 else round(100 * con_dir3 / total, 1),
        "nota": "Las alertas de ritmo/concentración/anticipación se evalúan a nivel servicio "
        "(≈ DG); el resto del gasto (Deuda, Clases Pasivas, transferencias a entes/SS) solo se "
        "observa a nivel sección. Ninguna alerta vigila la totalidad del gasto.",
    }


def informe(con: duckdb.DuckDBPyConnection, periodo: str) -> dict[str, Any]:
    """Informe consolidado de un periodo: cabecera de cobertura + alertas ordenadas."""
    alertas = run_alerts(con, [periodo])
    disparadas = [a for a in alertas if a.estado == ALERTA]
    omitidas = [a for a in alertas if a.estado == SKIPPED]
    disparadas.sort(key=lambda a: (
        _ORDEN_SEVERIDAD.get(a.severidad or "", 9),
        a.ambito.get("seccion_cod") or "",
        a.ambito.get("servicio_cod") or "",
    ))
    conteo: dict[str, int] = {DESTACADA: 0, A_REVISAR: 0, INFORMATIVA: 0}
    for a in disparadas:
        if a.severidad:
            conteo[a.severidad] += 1
    return {
        "periodo": periodo,
        "cobertura_global": _cobertura_global(con, periodo),
        "resumen": {"alertas": len(disparadas), "por_severidad": conteo, "skipped": len(omitidas)},
        "alertas": [asdict(a) for a in disparadas],
        "skipped": [asdict(a) for a in omitidas],
    }


def render_consola(inf: dict[str, Any], echo: Callable[[str], None]) -> None:
    """Informe legible para el analista."""
    cob = inf["cobertura_global"]
    echo(f"== Informe de alertas — periodo {inf['periodo']} ==")
    pct = cob.get("pct_orn_vigilable_a_nivel_dg")
    echo(f"Cobertura: {pct}% de la ORN vigilable a nivel dirección general (resto, solo sección).")
    r = inf["resumen"]
    echo(
        f"Alertas: {r['alertas']} ({r['por_severidad'][DESTACADA]} destacadas, "
        f"{r['por_severidad'][A_REVISAR]} a revisar, "
        f"{r['por_severidad'][INFORMATIVA]} informativas); "
        f"{r['skipped']} reglas omitidas."
    )
    for a in inf["alertas"]:
        amb = a["ambito"]
        ref = amb.get("denominacion") or amb.get("seccion_cod")
        echo(
            f"[{(a['severidad'] or '').upper():<10}] {a['tipo']:<26} {ref} "
            f"({a['naturaleza']}, confianza {a['confianza']}) — {a['contexto']}"
        )


def a_json(inf: dict[str, Any]) -> str:
    return json.dumps(inf, ensure_ascii=False, indent=2, default=str)
