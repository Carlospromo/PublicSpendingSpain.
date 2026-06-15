"""Definitions de Dagster: assets, jobs y schedules (Fase 7).

Punto de entrada del repositorio Dagster (``dagster dev -m
gasto_estado.orchestration.definitions``). Define la cadencia HETEROGÉNEA de las
tres velocidades vía *schedules*, no sensores: en el modelo de disparo por CI no
hay daemon permanente que observe, así que un schedule de sondeo (en la ventana
de publicación) + la extracción ya idempotente (descarga solo lo nuevo) logra el
mismo efecto que un sensor sin requerir un proceso vivo. En un despliegue futuro
con servidor, un sensor de publicación IGAE sería preferible.

GitHub Actions es el disparador externo real (.github/workflows): su cron lanza
``gasto-estado materialize``, que materializa estos assets dentro del runner y
termina. No hay servidor Dagster permanente.
"""

from __future__ import annotations

from dagster import (
    AssetSelection,
    Definitions,
    ScheduleDefinition,
    define_asset_job,
)

from gasto_estado.orchestration import assets

# Job mensual: dimensiones → fact_ejecucion → validación (la verdad contable).
job_mensual = define_asset_job(
    name="materializacion_mensual",
    selection=AssetSelection.assets(
        assets.dimensiones, assets.fact_ejecucion, assets.validacion_contable
    ),
)

# Job semanal/diario: dimensiones + las fuentes de alta frecuencia + frescura.
job_alta_frecuencia = define_asset_job(
    name="materializacion_alta_frecuencia",
    selection=AssetSelection.assets(
        assets.dimensiones,
        assets.fact_contratos,
        assets.fact_subvenciones,
        assets.fact_boe,
        assets.fact_acuerdos_cdm,
        assets.frescura_publicada,
    ),
)

# Cadencia (reflejada también en los workflows de Actions, que son el disparo real):
# - IGAE: sondeo diario en la ventana 20–31 (la IGAE publica ~25–30 días tras cierre,
#   con desfase variable); la extracción idempotente sale sin cambios si no hay dato.
# - Alta frecuencia: lunes (PLACSP/BDNS/BOE diarios; CdM semanal, publica los martes).
schedule_mensual = ScheduleDefinition(
    name="sonda_igae_mensual", job=job_mensual, cron_schedule="0 6 20-31 * *"
)
schedule_alta_frecuencia = ScheduleDefinition(
    name="alta_frecuencia_semanal", job=job_alta_frecuencia, cron_schedule="0 5 * * 1"
)

defs = Definitions(
    assets=[
        assets.seeds_dimensiones,
        assets.crosswalk_servicio_dir3,
        assets.dimensiones,
        assets.fact_ejecucion,
        assets.fact_contratos,
        assets.fact_subvenciones,
        assets.fact_boe,
        assets.fact_acuerdos_cdm,
        assets.validacion_contable,
        assets.frescura_publicada,
    ],
    jobs=[job_mensual, job_alta_frecuencia],
    schedules=[schedule_mensual, schedule_alta_frecuencia],
    resources={"opciones": assets.OpcionesMaterializacion()},
)
