"""Tests de carga del warehouse para la tercera velocidad (BOE/CdM, Fase 4).

Verifica que ``build`` puebla fact_boe_disposiciones y fact_acuerdos_cdm
clasificados y anclados a sección, que la carga es idempotente (reconstrucción
y ``update`` no duplican) y que las vistas exponen la denominación de sección
por vigencia. Las dimensiones reutilizan los seeds reales del repo.
"""

import shutil
from pathlib import Path

import duckdb
import pytest

from gasto_estado.db import load as db_load


def _siembra_raw(raw: Path) -> None:
    fix = Path(__file__).parent / "fixtures"
    dia = raw / "boe" / "2026-06-13" / "20240206"
    (dia / "disposiciones").mkdir(parents=True)
    shutil.copy(fix / "boe_sumario_muestra.xml", dia / "sumario.xml")
    shutil.copy(
        fix / "boe_disposicion_subvencion_rd.xml", dia / "disposiciones" / "BOE-A-2024-22930.xml"
    )
    shutil.copy(
        fix / "boe_disposicion_subvencion_extracto.xml",
        dia / "disposiciones" / "BOE-B-2024-3994.xml",
    )
    cdm = raw / "consejo_ministros" / "2026-06-13"
    for sub, src in (
        ("20260609", "consejo_referencia_2026.html"),
        ("20180427", "consejo_referencia_2018.html"),
    ):
        (cdm / sub).mkdir(parents=True)
        shutil.copy(fix / src, cdm / sub / "referencia.html")


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    _siembra_raw(raw)
    db = tmp_path / "warehouse.duckdb"
    db_load.build(db, raw)
    return db


def test_boe_cargado_y_anclado(warehouse: Path) -> None:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        filas = con.execute(
            "SELECT identificador, tipo_disposicion, seccion_cod, anclaje_tipo "
            "FROM fact_boe_disposiciones ORDER BY identificador"
        ).fetchall()
    assert filas == [
        ("BOE-A-2024-22930", "subvencion_directa", "17", "seccion"),
        ("BOE-B-2024-3994", "convocatoria_subvencion", "18", "seccion"),
    ]


def test_cdm_cargado_con_dos_referencias(warehouse: Path) -> None:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        fechas = con.execute(
            "SELECT DISTINCT fecha FROM fact_acuerdos_cdm ORDER BY fecha"
        ).fetchall()
        total = con.execute("SELECT count(*) FROM fact_acuerdos_cdm").fetchone()[0]
    assert [f[0].isoformat() for f in fechas] == ["2018-04-27", "2026-06-09"]
    assert total >= 50


def test_anclaje_seccion_y_no_mapeable_conviven(warehouse: Path) -> None:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        tipos = dict(
            con.execute(
                "SELECT anclaje_tipo, count(*) FROM fact_acuerdos_cdm GROUP BY anclaje_tipo"
            ).fetchall()
        )
    # 2026 ancla a sección; parte de 2018 queda sin mapear: ambas conviven.
    assert tipos["seccion"] > 0
    assert tipos["sin_anclar"] > 0


def test_vista_resuelve_denominacion_por_vigencia(warehouse: Path) -> None:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        # BOE de 2024 (ejercicio sin seed propio): la vista resuelve la
        # denominación con la estructura más cercana (2026).
        denom = con.execute(
            "SELECT seccion_denominacion FROM v_boe_disposiciones "
            "WHERE identificador = 'BOE-A-2024-22930'"
        ).fetchone()[0]
    assert denom == "MINISTERIO DE TRANSPORTES Y MOVILIDAD SOSTENIBLE"


def test_texto_bruto_y_url_conservados(warehouse: Path) -> None:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        fila = con.execute(
            "SELECT url_oficial, texto_bruto FROM fact_acuerdos_cdm "
            "WHERE descripcion LIKE '%Fondo Nacional de Eficiencia%' LIMIT 1"
        ).fetchone()
    assert fila[0].endswith("20260609-referencia-rueda-de-prensa-ministros.aspx")
    assert "168.000.000" in fila[1]


def test_idempotencia_rebuild(warehouse: Path, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    with duckdb.connect(str(warehouse), read_only=True) as con:
        antes_boe = con.execute("SELECT count(*) FROM fact_boe_disposiciones").fetchone()[0]
        antes_cdm = con.execute("SELECT count(*) FROM fact_acuerdos_cdm").fetchone()[0]
    db_load.build(warehouse, raw)
    with duckdb.connect(str(warehouse), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM fact_boe_disposiciones").fetchone()[0] == antes_boe
        assert con.execute("SELECT count(*) FROM fact_acuerdos_cdm").fetchone()[0] == antes_cdm


def test_update_no_recarga_capturas_presentes(warehouse: Path, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    stats = db_load.update(warehouse, raw)
    nuevos = {k: v for k, v in stats.items() if k.startswith(("boe@", "cdm@"))}
    assert nuevos == {}


def test_checks_contables_intactos(warehouse: Path) -> None:
    # Las fuentes de decisiones políticas NO entran en los checks de la Fase 3:
    # el warehouse sin IGAE no produce fallos por su causa.
    from gasto_estado.quality import checks

    with duckdb.connect(str(warehouse), read_only=True) as con:
        resultados = checks.run_checks(con, None)
    assert not [r for r in resultados if r.estado == checks.FAIL]
