"""Tests de regresión del parser del Consejo de Ministros (Fase 4).

Sobre referencias reales de dos vintages (docs/consejo_ministros_estructura.md):
detección de maquetación, segmentación de acuerdos del SUMARIO, clasificación de
tipos, extracción de importe con confianza (incluida la NO extracción de otra
moneda) y bloque de personal. Nada del SUMARIO se descarta.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gasto_estado.parsers import consejo_ministros as cdm

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def acuerdos_2026() -> pd.DataFrame:
    contenido = (FIXTURES / "consejo_referencia_2026.html").read_bytes()
    filas = cdm.parse_referencia(contenido, fecha=date(2026, 6, 9))
    return pd.DataFrame(filas)


@pytest.fixture(scope="module")
def acuerdos_2018() -> pd.DataFrame:
    contenido = (FIXTURES / "consejo_referencia_2018.html").read_bytes()
    filas = cdm.parse_referencia(contenido, fecha=date(2018, 4, 27))
    return pd.DataFrame(filas)


def test_detect_vintage_actual() -> None:
    assert cdm.detect_vintage(b"<h2>SUMARIO</h2><h3>Hacienda</h3>") == cdm.VINTAGE_V2024


def test_detect_vintage_antiguo() -> None:
    contenido = (FIXTURES / "consejo_referencia_2018.html").read_bytes()
    assert cdm.detect_vintage(contenido) == cdm.VINTAGE_V2018


def test_pagina_no_referencia_falla_loud() -> None:
    with pytest.raises(cdm.ReferenciaNoReconocida):
        cdm.detect_vintage(b"<html><body>portal caido</body></html>")


def test_ministerio_y_acuerdo_id_por_orden(acuerdos_2026: pd.DataFrame) -> None:
    assert acuerdos_2026["acuerdo_id"].is_unique
    # acuerdo_id sintético = <fecha>#<índice>.
    assert acuerdos_2026["acuerdo_id"].iloc[0] == "2026-06-09#000"
    assert acuerdos_2026["ministerio"].iloc[0] == "Economía, Comercio y Empresa"


def test_subvencion_con_importe_titular(acuerdos_2026: pd.DataFrame) -> None:
    fnee = acuerdos_2026[acuerdos_2026["descripcion"].str.contains("Fondo Nacional de Eficiencia")]
    fila = fnee.iloc[0]
    assert fila["tipo_acuerdo"] == cdm.TIPO_SUBVENCION
    assert fila["importe"] == 168_000_000.0
    assert fila["importe_confianza"] == "alta"
    assert fila["ministerio"] == "Para la Transición Ecológica y el Reto Demográfico"


def test_suplemento_de_credito(acuerdos_2026: pd.DataFrame) -> None:
    sup = acuerdos_2026[acuerdos_2026["descripcion"].str.contains("suplemento de crédito")]
    assert (sup["tipo_acuerdo"] == cdm.TIPO_CREDITO_SUPLEMENTO).all()
    assert sup.iloc[0]["importe"] == 9_972_634.0


def test_autorizacion_gasto_contrato_valor_estimado(acuerdos_2026: pd.DataFrame) -> None:
    vig = acuerdos_2026[acuerdos_2026["descripcion"].str.contains("vigilancia y seguridad")]
    fila = vig.iloc[0]
    assert fila["tipo_acuerdo"] == cdm.TIPO_AUTORIZACION_GASTO
    assert fila["importe"] == 61_234_370.46
    assert fila["importe_confianza"] == "alta"


def test_proyecto_de_ley_es_norma_sin_importe(acuerdos_2026: pd.DataFrame) -> None:
    ley = acuerdos_2026[acuerdos_2026["descripcion"].str.startswith("PROYECTO DE LEY")]
    assert (ley["tipo_acuerdo"] == cdm.TIPO_NORMA).all()
    assert ley["importe"].isna().all()


def test_bloque_personal_se_clasifica_como_personal(acuerdos_2026: pd.DataFrame) -> None:
    nombramientos = acuerdos_2026[acuerdos_2026["descripcion"].str.contains("se nombra")]
    assert len(nombramientos) >= 1
    assert (nombramientos["tipo_acuerdo"] == cdm.TIPO_PERSONAL).all()


def test_nada_del_sumario_se_descarta(acuerdos_2026: pd.DataFrame) -> None:
    # Todos los acuerdos del SUMARIO se ingieren (los irrelevantes en otro/personal).
    assert len(acuerdos_2026) >= 30
    assert acuerdos_2026["tipo_acuerdo"].isin(cdm.TIPOS_ACUERDO).all()


def test_vintage_antiguo_se_parsea(acuerdos_2018: pd.DataFrame) -> None:
    assert (acuerdos_2018["vintage"] == cdm.VINTAGE_V2018).all()
    assert len(acuerdos_2018) >= 20


def test_otra_moneda_no_da_importe(acuerdos_2018: pd.DataFrame) -> None:
    # Condonación de deuda en dólares: importe NULO (no es euros).
    guinea = acuerdos_2018[acuerdos_2018["descripcion"].str.contains("Guinea")]
    assert len(guinea) == 1
    assert pd.isna(guinea.iloc[0]["importe"])
    assert guinea.iloc[0]["importe_confianza"] == "sin_importe"


def test_url_oficial_reconstruida_por_vintage(acuerdos_2026: pd.DataFrame) -> None:
    url = acuerdos_2026["url_oficial"].iloc[0]
    assert url.endswith("/2026/20260609-referencia-rueda-de-prensa-ministros.aspx")
