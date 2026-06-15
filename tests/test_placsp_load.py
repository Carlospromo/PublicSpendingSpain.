"""Tests de la carga PLACSP en el warehouse: upsert "última foto" e integración.

La semántica a fijar (docs/placsp_estructura.md §5): recargar el mismo raw es
idempotente; una republicación borra el bloque ENTERO de la licitación (sin
filas-lote zombis); ``build``/``update`` descubren las capturas de raw y solo
cargan las pendientes.
"""

import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from gasto_estado.db import load
from gasto_estado.parsers.placsp import parse_captura
from gasto_estado.transform.placsp_anclaje import anclar_contratos

FIXTURES = Path(__file__).parent / "fixtures"
PAGINAS = [FIXTURES / "placsp_643_page1.atom", FIXTURES / "placsp_643_page2.atom"]

# Dimensiones sintéticas mínimas (la lógica fina del anclaje tiene sus propios
# tests): solo la DG del MAPA de la muestra real ancla a servicio.
_DIM = pd.DataFrame(
    [("E05024401", None, "MN", pd.Timestamp("2000-01-01"), pd.NaT)],
    columns=["dir3_cod", "dir3_padre_cod", "tipo_entidad", "fecha_inicio", "fecha_fin"],
)
_CROSSWALK = pd.DataFrame(
    [(2026, "21", "01", "E05024401")],
    columns=["ejercicio", "seccion_cod", "servicio_cod", "dir3_cod"],
)


def _anclado(fecha_captura: date = date(2026, 6, 11)) -> pd.DataFrame:
    contratos = parse_captura(PAGINAS, fecha_captura=fecha_captura)
    return anclar_contratos(contratos, _DIM, _CROSSWALK)


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = load.connect(tmp_path / "warehouse.duckdb")
    load.init_schema(connection)
    yield connection
    connection.close()


def test_carga_y_recarga_idempotente(con: duckdb.DuckDBPyConnection) -> None:
    anclado = _anclado()
    assert load.load_contratos(con, anclado) == 8
    assert load.load_contratos(con, anclado) == 8  # recarga del mismo raw
    total, licitaciones = con.execute(
        "SELECT count(*), count(DISTINCT licitacion_id) FROM fact_contratos"
    ).fetchone()
    assert (total, licitaciones) == (8, 6)
    # El anclaje persiste: la DG del MAPA quedó atribuida a su servicio.
    fila = con.execute(
        """
        SELECT seccion_cod, servicio_cod, anclaje_tipo FROM fact_contratos
        WHERE licitacion_id = '19663725'
        """
    ).fetchone()
    assert fila == ("21", "01", "servicio")
    # Y los periodos usados existen en dim_periodo (FK del modelo).
    huerfanos = con.execute(
        """
        SELECT count(*) FROM fact_contratos c
        LEFT JOIN dim_periodo p USING (periodo) WHERE p.periodo IS NULL
        """
    ).fetchone()[0]
    assert huerfanos == 0


def test_republicacion_con_menos_lotes_no_deja_zombis(
    con: duckdb.DuckDBPyConnection,
) -> None:
    load.load_contratos(con, _anclado())
    # Foto nueva de la licitación multi-lote: PLACSP la republica con UN lote.
    anclado = _anclado(fecha_captura=date(2026, 6, 12))
    refoto = anclado[(anclado["licitacion_id"] == "19046011") & (anclado["lote_id"] == "1")].assign(
        fecha_actualizacion=date(2026, 6, 12)
    )
    assert load.load_contratos(con, refoto) == 1
    lotes = con.execute(
        "SELECT lote_id FROM fact_contratos WHERE licitacion_id = '19046011'"
    ).fetchall()
    assert lotes == [("1",)]  # los lotes 3 y 4 de la foto vieja desaparecen
    # El resto de licitaciones queda intacto.
    assert con.execute("SELECT count(*) FROM fact_contratos").fetchone()[0] == 6


def test_falla_loud_si_el_lote_no_viene_anclado(con: duckdb.DuckDBPyConnection) -> None:
    sin_anclar = parse_captura(PAGINAS, fecha_captura=date(2026, 6, 11))
    with pytest.raises(ValueError, match="sin anclar"):
        load.load_contratos(con, sin_anclar)


def test_lote_vacio_devuelve_cero(con: duckdb.DuckDBPyConnection) -> None:
    assert load.load_contratos(con, _anclado().iloc[0:0]) == 0


# ---------------------------------------------------------------------------
# Integración con build/update (descubrimiento de capturas en raw)
# ---------------------------------------------------------------------------


def _captura_raw(raw_dir: Path, fecha: str, paginas: list[Path]) -> None:
    destino = raw_dir / "placsp" / fecha / "643" / "incremental"
    destino.mkdir(parents=True)
    for pagina in paginas:
        shutil.copy(pagina, destino / pagina.name)


def test_build_y_update_descubren_capturas(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    db = tmp_path / "warehouse.duckdb"
    _captura_raw(raw, "2026-06-11", PAGINAS)

    stats = load.build(db, raw)
    assert stats == {"placsp@2026-06-11": 8}

    # Sin capturas nuevas, update no recarga nada.
    assert load.update(db, raw) == {}

    # Una captura posterior se carga incrementalmente (y solo ella).
    _captura_raw(raw, "2026-06-12", [PAGINAS[1]])
    stats = load.update(db, raw)
    assert stats == {"placsp@2026-06-12": 3}

    with duckdb.connect(str(db), read_only=True) as con:
        total = con.execute("SELECT count(*) FROM fact_contratos").fetchone()[0]
        assert total == 8  # las 3 licitaciones republicadas pisan su foto
        capturas = con.execute(
            "SELECT DISTINCT fecha_captura FROM fact_contratos ORDER BY 1"
        ).fetchall()
        assert {c[0].isoformat() for c in capturas} == {"2026-06-11", "2026-06-12"}
        # La vista de exposición resuelve (anclados y no anclados incluidos).
        expuestos = con.execute("SELECT count(*) FROM v_contratos").fetchone()[0]
        assert expuestos == 8
