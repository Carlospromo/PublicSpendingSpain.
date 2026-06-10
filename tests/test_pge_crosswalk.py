"""Tests de la clasificación orgánica del PGE, nivel_organico y crosswalk.

Dos planos:
- Fixture (``pge_resumen_servicios_muestra.csv``): recorte real en latin-1 del
  resumen por servicios del presupuesto prorrogado (secciones 01, 02, 13, 15 y
  16) → regresión del parser.
- Seeds comprometidos (``db/seeds/*.csv``): el crosswalk del ejercicio vigente
  se regenera desde sus insumos y debe coincidir con el seed (determinismo +
  los overrides no se pierden al regenerar) y cumplir el umbral de calidad.
"""

from pathlib import Path

import pandas as pd
import pytest

from gasto_estado.parsers.pge_organica import parse_resumen_servicios
from gasto_estado.parsers.schemas import dim_seccion_servicio_schema
from gasto_estado.transform.crosswalks.historico import TIPOS_CAMBIO, load_historico
from gasto_estado.transform.crosswalks.servicio_dir3 import (
    build_crosswalk,
    load_overrides,
    match_stats,
)
from gasto_estado.transform.nivel_organico import classify

FIXTURE = Path(__file__).parent / "fixtures" / "pge_resumen_servicios_muestra.csv"
SEEDS = Path(__file__).parent.parent / "src" / "gasto_estado" / "db" / "seeds"

# Umbral de sin_match real (sin_candidato) sobre servicios matcheables.
# Justificación en transform/crosswalks/README.md (observado: 3,3 %).
UMBRAL_SIN_CANDIDATO_PCT = 10.0


# ---------------------------------------------------------------------------
# Parser PGE (fixture)
# ---------------------------------------------------------------------------


def test_parser_pge_fixture() -> None:
    df = parse_resumen_servicios(FIXTURE, ejercicio=2026)
    dim_seccion_servicio_schema.validate(df)
    assert df["presupuesto"].unique().tolist() == ["2025-P"]
    assert sorted(df["seccion_cod"].unique()) == ["01", "02", "13", "15", "16"]
    # Sin pérdida de filas: 1+5 servicios en 01/02 y los de 13, 15 y 16.
    assert (df["seccion_cod"] == "01").sum() == 1
    assert (df["seccion_cod"] == "02").sum() == 5
    fila = df[(df["seccion_cod"] == "13") & (df["servicio_cod"] == "02")].iloc[0]
    assert fila["servicio_denominacion"] == "SECRETARÍA DE ESTADO DE JUSTICIA"
    assert fila["seccion_denominacion"].startswith("MINISTERIO DE LA PRESIDENCIA")


# ---------------------------------------------------------------------------
# nivel_organico (casos conocidos del fixture DIR3 / fichero real)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("denominacion", "nivel_jerarquico", "esperado"),
    [
        ("Ministerio de Defensa", 1, "MINISTERIO"),
        ("Presidencia del Gobierno", 1, "MINISTERIO"),
        ("Secretaría de Estado de Cultura", 2, "SECRETARIA_ESTADO"),
        ("S. de E. de Seguridad", 2, "SECRETARIA_ESTADO"),  # abreviatura DIR3 real
        ("Subsecretaria del Interior", 2, "SUBSECRETARIA"),
        ("Dirección General de Bellas Artes", 3, "DIRECCION_GENERAL"),
        ("D.G. de Politica de Defensa", 2, "DIRECCION_GENERAL"),  # abreviatura DIR3 real
        ("Agencia Estatal de Administración Tributaria", 2, "ORGANISMO"),
        # Anti-falso-positivo: una Subdirección General NO es Dirección General.
        ("Subdirección General de Personal", 5, "OTRO"),
        ("Guardia Civil de Cuenca", 6, "OTRO"),
    ],
)
def test_nivel_organico_casos_conocidos(
    denominacion: str, nivel_jerarquico: int, esperado: str
) -> None:
    nivel, senal = classify(denominacion, nivel_jerarquico)
    assert nivel == esperado
    assert senal == ("denominacion" if esperado != "OTRO" else "sin_senal")


def test_nivel_organico_en_seed_auditable() -> None:
    dim = pd.read_csv(SEEDS / "dim_organica.csv", dtype=str)
    assert dim["nivel_organico"].notna().all()  # todo etiquetado, nada descartado
    assert dim["nivel_organico_senal"].notna().all()
    # Las 25 raíces (nivel jerárquico 1) son ministerios/Presidencia.
    raices = dim[dim["nivel_jerarquico"] == "1"]
    assert (raices["nivel_organico"] == "MINISTERIO").all()


