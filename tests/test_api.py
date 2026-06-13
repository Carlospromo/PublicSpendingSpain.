"""Tests de la API de exposición (Fase 6) sobre el warehouse real cargado.

Verifica que cada endpoint responde con su modelo; que los metadatos de
fiabilidad (naturaleza/confianza/cobertura/frescura) se PROPAGAN intactos; que el
árbol orgánico respeta vigencia (DG aproximada fuera de 2026); que las alertas
llegan con evidencias; que los filtros y los cruces funcionan; que salud refleja
el estado real; que los errores devuelven códigos correctos; y —clave— que la API
NO reimplementa lógica: sus valores coinciden con los de las funciones puras.
"""

from __future__ import annotations

import shutil
import warnings
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from gasto_estado.analytics import alerts, metrics
from gasto_estado.api.app import create_app
from gasto_estado.db import load as db_load

warnings.filterwarnings("ignore")  # StarletteDeprecationWarning (httpx en TestClient)
from fastapi.testclient import TestClient  # noqa: E402

RAW_REAL = Path(__file__).parent.parent / "data" / "raw"
FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not (RAW_REAL / "igae_mensual").is_dir() or not (RAW_REAL / "placsp").is_dir(),
    reason="raw real (IGAE/PLACSP) no disponible",
)


def _construir_warehouse(base: Path) -> Path:
    raw = base / "raw"
    raw.mkdir()
    shutil.copytree(RAW_REAL / "igae_mensual", raw / "igae_mensual")
    shutil.copytree(RAW_REAL / "placsp", raw / "placsp")
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
    cdm = raw / "consejo_ministros" / "2026-06-13" / "20260609"
    cdm.mkdir(parents=True)
    shutil.copy(FIXTURES / "consejo_referencia_2026.html", cdm / "referencia.html")
    db = base / "wh.duckdb"
    db_load.build(db, raw)
    return db


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _construir_warehouse(tmp_path_factory.mktemp("api"))


@pytest.fixture(scope="module")
def client(warehouse: Path) -> Iterator[TestClient]:
    from config import settings

    original = settings.WAREHOUSE_PATH
    settings.WAREHOUSE_PATH = warehouse
    try:
        with TestClient(create_app()) as c:
            yield c
    finally:
        settings.WAREHOUSE_PATH = original


