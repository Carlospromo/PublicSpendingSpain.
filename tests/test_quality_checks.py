"""Tests del motor de validaciones contables (CLAUDE.md §7).

Cada regla activable tiene un test que la hace FAIL deliberadamente. Como la
carga es fail-loud (load_periodo revierte y lanza CoherenceError ante un FAIL),
las corrupciones se inyectan por UPDATE/DDL directo sobre el warehouse, que es
justo el escenario que los checks a posteriori deben cazar.
"""

import json
from pathlib import Path

import duckdb
import pytest

from gasto_estado.db.load import build, init_schema, load_periodo, load_seeds
from gasto_estado.parsers.igae.v2021_plus import TOLERANCIA_CUADRE
from gasto_estado.quality import checks
from gasto_estado.quality.checks import (
    FAIL,
    PASS,
    SKIPPED,
    CoherenceError,
    a_json,
    run_checks,
)
from tests.test_db_load import lote

RAW_REAL = Path(__file__).parent.parent / "data" / "raw"


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    with duckdb.connect(str(tmp_path / "wh.duckdb")) as con:
        init_schema(con)
        load_seeds(con)
        yield con


def _por_regla(resultados: list[checks.CheckResult], cod: str) -> list[checks.CheckResult]:
    return [r for r in resultados if r.regla == cod]


def test_tolerancia_base_coherente_con_el_cuadre_del_parser() -> None:
    """La tolerancia por servicio ES la del cuadre interno del parser (0,5 €)."""
    assert checks.TOLERANCIA_SERVICIO == TOLERANCIA_CUADRE
    assert checks.TOLERANCIA_SERVICIO < checks.TOLERANCIA_SECCION < checks.TOLERANCIA_AGE


# ---------------------------------------------------------------------------
# R1/R2 — pérdida de filas en la capa de exposición
# ---------------------------------------------------------------------------


def test_r1_r2_detectan_perdida_en_la_exposicion(con) -> None:
    load_periodo(con, lote({}, {"programa_cod": "912M"}))
    # Regresión simulada de la capa de exposición: la vista pierde un programa.
    con.execute("CREATE TABLE _snap AS SELECT * FROM v_ejecucion")
    con.execute(
        "CREATE OR REPLACE VIEW v_ejecucion AS SELECT * FROM _snap WHERE programa_cod != '912M'"
    )
    resultados = run_checks(con, ["2026-03"])
    assert [r.estado for r in _por_regla(resultados, "R1")] == [FAIL]
    assert [r.estado for r in _por_regla(resultados, "R2")] == [FAIL]
    assert "descuadre" in _por_regla(resultados, "R1")[0].detalle


# ---------------------------------------------------------------------------
# R3 — ORN ≤ definitivo por bolsa, con propagación de NULL
# ---------------------------------------------------------------------------


def test_r3_detecta_orn_sobre_definitivo_en_los_tres_niveles(con) -> None:
    load_periodo(con, lote())
    con.execute("UPDATE fact_ejecucion SET orn = credito_definitivo * 1000")
    r3 = _por_regla(run_checks(con, ["2026-03"]), "R3")
    assert [r.ambito for r in r3] == ["servicio", "sección", "AGE"]
    assert all(r.estado == FAIL for r in r3)
    assert r3[0].descuadres[0]["servicio_cod"] == "01"


def test_r3_no_inventa_ceros_falsos_con_definitivo_sin_publicar(con) -> None:
    """Bolsa con ORN y definitivo íntegramente '-' (caso real: servicio 50 MRR
    en 2026): no comparable, jamás FAIL contra un cero falso (NULL ≠ 0)."""
    load_periodo(con, lote({"credito_inicial": None, "credito_definitivo": None, "orn": 60.0}))
    r3 = _por_regla(run_checks(con, ["2026-03"]), "R3")
    assert all(r.estado == PASS for r in r3)
    assert "no comparables" in r3[0].detalle


# ---------------------------------------------------------------------------
# R4 — identidad de crédito: derivada activa, explícita SKIPPED
# ---------------------------------------------------------------------------


def test_r4_derivada_pass_y_explicita_skipped(con) -> None:
    load_periodo(con, lote())
    r4 = _por_regla(run_checks(con, ["2026-03"]), "R4")
    estados = {r.ambito: r.estado for r in r4}
    assert estados["derivada (definitivo − inicial)"] == PASS
    assert "+20.00 €" in next(r.detalle for r in r4 if r.estado == PASS)  # 120 − 100
    skipped = next(r for r in r4 if r.estado == SKIPPED)
    assert "modificaciones explícitas" in skipped.detalle
    assert "Cuadros/Anexo II" in skipped.detalle


# ---------------------------------------------------------------------------
# R5 — pagos ≤ ORN: SKIPPED hoy, se activa sola por cobertura
# ---------------------------------------------------------------------------


