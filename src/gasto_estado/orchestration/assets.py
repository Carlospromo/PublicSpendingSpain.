"""Software-defined assets de Dagster (Fase 7).

Cada asset es una CÁSCARA FINA que invoca ``orchestration.pipeline`` (que a su vez
invoca extractores/parsers/carga/checks ya probados). Dagster define QUÉ se
ejecuta y en qué ORDEN; no reimplementa nada. El grafo refleja las dependencias
reales (docs/orquestacion.md):

    seeds (fuentes observables) → dimensiones → hechos → validación → frescura

Invalidación en cascada: ``crosswalk_servicio_dir3`` es una fuente observable cuya
versión de datos es el hash del fichero; ``fact_contratos`` y ``fact_subvenciones``
dependen de ella (la usan para anclar), de modo que cambiar el crosswalk los marca
obsoletos. Particiones: fact_ejecucion por mes; los hechos de alta frecuencia por
día de captura (backfill y carga incremental reproducibles).
"""

import hashlib
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    ConfigurableResource,
    DailyPartitionsDefinition,
    DataVersion,
    MaterializeResult,
    MonthlyPartitionsDefinition,
    asset,
    observable_source_asset,
)

from gasto_estado.db import load
from gasto_estado.orchestration import pipeline

SEEDS_DIR = load.SEEDS_DIR

# Particiones que reflejan la periodicidad real (CLAUDE.md §3).
periodos_igae = MonthlyPartitionsDefinition(start_date="2015-01-01")
capturas_diarias = DailyPartitionsDefinition(start_date="2012-01-01")


class OpcionesMaterializacion(ConfigurableResource):  # type: ignore[type-arg]
    """Opciones de ejecución. ``descargar``: bajar raw nuevo antes de cargar (CI=True)."""

    descargar: bool = True


def _rutas() -> tuple[Path, Path]:
    """Rutas del warehouse y del raw (de config/settings, perezoso)."""
    from config import settings

    return settings.WAREHOUSE_PATH, settings.RAW_DIR


def _hash_fichero(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:16] if ruta.exists() else "ausente"


def data_version_crosswalk(seeds_dir: Path = SEEDS_DIR) -> str:
    """Versión de datos del crosswalk = hash de su fichero (cambia ⇒ cascada)."""
    return _hash_fichero(seeds_dir / "crosswalk_servicio_dir3.csv")


def data_version_seeds(seeds_dir: Path = SEEDS_DIR) -> str:
    h = hashlib.sha256()
    for nombre in ("dim_organica.csv", "dim_seccion_servicio.csv"):
        h.update(_hash_fichero(seeds_dir / nombre).encode())
    return h.hexdigest()[:16]


# --- Fuentes observables (su cambio invalida aguas abajo) --------------------


@observable_source_asset(group_name="referencia")
def crosswalk_servicio_dir3() -> DataVersion:
    """Crosswalk servicio↔DIR3 (seed). Lo usan los anclajes de PLACSP/BDNS."""
    return DataVersion(data_version_crosswalk())


@observable_source_asset(group_name="referencia")
def seeds_dimensiones() -> DataVersion:
    """Seeds de dimensiones (dim_organica, dim_seccion_servicio)."""
    return DataVersion(data_version_seeds())


# --- Dimensiones (reference layer cargada en el warehouse) -------------------


@asset(group_name="referencia", deps=[seeds_dimensiones])
def dimensiones() -> MaterializeResult:  # type: ignore[type-arg]
    """Esquema + seeds en el warehouse (aguas arriba de todos los hechos)."""
    db_path, _ = _rutas()
    res = pipeline.materializar_dimensiones(db_path)
    return MaterializeResult(metadata={"filas_dim_seccion_servicio": res.filas})


# --- Hechos por fuente (cada uno depende de lo que necesita para anclar) ------


