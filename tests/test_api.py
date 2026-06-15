"""Tests de la API v1 (contrato + funcionamiento) sobre el warehouse real.

Dos planos: funcional (cada endpoint responde, metadatos propagados, vigencia DG,
filtros, errores) y de CONTRATO (envoltura {data, meta} uniforme con paginación,
enums estables, cuerpo de error uniforme, snapshot del esquema OpenAPI que rompe
si un campo cambia de forma incompatible). Mantiene el test de no-reimplementación:
los valores servidos coinciden con las funciones puras.
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
from gasto_estado.api.models import Naturaleza, Severidad, Velocidad
from gasto_estado.db import load as db_load

warnings.filterwarnings("ignore")  # StarletteDeprecationWarning (httpx en TestClient)
from fastapi.testclient import TestClient  # noqa: E402

RAW_REAL = Path(__file__).parent.parent / "data" / "raw"
FIXTURES = Path(__file__).parent / "fixtures"
V1 = "/v1"

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
# Versionado y envoltura común
# ---------------------------------------------------------------------------


def test_todo_bajo_v1_y_raiz_versionada(client: TestClient) -> None:
    assert client.get("/").json()["version"] == "v1"
    assert client.get("/v1/salud").status_code == 200
    assert client.get("/ejecucion/grado?periodo=2026-04").status_code == 404  # sin /v1 no existe


def test_envoltura_data_meta_en_colecciones(client: TestClient) -> None:
    for url in (
        f"{V1}/estructura/secciones?ejercicio=2026",
        f"{V1}/catalogos/programas",
        f"{V1}/ejecucion/grado?periodo=2026-04&nivel=seccion",
        f"{V1}/contratos/volumen?ejercicio=2026",
        f"{V1}/alertas?periodo=2020-11",
    ):
        js = client.get(url).json()
        assert set(js) == {"data", "meta"}, url
        assert isinstance(js["data"], list)
        pag = js["meta"]["paginacion"]
        assert {"total", "pagina", "tamano", "hay_siguiente"} == set(pag)
        assert js["meta"]["version"] == "v1"


def test_paginacion_funciona(client: TestClient) -> None:
    p1 = client.get(f"{V1}/catalogos/economicas?tamano=10&pagina=1").json()
    p2 = client.get(f"{V1}/catalogos/economicas?tamano=10&pagina=2").json()
    assert len(p1["data"]) == 10
    assert p1["meta"]["paginacion"]["total"] > 20
    assert p1["meta"]["paginacion"]["hay_siguiente"] is True
    assert p1["data"] != p2["data"]  # páginas distintas
    # Límite de tamaño de página → 422.
    assert client.get(f"{V1}/catalogos/economicas?tamano=99999").status_code == 422


def test_meta_transporta_fiabilidad_donde_aplica(client: TestClient) -> None:
    meta = client.get(f"{V1}/ejecucion/grado?periodo=2026-04&nivel=dg").json()["meta"]
    assert meta["naturaleza"] == "exacta"
    assert meta["frescura"]["ultima_actualizacion"] is not None
    assert meta["cobertura_anclaje"]["pct_atribuida"] is not None
    cruce = client.get(f"{V1}/cruces/compromiso-ejecucion?periodo=2026-04").json()["meta"]
    assert cruce["naturaleza"] == "indiciaria"
    assert cruce["advertencias"]  # advertencia inseparable presente


# ---------------------------------------------------------------------------
# Estructura, vigencia DG, datos por velocidad
# ---------------------------------------------------------------------------


def test_salud_y_frescura(client: TestClient) -> None:
    salud = client.get(f"{V1}/salud").json()["data"]
    assert salud["accesible"] is True and salud["n_periodos_igae"] == 8
    frescura = client.get(f"{V1}/frescura").json()["data"]
    igae = next(f for f in frescura if f["fuente_cod"] == "igae_anexo_i")
    assert igae["periodo_cubierto"][1] == "2026-04"


def test_vigencia_dg(client: TestClient) -> None:
    s26 = client.get(f"{V1}/estructura/secciones/16/servicios?ejercicio=2026").json()["data"]
    assert next(s for s in s26 if s["dg_dir3_cod"])["dg_equivalencia_aproximada"] is False
    s15 = client.get(f"{V1}/estructura/secciones/16/servicios?ejercicio=2015").json()["data"]
    dg15 = next(s for s in s15 if s["dg_dir3_cod"])
    assert dg15["dg_equivalencia_aproximada"] is True and "aproximada" in dg15["dg_nota"]


def test_decisiones_aproximada_y_cruce_ambas_magnitudes(client: TestClient) -> None:
    cdm = client.get(f"{V1}/decisiones/cdm/volumen?nivel=ministerio").json()
    assert cdm["meta"]["naturaleza"] == "aproximada"
    assert any("importe_alta" in fila for fila in cdm["data"])
    cruce = client.get(f"{V1}/cruces/compromiso-ejecucion?periodo=2026-04").json()
    assert {"orn", "adjudicado", "ratio_adjudicado_orn"} <= set(cruce["data"][0])


def test_alertas_informe_y_filtros(client: TestClient) -> None:
    inf = client.get(f"{V1}/alertas/informe?periodo=2020-11").json()["data"]
    assert inf["resumen"]["alertas"] >= 1
    assert all(a["evidencias"] for a in inf["alertas"])
    ritmo = client.get(f"{V1}/alertas?periodo=2020-11&tipo=ritmo_ejecucion").json()["data"]
    assert ritmo and all(a["tipo"] == "ritmo_ejecucion" for a in ritmo)
    assert client.get(f"{V1}/alertas?periodo=2020-11&velocidad=xxx").status_code == 422


# ---------------------------------------------------------------------------
# Enums estables
# ---------------------------------------------------------------------------


def test_enums_servidos_coinciden_con_declarados(client: TestClient) -> None:
    fuentes = client.get(f"{V1}/catalogos/fuentes").json()["data"]
    assert all(f["velocidad"] in {v.value for v in Velocidad} for f in fuentes)
    alertas_js = client.get(f"{V1}/alertas?periodo=2020-11").json()["data"]
    assert all(a["severidad"] in {s.value for s in Severidad} for a in alertas_js)
    assert all(a["naturaleza"] in {n.value for n in Naturaleza} for a in alertas_js)


# ---------------------------------------------------------------------------
# Contrato de errores uniforme
# ---------------------------------------------------------------------------


def test_cuerpo_de_error_uniforme(client: TestClient) -> None:
    casos = {
        f"{V1}/ejecucion/grado?periodo=1999-01": ("no_encontrado", 404),
        f"{V1}/ejecucion/grado?periodo=2026-04&nivel=xxx": ("entrada_invalida", 422),
        f"{V1}/ejecucion/grado?periodo=2026": ("entrada_invalida", 422),
        f"{V1}/decisiones/zzz/volumen": ("no_encontrado", 404),
    }
    for url, (codigo, http) in casos.items():
        r = client.get(url)
        assert r.status_code == http, url
        cuerpo = r.json()
        assert set(cuerpo) == {"error"}
        assert set(cuerpo["error"]) == {"codigo", "mensaje", "detalle"}
        assert cuerpo["error"]["codigo"] == codigo


def test_warehouse_ausente_503_y_salud_false(tmp_path: Path) -> None:
    from config import settings

    original = settings.WAREHOUSE_PATH
    settings.WAREHOUSE_PATH = tmp_path / "no_existe.duckdb"
    try:
        with TestClient(create_app()) as c:
            assert c.get("/v1/salud").json()["data"]["accesible"] is False
            r = c.get("/v1/ejecucion/grado?periodo=2026-04")
            assert r.status_code == 503
            assert r.json()["error"]["codigo"] == "servicio_no_disponible"
    finally:
        settings.WAREHOUSE_PATH = original


# ---------------------------------------------------------------------------
# Snapshot del esquema OpenAPI (rompe ante cambio incompatible)
# ---------------------------------------------------------------------------


def test_openapi_snapshot_de_modelos_clave(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    def props(nombre: str) -> set[str]:
        return set(schemas[nombre]["properties"])

    assert props("Meta") == {
        "generado_en",
        "version",
        "nivel",
        "naturaleza",
        "magnitudes",
        "fuentes",
        "frescura",
        "cobertura_anclaje",
        "advertencias",
        "paginacion",
    }
    assert props("Paginacion") == {"total", "pagina", "tamano", "hay_siguiente"}
    assert props("SeccionModel") == {
        "nivel",
        "ejercicio",
        "seccion_cod",
        "denominacion",
        "n_servicios",
    }
    assert props("ServicioModel") == {
        "nivel",
        "ejercicio",
        "seccion_cod",
        "servicio_cod",
        "denominacion",
        "dg_dir3_cod",
        "dg_denominacion",
        "dg_nivel_organico",
        "dg_equivalencia_aproximada",
        "dg_nota",
    }
    assert props("AlertaModel") == {
        "tipo",
        "estado",
        "periodo",
        "ambito",
        "naturaleza",
        "severidad",
        "confianza",
        "valor_observado",
        "referencia",
        "contexto",
        "cobertura",
        "evidencias",
        "magnitudes",
        "motivo",
    }
    assert props("ErrorDetalle") == {"codigo", "mensaje", "detalle"}


# ---------------------------------------------------------------------------
# La API NO reimplementa lógica: coincide con las funciones puras
# ---------------------------------------------------------------------------


def test_api_no_reimplementa_metricas(client: TestClient, con: duckdb.DuckDBPyConnection) -> None:
    api = client.get(f"{V1}/ejecucion/grado?periodo=2026-04&nivel=seccion&tamano=1000").json()
    puro = metrics.grado_ejecucion(con, "2026-04", nivel="seccion")
    assert api["meta"]["naturaleza"] == puro.naturaleza
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
    api = client.get(f"{V1}/alertas?periodo=2020-11&tamano=1000").json()["data"]
    puro = [a for a in alerts.run_alerts(con, ["2020-11"]) if a.estado == alerts.ALERTA]
    assert len(api) == len(puro)
    assert {a["tipo"] for a in api} == {a.tipo for a in puro}