def test_r5_skipped_con_motivo_y_nunca_pass(con) -> None:
    load_periodo(con, lote())
    (r5,) = _por_regla(run_checks(con, ["2026-03"]), "R5")
    assert r5.estado == SKIPPED
    assert "pagos no disponible en el Anexo I" in r5.detalle


def test_r5_se_activa_cuando_una_fuente_cubre_pagos(con) -> None:
    load_periodo(con, lote())
    con.execute("UPDATE fact_ejecucion SET pagos = orn + 1000, cobertura = cobertura || ',pagos'")
    (r5,) = _por_regla(run_checks(con, ["2026-03"]), "R5")
    assert r5.estado == FAIL
    assert r5.descuadres[0]["pagos"] == pytest.approx(1060.0)


# ---------------------------------------------------------------------------
# R6 — huérfanos orgánicos (red de seguridad si el esquema pierde la FK)
# ---------------------------------------------------------------------------


def test_r6_detecta_ancla_huerfana(con) -> None:
    load_periodo(con, lote())
    # Simula un warehouse degradado: el hecho perdió la FK y un dato corrupto
    # entró por otra vía — el escenario que la red de seguridad debe cazar.
    con.execute("CREATE TABLE _fact_sin_fk AS SELECT * FROM fact_ejecucion")
    con.execute("DROP TABLE fact_ejecucion")
    con.execute("ALTER TABLE _fact_sin_fk RENAME TO fact_ejecucion")
    con.execute("UPDATE fact_ejecucion SET ejercicio = 1999")
    (r6,) = _por_regla(run_checks(con, ["2026-03"]), "R6")
    assert r6.estado == FAIL
    assert r6.descuadres[0]["ejercicio"] == 1999


# ---------------------------------------------------------------------------
# R7 — signos por magnitud y nivel
# ---------------------------------------------------------------------------


def test_r7_detecta_negativos_donde_corresponde(con) -> None:
    load_periodo(con, lote({}, {"programa_cod": "912M"}))
    con.execute("UPDATE fact_ejecucion SET credito_inicial = -5 WHERE programa_cod = '911O'")
    con.execute("UPDATE fact_ejecucion SET orn = -3 WHERE programa_cod = '912M'")
    estados = {r.ambito: r.estado for r in _por_regla(run_checks(con, ["2026-03"]), "R7")}
    assert estados["crédito inicial ≥ 0 (aplicación)"] == FAIL
    assert estados["ORN ≥ 0 (aplicación)"] == FAIL
    assert estados["crédito definitivo ≥ 0 (servicio = bolsa)"] == PASS


def test_r7_definitivo_negativo_en_aplicacion_es_legitimo_si_la_bolsa_no_lo_es(con) -> None:
    """Regresión del caso real 2017-11 (−20.000 € en 18.05.322L.22000): el
    negativo en la aplicación es redistribución dentro de la bolsa; solo
    falla si la bolsa entera (servicio) queda en negativo."""
    load_periodo(con, lote({"credito_definitivo": 100000.0}, {"programa_cod": "912M"}))
    con.execute("UPDATE fact_ejecucion SET credito_definitivo = -20000 WHERE programa_cod = '912M'")
    estados = {r.ambito: r.estado for r in _por_regla(run_checks(con, ["2026-03"]), "R7")}
    assert estados["crédito definitivo ≥ 0 (servicio = bolsa)"] == PASS

    con.execute(
        "UPDATE fact_ejecucion SET credito_definitivo = -200000 WHERE programa_cod = '912M'"
    )
    estados = {r.ambito: r.estado for r in _por_regla(run_checks(con, ["2026-03"]), "R7")}
    assert estados["crédito definitivo ≥ 0 (servicio = bolsa)"] == FAIL


# ---------------------------------------------------------------------------
# R8 — continuidad intra-ejercicio del acumulado
# ---------------------------------------------------------------------------


def test_r8_primer_periodo_del_ejercicio_sale_skipped(con) -> None:
    load_periodo(con, lote())
    (r8,) = _por_regla(run_checks(con, ["2026-03"]), "R8")
    assert r8.estado == SKIPPED
    assert "primer periodo" in r8.detalle


def test_r8_detecta_orn_acumulada_decreciente(con) -> None:
    load_periodo(con, lote())
    load_periodo(con, lote({"periodo": "2026-04", "orn": 80.0}))
    con.execute("UPDATE fact_ejecucion SET orn = 10 WHERE periodo = '2026-04'")
    (r8,) = _por_regla(run_checks(con, ["2026-04"]), "R8")
    assert r8.estado == FAIL
    assert r8.descuadres[0]["orn_anterior"] == 60.0
    assert r8.descuadres[0]["orn_actual"] == 10.0


# ---------------------------------------------------------------------------
# Fail loud en la carga: transacción que revierte el periodo descuadrado
# ---------------------------------------------------------------------------


