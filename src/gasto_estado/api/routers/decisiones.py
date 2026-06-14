"""Router de decisiones políticas (BOE + Consejo de Ministros).

Acuerdos/disposiciones por ministerio/sección y periodo. El importe es de
extracción falible: la métrica lo desglosa por confianza y ``meta.naturaleza`` es
``aproximada``. No se sirve un importe agregado sin esa salvedad.
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from gasto_estado.analytics import metrics
from gasto_estado.api.deps import get_db, paginacion_params
from gasto_estado.api.models import Envelope
from gasto_estado.api.respuestas import envolver_metrica

router = APIRouter(prefix="/decisiones", tags=["decisiones (BOE/CdM)"])

MetricEnvelope = Envelope[list[dict[str, Any]]]
_FUENTES = {"boe", "cdm"}


@router.get(
    "/{fuente}/volumen",
    response_model=MetricEnvelope,
    summary="Volumen de decisiones por sección/ministerio y tipo",
)
def volumen(
    fuente: str,
    periodo: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    ejercicio: int | None = Query(None, ge=2000),
    nivel: str = Query("seccion"),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> MetricEnvelope:
    if fuente not in _FUENTES:
        raise HTTPException(status_code=404, detail=f"Fuente desconocida: {fuente} (usa boe|cdm).")
    res = metrics.volumen_decisiones(con, fuente, periodo=periodo, ejercicio=ejercicio, nivel=nivel)
    return envolver_metrica(res, pagina=pag[0], tamano=pag[1])
