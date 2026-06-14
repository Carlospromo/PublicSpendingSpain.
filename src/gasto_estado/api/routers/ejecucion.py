"""Router de ejecución presupuestaria (velocidad contable, IGAE).

Cada endpoint invoca la función pura de ``analytics.metrics`` y la envuelve en
``{data, meta}`` SIN tocar el dato ni sus metadatos (naturaleza, advertencias,
cobertura, frescura). ``nivel`` admite AGE/seccion/servicio/dg/programa/economica
/capitulo; un nivel inválido lo rechaza la métrica (→ 422 vía el manejador).
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import (
    PeriodoQuery,
    exigir_ejercicio_cargado,
    exigir_periodo_cargado,
    get_db,
    paginacion_params,
)
from gasto_estado.api.models import Envelope, NivelAgregacion
from gasto_estado.api.respuestas import envolver_metrica

router = APIRouter(prefix="/ejecucion", tags=["ejecucion (IGAE)"])

MetricEnvelope = Envelope[list[dict[str, Any]]]


@router.get("/grado", response_model=MetricEnvelope, summary="Grado de ejecución (ORN/definitivo)")
def grado(
    periodo: str = PeriodoQuery,
    nivel: NivelAgregacion = Query(NivelAgregacion.AGE),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    exigir_periodo_cargado(con, periodo)
    res = metrics.grado_ejecucion(con, periodo, nivel=nivel.value)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])


@router.get("/ritmo", response_model=MetricEnvelope, summary="Ritmo intra-anual (serie mensual)")
def ritmo(
    ejercicio: int = Query(..., ge=2000),
    nivel: NivelAgregacion = Query(NivelAgregacion.AGE),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    exigir_ejercicio_cargado(con, ejercicio)
    res = metrics.ritmo_ejecucion(con, ejercicio, nivel=nivel.value)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])


@router.get(
    "/interanual", response_model=MetricEnvelope, summary="Comparativa mismo-mes año anterior"
)
def interanual(
    periodo: str = PeriodoQuery,
    nivel: NivelAgregacion = Query(NivelAgregacion.AGE),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    exigir_periodo_cargado(con, periodo)
    res = metrics.comparativa_interanual(con, periodo, nivel=nivel.value)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])


@router.get("/modificaciones", response_model=MetricEnvelope, summary="Modificaciones de crédito")
def modificaciones(
    periodo: str = PeriodoQuery,
    nivel: NivelAgregacion = Query(NivelAgregacion.seccion),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    exigir_periodo_cargado(con, periodo)
    res = metrics.modificaciones_credito(con, periodo, nivel=nivel.value)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])
