"""Router de estructura orgánica y catálogos (navegación del frontal).

Árbol AGE → secciones → servicios → (DG nominal vía crosswalk), con vigencia
temporal: cada servicio declara si su equivalencia DG es aproximada fuera del
ejercicio del seed. Solo invoca ``analytics.estructura`` (cero lógica aquí).
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import estructura
from gasto_estado.api.deps import exigir_ejercicio_cargado, get_db, paginacion_params
from gasto_estado.api.models import (
    EconomicaModel,
    Envelope,
    FuenteModel,
    ProgramaModel,
    SeccionModel,
    ServicioModel,
)
from gasto_estado.api.respuestas import envolver_coleccion

router = APIRouter(tags=["estructura"])


@router.get(
    "/estructura/ejercicios", response_model=Envelope[list[int]], summary="Ejercicios cargados"
)
def ejercicios(
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[int]]:
    return envolver_coleccion(estructura.ejercicios_disponibles(con), pagina=pag[0], tamano=pag[1])


@router.get(
    "/estructura/secciones",
    response_model=Envelope[list[SeccionModel]],
    summary="Secciones (ministerios) de un ejercicio",
)
def secciones(
    ejercicio: int = Query(..., ge=2000),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[SeccionModel]]:
    exigir_ejercicio_cargado(con, ejercicio)
    items = [SeccionModel(**s) for s in estructura.secciones(con, ejercicio)]
    return envolver_coleccion(items, pagina=pag[0], tamano=pag[1])


@router.get(
    "/estructura/secciones/{seccion_cod}/servicios",
    response_model=Envelope[list[ServicioModel]],
    summary="Servicios de una sección, con su DG nominal y la marca de vigencia",
)
def servicios(
    seccion_cod: str,
    ejercicio: int = Query(..., ge=2000),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[ServicioModel]]:
    exigir_ejercicio_cargado(con, ejercicio)
    items = [ServicioModel(**s) for s in estructura.servicios(con, ejercicio, seccion_cod)]
    return envolver_coleccion(items, pagina=pag[0], tamano=pag[1])


@router.get(
    "/catalogos/programas",
    response_model=Envelope[list[ProgramaModel]],
    summary="Catálogo de programas",
)
def programas(
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[ProgramaModel]]:
    items = [ProgramaModel(**p) for p in estructura.catalogo_programas(con)]
    return envolver_coleccion(items, pagina=pag[0], tamano=pag[1])


@router.get(
    "/catalogos/economicas",
    response_model=Envelope[list[EconomicaModel]],
    summary="Catálogo de clasificación económica",
)
def economicas(
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[EconomicaModel]]:
    items = [EconomicaModel(**e) for e in estructura.catalogo_economicas(con)]
    return envolver_coleccion(items, pagina=pag[0], tamano=pag[1])


@router.get(
    "/catalogos/fuentes",
    response_model=Envelope[list[FuenteModel]],
    summary="Fuentes con su velocidad y periodicidad",
)
def fuentes(
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[FuenteModel]]:
    items = [FuenteModel(**f) for f in estructura.catalogo_fuentes(con)]
    return envolver_coleccion(items, pagina=pag[0], tamano=pag[1])
