"""Tests de la carga BDNS en el warehouse: upsert "última foto" e integración.

Semántica a fijar (docs/bdns_estructura.md §6): recargar el mismo raw es
idempotente; una corrección republicada con el mismo ``concesion_id`` pisa la
foto anterior; ``build``/``update`` descubren las capturas de raw y solo
cargan las pendientes.
"""

import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from gasto_estado.db import load
from gasto_estado.parsers.bdns import parse_captura
from gasto_estado.transform.anclaje_organico import anclar_concesiones

FIXTURES = Path(__file__).parent / "fixtures"
PAGINAS = [
    FIXTURES / "bdns_concesiones_page1.json",
    FIXTURES / "bdns_concesiones_page2.json",
]

# Dimensiones sintéticas mínimas (la lógica fina del anclaje tiene sus propios
# tests): solo la DG de Programas Industriales de la muestra ancla a servicio.
_DIM = pd.DataFrame(
    [
        ("E05231501", None, "MN", "Ministerio de Industria y Turismo", 1, "E05231501"),
        (
            "E05248501",
            "E05231501",
            "MN",
            "Dirección General de Programas Industriales",
            3,
            "E05231501",
        ),
    ],
    columns=[
        "dir3_cod",
        "dir3_padre_cod",
        "tipo_entidad",
        "denominacion",
        "nivel_jerarquico",
        "ministerio_dir3_cod",
    ],
)
_DIM["fecha_inicio"] = pd.Timestamp("2000-01-01")
_DIM["fecha_fin"] = pd.NaT
_CROSSWALK = pd.DataFrame(
    [(2026, "20", "10", "E05248501")],
    columns=["ejercicio", "seccion_cod", "servicio_cod", "dir3_cod"],
)


def _anclado(
    paginas: list[Path] = PAGINAS, fecha_captura: date = date(2026, 6, 13)
) -> pd.DataFrame:
    concesiones = parse_captura(paginas, fecha_captura=fecha_captura)
    return anclar_concesiones(concesiones, _DIM, _CROSSWALK)


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = load.connect(tmp_path / "warehouse.duckdb")
    load.init_schema(connection)
    yield connection
    connection.close()


def test_carga_y_recarga_idempotente(con: duckdb.DuckDBPyConnection) -> None:
    anclado = _anclado()
    assert load.load_concesiones(con, anclado) == 9
    assert load.load_concesiones(con, anclado) == 9  # recarga del mismo raw
    total = con.execute("SELECT count(*) FROM fact_subvenciones").fetchone()[0]
    assert total == 9
    # El anclaje persiste: la DG de Industria quedó atribuida a su servicio.
    filas = con.execute(
        """
        SELECT DISTINCT seccion_cod, servicio_cod, anclaje_tipo FROM fact_subvenciones
        WHERE nivel3 = 'DIRECCIÓN GENERAL DE PROGRAMAS INDUSTRIALES'
        """
    ).fetchall()
    assert filas == [("20", "10", "servicio")]
    # Y los periodos usados existen en dim_periodo (FK del modelo).
    huerfanos = con.execute(
        """
        SELECT count(*) FROM fact_subvenciones s
        LEFT JOIN dim_periodo p USING (periodo) WHERE p.periodo IS NULL
        """
    ).fetchone()[0]
    assert huerfanos == 0


def test_correccion_republicada_pisa_la_foto(con: duckdb.DuckDBPyConnection) -> None:
    # Captura 1: solo la página 1 (importe original …,45 de la concesión).
    load.load_concesiones(con, _anclado([PAGINAS[0]], date(2026, 6, 5)))
    importe = con.execute(
        "SELECT importe FROM fact_subvenciones WHERE concesion_id = '153038882'"
    ).fetchone()[0]
    assert importe == pytest.approx(2421206.45)
    # Captura 2: la página 2 trae la corrección (…,46) con el mismo id.
    load.load_concesiones(con, _anclado([PAGINAS[1]], date(2026, 6, 13)))
    importe, captura = con.execute(
        "SELECT importe, fecha_captura FROM fact_subvenciones WHERE concesion_id = '153038882'"
    ).fetchone()
    assert importe == pytest.approx(2421206.46)
    assert captura.isoformat() == "2026-06-13"
    # 5 (página 1) + 5 (página 2) - 1 republicada = 9 concesiones.
    assert con.execute("SELECT count(*) FROM fact_subvenciones").fetchone()[0] == 9


def test_falla_loud_si_el_lote_no_viene_anclado(con: duckdb.DuckDBPyConnection) -> None:
    sin_anclar = parse_captura(PAGINAS, fecha_captura=date(2026, 6, 13))
    with pytest.raises(ValueError, match="sin anclar"):
        load.load_concesiones(con, sin_anclar)


def test_lote_vacio_devuelve_cero(con: duckdb.DuckDBPyConnection) -> None:
    assert load.load_concesiones(con, _anclado().iloc[0:0]) == 0


# ---------------------------------------------------------------------------
# Integración con build/update (descubrimiento de capturas en raw)
# ---------------------------------------------------------------------------


def _captura_raw(raw_dir: Path, fecha: str, paginas: list[Path]) -> None:
    destino = raw_dir / "bdns" / fecha / "concesiones" / "C_2026-06-01_2026-06-13"
    destino.mkdir(parents=True)
    for num, pagina in enumerate(paginas):
        shutil.copy(pagina, destino / f"page_{num:05d}.json")


def test_build_y_update_descubren_capturas(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    db = tmp_path / "warehouse.duckdb"
    _captura_raw(raw, "2026-06-12", PAGINAS)

    stats = load.build(db, raw)
    assert stats == {"bdns@2026-06-12": 9}

    # Sin capturas nuevas, update no recarga nada.
    assert load.update(db, raw) == {}

    # Una captura posterior se carga incrementalmente (y solo ella).
    _captura_raw(raw, "2026-06-13", [PAGINAS[1]])
    stats = load.update(db, raw)
    assert stats == {"bdns@2026-06-13": 5}

    with duckdb.connect(str(db), read_only=True) as con:
        total = con.execute("SELECT count(*) FROM fact_subvenciones").fetchone()[0]
        assert total == 9  # las 5 concesiones republicadas pisan su foto
        # build/update anclan contra los seeds REALES: la DG de Programas
        # Industriales del fixture debe resolver a un servicio presupuestario.
        tipos = con.execute(
            """
            SELECT DISTINCT anclaje_tipo FROM fact_subvenciones
            WHERE nivel3 = 'DIRECCIÓN GENERAL DE PROGRAMAS INDUSTRIALES'
            """
        ).fetchall()
        assert tipos == [("servicio",)]
        # La concesión autonómica queda etiquetada, nunca descartada.
        navarra = con.execute(
            "SELECT anclaje_tipo FROM fact_subvenciones WHERE nivel1 = 'AUTONOMICA'"
        ).fetchall()
        assert navarra == [("fuera_perimetro",)]
        # La vista de exposición resuelve (anclados y no anclados incluidos).
        expuestos = con.execute("SELECT count(*) FROM v_subvenciones").fetchone()[0]
        assert expuestos == 9
