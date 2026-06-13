"""Tests del anclaje orgánico PLACSP → espina presupuestaria (Fase 4).

Dimensiones sintéticas mínimas que reproducen las topologías reales: DG con
crosswalk directo, junta de contratación que asciende por sus padres, ente
instrumental con presupuesto propio, entidades fuera del perímetro AGE y
órganos sin DIR3. Cada decisión queda etiquetada (tipo + señal): aquí se fija
ese contrato.
"""

from datetime import date

import pandas as pd
import pytest

from gasto_estado.transform import placsp_anclaje as pa

# Árbol sintético: ministerio (MN) -> DG (MN) -> junta; y un ente EE colgando
# del ministerio con una unidad hija propia.
_DIM = pd.DataFrame(
    [
        # dir3, padre, tipo_entidad, inicio, fin
        ("E00000001", None, "MN", "2000-01-01", None),  # ministerio
        ("E00000002", "E00000001", "MN", "2000-01-01", None),  # DG (en crosswalk)
        ("E00000003", "E00000002", None, "2000-01-01", None),  # junta de contratación
        # Ente instrumental CON override manual en el crosswalk y su unidad:
        ("EA0000004", "E00000001", "EE", "2000-01-01", None),
        ("EA0000005", "EA0000004", None, "2000-01-01", None),
        ("E00000006", "E00000001", "MN", "2000-01-01", "2020-12-31"),  # DG extinguida
        # Ente instrumental SIN entrada en el crosswalk y su unidad:
        ("EA0000007", "E00000001", "EE", "2000-01-01", None),
        ("EA0000008", "EA0000007", None, "2000-01-01", None),
    ],
    columns=["dir3_cod", "dir3_padre_cod", "tipo_entidad", "fecha_inicio", "fecha_fin"],
)
_DIM["fecha_inicio"] = pd.to_datetime(_DIM["fecha_inicio"])
_DIM["fecha_fin"] = pd.to_datetime(_DIM["fecha_fin"])

_CROSSWALK = pd.DataFrame(
    [
        (2026, "20", "03", "E00000002"),
        # Override manual: la cabecera del ente SÍ está mapeada a un servicio.
        (2026, "20", "40", "EA0000004"),
        # Duplicado deliberado: E00000002 también mapea a un servicio "mayor".
        (2026, "20", "07", "E00000002"),
    ],
    columns=["ejercicio", "seccion_cod", "servicio_cod", "dir3_cod"],
)

_FECHA = date(2026, 5, 1)


@pytest.fixture(scope="module")
def anclador() -> pa.Anclador:
    return pa.Anclador(_DIM, _CROSSWALK)


def test_dir3_directo(anclador: pa.Anclador) -> None:
    out = anclador.anclar("E00000002", _FECHA)
    assert out["anclaje_tipo"] == pa.ANCLA_SERVICIO
    assert out["anclaje_senal"] == pa.SENAL_DIR3_DIRECTO
    assert out["anclaje_dir3_cod"] == "E00000002"
    # Determinismo ante crosswalk no 1:1: gana el menor (seccion, servicio).
    assert (out["seccion_cod"], out["servicio_cod"]) == ("20", "03")


def test_dir3_ancestro_la_junta_asciende_a_su_dg(anclador: pa.Anclador) -> None:
    out = anclador.anclar("E00000003", _FECHA)
    assert out["anclaje_tipo"] == pa.ANCLA_SERVICIO
    assert out["anclaje_senal"] == pa.SENAL_DIR3_ANCESTRO
    assert out["anclaje_dir3_cod"] == "E00000002"  # el eslabón que resolvió
    assert (out["seccion_cod"], out["servicio_cod"]) == ("20", "03")


def test_entidad_instrumental_no_asciende_al_ministerio(anclador: pa.Anclador) -> None:
    # La unidad del ente EE (sin override) NO debe heredar el servicio del
    # ministerio: su gasto nunca aparecerá en la ORN de ese servicio.
    out = anclador.anclar("EA0000008", _FECHA)
    assert out["anclaje_tipo"] == pa.ANCLA_ORGANICA_SIN_SERVICIO
    assert out["anclaje_senal"] == pa.SENAL_ENTIDAD_INSTRUMENTAL
    assert out["seccion_cod"] is None and out["servicio_cod"] is None


