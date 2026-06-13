"""Dependencias compartidas de la API: conexión read-only y validación de entrada.

Conexión a DuckDB (CLAUDE.md §2, decisión documentada): la app abre UNA conexión
``read_only=True`` al warehouse en el arranque (lifespan) y cada petición recibe
un ``.cursor()`` propio. El cursor aísla el catálogo temporal por petición (las
funciones analíticas materializan vistas como ``_cw_dg``), de modo que peticiones
concurrentes —uvicorn ejecuta los endpoints síncronos en un threadpool— no se
pisan. read-only garantiza que la API jamás escribe (objetivo de exposición pura).
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
from fastapi import HTTPException, Query, Request

# Periodo presupuestario YYYY-MM (validado en la query → 422 si no casa).
PeriodoQuery = Query(..., pattern=r"^\d{4}-\d{2}$", description="Periodo mensual YYYY-MM")


def get_db(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    """Cede un cursor read-only del warehouse; 503 si el warehouse no está disponible."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Warehouse no disponible (no construido).")
    cursor = db.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def exigir_periodo_cargado(con: duckdb.DuckDBPyConnection, periodo: str) -> None:
    """404 si el periodo IGAE no está cargado (distingue 'sin dato' de 'vacío')."""
    existe = con.execute(
        "SELECT 1 FROM fact_ejecucion WHERE periodo = ? LIMIT 1", [periodo]
    ).fetchone()
    if not existe:
        raise HTTPException(status_code=404, detail=f"Periodo IGAE no cargado: {periodo}.")


def exigir_ejercicio_cargado(con: duckdb.DuckDBPyConnection, ejercicio: int) -> None:
    existe = con.execute(
        "SELECT 1 FROM fact_ejecucion WHERE ejercicio = ? LIMIT 1", [ejercicio]
    ).fetchone()
    if not existe:
        raise HTTPException(status_code=404, detail=f"Ejercicio no cargado: {ejercicio}.")
