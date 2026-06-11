"""Tests de la carga idempotente del warehouse (Fase 3).

Cubren la semántica documentada en docs/modelo_datos.md §5: reemplazo de
partición por (periodo, fuente), dimensiones resolver-o-derivar con fail loud,
y build/update extremo a extremo sobre un raw sintético construido con el
fixture real del Anexo I.
"""

import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from gasto_estado.db import load as db_load
from gasto_estado.db.load import (
    OrphanOrganicError,
    build,
    discover_periodos,
    init_schema,
    load_periodo,
    load_seeds,
    update,
)

FIXTURE_ANEXO_I = Path(__file__).parent / "fixtures" / "igae_anexo_i_muestra.xlsx"
CAPTURA = date(2026, 6, 11)

_FILA_BASE = {
    "periodo": "2026-03",
    "fuente": "igae_anexo_i",
    "fecha_captura": CAPTURA,
    "seccion_cod": "01",
    "servicio_cod": "01",
    "servicio_denominacion": "CASA DE SU MAJESTAD EL REY",
    "programa_cod": "911O",
    "provincia_cod": None,
    "economica_cod": "22706",
    "aplicacion_denominacion": "Estudios y trabajos técnicos",
    "credito_inicial": 100.0,
    "credito_definitivo": 120.0,
    "orn": 60.0,
}


def lote(*filas: dict) -> pd.DataFrame:
    """Lote canónico mínimo válido contra ``igae_anexo_i_schema``."""
    df = pd.DataFrame([{**_FILA_BASE, **fila} for fila in (filas or ({},))])
    for col in ("provincia_cod", "servicio_denominacion"):
        df[col] = df[col].astype("str")
    for col in ("credito_inicial", "credito_definitivo", "orn"):
        df[col] = df[col].astype("float64")
    return df


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    with duckdb.connect(str(tmp_path / "wh.duckdb")) as con:
        init_schema(con)
        load_seeds(con)
        yield con


def _facts(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "SELECT * FROM fact_ejecucion ORDER BY periodo, seccion_cod, servicio_cod, "
        "programa_cod, economica_cod, provincia_cod"
    ).df()


# ---------------------------------------------------------------------------
# load_periodo: hechos y dimensiones
# ---------------------------------------------------------------------------


def test_carga_hechos_con_cobertura_y_provincia_materializada(con) -> None:
    assert load_periodo(con, lote()) == 1
    fila = _facts(con).iloc[0]
    # NULL del parser materializado como valor categórico de la clave.
    assert fila["provincia_cod"] == "NT"
    assert fila["cobertura"] == "credito_inicial,credito_definitivo,orn"
    assert fila["ejercicio"] == 2026
    # Magnitudes no cubiertas por el Anexo I: NULL, nunca ceros falsos.
    for col in ("pagos", "comprometido", "modificaciones"):
        assert pd.isna(fila[col])


def test_dim_periodo_toma_presupuesto_del_seed_solo_si_cubre_el_ejercicio(con) -> None:
    load_periodo(con, lote())  # 2026: seed PGE presente -> '2025-P' (prórroga)
    load_periodo(con, lote({"periodo": "2015-12", "seccion_cod": "12", "servicio_cod": "03"}))
    periodos = dict(con.execute("SELECT periodo, presupuesto FROM dim_periodo").fetchall())
    assert periodos == {"2026-03": "2025-P", "2015-12": None}


def test_resuelve_contra_seed_y_deriva_sin_seed(con) -> None:
    load_periodo(con, lote())  # (2026, 01, 01) está en el seed PGE
    load_periodo(
        con,
        lote(
            {
                "periodo": "2015-12",
                "seccion_cod": "12",
                "servicio_cod": "03",
                "servicio_denominacion": "SECRETARÍA DE ESTADO DE COOPERACIÓN",
            }
        ),
    )
    origenes = dict(
        con.execute(
            "SELECT ejercicio, origen FROM dim_seccion_servicio "
            "WHERE (ejercicio, seccion_cod, servicio_cod) IN ((2026,'01','01'),(2015,'12','03'))"
        ).fetchall()
    )
    assert origenes == {2026: "seed_pge", 2015: "derivado_igae"}
    derivada = con.execute(
        "SELECT seccion_denominacion, servicio_denominacion, presupuesto "
        "FROM dim_seccion_servicio WHERE ejercicio = 2015"
    ).fetchone()
    # La derivada solo conoce lo que trae el Anexo I: nombre del servicio.
    assert derivada == (None, "SECRETARÍA DE ESTADO DE COOPERACIÓN", None)


def test_fail_loud_ante_ancla_organica_sin_nombre(con) -> None:
    huerfano = lote(
        {
            "periodo": "2015-12",
            "seccion_cod": "99",
            "servicio_cod": "99",
            "servicio_denominacion": None,
        }
    )
    with pytest.raises(OrphanOrganicError, match="2015/99.99"):
        load_periodo(con, huerfano)
    assert con.execute("SELECT count(*) FROM fact_ejecucion").fetchone()[0] == 0


