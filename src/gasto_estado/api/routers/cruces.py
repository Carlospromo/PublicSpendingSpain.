"""Router de cruces entre velocidades (INDICIARIOS).

Compromiso (PLACSP) frente a ejecución (ORN) y decisión (CdM) frente a
compromiso. La respuesta es ``naturaleza='indiciaria'`` y expone SIEMPRE ambas
magnitudes por separado además del ratio; las advertencias inseparables viajan
intactas. No es una conciliación contable.
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import PeriodoQuery, exigir_periodo_cargado, get_db
from gasto_estado.api.models import MetricResponse

router = APIRouter(prefix="/cruces", tags=["cruces (indiciarios)"])


@router.get(
    "/compromiso-ejecucion",
    response_model=MetricResponse,
    summary="Adjudicación PLACSP vs ORN IGAE (indiciario)",
)
def compromiso_ejecucion(
    periodo: str = PeriodoQuery,
    nivel: str = Query("seccion"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    exigir_periodo_cargado(con, periodo)
    return MetricResponse(**metrics.compromiso_vs_ejecucion(con, periodo, nivel=nivel).to_dict())


@router.get(
    "/decisiones-compromiso",
    response_model=MetricResponse,
    summary="Autorización de gasto CdM vs adjudicación PLACSP (indiciario)",
)
def decisiones_compromiso(
    ejercicio: int = Query(..., ge=2000),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    return MetricResponse(**metrics.decisiones_vs_compromiso(con, ejercicio=ejercicio).to_dict())