def test_crosswalk_autoritativo_sobre_frontera_de_ente(anclador: pa.Anclador) -> None:
    # La cabecera EE está mapeada explícitamente (override manual): ancla, y
    # sus unidades hijas ascienden hasta ella en vez de pararse en la frontera.
    out = anclador.anclar("EA0000004", _FECHA)
    assert out["anclaje_tipo"] == pa.ANCLA_SERVICIO
    assert (out["seccion_cod"], out["servicio_cod"]) == ("20", "40")
    hija = anclador.anclar("EA0000005", _FECHA)
    assert hija["anclaje_senal"] == pa.SENAL_DIR3_ANCESTRO
    assert (hija["seccion_cod"], hija["servicio_cod"]) == ("20", "40")


def test_ministerio_sin_mapeo_queda_etiquetado(anclador: pa.Anclador) -> None:
    out = anclador.anclar("E00000001", _FECHA)
    assert out["anclaje_tipo"] == pa.ANCLA_ORGANICA_SIN_SERVICIO
    assert out["anclaje_senal"] == pa.SENAL_SIN_SERVICIO_EN_CADENA


def test_ejercicio_sin_crosswalk_no_se_fuerza(anclador: pa.Anclador) -> None:
    # Contrato de 2019: la estructura de 2026 NO se le aplica.
    out = anclador.anclar("E00000003", date(2019, 3, 1))
    assert out["anclaje_tipo"] == pa.ANCLA_ORGANICA_SIN_SERVICIO
    assert out["anclaje_senal"] == pa.SENAL_EJERCICIO_SIN_CROSSWALK


def test_version_scd2_no_vigente_corta_el_ascenso(anclador: pa.Anclador) -> None:
    # DG extinguida en 2020: para una fecha de 2026 no hay versión vigente,
    # pero el código sigue siendo AGE conocido → orgánica sin servicio.
    out = anclador.anclar("E00000006", _FECHA)
    assert out["anclaje_tipo"] == pa.ANCLA_ORGANICA_SIN_SERVICIO
    assert out["anclaje_senal"] == pa.SENAL_SIN_SERVICIO_EN_CADENA


def test_fuera_perimetro_y_sin_anclar(anclador: pa.Anclador) -> None:
    local = anclador.anclar("L01180896", _FECHA)
    assert local["anclaje_tipo"] == pa.ANCLA_FUERA_PERIMETRO
    assert local["anclaje_senal"] == pa.SENAL_DIR3_NO_AGE

    assert anclador.anclar(None, _FECHA)["anclaje_senal"] == pa.SENAL_SIN_DIR3
    assert anclador.anclar(float("nan"), _FECHA)["anclaje_senal"] == pa.SENAL_SIN_DIR3
    assert anclador.anclar("12345", _FECHA)["anclaje_senal"] == pa.SENAL_DIR3_MALFORMADO


def test_anclar_contratos_y_stats() -> None:
    contratos = pd.DataFrame(
        {
            "expediente_id": ["A", "A", "B", "C"],
            "organo_dir3_cod": ["E00000003", "E00000003", "L01180896", None],
            "fecha_adjudicacion": [date(2026, 5, 1), date(2026, 5, 2), None, None],
            "fecha_actualizacion": [None, None, date(2026, 6, 1), date(2026, 6, 1)],
            "periodo": ["2026-05", "2026-05", "2026-06", "2026-06"],
        }
    )
    anclado = pa.anclar_contratos(contratos, _DIM, _CROSSWALK)
    assert list(anclado["anclaje_tipo"]) == [
        pa.ANCLA_SERVICIO,
        pa.ANCLA_SERVICIO,
        pa.ANCLA_FUERA_PERIMETRO,
        pa.ANCLA_SIN_ANCLAR,
    ]
    assert set(pa.ANCLAJE_COLUMNS) <= set(anclado.columns)
    # Stats por EXPEDIENTE (A multi-lote cuenta una vez): 3 expedientes.
    stats = pa.anclaje_stats(anclado)
    assert stats["expedientes_total"] == 3.0
    assert stats["servicio_pct"] == pytest.approx(100 / 3)
    assert stats["fuera_perimetro_pct"] == pytest.approx(100 / 3)
    assert stats["sin_anclar_pct"] == pytest.approx(100 / 3)
    assert stats["organica_sin_servicio_pct"] == 0.0
