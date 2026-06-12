"""Tests del anclaje orgánico BDNS: órgano concedente SIN DIR3 (Fase 4).

La API del SNPSAP solo publica la jerarquía administrativa como texto
(``nivel1/nivel2/nivel3``); aquí se fija el contrato de la resolución por
denominación (override > exacta en subárbol del ministerio > tokens en
subárbol > nombre único global) y su delegación en el motor DIR3 común.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gasto_estado.transform import anclaje_organico as ao

# Árbol sintético con DOS ministerios que comparten el nombre de una DG (la
# colisión real que obliga al scoping por nivel2) y un ente EPE instrumental.
_DIM = pd.DataFrame(
    [
        # dir3, padre, tipo_entidad, denominacion, nivel_jerarquico, ministerio
        ("E00000001", None, "MN", "Ministerio de Pruebas", 1, "E00000001"),
        ("E00000002", "E00000001", "MN", "Dirección General de Cosas", 3, "E00000001"),
        ("E00000010", None, "MN", "Ministerio Segundo", 1, "E00000010"),
        ("E00000011", "E00000010", "MN", "Dirección General de Cosas", 3, "E00000010"),
        # Nombre único en todo el directorio (resolución global).
        ("E00000012", "E00000010", "MN", "Instituto Único Nacional", 3, "E00000010"),
        # EPE instrumental: presupuesto propio, no asciende al ministerio.
        ("EA0000004", "E00000001", "EE", "Entidad Pública Empresarial Roja", 2, "E00000001"),
    ],
    columns=[
        "dir3_cod",
        "dir3_padre_cod",
        "tipo_entidad",
        "denominacion",
        "nivel_jerarquico",
        "ministerio_dir3_cod",
    ],
)
_DIM["fecha_inicio"] = pd.Timestamp("2000-01-01")
_DIM["fecha_fin"] = pd.NaT

_CROSSWALK = pd.DataFrame(
    [(2026, "20", "03", "E00000002"), (2026, "27", "05", "E00000011")],
    columns=["ejercicio", "seccion_cod", "servicio_cod", "dir3_cod"],
)

_FECHA = date(2026, 6, 1)


@pytest.fixture(scope="module")
def anclador() -> ao.Anclador:
    return ao.Anclador(_DIM, _CROSSWALK)


def test_exacta_en_subarbol_del_ministerio(anclador: ao.Anclador) -> None:
    # El mismo nombre de DG existe en dos ministerios: el scoping por nivel2
    # resuelve cada uno al suyo (la global ambigua habría devuelto None).
    assert (
        anclador.resolver_denominacion("MINISTERIO DE PRUEBAS", "DIRECCIÓN GENERAL DE COSAS")
        == "E00000002"
    )
    assert (
        anclador.resolver_denominacion("MINISTERIO SEGUNDO", "DIRECCIÓN GENERAL DE COSAS")
        == "E00000011"
    )


def test_tokens_en_subarbol_ignora_stopwords(anclador: ao.Anclador) -> None:
    # "DE LAS COSAS" vs "DE COSAS": mismo conjunto de tokens significativos.
    assert (
        anclador.resolver_denominacion("MINISTERIO DE PRUEBAS", "DIRECCIÓN GENERAL DE LAS COSAS")
        == "E00000002"
    )


def test_global_solo_si_unica(anclador: ao.Anclador) -> None:
    # Ministerio no resuelto + nombre único en el directorio: resuelve.
    assert (
        anclador.resolver_denominacion("MINISTERIO DESCONOCIDO", "INSTITUTO ÚNICO NACIONAL")
        == "E00000012"
    )
    # Nombre ambiguo (existe en dos ministerios): NO se inventa una elección.
    assert (
        anclador.resolver_denominacion("MINISTERIO DESCONOCIDO", "DIRECCIÓN GENERAL DE COSAS")
        is None
    )
    assert anclador.resolver_denominacion("MINISTERIO DE PRUEBAS", None) is None


def test_override_prevalece(anclador: ao.Anclador) -> None:
    overrides = {"nombre que la bdns escribe raro": "E00000002"}
    assert (
        anclador.resolver_denominacion(
            "MINISTERIO SEGUNDO", "NOMBRE QUE LA BDNS ESCRIBE RARO", overrides
        )
        == "E00000002"
    )


def test_load_overrides_organo(tmp_path: Path) -> None:
    csv = tmp_path / "overrides.csv"
    csv.write_text(
        "# comentario\n"
        "organo_bdns,dir3_cod,nota\n"
        '"DIRECCIÓN GENERAL DE COSAS RARAS",E00000002,"verificado a mano"\n',
        encoding="utf-8",
    )
    overrides = ao.load_overrides_organo(csv)
    assert overrides == {"direccion general de cosas raras": "E00000002"}


def test_overrides_reales_apuntan_a_dir3_validos() -> None:
    # El seed versionado debe cargar y todas sus claves resolver a un DIR3.
    seeds = Path(__file__).parents[1] / "src" / "gasto_estado" / "db" / "seeds"
    overrides = ao.load_overrides_organo(seeds / "crosswalk_organo_bdns_dir3.csv")
    assert overrides  # no vacío
    assert all(ao._DIR3_RE.match(dir3) for dir3 in overrides.values())


def test_anclar_organo_no_estatal_fuera_perimetro(anclador: ao.Anclador) -> None:
    out = anclador.anclar_organo_bdns(
        "AUTONOMICA", "COMUNIDAD FORAL DE NAVARRA", "DEPARTAMENTO X", _FECHA, 2026
    )
    assert out["anclaje_tipo"] == ao.ANCLA_FUERA_PERIMETRO
    assert out["anclaje_senal"] == ao.SENAL_NO_ESTATAL
    assert out["anclaje_dir3_cod"] is None


def test_anclar_organo_estatal_no_resuelto(anclador: ao.Anclador) -> None:
    out = anclador.anclar_organo_bdns(
        "ESTADO", "MINISTERIO DE PRUEBAS", "ÓRGANO INEXISTENTE", _FECHA, 2026
    )
    assert out["anclaje_tipo"] == ao.ANCLA_SIN_ANCLAR
    assert out["anclaje_senal"] == ao.SENAL_ORGANO_NO_RESUELTO


def test_anclar_organo_resuelto_delega_en_motor_dir3(anclador: ao.Anclador) -> None:
    out = anclador.anclar_organo_bdns(
        "ESTADO", "MINISTERIO DE PRUEBAS", "DIRECCIÓN GENERAL DE COSAS", _FECHA, 2026
    )
    assert out["anclaje_tipo"] == ao.ANCLA_SERVICIO
    assert out["anclaje_senal"] == ao.SENAL_DIR3_DIRECTO
    assert (out["seccion_cod"], out["servicio_cod"]) == ("20", "03")
    # La EPE resuelve por nombre pero la frontera de perímetro la retiene.
    epe = anclador.anclar_organo_bdns(
        "ESTADO", "MINISTERIO DE PRUEBAS", "ENTIDAD PÚBLICA EMPRESARIAL ROJA", _FECHA, 2026
    )
    assert epe["anclaje_tipo"] == ao.ANCLA_ORGANICA_SIN_SERVICIO
    assert epe["anclaje_senal"] == ao.SENAL_ENTIDAD_INSTRUMENTAL


def test_anclar_concesiones_y_stats() -> None:
    concesiones = pd.DataFrame(
        {
            "concesion_id": ["1", "2", "3", "4"],
            "nivel1": ["ESTADO", "ESTADO", "AUTONOMICA", "ESTADO"],
            "nivel2": ["MINISTERIO DE PRUEBAS", "MINISTERIO DE PRUEBAS", "NAVARRA", None],
            "nivel3": [
                "DIRECCIÓN GENERAL DE COSAS",
                "ÓRGANO INEXISTENTE",
                "DEPARTAMENTO X",
                "INSTITUTO ÚNICO NACIONAL",
            ],
            "fecha_concesion": [date(2026, 6, 1), date(2026, 6, 2), None, None],
            "fecha_alta": [None, None, date(2026, 6, 3), date(2026, 6, 3)],
            "periodo": ["2026-06", "2026-06", "2026-06", "2026-06"],
        }
    )
    anclado = ao.anclar_concesiones(concesiones, _DIM, _CROSSWALK)
    assert list(anclado["anclaje_tipo"]) == [
        ao.ANCLA_SERVICIO,
        ao.ANCLA_SIN_ANCLAR,
        ao.ANCLA_FUERA_PERIMETRO,
        ao.ANCLA_ORGANICA_SIN_SERVICIO,  # único global, pero sin crosswalk
    ]
    assert set(ao.ANCLAJE_COLUMNS) <= set(anclado.columns)
    stats = ao.anclaje_stats(anclado, unidad_col="concesion_id")
    assert stats["unidades_total"] == 4.0
    assert stats["servicio_pct"] == pytest.approx(25.0)
    assert stats["sin_anclar_pct"] == pytest.approx(25.0)
