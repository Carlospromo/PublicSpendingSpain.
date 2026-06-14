"""Lanzador de materializaciones (lo que invocan el CLI y los workflows de CI).

Materializa, en proceso y con instancia efímera, el subconjunto de assets de cada
grupo (mensual / alta frecuencia) para una partición. No requiere servidor
Dagster permanente: la materialización ocurre y termina dentro del runner
(git-scraping). Es una cáscara sobre ``dagster.materialize`` + los assets.
"""

from __future__ import annotations

from datetime import date

from gasto_estado.orchestration import assets

# Selección de assets por grupo (incluye las fuentes observables necesarias como
# input). El monthly cubre la verdad contable; alta frecuencia, el resto + frescura.
_GRUPOS = {
    "mensual": [
        assets.seeds_dimensiones,
        assets.dimensiones,
        assets.fact_ejecucion,
        assets.validacion_contable,
    ],
    "alta_frecuencia": [
        assets.seeds_dimensiones,
        assets.crosswalk_servicio_dir3,
        assets.dimensiones,
        assets.fact_contratos,
        assets.fact_subvenciones,
        assets.fact_boe,
        assets.fact_acuerdos_cdm,
        assets.frescura_publicada,
    ],
}

GRUPOS = tuple(_GRUPOS)


def particion_por_defecto(grupo: str) -> str:
    """Partición por defecto: el mes en curso (mensual) o el día de hoy (alta frecuencia)."""
    hoy = date.today()
    return f"{hoy:%Y-%m}-01" if grupo == "mensual" else hoy.isoformat()


def materializar(grupo: str, *, particion: str | None = None, descargar: bool = True) -> bool:
    """Materializa el grupo para la partición (por defecto, la actual). Devuelve éxito."""
    if grupo not in _GRUPOS:
        raise ValueError(f"grupo desconocido {grupo!r}; usa {GRUPOS}.")
    import dagster

    particion = particion or particion_por_defecto(grupo)
    resultado = dagster.materialize(
        _GRUPOS[grupo],  # type: ignore[arg-type]
        partition_key=particion,
        resources={"opciones": assets.OpcionesMaterializacion(descargar=descargar)},
    )
    return bool(resultado.success)