def test_economica_sintetiza_ancestros_y_denominacion_modal(con) -> None:
    load_periodo(
        con,
        lote(
            {"economica_cod": "22706", "aplicacion_denominacion": "Estudios y trabajos técnicos"},
            {
                "programa_cod": "912M",
                "economica_cod": "22706",
                "aplicacion_denominacion": "Estudios y trabajos técnicos",
            },
            {
                "programa_cod": "912N",
                "economica_cod": "22706",
                "aplicacion_denominacion": "Otros trabajos",
            },
        ),
    )
    filas = dict(
        con.execute(
            "SELECT economica_cod, struct_pack(nivel, denominacion, denominacion_origen) "
            "FROM dim_economica WHERE economica_cod IN ('2', '22', '22706')"
        ).fetchall()
    )
    # Modal determinista de aplicacion_denominacion (2 frente a 1).
    assert filas["22706"] == {
        "nivel": "subconcepto",
        "denominacion": "Estudios y trabajos técnicos",
        "denominacion_origen": "derivado_anexo_i",
    }
    # Ancestro artículo sintetizado, sin denominación propia.
    assert filas["22"] == {"nivel": "articulo", "denominacion": None, "denominacion_origen": None}
    # El catálogo estático de capítulos nunca se pisa.
    assert filas["2"]["denominacion_origen"] == "catalogo_estatico"


# ---------------------------------------------------------------------------
# Idempotencia y reemplazo de partición
# ---------------------------------------------------------------------------


def test_recargar_el_mismo_lote_es_idempotente(con) -> None:
    datos = lote({}, {"programa_cod": "912M"})
    load_periodo(con, datos)
    antes = _facts(con)
    load_periodo(con, datos)
    pd.testing.assert_frame_equal(_facts(con), antes)


def test_recarga_reemplaza_la_particion_sin_tocar_otras(con) -> None:
    load_periodo(con, lote({}, {"programa_cod": "912M", "orn": 10.0}))
    load_periodo(con, lote({"periodo": "2026-04", "orn": 80.0}))
    # Revisión de 2026-03: corrige una aplicación y retira la otra.
    load_periodo(con, lote({"orn": 65.0}))
    facts = _facts(con)
    assert facts["periodo"].tolist() == ["2026-03", "2026-04"]
    assert facts["orn"].tolist() == [65.0, 80.0]


def test_load_periodo_rechaza_lotes_mixtos(con) -> None:
    mixto = lote({}, {"periodo": "2026-04"})
    with pytest.raises(ValueError, match="único"):
        load_periodo(con, mixto)


# ---------------------------------------------------------------------------
# build / update extremo a extremo (raw sintético desde el fixture real)
# ---------------------------------------------------------------------------


def _raw_con_periodos(base: Path, periodos: list[str]) -> Path:
    raw = base / "raw"
    for periodo in periodos:
        destino = raw / "igae_mensual" / periodo
        destino.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE_ANEXO_I, destino / f"MENSUAL {periodo} ANEXO I.xlsx")
    return raw


def test_build_y_update_incremental(tmp_path: Path) -> None:
    raw = _raw_con_periodos(tmp_path, ["2026-03", "2026-04"])
    db = tmp_path / "warehouse.duckdb"

    stats = build(db, raw)
    assert list(stats) == ["2026-03", "2026-04"]
    assert all(n > 0 for n in stats.values())

    # Sin periodos nuevos: update no toca nada.
    assert update(db, raw) == {}

    # Periodo nuevo en raw: update carga SOLO ese.
    _raw_con_periodos(tmp_path, ["2026-05"])
    assert list(update(db, raw)) == ["2026-05"]

    with duckdb.connect(str(db)) as con:
        # "Último dato disponible" = periodo máximo del ejercicio.
        vigente = con.execute("SELECT DISTINCT periodo FROM v_ejecucion_vigente").fetchall()
        assert vigente == [("2026-05",)]
        # La vista desnormalizada no pierde filas: el ancla orgánica resuelve.
        assert (
            con.execute("SELECT count(*) FROM v_ejecucion").fetchone()
            == con.execute("SELECT count(*) FROM fact_ejecucion").fetchone()
        )


def test_build_es_reproducible(tmp_path: Path) -> None:
    raw = _raw_con_periodos(tmp_path, ["2026-03"])
    db = tmp_path / "warehouse.duckdb"
    build(db, raw)
    with duckdb.connect(str(db)) as con:
        antes = _facts(con)
    build(db, raw)  # segunda reconstrucción desde cero sobre el mismo raw
    with duckdb.connect(str(db)) as con:
        pd.testing.assert_frame_equal(_facts(con), antes)


def test_discover_periodos_ignora_directorios_ajenos(tmp_path: Path) -> None:
    raw = _raw_con_periodos(tmp_path, ["2026-04", "2026-03"])
    (raw / "igae_mensual" / "indice").mkdir()
    assert discover_periodos(raw) == ["2026-03", "2026-04"]
    assert discover_periodos(tmp_path / "no-existe") == []


def test_modulo_no_depende_de_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """build/update reciben rutas explícitas: utilizables sin config/ en sys.path."""
    monkeypatch.chdir(tmp_path)
    assert db_load.build(tmp_path / "wh.duckdb", tmp_path / "raw") == {}
