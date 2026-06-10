"""Tests de regresión del parser DIR3 y de la dimensión orgánica base.

Fixture: ``dir3_unidades_age_muestra.xlsx`` — subárboles completos de tres
raíces (Presidencia del Gobierno, Cultura, Juventud e Infancia) recortados del
fichero oficial real (captura 2026-06-10), conservando su maquetación (fila en
blanco inicial, cabecera oficial, primera columna vacía, fechas DD/MM/YY).
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gasto_estado.parsers.dir3 import ROOT_ESTADO, parse_unidades_age
from gasto_estado.parsers.schemas import dir3_unidades_schema
from gasto_estado.transform.organica import DIM_COLUMNS, build_dim_organica

FIXTURE = Path(__file__).parent / "fixtures" / "dir3_unidades_age_muestra.xlsx"
FIXTURE_ROWS = 336  # filas de datos del fixture (regresión: sin pérdida)
CAPTURE = date(2026, 6, 10)


@pytest.fixture(scope="module")
def unidades() -> pd.DataFrame:
    return parse_unidades_age(FIXTURE)


def test_parsea_sin_perdida_de_filas(unidades: pd.DataFrame) -> None:
    assert len(unidades) == FIXTURE_ROWS


def test_valida_esquema_pandera(unidades: pd.DataFrame) -> None:
    dir3_unidades_schema.validate(unidades)


def test_jerarquia_padre_hijo_integra(unidades: pd.DataFrame) -> None:
    """Todo hijo tiene padre existente en el fichero o la raíz declarada."""
    codigos = set(unidades["dir3_cod"])
    padres = set(unidades["dir3_padre_cod"])
    huerfanos = padres - codigos - {ROOT_ESTADO}
    assert not huerfanos, f"padres inexistentes: {sorted(huerfanos)}"


def test_sin_codigos_activos_duplicados(unidades: pd.DataFrame) -> None:
    activos = unidades[unidades["estado"].isin(["V", "T"])]
    duplicados = activos[activos["dir3_cod"].duplicated()]["dir3_cod"]
    assert duplicados.empty, f"códigos activos duplicados: {list(duplicados)}"


def test_fechas_alta_no_futuras(unidades: pd.DataFrame) -> None:
    """Regresión del pivote de siglo: DD/MM/59 es 1959, nunca 2059."""
    fechas = unidades["fecha_alta"].dropna()
    assert (fechas <= date.today()).all()


def test_dim_organica_estructura(unidades: pd.DataFrame) -> None:
    dim = build_dim_organica(unidades, capture_date=CAPTURE)
    assert list(dim.columns) == DIM_COLUMNS
    assert len(dim) == FIXTURE_ROWS
    # Enganche presupuestario pendiente del Prompt 3: columnas a null.
    assert dim["seccion_cod"].isna().all()
    assert dim["servicio_cod"].isna().all()


def test_dim_organica_scd2_fechas() -> None:
    """SCD tipo 2: vigentes sin fecha_fin; extinguidas/anuladas con fecha_fin."""
    unidades = parse_unidades_age(FIXTURE)
    # El snapshot real solo trae vigentes; se simulan los estados E/A oficiales
    # del catálogo para fijar el contrato de la transformación.
    unidades.loc[unidades.index[:2], "estado"] = ["E", "A"]

    dim = build_dim_organica(unidades, capture_date=CAPTURE)
    extinguidas = dim[dim["estado"].isin(["E", "A"])]
    vigentes = dim[dim["estado"].isin(["V", "T"])]
    assert len(extinguidas) == 2
    assert (extinguidas["fecha_fin"] == CAPTURE).all()
    assert vigentes["fecha_fin"].isna().all()
    # fecha_inicio: alta oficial o, en su defecto, fecha de captura.
    assert dim["fecha_inicio"].notna().all()
