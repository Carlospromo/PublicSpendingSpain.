"""Tests de las métricas analíticas (Fase 5) sobre datos reales + fixtures.

Warehouse de prueba = raw real (IGAE + PLACSP) más las muestras de BOE/CdM, de
modo que las cinco fuentes y las tres velocidades estén pobladas. Se verifica:
cifras macro conocidas calculadas por la métrica, cuadre DG↔sección, monotonía
intra-anual, emparejamiento mismo-mes, no doble conteo de compromisos, propagación
de confianza/anclaje, y la marca de aproximación de los cruces.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from gasto_estado.analytics import metrics as m
from gasto_estado.db import load as db_load

RAW_REAL = Path(__file__).parent.parent / "data" / "raw"
FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not (RAW_REAL / "igae_mensual").is_dir() or not (RAW_REAL / "placsp").is_dir(),
    reason="raw real (IGAE/PLACSP) no disponible",
)


@pytest.fixture(scope="module")
def con(tmp_path_factory: pytest.TempPathFactory) -> Iterator[duckdb.DuckDBPyConnection]:
    """Construye una vez el warehouse combinado y cede una conexión read-only."""
    base = tmp_path_factory.mktemp("metrics")
    raw = base / "raw"
    raw.mkdir()
    shutil.copytree(RAW_REAL / "igae_mensual", raw / "igae_mensual")
    shutil.copytree(RAW_REAL / "placsp", raw / "placsp")
    # BOE + Consejo desde fixtures.
    dia = raw / "boe" / "2026-06-13" / "20240206"
    (dia / "disposiciones").mkdir(parents=True)
    shutil.copy(FIXTURES / "boe_sumario_muestra.xml", dia / "sumario.xml")
    shutil.copy(
        FIXTURES / "boe_disposicion_subvencion_rd.xml",
        dia / "disposiciones" / "BOE-A-2024-22930.xml",
    )
    shutil.copy(
        FIXTURES / "boe_disposicion_subvencion_extracto.xml",
        dia / "disposiciones" / "BOE-B-2024-3994.xml",
    )
    cdm = raw / "consejo_ministros" / "2026-06-13"
    for sub, src in (("20260609", "consejo_referencia_2026.html"),):
        (cdm / sub).mkdir(parents=True)
        shutil.copy(FIXTURES / src, cdm / sub / "referencia.html")
    db = base / "wh.duckdb"
    db_load.build(db, raw)
    with duckdb.connect(str(db), read_only=True) as conn:
        yield conn


# ---------------------------------------------------------------------------
# Paso 1 — Ejecución
# ---------------------------------------------------------------------------


def test_grado_ejecucion_macros_conocidas(con: duckdb.DuckDBPyConnection) -> None:
    abril = m.grado_ejecucion(con, "2026-04", nivel="AGE")
    assert abril.naturaleza == m.EXACTA
    assert round(float(abril.data.iloc[0]["pct_ejecucion"]), 1) == 28.5
    dic15 = m.grado_ejecucion(con, "2015-12", nivel="AGE").data.iloc[0]
    assert round(float(dic15["pct_ejecucion"]), 1) == 95.9


def test_grado_ejecucion_seccion_no_se_parte(con: duckdb.DuckDBPyConnection) -> None:
    # Una sección = una fila (agrupar por código, no por denominación).
    sec = m.grado_ejecucion(con, "2026-04", nivel="seccion").data
    assert sec["seccion_cod"].is_unique


def test_dg_cuadra_con_seccion_padre(con: duckdb.DuckDBPyConnection) -> None:
    dg = m.grado_ejecucion(con, "2026-04", nivel="dg").data
    sec = m.grado_ejecucion(con, "2026-04", nivel="seccion").data.set_index("seccion_cod")["orn"]
    por_sec = dg.groupby("seccion_cod")["orn"].sum(min_count=1)  # preserva NaN si todo NaN
    for s, orn in por_sec.items():
        izq = 0.0 if pd.isna(orn) else float(orn)
        der = 0.0 if pd.isna(sec.loc[s]) else float(sec.loc[s])  # sección sin ORN → NaN
        assert abs(izq - der) < 1.0, f"DG no cuadra con sección {s}"
    # Y el total DG conserva el total AGE (dedup del crosswalk sin doble conteo).
    age = float(m.grado_ejecucion(con, "2026-04", nivel="AGE").data.iloc[0]["orn"])
    assert abs(float(dg["orn"].sum()) - age) < 1.0


def test_dg_expone_cobertura_de_anclaje(con: duckdb.DuckDBPyConnection) -> None:
    r = m.grado_ejecucion(con, "2026-04", nivel="dg")
    assert r.cobertura_anclaje is not None
    pct = r.cobertura_anclaje["pct_atribuida"]
    assert 0 < pct < 100  # parte a unidad DIR3, parte residual (deuda/pensiones)


def test_dg_nombra_unidades_reales(con: duckdb.DuckDBPyConnection) -> None:
    dg = m.grado_ejecucion(con, "2026-04", nivel="dg").data
    interior = set(dg[dg["seccion_cod"] == "16"]["dg_denominacion"])
    assert any("Polic" in d for d in interior)


def test_ritmo_intraanual_orn_monotona(con: duckdb.DuckDBPyConnection) -> None:
    # Coherente con R8: el acumulado de ORN no decrece dentro del ejercicio.
    rt = m.ritmo_ejecucion(con, 2026, nivel="AGE").data
    assert rt["orn"].is_monotonic_increasing
    assert len(rt) >= 2


def test_interanual_mismo_mes_empareja(con: duckdb.DuckDBPyConnection) -> None:
    ci = m.comparativa_interanual(con, "2017-11", nivel="AGE")
    fila = ci.data.iloc[0]
    assert fila["orn"] > 0 and fila["orn_prev"] > 0  # 2017-11 vs 2016-11 ambos cargados
    assert "2016-11" in ci.advertencias[0]


def test_interanual_avisa_prorroga_y_sin_dato(con: duckdb.DuckDBPyConnection) -> None:
    ci = m.comparativa_interanual(con, "2026-04", nivel="AGE")
    texto = " ".join(ci.advertencias)
    assert "2025-04" in texto  # sin dato del año anterior
    assert "prórroga" in texto.lower()


def test_modificaciones_derivadas(con: duckdb.DuckDBPyConnection) -> None:
    r = m.modificaciones_credito(con, "2026-04", nivel="seccion")
    assert r.naturaleza == m.EXACTA
    assert any("DERIVADA" in a for a in r.advertencias)
    fila = r.data.iloc[0]
    assert (
        abs(
            float(fila["modificaciones"])
            - (float(fila["credito_definitivo"]) - float(fila["credito_inicial"]))
        )
        < 1e-6
    )


# ---------------------------------------------------------------------------
# Paso 2 — Compromisos
# ---------------------------------------------------------------------------


def test_volumen_adjudicacion_no_doble_cuenta(con: duckdb.DuckDBPyConnection) -> None:
    age = m.volumen_adjudicacion(con, ejercicio=2026, nivel="AGE")
    total_metric = float(age.data.iloc[0]["importe"])
    total_raw = con.execute(
        "SELECT sum(importe_adjudicacion) FROM fact_contratos WHERE ejercicio=2026"
    ).fetchone()[0]
    assert abs(total_metric - float(total_raw)) < 1.0  # aditivo por lote, sin doble conteo


def test_volumen_adjudicacion_expone_cobertura_anclaje(con: duckdb.DuckDBPyConnection) -> None:
    r = m.volumen_adjudicacion(con, ejercicio=2026, nivel="seccion")
    assert r.cobertura_anclaje is not None
    assert "pct_anclado_a_servicio" in r.cobertura_anclaje
    # La suma anclada a sección ≤ importe total (lo no anclado no se imputa).
    anclado = float(r.data["importe"].sum())
    assert anclado <= r.cobertura_anclaje["importe_total"] + 1.0


def test_concentracion_hhi_acotado(con: duckdb.DuckDBPyConnection) -> None:
    cc = m.concentracion_adjudicatarios(con, nivel="servicio", ejercicio=2026).data
    assert (cc["hhi"] >= 0).all() and (cc["hhi"] <= 10000).all()
    assert (cc["top_n_cuota_pct"] <= 100.0 + 1e-6).all()
    # Un órgano con un único adjudicatario → HHI máximo.
    solo = cc[cc["n_adjudicatarios"] == 1]
    if len(solo):
        assert (solo["hhi"] == 10000).all()


# ---------------------------------------------------------------------------
# Paso 3 — Decisiones políticas
# ---------------------------------------------------------------------------


def test_decisiones_cdm_propaga_confianza(con: duckdb.DuckDBPyConnection) -> None:
    r = m.volumen_decisiones(con, "cdm", nivel="ministerio")
    assert r.naturaleza == m.APROXIMADA
    # NO hay un único 'importe' agregado: se desglosa por confianza.
    assert {"importe_alta", "importe_media", "n_sin_importe"} <= set(r.data.columns)
    assert "importe" not in r.data.columns
    hacienda = r.data[(r.data["grupo"] == "Hacienda") & (r.data["tipo"] == "autorizacion_gasto")]
    assert float(hacienda.iloc[0]["importe_alta"]) == 374066110.0


def test_decisiones_boe_clasifica_y_confianza(con: duckdb.DuckDBPyConnection) -> None:
    r = m.volumen_decisiones(con, "boe", nivel="seccion")
    sd = r.data[r.data["tipo"] == "subvencion_directa"].iloc[0]
    assert sd["grupo"] == "17"
    assert float(sd["importe_alta"]) == 1_000_000.0


# ---------------------------------------------------------------------------
# Paso 4 — Cruces (indiciario)
# ---------------------------------------------------------------------------


def test_cruce_compromiso_vs_ejecucion_expone_ambas_y_marca(
    con: duckdb.DuckDBPyConnection,
) -> None:
    r = m.compromiso_vs_ejecucion(con, "2026-04", nivel="seccion")
    assert r.naturaleza == m.INDICIARIA
    assert {"orn", "adjudicado", "ratio_adjudicado_orn"} <= set(r.data.columns)
    assert any("INDICIARIA" in a or "identidad contable" in a for a in r.advertencias)


def test_cruce_decisiones_vs_compromiso_doble_marca(con: duckdb.DuckDBPyConnection) -> None:
    r = m.decisiones_vs_compromiso(con, ejercicio=2026, nivel="seccion")
    assert r.naturaleza == m.INDICIARIA
    assert {"autorizado_cdm", "autorizado_cdm_alta", "adjudicado"} <= set(r.data.columns)
    assert sum("aproximaci" in a.lower() or "INDICIARIA" in a for a in r.advertencias) >= 2


# ---------------------------------------------------------------------------
# Contrato de salida
# ---------------------------------------------------------------------------


def test_toda_metrica_propaga_frescura_y_serializa(con: duckdb.DuckDBPyConnection) -> None:
    resultados = [
        m.grado_ejecucion(con, "2026-04", nivel="servicio"),
        m.ritmo_ejecucion(con, 2026),
        m.volumen_adjudicacion(con, ejercicio=2026),
        m.volumen_decisiones(con, "cdm"),
        m.compromiso_vs_ejecucion(con, "2026-04"),
    ]
    for r in resultados:
        assert r.frescura  # no vacío
        assert r.naturaleza in (m.EXACTA, m.APROXIMADA, m.INDICIARIA)
        # JSON-serializable de punta a punta (contrato de la API/frontal).
        json.dumps(r.to_dict(), default=str)
