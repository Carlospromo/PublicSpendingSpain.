"""Tests del motor de alertas analíticas (Fase 5).

Dos planos: (1) warehouse SINTÉTICO con valores inyectados para comprobar que
cada regla dispara cuando debe y NO dispara sobre patrones normales (control de
falsos positivos) y sale SKIPPED sin histórico; (2) warehouse REAL (IGAE+PLACSP)
para verificar que el volumen del motor completo es razonable y el informe se
serializa.
"""

from __future__ import annotations

import json
import shutil
from calendar import monthrange
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import duckdb
import pytest

from gasto_estado.analytics import alerts as al
from gasto_estado.db import load as db_load

RAW_REAL = Path(__file__).parent.parent / "data" / "raw"

_FACT_COLS = (
    "periodo, fuente_cod, ejercicio, seccion_cod, servicio_cod, programa_cod, economica_cod, "
    "provincia_cod, aplicacion_denominacion, credito_inicial, credito_definitivo, modificaciones, "
    "comprometido, orn, pagos, cobertura, fecha_captura"
)


def _synth() -> duckdb.DuckDBPyConnection:
    """Warehouse sintético en memoria: esquema + seeds, listo para inyectar hechos."""
    con = duckdb.connect(":memory:")
    db_load.init_schema(con)
    db_load.load_seeds(con)
    return con


def _ins_ejec(
    con: duckdb.DuckDBPyConnection, periodo: str, seccion: str, servicio: str,
    inicial: float, definitivo: float, orn: float,
    *, programa: str = "000A", economica: str = "100",
) -> None:
    ej, mes = int(periodo[:4]), int(periodo[5:7])
    fin = date(ej, mes, monthrange(ej, mes)[1])
    con.execute(
        "INSERT OR IGNORE INTO dim_periodo VALUES (?,?,?,?,?)", [periodo, ej, mes, None, fin]
    )
    con.execute(
        "INSERT OR IGNORE INTO dim_seccion_servicio VALUES (?,?,?,?,?,?,?)",
        [ej, seccion, servicio, f"SECCION {seccion}", f"SERVICIO {seccion}.{servicio}",
         None, "derivado_igae"],
    )
    con.execute(
        "INSERT OR IGNORE INTO dim_programa VALUES (?,?,?,?,?,?)",
        [programa, programa[0], programa[:2], programa[:3], programa[:4], None],
    )
    con.execute(
        "INSERT OR IGNORE INTO dim_economica VALUES (?,?,?,?,?,?,?)",
        [economica, "concepto", economica[0], economica[:2], economica[:3], None, None],
    )
    con.execute(
        f"INSERT INTO fact_ejecucion ({_FACT_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [periodo, "igae_anexo_i", ej, seccion, servicio, programa, economica, "NT",
         "test", inicial, definitivo, None, None, orn, None,
         "credito_inicial,credito_definitivo,orn", fin],
    )


def _ins_contrato(
    con: duckdb.DuckDBPyConnection, lic: str, lote: str, periodo: str, seccion: str,
    servicio: str, adjudicatario: str, importe: float,
) -> None:
    ej, mes = int(periodo[:4]), int(periodo[5:7])
    fin = date(ej, mes, monthrange(ej, mes)[1])
    con.execute(
        "INSERT OR IGNORE INTO dim_periodo VALUES (?,?,?,?,?)", [periodo, ej, mes, None, fin]
    )
    con.execute(
        "INSERT INTO fact_contratos (licitacion_id, lote_id, fuente_cod, periodo, ejercicio, "
        "es_cabecera_expediente, seccion_cod, servicio_cod, anclaje_dir3_cod, anclaje_tipo, "
        "anclaje_senal, importe_adjudicacion, adjudicatario_id, fecha_captura) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [lic, lote, "placsp", periodo, ej, True, seccion, servicio, "E00000001", "servicio",
         "dir3_directo", importe, adjudicatario, fin],
    )


# ---------------------------------------------------------------------------
# Ritmo de ejecución
# ---------------------------------------------------------------------------


def test_ritmo_dispara_en_desviacion_y_respeta_estable() -> None:
    con = _synth()
    # Servicio 16.02: estable ~85% en 3 noviembres, se desploma a 20% en 2024-11.
    for y in (2021, 2022, 2023):
        _ins_ejec(con, f"{y}-11", "16", "02", 100e6, 100e6, 85e6)
    _ins_ejec(con, "2024-11", "16", "02", 100e6, 100e6, 20e6)
    # Servicio 16.03: estable ~85% siempre (no debe alertar).
    for y in (2021, 2022, 2023, 2024):
        _ins_ejec(con, f"{y}-11", "16", "03", 100e6, 100e6, 85e6)
    res = al.alertas_ritmo(con, "2024-11")
    disparadas = [a for a in res if a.estado == al.ALERTA]
    assert len(disparadas) == 1
    a = disparadas[0]
    assert a.ambito["servicio_cod"] == "02" and a.ambito["seccion_cod"] == "16"
    assert a.naturaleza == al.metrics.EXACTA
    assert a.severidad in (al.A_REVISAR, al.DESTACADA)
    assert a.referencia["salto_pp"] < 0  # sub-ejecución
    assert a.cobertura["pct_del_credito_age"] is not None