@asset(group_name="hechos", partitions_def=periodos_igae, deps=[dimensiones])
def fact_ejecucion(
    context: AssetExecutionContext, opciones: OpcionesMaterializacion
) -> MaterializeResult:  # type: ignore[type-arg]
    """Ejecución IGAE (Anexo I), partición mensual. Skip si el mes no está publicado."""
    db_path, raw_dir = _rutas()
    periodo = context.partition_key[:7]  # 'YYYY-MM-01' → 'YYYY-MM'
    res = pipeline.materializar_ejecucion(db_path, raw_dir, periodo, descargar=opciones.descargar)
    return MaterializeResult(metadata={"periodo": periodo, "filas": res.filas})


@asset(
    group_name="hechos",
    partitions_def=capturas_diarias,
    deps=[dimensiones, crosswalk_servicio_dir3],
)
def fact_contratos(
    context: AssetExecutionContext, opciones: OpcionesMaterializacion
) -> MaterializeResult:  # type: ignore[type-arg]
    """Contratos PLACSP. Depende del crosswalk (anclaje a servicio/DIR3)."""
    db_path, raw_dir = _rutas()
    res = pipeline.materializar_placsp(
        db_path, raw_dir, capturas=[context.partition_key], descargar=opciones.descargar
    )
    return MaterializeResult(metadata={"captura": context.partition_key, "filas": res.filas})


@asset(
    group_name="hechos",
    partitions_def=capturas_diarias,
    deps=[dimensiones, crosswalk_servicio_dir3],
)
def fact_subvenciones(
    context: AssetExecutionContext, opciones: OpcionesMaterializacion
) -> MaterializeResult:  # type: ignore[type-arg]
    """Subvenciones BDNS. Depende del crosswalk (anclaje a servicio/DIR3)."""
    db_path, raw_dir = _rutas()
    res = pipeline.materializar_bdns(
        db_path, raw_dir, capturas=[context.partition_key], descargar=opciones.descargar
    )
    return MaterializeResult(metadata={"captura": context.partition_key, "filas": res.filas})


@asset(group_name="hechos", partitions_def=capturas_diarias, deps=[dimensiones])
def fact_boe(
    context: AssetExecutionContext, opciones: OpcionesMaterializacion
) -> MaterializeResult:  # type: ignore[type-arg]
    """Disposiciones BOE. Ancla a sección (no usa el crosswalk DIR3)."""
    db_path, raw_dir = _rutas()
    res = pipeline.materializar_boe(
        db_path, raw_dir, capturas=[context.partition_key], descargar=opciones.descargar
    )
    return MaterializeResult(metadata={"captura": context.partition_key, "filas": res.filas})


@asset(group_name="hechos", partitions_def=capturas_diarias, deps=[dimensiones])
def fact_acuerdos_cdm(
    context: AssetExecutionContext, opciones: OpcionesMaterializacion
) -> MaterializeResult:  # type: ignore[type-arg]
    """Acuerdos del Consejo de Ministros. Ancla a sección."""
    db_path, raw_dir = _rutas()
    res = pipeline.materializar_cdm(
        db_path, raw_dir, capturas=[context.partition_key], descargar=opciones.descargar
    )
    return MaterializeResult(metadata={"captura": context.partition_key, "filas": res.filas})


# --- Validación (gate) y analítica de frescura -------------------------------


@asset(group_name="validacion", deps=[fact_ejecucion])
def validacion_contable() -> MaterializeResult:  # type: ignore[type-arg]
    """Gate: los checks contables de la Fase 3 deben pasar (fail loud si FAIL)."""
    db_path, _ = _rutas()
    n = pipeline.validar_contabilidad(db_path)
    return MaterializeResult(metadata={"reglas_evaluadas": n})


@asset(
    group_name="analitica",
    deps=[validacion_contable, fact_contratos, fact_subvenciones, fact_boe, fact_acuerdos_cdm],
)
def frescura_publicada() -> MaterializeResult:  # type: ignore[type-arg]
    """Snapshot de frescura por fuente (lo que la API expone). Cierra el grafo."""
    from gasto_estado.orchestration import frescura

    db_path, _ = _rutas()
    estado = frescura.leer(db_path)
    return MaterializeResult(metadata={"fuentes_registradas": len(estado)})
