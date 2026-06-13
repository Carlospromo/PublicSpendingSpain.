"""Router de compromisos jurídicos (PLACSP + BDNS).

Volúmenes y concentración por órgano/servicio/DG y ventana temporal. La tasa y
fiabilidad de anclaje viajan en ``cobertura_anclaje`` de cada respuesta (no se
oculta qué fracción del importe no se ha podido atribuir).
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import get_db
from gasto_estado.api.models import MetricResponse

router = APIRouter(tags=["compromisos (PLACSP/BDNS)"])


@router.get(
    "/contratos/volumen", response_model=MetricResponse, summary="Importe adjudicado (PLACSP)"
)
def contratos_volumen(
    periodo: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    ejercicio: int | None = Query(None, ge=2000),
    nivel: str = Query("seccion"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    res = metrics.volumen_adjudicacion(con, periodo=periodo, ejercicio=ejercicio, nivel=nivel)
    return MetricResponse(**res.to_dict())


@router.get(
    "/subvenciones/volumen", response_model=MetricResponse, summary="Importe concedido (BDNS)"
)
def subvenciones_volumen(
    periodo: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    ejercicio: int | None = Query(None, ge=2000),
    nivel: str = Query("seccion"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    res = metrics.volumen_concesion(con, periodo=periodo, ejercicio=ejercicio, nivel=nivel)
    return MetricResponse(**res.to_dict())


@router.get(
    "/contratos/concentracion",
    response_model=MetricResponse,
    summary="Concentración de adjudicatarios (top-N, HHI)",
)
def concentracion(
    ejercicio: int | None = Query(None, ge=2000),
    periodo: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    nivel: str = Query("servicio"),
    top_n: int = Query(5, ge=1, le=50),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    res = metrics.concentracion_adjudicatarios(
        con, nivel=nivel, ejercicio=ejercicio, periodo=periodo, top_n=top_n
    )
    return MetricResponse(**res.to_dict())
