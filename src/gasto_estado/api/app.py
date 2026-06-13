"""Aplicación FastAPI: capa de exposición de SOLO LECTURA para el frontal (Fase 6).

CLAUDE.md §1 (objetivo 4) y §5: API limpia y autoexplicativa que el frontal web
consumirá. Capa FINA (§2): no contiene lógica de negocio; cada endpoint invoca las
funciones puras de ``analytics`` y propaga sus metadatos de fiabilidad intactos.

Servir el warehouse: el lifespan abre UNA conexión ``read_only=True`` al fichero
DuckDB (``settings.WAREHOUSE_PATH``) y cada petición recibe un cursor propio
(``deps.get_db``). Si el warehouse no existe, la app arranca igual pero los
endpoints de datos responden 503 y ``/salud`` lo refleja: el contrato OpenAPI se
genera sin depender de que haya datos.

El contrato fino/estable y la paginación avanzada son el Prompt 15; aquí los
endpoints existen con validación y paginación básicas, sin congelar el contrato.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import duckdb
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gasto_estado.api.routers import (
    alertas,
    compromisos,
    cruces,
    decisiones,
    ejecucion,
    estructura,
    salud,
)

DESCRIPCION = (
    "API de solo lectura del gasto del Estado español a nivel de servicio "
    "presupuestario / dirección general. Expone las tres velocidades (ejecución "
    "contable IGAE; compromisos PLACSP/BDNS; decisiones BOE/Consejo de Ministros), "
    "sus cruces indiciarios y las alertas analíticas, con metadatos de fiabilidad "
    "(naturaleza, confianza, cobertura de anclaje, advertencias) y frescura. "
    "La equivalencia dirección general es nominal vía crosswalk y aproximada fuera "
    "del ejercicio del seed; viaja marcada en cada respuesta pertinente."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre la conexión read-only al warehouse al arrancar; la cierra al parar."""
    from config import settings

    path = settings.WAREHOUSE_PATH
    app.state.warehouse_path = path
    app.state.db = duckdb.connect(str(path), read_only=True) if path.exists() else None
    try:
        yield
    finally:
        if getattr(app.state, "db", None) is not None:
            app.state.db.close()


def create_app(cors_origins: list[str] | None = None) -> FastAPI:
    """Construye la app FastAPI (factoría; sin efectos hasta el lifespan)."""
    app = FastAPI(
        title="gasto-estado API",
        version="0.1.0",
        description=DESCRIPCION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],  # el frontal vive en otro origen
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        # Las funciones puras validan su entrada con ValueError (nivel/periodo
        # inválido): se traduce a 422, no a un 500 opaco.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    for modulo in (salud, estructura, ejecucion, compromisos, decisiones, cruces, alertas):
        app.include_router(modulo.router)

    @app.get("/", tags=["salud"], summary="Raíz: enlaces a la documentación")
    def raiz() -> dict[str, str]:
        return {"nombre": "gasto-estado API", "docs": "/docs", "openapi": "/openapi.json"}

    return app


app = create_app()
