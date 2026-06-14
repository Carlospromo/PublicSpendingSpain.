"""Router de salud y frescura (objetivo 5 de CLAUDE.md §1).

Materializa "siempre actualizado, y que se vea hasta dónde": el frontal consulta
aquí hasta qué fecha llega cada fuente sin adivinar.
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Request

from gasto_estado.analytics import estructura
from gasto_estado.api.deps import get_db, paginacion_params
from gasto_estado.api.models import Envelope, FrescuraFuenteModel, SaludModel
from gasto_estado.api.respuestas import envolver_coleccion, envolver_objeto

router = APIRouter(tags=["salud"])

_PERIMETRO = "AGE + organismos estatales (sin CCAA ni entes locales)"
_COBERTURA_DG = (
    "Las métricas/alertas a nivel dirección general cubren la porción del gasto con anclaje "
    "DIR3 (~27% de la ORN); el resto se observa a nivel sección."
)


@router.get("/salud", response_model=Envelope[SaludModel], summary="Salud del warehouse")
def salud(request: Request) -> Envelope[SaludModel]:
    """Estado del warehouse. Responde 200 SIEMPRE: si no está disponible, accesible=False.

    Es el endpoint que el frontal consulta para saber si hay datos, así que no debe
    fallar cuando el warehouse aún no se ha construido.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        modelo = SaludModel(
            accesible=False, ejercicios=[], n_periodos_igae=0,
            perimetro=_PERIMETRO, cobertura_dg_nota=_COBERTURA_DG,
        )
    else:
        modelo = SaludModel(**estructura.salud(db.cursor()))
    return envolver_objeto(modelo)


@router.get(
    "/frescura",
    response_model=Envelope[list[FrescuraFuenteModel]],
    summary="Frescura por fuente (último periodo/captura cargado)",
)
def frescura(
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[FrescuraFuenteModel]]:
    pagina, tamano = pag
    items = [FrescuraFuenteModel(**f) for f in estructura.frescura_fuentes(con)]
    return envolver_coleccion(items, pagina=pagina, tamano=tamano)
