"""Router de decisiones políticas (BOE + Consejo de Ministros).

Acuerdos/disposiciones por ministerio/sección y periodo. El importe es de
extracción falible: la métrica lo desglosa por confianza y la respuesta marca su
naturaleza ``aproximada``. No se sirve un importe agregado sin esa salvedad.
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import get_db
from gasto_estado.api.models import MetricResponse

router = APIRouter(prefix="/decisiones", tags=["decisiones (BOE/CdM)"])

_FUENTES = {"boe", "cdm"}


@router.get(
    "/{fuente}/volumen",
    response_model=MetricResponse,
    summary="Volumen de decisiones por sección/ministerio y tipo",
)
def volumen(
    fuente: str,
    periodo: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    ejercicio: int | None = Query(None, ge=2000),
    nivel: str = Query("seccion"),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricResponse:
    if fuente not in _FUENTES:
        raise HTTPException(status_code=404, detail=f"Fuente desconocida: {fuente} (usa boe|cdm).")
    res = metrics.volumen_decisiones(con, fuente, periodo=periodo, ejercicio=ejercicio, nivel=nivel)
    return MetricResponse(**res.to_dict())
