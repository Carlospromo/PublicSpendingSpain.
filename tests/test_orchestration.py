"""Tests de la capa de orquestación Dagster (Fase 7).

Cubren:
- Estructura del grafo (assets, grupos, dependencias correctas).
- Ledger de frescura (registrar/leer, idempotencia, ausencia graceful).
- run.py: GRUPOS, particion_por_defecto.
- Sin reimplementación: los assets son cáscaras finas que invocan pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gasto_estado.orchestration import frescura as ledger_mod
from gasto_estado.orchestration import run as run_mod
from gasto_estado.orchestration.assets import (
    OpcionesMaterializacion,
    capturas_diarias,
    crosswalk_servicio_dir3,
    dimensiones,
    fact_acuerdos_cdm,
    fact_boe,
    fact_contratos,
    fact_ejecucion,
    fact_subvenciones,
    frescura_publicada,
    periodos_igae,
    seeds_dimensiones,
    validacion_contable,
)

# ── Estructura del grafo ──────────────────────────────────────────────────────


def test_grupos_conocidos() -> None:
    assert set(run_mod.GRUPOS) == {"mensual", "alta_frecuencia"}


def test_particion_por_defecto_mensual_formato() -> None:
    p = run_mod.particion_por_defecto("mensual")
    # YYYY-MM-01
    assert len(p) == 10
    assert p.endswith("-01")
    parts = p.split("-")
    assert len(parts) == 3
    assert parts[2] == "01"


def test_particion_por_defecto_alta_frecuencia_formato() -> None:
    p = run_mod.particion_por_defecto("alta_frecuencia")
    # YYYY-MM-DD
    from datetime import date

    date.fromisoformat(p)  # no lanza ↔ formato ISO válido


def test_materializar_grupo_desconocido_lanza() -> None:
    with pytest.raises(ValueError, match="grupo desconocido"):
        run_mod.materializar("no_existe", descargar=False)


def test_assets_partitions_correct() -> None:
    # fact_ejecucion usa particiones mensuales
    assert fact_ejecucion.partitions_def is periodos_igae
    # fact_contratos, fact_subvenciones, fact_boe, fact_acuerdos_cdm: diarias
    for asset_obj in (fact_contratos, fact_subvenciones, fact_boe, fact_acuerdos_cdm):
        assert asset_obj.partitions_def is capturas_diarias, asset_obj.key


def _dep_keys(asset_obj: object) -> set[object]:
    """Extrae el conjunto de AssetKey de los que depende un asset (Dagster 1.11)."""
    # asset_deps es un dict {self_key: set[dep_key, ...]}
    deps: dict = asset_obj.asset_deps  # type: ignore[attr-defined]
    return set().union(*deps.values()) if deps else set()


def test_crosswalk_cascade_deps() -> None:
    """fact_contratos/fact_subvenciones dependen del crosswalk; fact_boe/fact_acuerdos_cdm no."""
    crosswalk_key = crosswalk_servicio_dir3.key

    assert crosswalk_key in _dep_keys(fact_contratos), "fact_contratos debe depender del crosswalk"
    assert crosswalk_key in _dep_keys(fact_subvenciones), (
        "fact_subvenciones debe depender del crosswalk"
    )
    assert crosswalk_key not in _dep_keys(fact_boe), "fact_boe NO debe depender del crosswalk"
    assert crosswalk_key not in _dep_keys(fact_acuerdos_cdm), (
        "fact_acuerdos_cdm NO debe depender del crosswalk"
    )


def test_frescura_publicada_cierra_el_grafo() -> None:
    """frescura_publicada depende de todos los hechos y de la validación."""
    dep_keys = _dep_keys(frescura_publicada)
    expected = {
        validacion_contable.key,
        fact_contratos.key,
        fact_subvenciones.key,
        fact_boe.key,
        fact_acuerdos_cdm.key,
    }
    assert expected.issubset(dep_keys)


def test_validacion_contable_depende_de_fact_ejecucion() -> None:
    dep_keys = _dep_keys(validacion_contable)
    assert fact_ejecucion.key in dep_keys


def test_dimensiones_depende_de_seeds() -> None:
    dep_keys = _dep_keys(dimensiones)
    assert seeds_dimensiones.key in dep_keys


def test_observable_source_assets_exportados() -> None:
    from dagster import SourceAsset

    assert isinstance(crosswalk_servicio_dir3, SourceAsset)
    assert isinstance(seeds_dimensiones, SourceAsset)


def test_grupos_contienen_assets_correctos() -> None:
    from gasto_estado.orchestration import run

    grupo_mensual = run._GRUPOS["mensual"]
    grupo_af = run._GRUPOS["alta_frecuencia"]

    # mensual cubre la verdad contable
    assert fact_ejecucion in grupo_mensual
    assert validacion_contable in grupo_mensual
    assert dimensiones in grupo_mensual

    # alta frecuencia cubre el resto
    assert fact_contratos in grupo_af
    assert fact_subvenciones in grupo_af
    assert fact_boe in grupo_af
    assert fact_acuerdos_cdm in grupo_af
    assert frescura_publicada in grupo_af


def test_opciones_materializacion_default() -> None:
    opciones = OpcionesMaterializacion()
    assert opciones.descargar is True


# ── Ledger de frescura ────────────────────────────────────────────────────────


def test_leer_ledger_ausente_devuelve_vacio(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    assert ledger_mod.leer(warehouse) == {}


def test_leer_ledger_corrupto_devuelve_vacio(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    ledger_mod.ledger_path(warehouse).write_text("no-es-json", encoding="utf-8")
    assert ledger_mod.leer(warehouse) == {}


def test_registrar_y_leer(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    ledger_mod.registrar(warehouse, "igae_anexo_i", particion="2026-04", filas=1234)
    datos = ledger_mod.leer(warehouse)
    assert "igae_anexo_i" in datos
    assert datos["igae_anexo_i"]["filas"] == 1234
    assert datos["igae_anexo_i"]["particion"] == "2026-04"
    assert "materializado_en" in datos["igae_anexo_i"]


def test_registrar_sobrescribe_entrada_anterior(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    ledger_mod.registrar(warehouse, "placsp", particion="2026-06-01", filas=100)
    ledger_mod.registrar(warehouse, "placsp", particion="2026-06-14", filas=200)
    datos = ledger_mod.leer(warehouse)
    assert datos["placsp"]["filas"] == 200
    assert datos["placsp"]["particion"] == "2026-06-14"


def test_registrar_multiples_fuentes(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    ledger_mod.registrar(warehouse, "igae_anexo_i", particion="2026-04", filas=10000)
    ledger_mod.registrar(warehouse, "placsp", particion="2026-06-14", filas=500)
    datos = ledger_mod.leer(warehouse)
    assert set(datos.keys()) == {"igae_anexo_i", "placsp"}


def test_ledger_es_json_legible(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    ledger_mod.registrar(warehouse, "bdns", particion="2026-06-14", filas=42)
    ruta = ledger_mod.ledger_path(warehouse)
    parsed = json.loads(ruta.read_text(encoding="utf-8"))
    assert "bdns" in parsed


def test_ledger_path_junto_al_warehouse(tmp_path: Path) -> None:
    warehouse = tmp_path / "subdir" / "warehouse.duckdb"
    ledger = ledger_mod.ledger_path(warehouse)
    assert ledger.parent == warehouse.parent
    assert ledger.name == "materializacion.json"


# ── Integración con analytics/estructura ──────────────────────────────────────


def test_frescura_fuentes_acepta_warehouse_path_none(tmp_path: Path) -> None:
    """frescura_fuentes funciona sin ledger (comportamiento pre-Dagster)."""
    from gasto_estado.analytics import estructura
    from gasto_estado.db import load

    db_path = tmp_path / "warehouse.duckdb"
    con = load.connect(db_path)
    load.init_schema(con)
    load.load_seeds(con)
    resultado = estructura.frescura_fuentes(con, warehouse_path=None)
    assert isinstance(resultado, list)
    assert len(resultado) > 0
    # Sin ledger, materializado_en es None para todas las fuentes
    for f in resultado:
        assert f["materializado_en"] is None
    con.close()


def test_frescura_fuentes_con_ledger_enriquece(tmp_path: Path) -> None:
    """frescura_fuentes añade materializado_en desde el ledger cuando existe."""
    from gasto_estado.analytics import estructura
    from gasto_estado.db import load

    db_path = tmp_path / "warehouse.duckdb"
    con = load.connect(db_path)
    load.init_schema(con)
    load.load_seeds(con)

    ledger_mod.registrar(db_path, "igae_anexo_i", particion="2026-04", filas=100)

    resultado = estructura.frescura_fuentes(con, warehouse_path=db_path)
    igae = next(f for f in resultado if f["fuente_cod"] == "igae_anexo_i")
    assert igae["materializado_en"] is not None
    # Las otras fuentes sin entrada en ledger quedan None
    placsp = next(f for f in resultado if f["fuente_cod"] == "placsp")
    assert placsp["materializado_en"] is None
    con.close()