@pytest.fixture(scope="module")
def con(warehouse: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect(str(warehouse), read_only=True) as conn:
        yield conn


# ---------------------------------------------------------------------------
# Estructura y navegación
# ---------------------------------------------------------------------------


def test_salud_refleja_estado_real(client: TestClient) -> None:
    r = client.get("/salud")
    assert r.status_code == 200
    js = r.json()
    assert js["accesible"] is True
    assert js["n_periodos_igae"] == 8
    assert 2026 in js["ejercicios"]


def test_frescura_por_fuente(client: TestClient) -> None:
    js = client.get("/frescura").json()
    fuentes = {f["fuente_cod"]: f for f in js}
    assert fuentes["igae_anexo_i"]["ultima_actualizacion"] is not None
    assert fuentes["igae_anexo_i"]["periodo_cubierto"][1] == "2026-04"
    assert fuentes["consejo_ministros"]["n_filas"] > 0  # se cargó el fixture


def test_arbol_organico_respeta_vigencia_dg(client: TestClient) -> None:
    # 2026: equivalencia DG exacta. 2015: aproximada (estructura 2026), con nota.
    s26 = client.get("/estructura/secciones/16/servicios?ejercicio=2026").json()
    con_dg26 = next(s for s in s26 if s["dg_dir3_cod"])
    assert con_dg26["dg_equivalencia_aproximada"] is False
    s15 = client.get("/estructura/secciones/16/servicios?ejercicio=2015").json()
    con_dg15 = next(s for s in s15 if s["dg_dir3_cod"])
    assert con_dg15["dg_equivalencia_aproximada"] is True
    assert "aproximada" in con_dg15["dg_nota"]


def test_catalogos(client: TestClient) -> None:
    assert len(client.get("/catalogos/programas").json()) > 0
    assert len(client.get("/catalogos/economicas").json()) > 0
    fuentes = client.get("/catalogos/fuentes").json()
    assert {"velocidad", "periodicidad"} <= set(fuentes[0])


# ---------------------------------------------------------------------------
# Datos por velocidad + propagación de metadatos
# ---------------------------------------------------------------------------


def test_grado_propaga_naturaleza_y_frescura(client: TestClient) -> None:
    js = client.get("/ejecucion/grado?periodo=2026-04&nivel=AGE").json()
    assert js["naturaleza"] == "exacta"
    assert js["frescura"]["ultima_actualizacion"] is not None
    assert round(js["data"][0]["pct_ejecucion"], 1) == 28.5


def test_grado_dg_propaga_cobertura(client: TestClient) -> None:
    js = client.get("/ejecucion/grado?periodo=2026-04&nivel=dg").json()
    assert js["cobertura_anclaje"]["pct_atribuida"] is not None


def test_contratos_volumen_propaga_anclaje(client: TestClient) -> None:
    js = client.get("/contratos/volumen?ejercicio=2026&nivel=seccion").json()
    assert "pct_anclado_a_servicio" in js["cobertura_anclaje"]


def test_decisiones_cdm_aproximada_con_confianza(client: TestClient) -> None:
    js = client.get("/decisiones/cdm/volumen?nivel=ministerio").json()
    assert js["naturaleza"] == "aproximada"
    assert any("importe_alta" in fila for fila in js["data"])


def test_cruce_indiciario_expone_ambas_magnitudes(client: TestClient) -> None:
    js = client.get("/cruces/compromiso-ejecucion?periodo=2026-04&nivel=seccion").json()
    assert js["naturaleza"] == "indiciaria"
    assert {"orn", "adjudicado", "ratio_adjudicado_orn"} <= set(js["data"][0])


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------


def test_informe_alertas_y_cobertura(client: TestClient) -> None:
    js = client.get("/alertas/informe?periodo=2020-11").json()
    assert js["resumen"]["alertas"] >= 1
    assert js["cobertura_global"]["pct_orn_vigilable_a_nivel_dg"] is not None
    assert all(a["evidencias"] for a in js["alertas"])  # cada alerta enlaza evidencias


def test_alertas_filtrables(client: TestClient) -> None:
    ritmo = client.get("/alertas?periodo=2020-11&tipo=ritmo_ejecucion").json()
    assert ritmo and all(a["tipo"] == "ritmo_ejecucion" for a in ritmo)
    contable = client.get("/alertas?periodo=2020-11&velocidad=contable").json()
    assert all(a["tipo"] in ("ritmo_ejecucion", "modificacion_atipica") for a in contable)
    assert client.get("/alertas?periodo=2020-11&velocidad=xxx").status_code == 422


# ---------------------------------------------------------------------------
# Errores y contrato
# ---------------------------------------------------------------------------


def test_errores_codigos_correctos(client: TestClient) -> None:
    assert client.get("/ejecucion/grado?periodo=1999-01").status_code == 404  # periodo no cargado
    assert client.get("/ejecucion/grado?periodo=2026-04&nivel=xxx").status_code == 422  # nivel
    assert client.get("/ejecucion/grado?periodo=2026").status_code == 422  # malformado
    assert client.get("/decisiones/zzz/volumen").status_code == 404  # fuente desconocida
    assert client.get("/estructura/secciones?ejercicio=1999").status_code == 422  # < ge=2000
    assert client.get("/estructura/secciones?ejercicio=2099").status_code == 404  # no cargado


def test_openapi_se_genera(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "gasto-estado API"
    assert "/ejecucion/grado" in schema["paths"]


def test_warehouse_ausente_responde_503_y_salud_false(tmp_path: Path) -> None:
    from config import settings

    original = settings.WAREHOUSE_PATH
    settings.WAREHOUSE_PATH = tmp_path / "no_existe.duckdb"
    try:
        with TestClient(create_app()) as c:
            assert c.get("/salud").json()["accesible"] is False
            assert c.get("/ejecucion/grado?periodo=2026-04").status_code == 503
    finally:
        settings.WAREHOUSE_PATH = original


# ---------------------------------------------------------------------------
# La API NO reimplementa lógica: coincide con las funciones puras
# ---------------------------------------------------------------------------


def test_api_no_reimplementa_metricas(client: TestClient, con: duckdb.DuckDBPyConnection) -> None:
    api = client.get("/ejecucion/grado?periodo=2026-04&nivel=seccion").json()
    puro = metrics.grado_ejecucion(con, "2026-04", nivel="seccion")
    assert api["naturaleza"] == puro.naturaleza
    assert len(api["data"]) == len(puro.data)
    api_por_sec = {d["seccion_cod"]: d["orn"] for d in api["data"]}
    for fila in puro.data.to_dict("records"):
        esperado = fila["orn"]
        obtenido = api_por_sec[fila["seccion_cod"]]
        if esperado is None or (isinstance(esperado, float) and esperado != esperado):
            assert obtenido is None  # NaN del DataFrame → null en JSON
        else:
            assert obtenido == pytest.approx(esperado, rel=1e-9)


def test_api_no_reimplementa_alertas(client: TestClient, con: duckdb.DuckDBPyConnection) -> None:
    api = client.get("/alertas?periodo=2020-11").json()
    puro = [a for a in alerts.run_alerts(con, ["2020-11"]) if a.estado == alerts.ALERTA]
    assert len(api) == len(puro)
    assert {a["tipo"] for a in api} == {a.tipo for a in puro}