def test_ritmo_skipped_sin_historico() -> None:
    con = _synth()
    _ins_ejec(con, "2024-11", "16", "02", 100e6, 100e6, 50e6)
    _ins_ejec(con, "2023-11", "16", "02", 100e6, 100e6, 50e6)  # solo 1 año previo
    res = al.alertas_ritmo(con, "2024-11")
    assert len(res) == 1 and res[0].estado == al.SKIPPED
    assert "insuficiente" in (res[0].motivo or "")


# ---------------------------------------------------------------------------
# Modificaciones de crédito
# ---------------------------------------------------------------------------


def test_modificaciones_dispara_en_atipica() -> None:
    con = _synth()
    # 5 secciones sin modificación + 1 con +100% (200M definitivo sobre 100M inicial).
    for i, s in enumerate(("01", "02", "03", "04", "05")):
        _ins_ejec(con, "2024-04", s, "01", 200e6, 200e6 + i, 50e6)
    _ins_ejec(con, "2024-04", "20", "01", 100e6, 200e6, 50e6)  # +100M, +100%
    res = [a for a in al.alertas_modificaciones(con, "2024-04") if a.estado == al.ALERTA]
    assert len(res) == 1
    a = res[0]
    assert a.ambito["seccion_cod"] == "20"
    assert a.severidad == al.DESTACADA  # +100% supera el umbral destacada
    assert "legal" in a.contexto.lower()  # enmarca como no-necesariamente-irregular
    assert a.referencia["modificacion_eur"] == 100e6


def test_modificaciones_no_dispara_sin_atipicas() -> None:
    con = _synth()
    for s in ("01", "02", "03", "04", "05", "06"):
        _ins_ejec(con, "2024-04", s, "01", 200e6, 201e6, 50e6)  # +0.5%, inmaterial
    res = [a for a in al.alertas_modificaciones(con, "2024-04") if a.estado == al.ALERTA]
    assert res == []


# ---------------------------------------------------------------------------
# Concentración de adjudicatarios
# ---------------------------------------------------------------------------


def test_concentracion_dispara_y_no_sobre_competido() -> None:
    con = _synth()
    # Órgano 16.02: un adjudicatario se lleva el 95% (concentrado).
    _ins_contrato(con, "L1", "0", "2024-06", "16", "02", "EMP_A", 9.5e6)
    _ins_contrato(con, "L2", "0", "2024-06", "16", "02", "EMP_B", 0.5e6)
    # Órgano 16.03: 5 adjudicatarios equilibrados (no concentrado).
    for i in range(5):
        _ins_contrato(con, f"M{i}", "0", "2024-06", "16", "03", f"EMP_{i}", 2e6)
    res = [a for a in al.alertas_concentracion(con, "2024-06", ejercicio=2024)
           if a.estado == al.ALERTA]
    servicios = {a.ambito["servicio_cod"] for a in res}
    assert "02" in servicios and "03" not in servicios
    conc = next(a for a in res if a.ambito["servicio_cod"] == "02")
    assert conc.referencia["hhi"] >= al.CONC_HHI_MIN
    assert "amaño" in conc.contexto.lower()  # descarta interpretación de amaño


# ---------------------------------------------------------------------------
# Anticipación compromiso → ORN (indiciaria)
# ---------------------------------------------------------------------------


def test_anticipacion_indiciaria_expone_ambas_magnitudes() -> None:
    con = _synth()
    _ins_ejec(con, "2024-03", "16", "02", 100e6, 100e6, 1e6)  # ORN baja
    _ins_contrato(con, "L1", "0", "2024-03", "16", "02", "EMP_A", 50e6)  # compromiso alto
    res = [a for a in al.alertas_anticipacion(con, "2024-03") if a.estado == al.ALERTA]
    assert len(res) == 1
    a = res[0]
    assert a.naturaleza == al.metrics.INDICIARIA
    # Ambas magnitudes por separado, no solo el ratio.
    assert a.magnitudes["orn_igae_eur"] == 1e6
    assert a.magnitudes["adjudicado_placsp_eur"] == 50e6
    assert "NO una conciliación contable" in a.contexto


def test_anticipacion_no_dispara_si_orn_supera_compromiso() -> None:
    con = _synth()
    _ins_ejec(con, "2024-03", "16", "02", 100e6, 100e6, 80e6)
    _ins_contrato(con, "L1", "0", "2024-03", "16", "02", "EMP_A", 10e6)  # ratio 0.125
    res = [a for a in al.alertas_anticipacion(con, "2024-03") if a.estado == al.ALERTA]
    assert res == []