# ---------------------------------------------------------------------------
# Crosswalk servicio↔DIR3 (seeds comprometidos)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeds() -> dict[str, pd.DataFrame]:
    return {
        "dss": pd.read_csv(SEEDS / "dim_seccion_servicio.csv", dtype=str).assign(
            ejercicio=lambda d: d["ejercicio"].astype("int64")
        ),
        "dim": pd.read_csv(SEEDS / "dim_organica.csv", dtype=str),
        "cw": pd.read_csv(SEEDS / "crosswalk_servicio_dir3.csv", dtype=str).assign(
            ejercicio=lambda d: d["ejercicio"].astype("int64")
        ),
    }


def test_crosswalk_cubre_todos_los_servicios(seeds: dict[str, pd.DataFrame]) -> None:
    """(a) Ningún servicio del ejercicio vigente queda fuera del crosswalk."""
    clave = ["ejercicio", "seccion_cod", "servicio_cod"]
    servicios = set(map(tuple, seeds["dss"][clave].itertuples(index=False)))
    cubiertos = set(map(tuple, seeds["cw"][clave].itertuples(index=False)))
    assert servicios == cubiertos


def test_crosswalk_sin_match_bajo_umbral(seeds: dict[str, pd.DataFrame]) -> None:
    stats = match_stats(seeds["cw"])
    assert stats["sin_candidato_pct"] <= UMBRAL_SIN_CANDIDATO_PCT, stats


def test_overrides_se_aplican_y_sobreviven_a_la_regeneracion(
    seeds: dict[str, pd.DataFrame],
) -> None:
    """(c) Regenerar desde los insumos reproduce el seed, overrides incluidos."""
    regenerado = build_crosswalk(seeds["dss"], seeds["dim"], load_overrides())
    seed = seeds["cw"]
    assert len(regenerado) == len(seed)
    izq = regenerado.fillna("").astype(str).reset_index(drop=True)
    der = seed.fillna("").astype(str).reset_index(drop=True)
    pd.testing.assert_frame_equal(izq, der, check_dtype=False)
    # El override manual está presente y resuelto.
    manual = seed[(seed["seccion_cod"] == "13") & (seed["servicio_cod"] == "07")]
    assert manual["match_tipo"].tolist() == ["manual"]
    assert manual["dir3_cod"].tolist() == ["EA0008567"]


def test_crosswalk_cardinalidad_coherente(seeds: dict[str, pd.DataFrame]) -> None:
    """(d) Sin huérfanos no declarados: todo dir3_cod existe en dim_organica
    vigente y los sin_match (y solo ellos) llevan dir3_cod vacío con motivo."""
    cw, dim = seeds["cw"], seeds["dim"]
    vigentes = set(dim[dim["fecha_fin"].isna()]["dir3_cod"])
    con_unidad = cw[cw["match_tipo"] != "sin_match"]
    assert con_unidad["dir3_cod"].notna().all()
    huerfanos = set(con_unidad["dir3_cod"]) - vigentes
    assert not huerfanos, f"dir3_cod fuera de dim_organica vigente: {huerfanos}"
    sin = cw[cw["match_tipo"] == "sin_match"]
    assert sin["dir3_cod"].isna().all()
    assert (
        sin["match_detalle"]
        .isin(
            [
                "seccion_sin_ministerio_dir3",
                "servicio_instrumental_prtr",
                "sin_candidato_en_subarbol",
            ]
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Histórico de secciones
# ---------------------------------------------------------------------------


def test_historico_carga_y_es_coherente(seeds: dict[str, pd.DataFrame]) -> None:
    historico = load_historico()
    assert set(historico["tipo_cambio"]) <= set(TIPOS_CAMBIO)
    # La remodelación 2023→2024 está cargada y sus destinos existen en la
    # estructura vigente (las secciones 2024P no cambiaron en 2025P).
    aristas = historico[historico["ejercicio_destino"] == "2024"]
    assert len(aristas) >= 13
    secciones_vigentes = set(seeds["dss"]["seccion_cod"])
    destinos = set(aristas["seccion_destino"].dropna())
    assert destinos <= secciones_vigentes
