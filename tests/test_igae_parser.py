"""Tests de regresión del parser del Anexo I (vintage 2021+) contra el fixture.

Fixture: ``igae_anexo_i_muestra.xlsx`` (hojas S5, S01, S04, S15 del fichero real
de abril 2026). El fichero completo se valida en la verificación previa; aquí
fijamos el contrato del parser con un subconjunto pequeño y reproducible.
"""

from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from gasto_estado.parsers.igae import parse_anexo_i
from gasto_estado.parsers.igae.detect import VINTAGE_2021_PLUS, detect_vintage
from gasto_estado.parsers.igae.v2021_plus import (
    APLICACION,
    CABECERA_PROGRAMA,
    SEPARADOR,
    SUBTOTAL_SERVICIO,
    CuadreError,
    classify_row,
    parse_aplicacion,
)
from gasto_estado.parsers.schemas import igae_anexo_i_schema

FIXTURE = Path(__file__).parent / "fixtures" / "igae_anexo_i_muestra.xlsx"
PERIODO = "2026-04"
CAPTURA = date(2026, 6, 11)
FIXTURE_APLICACIONES = 601  # regresión: sin pérdida de aplicaciones


@pytest.fixture(scope="module")
def detalle() -> pd.DataFrame:
    return parse_anexo_i(FIXTURE, periodo=PERIODO, fecha_captura=CAPTURA)


def test_detecta_vintage_2021_plus() -> None:
    assert detect_vintage(FIXTURE) == VINTAGE_2021_PLUS


# ---------------------------------------------------------------------------
# Clasificación de filas (ninguna sin etiquetar)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("celda", "tipo"),
    [
        ("1501  923M   22501  -Estudios y trabajos técnicos", APLICACION),
        ("150107923M   22501  -Autonómicos", APLICACION),
        ("1602  132A   2210201-GAS NATURAL", APLICACION),  # económica 7 + denom pegada
        ("923M-Dirección y Servicios Generales", CABECERA_PROGRAMA),
        ("000X-Transferencias y libramientos internos", CABECERA_PROGRAMA),
        ("TOTAL SERVICIO", SUBTOTAL_SERVICIO),
        (None, SEPARADOR),
        ("", SEPARADOR),
        ("APLICACIÓN PGE", "OTRO"),
    ],
)
def test_classify_row(celda: object, tipo: str) -> None:
    assert classify_row(celda) == tipo


# ---------------------------------------------------------------------------
# Descomposición de la orgánica (casos verificados a mano)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("celda", "esperado"),
    [
        # seccion, servicio, programa, provincia, economica, denominacion
        ("1501  923M   22501  -Estudios", ("15", "01", "923M", None, "22501", "Estudios")),
        ("150107923M   22501  -Autonómicos", ("15", "01", "923M", "07", "22501", "Autonómicos")),
        ("1401  121M2  231    -Locomoción", ("14", "01", "121M2", None, "231", "Locomoción")),
        ("120111142A   22603  -Jurídicos", ("12", "01", "142A", "11", "22603", "Jurídicos")),
        ("1602  132A   2210201-GAS NATURAL", ("16", "02", "132A", None, "2210201", "GAS NATURAL")),
    ],
)
def test_parse_aplicacion(celda: str, esperado: tuple[str, ...]) -> None:
    a = parse_aplicacion(celda)
    assert (
        a.seccion_cod,
        a.servicio_cod,
        a.programa_cod,
        a.provincia_cod,
        a.economica_cod,
        a.denominacion,
    ) == esperado


# ---------------------------------------------------------------------------
# DataFrame canónico
# ---------------------------------------------------------------------------


def test_sin_perdida_de_aplicaciones(detalle: pd.DataFrame) -> None:
    assert len(detalle) == FIXTURE_APLICACIONES


def test_valida_esquema_pandera(detalle: pd.DataFrame) -> None:
    igae_anexo_i_schema.validate(detalle)


def test_metadatos_de_fuente(detalle: pd.DataFrame) -> None:
    assert (detalle["periodo"] == PERIODO).all()
    assert (detalle["fuente"] == "igae_anexo_i").all()
    assert (detalle["fecha_captura"] == CAPTURA).all()


def test_cobertura_de_magnitudes_explicita(detalle: pd.DataFrame) -> None:
    """Solo 3 magnitudes; comprometido y pagos NO existen en esta fuente."""
    assert {"credito_inicial", "credito_definitivo", "orn"} <= set(detalle.columns)
    assert "comprometido" not in detalle.columns
    assert "pagos" not in detalle.columns


def test_guion_se_mapea_a_nulo_no_cero(detalle: pd.DataFrame) -> None:
    """El '-' del fichero (sin dato) es nulo, distinto de 0."""
    # 337B en S15: ORN '-' (programa sin obligaciones reconocidas).
    fila = detalle[
        (detalle["seccion_cod"] == "15")
        & (detalle["programa_cod"] == "337B")
        & (detalle["economica_cod"] == "443")
    ]
    assert not fila.empty
    assert fila["orn"].isna().all()
    assert fila["credito_inicial"].notna().all()  # crédito sí tiene dato
    # Nulo ≠ 0: hay ORN nulos pero ningún crédito definitivo es exactamente 0 aquí.
    assert detalle["orn"].isna().any()


def test_desglose_territorial_preserva_filas(detalle: pd.DataFrame) -> None:
    """Filas con misma sección/servicio/programa/económica y provincia distinta."""
    autonomicos = detalle[
        (detalle["seccion_cod"] == "15")
        & (detalle["programa_cod"] == "923M")
        & (detalle["economica_cod"] == "22501")
        & (detalle["aplicacion_denominacion"] == "Autonómicos")
    ]
    # Varias provincias distintas, ninguna colisiona.
    assert autonomicos["provincia_cod"].notna().all()
    assert autonomicos["provincia_cod"].nunique() == len(autonomicos) >= 2


# ---------------------------------------------------------------------------
# Cuadre interno aplicaciones ↔ TOTAL SERVICIO
# ---------------------------------------------------------------------------


def test_cuadre_interno_pasa_en_fixture(detalle: pd.DataFrame) -> None:
    # Si el cuadre fallara, parse_anexo_i ya habría lanzado CuadreError; que el
    # DataFrame exista y tenga las aplicaciones esperadas confirma el cuadre.
    assert len(detalle) == FIXTURE_APLICACIONES


def test_cuadre_falla_loud_si_se_corrompe_un_subtotal(tmp_path: Path) -> None:
    """Si un TOTAL SERVICIO no cuadra con sus aplicaciones, fail loud."""
    wb = openpyxl.load_workbook(FIXTURE)
    ws = wb["S15"]
    # Corrompe el primer TOTAL SERVICIO de la hoja (columna ORN).
    for row in ws.iter_rows():
        if row[1].value and str(row[1].value).strip().upper().startswith("TOTAL SERVICIO"):
            row[4].value = 999999999.0
            break
    corrupto = tmp_path / "corrupto.xlsx"
    wb.save(corrupto)
    with pytest.raises(CuadreError, match="Descuadre"):
        parse_anexo_i(corrupto, periodo=PERIODO, fecha_captura=CAPTURA)
