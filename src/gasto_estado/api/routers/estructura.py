"""Router de estructura orgánica y catálogos (navegación del frontal).

Árbol AGE → secciones → servicios → (DG nominal vía crosswalk), con vigencia
temporal: cada servicio declara si su equivalencia DG es aproximada fuera del
ejercicio del seed. Solo invoca ``analytics.estructura`` (cero lógica aquí).
"""

from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import estructura
from gasto_estado.api.deps import exigir_ejercicio_cargado, get_db
from gasto_estado.api.models import (
    EconomicaModel,
    FuenteModel,
    ProgramaModel,
    SeccionModel,
    ServicioModel,
)

router = APIRouter(tags=["estructura"])


@router.get("/estructura/ejercicios", response_model=list[int], summary="Ejercicios cargados")
def ejercicios(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> list[int]:
    return estructura.ejercicios_disponibles(con)


@router.get(
    "/estructura/secciones",
    response_model=list[SeccionModel],
    summary="Secciones (ministerios) de un ejercicio",
)
def secciones(
    ejercicio: int = Query(..., ge=2000),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> list[SeccionModel]:
    exigir_ejercicio_cargado(con, ejercicio)
    return [SeccionModel(**s) for s in estructura.secciones(con, ejercicio)]


@router.get(
    "/estructura/secciones/{seccion_cod}/servicios",
    response_model=list[ServicioModel],
    summary="Servicios de una sección, con su DG nominal y la marca de vigencia",
)
def servicios(
    seccion_cod: str,
    ejercicio: int = Query(..., ge=2000),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> list[ServicioModel]:
    exigir_ejercicio_cargado(con, ejercicio)
    return [ServicioModel(**s) for s in estructura.servicios(con, ejercicio, seccion_cod)]


@router.get(
    "/catalogos/programas", response_model=list[ProgramaModel], summary="Catálogo de programas"
)
def programas(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> list[ProgramaModel]:
    return [ProgramaModel(**p) for p in estructura.catalogo_programas(con)]


@router.get(
    "/catalogos/economicas",
    response_model=list[EconomicaModel],
    summary="Catálogo de clasificación económica",
)
def economicas(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> list[EconomicaModel]:
    return [EconomicaModel(**e) for e in estructura.catalogo_economicas(con)]


@router.get(
    "/catalogos/fuentes",
    response_model=list[FuenteModel],
    summary="Fuentes con su velocidad y periodicidad",
)
def fuentes(con: duckdb.DuckDBPyConnection = Depends(get_db)) -> list[FuenteModel]:
    return [FuenteModel(**f) for f in estructura.catalogo_fuentes(con)]
