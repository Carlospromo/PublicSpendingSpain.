"""Tests de regresión del parser BOE (sumario + disposiciones, Fase 4).

Sobre las muestras reales (docs/boe_estructura.md): prefiltro de interés en el
sumario (descarte de personal/contratación/justicia y de los RD/RDL sin título
de crédito), clasificación de tipos verificada a mano, extracción de importe con
confianza, puente BDNS y conservación del texto bruto.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from gasto_estado.parsers import boe

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def captura_boe(tmp_path: Path) -> Path:
    """Capa raw de una captura BOE: sumario + las dos disposiciones de muestra."""
    dia = tmp_path / "boe" / "2026-06-13" / "20240206"
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
    return tmp_path / "boe" / "2026-06-13"


def test_prefiltro_solo_disposiciones_de_interes(captura_boe: Path) -> None:
    df = boe.parse_capture_dir(captura_boe)
    # De los 5 items del sumario solo interesan 2 (RD subvención y extracto):
    # personal (2A), servicios mínimos (3), contratación (5A) y el RDL DANA
    # (sin título de crédito) se descartan.
    assert set(df["identificador"]) == {"BOE-A-2024-22930", "BOE-B-2024-3994"}


def test_rdl_dana_sin_titulo_de_credito_no_se_ingiere(captura_boe: Path) -> None:
    df = boe.parse_capture_dir(captura_boe)
    assert "BOE-A-2024-22928" not in set(df["identificador"])


def test_clasificacion_subvencion_directa_e_importe_alta(captura_boe: Path) -> None:
    df = boe.parse_capture_dir(captura_boe).set_index("identificador")
    rd = df.loc["BOE-A-2024-22930"]
    assert rd["tipo_disposicion"] == boe.TIPO_SUBVENCION_DIRECTA
    assert rd["importe"] == 1_000_000.0
    assert rd["importe_confianza"] == "alta"
    assert rd["departamento"] == "MINISTERIO DE TRANSPORTES Y MOVILIDAD SOSTENIBLE"
    # periodo del día del boletín (fecha_publicacion del sumario), común a todos
    # los items de ese sumario.
    assert rd["periodo"] == "2024-02"


def test_extracto_es_convocatoria_con_bdns_e_importe_media(captura_boe: Path) -> None:
    df = boe.parse_capture_dir(captura_boe).set_index("identificador")
    ext = df.loc["BOE-B-2024-3994"]
    assert ext["tipo_disposicion"] == boe.TIPO_CONVOCATORIA
    assert ext["bdns_id"] == "742455"  # puente con la convocatoria BDNS
    assert ext["importe"] == 8_000.0
    assert ext["importe_confianza"] == "media"
    assert ext["seccion_boe"] == "5B"


def test_texto_bruto_conservado(captura_boe: Path) -> None:
    df = boe.parse_capture_dir(captura_boe).set_index("identificador")
    assert "aparcamiento disuasorio" in df.loc["BOE-A-2024-22930"]["texto_bruto"]


def test_classify_credito_extraordinario_por_titulo() -> None:
    assert (
        boe.classify_tipo("Real Decreto-ley por el que se concede un crédito extraordinario", None)
        == boe.TIPO_CREDITO_EXTRAORDINARIO
    )


def test_classify_transferencia_de_credito() -> None:
    assert (
        boe.classify_tipo("Orden por la que se autoriza una transferencia de crédito", None)
        == boe.TIPO_TRANSFERENCIA_CREDITO
    )


def test_classify_otro_cuando_no_casa() -> None:
    assert boe.classify_tipo("Resolución sobre cuestiones de personal", None) == boe.TIPO_OTRO


def test_dedup_por_identificador(captura_boe: Path) -> None:
    # parsear dos veces el mismo día no duplica disposiciones (clave natural).
    df = boe.parse_capture_dir(captura_boe, fecha_captura=date(2026, 6, 13))
    assert df["identificador"].is_unique
