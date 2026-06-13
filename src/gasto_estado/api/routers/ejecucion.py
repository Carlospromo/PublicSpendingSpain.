"""Router de ejecución presupuestaria (velocidad contable, IGAE).

Cada endpoint invoca la función pura de ``analytics.metrics`` y la envuelve en
``MetricResponse`` SIN tocar el dato ni sus metadatos (naturaleza, advertencias,
cobertura, frescura). ``nivel`` admite AGE/seccion/servicio/dg/programa/economica
/capitulo; un nivel inválido lo rechaza la métrica (→ 422 vía el manejador).
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import (
    PeriodoQuery,
    exigir_ejercicio_cargado,
    exigir_periodo_cargado,
    get_db,
)
from gasto_estado.api.models import MetricResponse

router = APIRouter(prefix="/ejecucion", tags=["ejecucion (IGAE)"])


@router.get("/grado", response_model=MetricResponse, summary="Grado de ejecución (ORN/definitivo)")
def grado(
    periodo: str = PeriodoQuery,
    nivel: str = Query("AGE"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    exigir_periodo_cargado(con, periodo)
    return MetricResponse(**metrics.grado_ejecucion(con, periodo, nivel=nivel).to_dict())


@router.get("/ritmo", response_model=MetricResponse, summary="Ritmo intra-anual (serie mensual)")
def ritmo(
    ejercicio: int = Query(..., ge=2000),
    nivel: str = Query("AGE"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    exigir_ejercicio_cargado(con, ejercicio)
    return MetricResponse(**metrics.ritmo_ejecucion(con, ejercicio, nivel=nivel).to_dict())


@router.get(
    "/interanual", response_model=MetricResponse, summary="Comparativa mismo-mes año anterior"
)
def interanual(
    periodo: str = PeriodoQuery,
    nivel: str = Query("AGE"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    exigir_periodo_cargado(con, periodo)
    return MetricResponse(**metrics.comparativa_interanual(con, periodo, nivel=nivel).to_dict())


@router.get("/modificaciones", response_model=MetricResponse, summary="Modificaciones de crédito")
def modificaciones(
    periodo: str = PeriodoQuery,
    nivel: str = Query("seccion"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    exigir_periodo_cargado(con, periodo)
    return MetricResponse(**metrics.modificaciones_credito(con, periodo, nivel=nivel).to_dict())
