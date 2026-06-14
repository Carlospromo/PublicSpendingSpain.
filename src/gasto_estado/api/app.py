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
from typing import Any

import duckdb
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gasto_estado.api.errores import registrar_manejadores
from gasto_estado.api.models import ErrorRespuesta
from gasto_estado.api.routers import (
    alertas,
    compromisos,
    cruces,
    decisiones,
    ejecucion,
    estructura,
    salud,
)

API_VERSION = "v1"
PREFIJO = f"/{API_VERSION}"

# Respuestas de error documentadas en OpenAPI para toda la superficie (cuerpo
# uniforme; ver api/errores.py y API.md).
_RESPUESTAS_ERROR: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorRespuesta, "description": "Recurso no encontrado."},
    422: {"model": ErrorRespuesta, "description": "Parámetros inválidos."},
    503: {"model": ErrorRespuesta, "description": "Warehouse no disponible."},
}

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
    registrar_manejadores(app)

    # Toda la superficie vive bajo /v1: lo incompatible irá a /v2 (ver API.md).
    for modulo in (salud, estructura, ejecucion, compromisos, decisiones, cruces, alertas):
        app.include_router(modulo.router, prefix=PREFIJO, responses=_RESPUESTAS_ERROR)

    @app.get("/", tags=["meta"], summary="Raíz: versión y enlaces a la documentación")
    def raiz() -> dict[str, str]:
        return {
            "nombre": "gasto-estado API",
            "version": API_VERSION,
            "base": PREFIJO,
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


app = create_app()
