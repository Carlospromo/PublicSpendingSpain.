"""Router de cruces entre velocidades (INDICIARIOS).

Compromiso (PLACSP) frente a ejecución (ORN) y decisión (CdM) frente a
compromiso. ``meta.naturaleza='indiciaria'`` y las filas exponen SIEMPRE ambas
magnitudes por separado además del ratio; las advertencias inseparables viajan en
``meta.advertencias``. No es una conciliación contable.
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import PeriodoQuery, exigir_periodo_cargado, get_db, paginacion_params
from gasto_estado.api.models import Envelope
from gasto_estado.api.respuestas import envolver_metrica

router = APIRouter(prefix="/cruces", tags=["cruces (indiciarios)"])

MetricEnvelope = Envelope[list[dict[str, Any]]]


@router.get(
    "/compromiso-ejecucion",
    response_model=MetricEnvelope,
    summary="Adjudicación PLACSP vs ORN IGAE (indiciario)",
)
def compromiso_ejecucion(
    periodo: str = PeriodoQuery,
    nivel: str = Query("seccion"),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    exigir_periodo_cargado(con, periodo)
    res = metrics.compromiso_vs_ejecucion(con, periodo, nivel=nivel)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])


@router.get(
    "/decisiones-compromiso",
    response_model=MetricEnvelope,
    summary="Autorización de gasto CdM vs adjudicación PLACSP (indiciario)",
)
def decisiones_compromiso(
    ejercicio: int = Query(..., ge=2000),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    res = metrics.decisiones_vs_compromiso(con, ejercicio=ejercicio)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])