def test_carga_descuadrada_se_revierte_entera(con) -> None:
    load_periodo(con, lote())
    with pytest.raises(CoherenceError, match="2026-04"):
        load_periodo(con, lote({"periodo": "2026-04", "orn": 5.0}))  # acumulado decrece
    assert con.execute(
        "SELECT count(*) FROM fact_ejecucion WHERE periodo = '2026-04'"
    ).fetchone() == (0,)
    # El rollback alcanza también a las dimensiones del periodo fallido.
    assert con.execute("SELECT count(*) FROM dim_periodo WHERE periodo = '2026-04'").fetchone() == (
        0,
    )


def test_recarga_descuadrada_conserva_la_version_buena_anterior(con) -> None:
    """Mecanismo transacción (no cuarentena): la recarga fallida de una
    revisión IGAE deja intacta la versión buena ya cargada del periodo."""
    load_periodo(con, lote())
    load_periodo(con, lote({"periodo": "2026-04", "orn": 80.0}))
    with pytest.raises(CoherenceError):
        load_periodo(con, lote({"periodo": "2026-04", "orn": 5.0}))
    assert con.execute("SELECT orn FROM fact_ejecucion WHERE periodo = '2026-04'").fetchone() == (
        80.0,
    )


def test_carga_con_inicial_cambiante_intra_ejercicio_falla(con) -> None:
    load_periodo(con, lote())
    with pytest.raises(CoherenceError, match="R8"):
        load_periodo(con, lote({"periodo": "2026-04", "credito_inicial": 999.0, "orn": 80.0}))


# ---------------------------------------------------------------------------
# Motor e informes
# ---------------------------------------------------------------------------


def test_periodo_no_cargado_es_error(con) -> None:
    load_periodo(con, lote())
    with pytest.raises(ValueError, match="1999-01"):
        run_checks(con, ["1999-01"])


def test_informe_json_es_estructurado(con) -> None:
    load_periodo(con, lote())
    informe = json.loads(a_json(run_checks(con, ["2026-03"])))
    assert {r["regla"] for r in informe} >= {"R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"}
    assert all(
        set(r) == {"regla", "nombre", "periodo", "ambito", "estado", "detalle", "descuadres"}
        for r in informe
    )
    assert {r["estado"] for r in informe} <= {PASS, FAIL, SKIPPED}


# ---------------------------------------------------------------------------
# Comando check: códigos de salida e informe JSON
# ---------------------------------------------------------------------------


def test_cli_check_codigos_de_salida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings
    from typer.testing import CliRunner

    from gasto_estado.cli import app

    db = tmp_path / "wh.duckdb"
    with duckdb.connect(str(db)) as con:
        init_schema(con)
        load_seeds(con)
        load_periodo(con, lote())
    monkeypatch.chdir(Path(__file__).parent.parent)
    monkeypatch.setattr(settings, "WAREHOUSE_PATH", db)
    runner = CliRunner()

    informe = tmp_path / "informe.json"
    verde = runner.invoke(app, ["check", "--json", str(informe)])
    assert verde.exit_code == 0, verde.output
    assert "0 FAIL" in verde.output
    assert json.loads(informe.read_text(encoding="utf-8"))

    desconocido = runner.invoke(app, ["check", "--periodo", "1999-01"])
    assert desconocido.exit_code == 1
    assert "1999-01" in desconocido.output

    with duckdb.connect(str(db)) as con:
        con.execute("UPDATE fact_ejecucion SET orn = credito_definitivo * 1000")
    rojo = runner.invoke(app, ["check"])
    assert rojo.exit_code == 1
    assert "FAIL" in rojo.output


# ---------------------------------------------------------------------------
# Aceptación: los 8 periodos reales pasan en verde
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not RAW_REAL.is_dir(), reason="raw real no disponible")
def test_los_periodos_reales_pasan_en_verde(tmp_path: Path) -> None:
    """Valida que el 28,5 %–95,9 % de ejecución observado no esconde
    descuadres. build ya es fail-loud, así que terminar es media prueba; el
    informe completo confirma 0 FAIL y las SKIPPED con motivo."""
    stats = build(tmp_path / "wh.duckdb", RAW_REAL)
    assert len(stats) >= 8
    with duckdb.connect(str(tmp_path / "wh.duckdb"), read_only=True) as con:
        resultados = run_checks(con)
    contadores = checks.resumen(resultados)
    assert contadores[FAIL] == 0
    assert contadores[PASS] > 0
    pendientes = [r for r in resultados if r.estado == SKIPPED and r.regla == "R5"]
    # stats mezcla fuentes desde la Fase 4 ("YYYY-MM" para IGAE,
    # "fuente@captura" para PLACSP/BDNS); R5 solo aplica a periodos IGAE.
    periodos_igae = [clave for clave in stats if "@" not in clave]
    assert len(pendientes) == len(periodos_igae)
    assert all("Cuadros/Anexo II" in r.detalle for r in pendientes)
    # 2026 tiene dos periodos: R8 debe haberse contrastado de verdad.
    r8_2026_04 = next(r for r in resultados if r.regla == "R8" and r.periodo == "2026-04")
    assert r8_2026_04.estado == PASS
