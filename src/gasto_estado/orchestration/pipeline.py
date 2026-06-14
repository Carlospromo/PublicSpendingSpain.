"""Orquestación de la carga por fuente/partición (núcleo puro, sin Dagster).

Cada función es una CÁSCARA FINA sobre la lógica ya probada de ``db.load`` y los
extractores: descarga (idempotente, opcional) + parseo + anclaje + carga, sin
reimplementar nada (CLAUDE.md §6: un asset invoca código probado). Son funciones
puras de Python — Dagster (``assets.py``) las envuelve, pero se pueden ejecutar y
testear sin él. La idempotencia ya construida en ``db.load`` se preserva:
re-materializar una partición no duplica.

Cada materialización anota el ledger de frescura (``frescura.registrar``) para
que la API exponga el estado real de materialización.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

from gasto_estado.db import load
from gasto_estado.orchestration import frescura
from gasto_estado.parsers import bdns as bdns_parser
from gasto_estado.parsers import boe as boe_parser
from gasto_estado.parsers import consejo_ministros as cdm_parser
from gasto_estado.parsers.placsp import discover_capturas as placsp_capturas


@dataclass(frozen=True)
class Materializacion:
    """Resultado de materializar un asset/partición: qué, cuánto y su clave."""

    fuente: str
    particion: str | None
    filas: int


def _conexion_con_dimensiones(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Abre el warehouse asegurando esquema + seeds (idempotente; cada asset es autosuficiente)."""
    con = load.connect(db_path)
    load.init_schema(con)
    load.load_seeds(con)
    return con


def materializar_dimensiones(db_path: Path) -> Materializacion:
    """Reference layer: esquema + seeds (dim_organica, dim_seccion_servicio, dim_economica)."""
    con = _conexion_con_dimensiones(db_path)
    n = con.execute("SELECT count(*) FROM dim_seccion_servicio").fetchone()
    con.close()
    return Materializacion("dimensiones", None, int(n[0]) if n else 0)


def materializar_ejecucion(
    db_path: Path, raw_dir: Path, periodo: str, *, descargar: bool = False
) -> Materializacion:
    """fact_ejecucion para un periodo IGAE (partición mensual). Skip si no hay raw."""
    if descargar:
        from gasto_estado.extractors import igae_mensual

        igae_mensual.extract(periodo=periodo, raw_dir=raw_dir)
    con = _conexion_con_dimensiones(db_path)
    try:
        if periodo not in load.discover_periodos(raw_dir):
            return Materializacion("igae_anexo_i", periodo, 0)  # nada publicado aún
        stats = load.cargar_periodos_ejecucion(con, raw_dir, [periodo])
    finally:
        con.close()
    filas = stats.get(periodo, 0)
    frescura.registrar(db_path, "igae_anexo_i", particion=periodo, filas=filas)
    return Materializacion("igae_anexo_i", periodo, filas)


def _materializar_capturas(
    db_path: Path,
    raw_dir: Path,
    *,
    fuente_cod: str,
    capturas: list[str] | None,
    descubrir: list[str],
    cargar: object,
    particion: str | None,
) -> Materializacion:
    objetivo = capturas if capturas is not None else descubrir
    con = _conexion_con_dimensiones(db_path)
    try:
        stats = cargar(con, raw_dir, objetivo) if objetivo else {}  # type: ignore[operator]
    finally:
        con.close()
    filas = sum(stats.values())
    frescura.registrar(db_path, fuente_cod, particion=particion or ",".join(objetivo) or None,
                       filas=filas)
    return Materializacion(fuente_cod, particion, filas)


def materializar_placsp(
    db_path: Path, raw_dir: Path, *, capturas: list[str] | None = None, descargar: bool = False
) -> Materializacion:
    """fact_contratos (PLACSP). Depende de dimensiones + crosswalk servicio↔DIR3."""
    if descargar:
        from gasto_estado.extractors import placsp_atom

        placsp_atom.extract(paginas=1, raw_dir=raw_dir)
    return _materializar_capturas(
        db_path, raw_dir, fuente_cod="placsp", capturas=capturas,
        descubrir=placsp_capturas(raw_dir), cargar=load.cargar_capturas_placsp,
        particion=capturas[0] if capturas else None,
    )


def materializar_bdns(
    db_path: Path, raw_dir: Path, *, capturas: list[str] | None = None, descargar: bool = False
) -> Materializacion:
    """fact_subvenciones (BDNS). Depende de dimensiones + crosswalk servicio↔DIR3."""
    if descargar:
        from gasto_estado.extractors import bdns_api

        hoy = date.today()
        bdns_api.extract(desde=hoy - timedelta(days=7), hasta=hoy, raw_dir=raw_dir)
    return _materializar_capturas(
        db_path, raw_dir, fuente_cod="bdns", capturas=capturas,
        descubrir=bdns_parser.discover_capturas(raw_dir), cargar=load.cargar_capturas_bdns,
        particion=capturas[0] if capturas else None,
    )


def materializar_boe(
    db_path: Path, raw_dir: Path, *, capturas: list[str] | None = None, descargar: bool = False
) -> Materializacion:
    """fact_boe_disposiciones (BOE). Ancla a sección (no usa el crosswalk DIR3)."""
    if descargar:
        from gasto_estado.extractors import boe_sumario

        hoy = date.today()
        boe_sumario.extract(desde=hoy - timedelta(days=7), hasta=hoy, raw_dir=raw_dir)
    return _materializar_capturas(
        db_path, raw_dir, fuente_cod="boe_sumario", capturas=capturas,
        descubrir=boe_parser.discover_capturas(raw_dir), cargar=load.cargar_capturas_boe,
        particion=capturas[0] if capturas else None,
    )


def materializar_cdm(
    db_path: Path, raw_dir: Path, *, capturas: list[str] | None = None, descargar: bool = False
) -> Materializacion:
    """fact_acuerdos_cdm (Consejo de Ministros). Ancla a sección."""
    if descargar:
        from gasto_estado.extractors import consejo_ministros

        hoy = date.today()
        consejo_ministros.extract(desde=hoy - timedelta(days=7), hasta=hoy, raw_dir=raw_dir)
    return _materializar_capturas(
        db_path, raw_dir, fuente_cod="consejo_ministros", capturas=capturas,
        descubrir=cdm_parser.discover_capturas(raw_dir), cargar=load.cargar_capturas_cdm,
        particion=capturas[0] if capturas else None,
    )


def validar_contabilidad(db_path: Path) -> int:
    """Gate de validación: re-ejecuta los checks de la Fase 3; *fail loud* si algún FAIL.

    Devuelve el nº de reglas evaluadas. La carga ya valida transaccionalmente
    cada periodo; este gate reafirma la coherencia del warehouse completo como
    nodo explícito del grafo (un hecho no es confiable si no lo pasa).
    """
    from gasto_estado.quality import checks

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        resultados = checks.run_checks(con, None)
    finally:
        con.close()
    fallos = [r for r in resultados if r.estado == checks.FAIL]
    if fallos:
        raise checks.CoherenceError("warehouse", fallos)
    return len(resultados)
