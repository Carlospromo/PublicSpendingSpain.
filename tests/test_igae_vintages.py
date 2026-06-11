"""Tests del enrutado por vintage y del parser histórico 2015–2020.

Insumos:
- ``tests/fixtures/igae_anexo_i_2016_muestra.xlsx``: recorte real de nov-2016
  (hojas S5, S04 y S31; S31 contiene la fila con provincia ``DT``).
- ``data/raw/igae_mensual/2015-12/…(EXCEL).xls``: el raw BIFF completo,
  versionado en el repo. Se usa entero como fixture porque BIFF no puede
  reescribirse reducido sin añadir una dependencia muerta (xlwt); el fichero
  ES la captura inmutable.
- El fixture 2021+ existente, para la no-regresión del enrutado.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gasto_estado.parsers.igae import parse_anexo_i, parse_periodo
from gasto_estado.parsers.igae.detect import (
    VINTAGE_2015_2020_XLS,
    VINTAGE_2021_PLUS,
    detect_vintage,
)
from gasto_estado.parsers.igae.v2021_plus import DETALLE_COLUMNS
from gasto_estado.parsers.schemas import igae_anexo_i_schema

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_2021 = FIXTURES / "igae_anexo_i_muestra.xlsx"
FIXTURE_2016 = FIXTURES / "igae_anexo_i_2016_muestra.xlsx"
RAW_2015 = (
    Path(__file__).parent.parent
    / "data/raw/igae_mensual/2015-12/MENSUAL DICIEMBRE PROVISIONAL 2015 ANEXO I (EXCEL).xls"
)
CAPTURA = date(2026, 6, 11)


# ---------------------------------------------------------------------------
# Enrutado por vintage (detección por contenido, no por extensión/año)
# ---------------------------------------------------------------------------


def test_xlsx_moderno_enruta_a_2021_plus() -> None:
    assert detect_vintage(FIXTURE_2021) == VINTAGE_2021_PLUS


def test_xlsx_historico_enruta_a_2021_plus() -> None:
    """Los .xlsx de 2016-2020 comparten gramática con 2021+: mismo parser."""
    assert detect_vintage(FIXTURE_2016) == VINTAGE_2021_PLUS


def test_xls_biff_enruta_a_2015_2020() -> None:
    assert detect_vintage(RAW_2015) == VINTAGE_2015_2020_XLS


def test_contenedor_desconocido_fail_loud(tmp_path: Path) -> None:
    falso = tmp_path / "falso.xlsx"
    falso.write_bytes(b"esto no es un excel")
    with pytest.raises(ValueError, match="Contenedor no reconocido"):
        detect_vintage(falso)


# ---------------------------------------------------------------------------
# Parser histórico: vintage BIFF (2015) y xlsx histórico (2016, con DT)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def detalle_2015() -> pd.DataFrame:
    # Si el cuadre interno fallara, parse_anexo_i lanzaría CuadreError aquí.
    return parse_anexo_i(RAW_2015, periodo="2015-12", fecha_captura=CAPTURA)


def test_2015_parsea_y_valida(detalle_2015: pd.DataFrame) -> None:
    igae_anexo_i_schema.validate(detalle_2015)
    assert len(detalle_2015) == 8259  # regresión: sin pérdida de aplicaciones
    assert detalle_2015["seccion_cod"].nunique() == 27
    # El histórico llega a concepto/subconcepto (3/5 dígitos); el nivel de
    # partida (7) solo aparece en ficheros recientes.
    assert sorted(detalle_2015["economica_cod"].str.len().unique()) == [3, 5]


def test_2015_descomposicion_verificada_a_mano(detalle_2015: pd.DataFrame) -> None:
    """Aplicación 0401 911P 10000 de S04, cotejada contra el fichero real."""
    fila = detalle_2015[
        (detalle_2015["seccion_cod"] == "04")
        & (detalle_2015["servicio_cod"] == "01")
        & (detalle_2015["programa_cod"] == "911P")
        & (detalle_2015["economica_cod"] == "10000")
    ]
    assert len(fila) == 1
    assert fila.iloc[0]["credito_inicial"] == 566380.0
    assert fila.iloc[0]["orn"] == 563325.46
    assert pd.isna(fila.iloc[0]["provincia_cod"])
    assert fila.iloc[0]["servicio_denominacion"] == "tribunal constitucional"


def test_2015_guion_a_nulo(detalle_2015: pd.DataFrame) -> None:
    """S14 Defensa: '1401 121M 16202' tiene créditos '-' y ORN con dato."""
    fila = detalle_2015[
        (detalle_2015["seccion_cod"] == "14")
        & (detalle_2015["servicio_cod"] == "01")
        & (detalle_2015["programa_cod"] == "121M")
        & (detalle_2015["economica_cod"] == "16202")
    ]
    assert len(fila) == 1
    assert pd.isna(fila.iloc[0]["credito_inicial"])
    assert pd.isna(fila.iloc[0]["credito_definitivo"])
    assert fila.iloc[0]["orn"] == 75000.0


def test_2016_provincia_dt() -> None:
    df = parse_anexo_i(FIXTURE_2016, periodo="2016-11", fecha_captura=CAPTURA)
    igae_anexo_i_schema.validate(df)
    dt = df[df["provincia_cod"] == "DT"]
    assert len(dt) == 1
    assert dt.iloc[0]["seccion_cod"] == "31"
    assert dt.iloc[0]["programa_cod"] == "923R"


# ---------------------------------------------------------------------------
# Equivalencia de contrato canónico entre vintages
# ---------------------------------------------------------------------------


def test_contrato_canonico_identico_entre_vintages(detalle_2015: pd.DataFrame) -> None:
    moderno = parse_anexo_i(FIXTURE_2021, periodo="2026-04", fecha_captura=CAPTURA)
    assert list(detalle_2015.columns) == list(moderno.columns) == DETALLE_COLUMNS
    assert detalle_2015.dtypes.astype(str).to_dict() == moderno.dtypes.astype(str).to_dict()


def test_parse_periodo_historico_devuelve_canonico() -> None:
    df = parse_periodo("2015-12", fecha_captura=CAPTURA)
    igae_anexo_i_schema.validate(df)
    assert (df["periodo"] == "2015-12").all()


def test_no_regresion_2021_plus() -> None:
    """El fixture 2021+ sigue parseando exactamente igual tras el enrutado."""
    df = parse_anexo_i(FIXTURE_2021, periodo="2026-04", fecha_captura=CAPTURA)
    igae_anexo_i_schema.validate(df)
    assert len(df) == 601