# ---------------------------------------------------------------------------
# Propagación de metadatos y serialización del informe
# ---------------------------------------------------------------------------


def test_informe_se_serializa_y_propaga_metadatos() -> None:
    con = _synth()
    for y in (2021, 2022, 2023):
        _ins_ejec(con, f"{y}-11", "16", "02", 100e6, 100e6, 85e6)
    _ins_ejec(con, "2024-11", "16", "02", 100e6, 100e6, 20e6)
    for s in ("01", "02", "03", "04", "05"):
        _ins_ejec(con, "2024-11", s, "09", 100e6, 100e6, 50e6)
    _ins_ejec(con, "2024-11", "20", "09", 100e6, 250e6, 50e6)  # modificación atípica
    inf = al.informe(con, "2024-11")
    assert inf["resumen"]["alertas"] >= 2
    assert "pct_orn_vigilable_a_nivel_dg" in inf["cobertura_global"]
    for a in inf["alertas"]:
        assert a["naturaleza"] in (al.metrics.EXACTA, al.metrics.APROXIMADA, al.metrics.INDICIARIA)
        assert a["confianza"] in (al.CONF_ALTA, al.CONF_MEDIA, al.CONF_BAJA)
        assert a["cobertura"]  # no vacío
        assert a["evidencias"]  # enlaza evidencias
    json.dumps(inf, default=str)  # serializable de punta a punta
    assert isinstance(al.a_json(inf), str)


def test_ninguna_alerta_afirma_irregularidad() -> None:
    # Salvaguarda del lenguaje: ninguna alerta usa términos de acusación.
    con = _synth()
    for y in (2021, 2022, 2023):
        _ins_ejec(con, f"{y}-11", "16", "02", 100e6, 100e6, 85e6)
    _ins_ejec(con, "2024-11", "16", "02", 100e6, 100e6, 20e6)
    prohibidos = ("ilegal", "fraude", "irregularidad", "delito", "corrupción", "amaño es")
    for a in al.run_alerts(con, ["2024-11"]):
        texto = ((a.contexto or "") + " " + (a.motivo or "")).lower()
        assert not any(p in texto for p in prohibidos)


# ---------------------------------------------------------------------------
# Motor completo sobre datos reales: volumen razonable
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def con_real(tmp_path_factory: pytest.TempPathFactory) -> Iterator[duckdb.DuckDBPyConnection]:
    if not (RAW_REAL / "igae_mensual").is_dir() or not (RAW_REAL / "placsp").is_dir():
        pytest.skip("raw real (IGAE/PLACSP) no disponible")
    base = tmp_path_factory.mktemp("alerts_real")
    raw = base / "raw"
    raw.mkdir()
    shutil.copytree(RAW_REAL / "igae_mensual", raw / "igae_mensual")
    shutil.copytree(RAW_REAL / "placsp", raw / "placsp")
    db = base / "wh.duckdb"
    db_load.build(db, raw)
    with duckdb.connect(str(db), read_only=True) as conn:
        yield conn


def test_volumen_razonable_sobre_8_periodos(con_real: duckdb.DuckDBPyConnection) -> None:
    """Volumen razonable: ni cero (umbrales inertes) ni avalancha (umbrales histéricos).

    Sobre los 8 periodos IGAE reales el motor produce decenas de alertas (no
    miles): dominan las modificaciones materiales (~2-4 por periodo, las
    secciones con mayor swing de crédito) y unas pocas desviaciones de ritmo (solo
    noviembre tiene histórico mismo-mes suficiente). El resto de reglas salen
    SKIPPED donde no hay datos. "Razonable" = entre ~8 y ~90 alertas en total.
    """
    todos = al.run_alerts(con_real)
    disparadas = [a for a in todos if a.estado == al.ALERTA]
    omitidas = [a for a in todos if a.estado == al.SKIPPED]
    assert 8 <= len(disparadas) <= 90, f"volumen fuera de rango: {len(disparadas)}"
    assert omitidas, "deberían existir reglas SKIPPED (p. ej. ritmo sin histórico)"
    tipos = {a.tipo for a in disparadas}
    assert "modificacion_atipica" in tipos
    assert "ritmo_ejecucion" in tipos  # noviembre evaluable
    # Toda alerta propaga naturaleza, severidad, confianza y cobertura.
    for a in disparadas:
        assert a.naturaleza and a.severidad and a.confianza
        assert a.cobertura


def test_informe_real_ordena_por_severidad(con_real: duckdb.DuckDBPyConnection) -> None:
    inf = al.informe(con_real, "2020-11")
    severidades = [a["severidad"] for a in inf["alertas"]]
    orden = [al._ORDEN_SEVERIDAD[s] for s in severidades]
    assert orden == sorted(orden)  # destacadas primero
    cob = inf["cobertura_global"]["pct_orn_vigilable_a_nivel_dg"]
    assert cob is not None and 0 < cob < 100  # ni 0% ni 100%: vigilancia parcial honesta
