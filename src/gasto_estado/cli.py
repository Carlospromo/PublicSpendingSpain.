"""CLI de gasto-estado (typer): raíz de composición del proyecto.

Comandos canónicos (CLAUDE.md §6): extract, build, update, check, api.
Los aún no implementados imprimen la fase en la que se implementarán.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import typer

app = typer.Typer(
    name="gasto-estado",
    help="Monitorización y auditoría del gasto del Estado español.",
    no_args_is_help=True,
)


def _bootstrap_repo_root() -> None:
    """Hace importable ``config/`` (vive en la raíz del repo, fuera del paquete).

    El proyecto se opera desde el checkout del repo (git-scraping: ``config/`` y
    ``data/`` viven ahí), pero el *console script* instalado no añade el CWD a
    ``sys.path``. Fail loud si no estamos en la raíz del repo.
    """
    repo_root = Path.cwd()
    if not (repo_root / "config" / "settings.py").exists():
        typer.echo(
            "error: ejecuta el comando desde la raíz del repositorio "
            "(no se encuentra config/settings.py).",
            err=True,
        )
        raise typer.Exit(code=1)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


@app.command()
def extract(
    source: str = typer.Option(
        ...,
        "--source",
        help=(
            "Fuente a extraer: igae, pge, pge_organica, placsp, bdns, boe, "
            "consejo_ministros, dir3, invente."
        ),
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Descargar solo el último dato disponible (en lugar del histórico).",
    ),
    periodo: str | None = typer.Option(
        None,
        "--periodo",
        help="Periodo mensual explícito (YYYY-MM); solo para fuentes mensuales (igae).",
    ),
    anio: int | None = typer.Option(
        None,
        "--anio",
        help="Año del ZIP anual (placsp): volcado histórico completo de ese ejercicio.",
    ),
    paginas: int = typer.Option(
        1,
        "--paginas",
        help="Páginas ATOM del modo incremental (placsp); 1 = solo la cabecera diaria.",
    ),
    fecha: str | None = typer.Option(
        None,
        "--fecha",
        help="Día concreto (YYYY-MM-DD) a descargar (boe, consejo_ministros).",
    ),
    desde: str | None = typer.Option(
        None,
        "--desde",
        help="Inicio de la ventana (YYYY-MM-DD): concesión en bdns, publicación "
        "en boe/consejo_ministros. Por defecto, 7 días antes de --hasta.",
    ),
    hasta: str | None = typer.Option(
        None,
        "--hasta",
        help="Fin de la ventana (YYYY-MM-DD, bdns/boe/consejo_ministros); por defecto, hoy.",
    ),
    ambito: str = typer.Option(
        "C",
        "--ambito",
        help="Ámbito de administración (bdns): C=Estado, A=autonómica, L=local, O=otros.",
    ),
) -> None:
    """Descarga datos de una fuente oficial a la capa raw (inmutable)."""
    fuentes = ("dir3", "pge_organica", "igae", "placsp", "bdns", "boe", "consejo_ministros")
    if source in fuentes:
        _bootstrap_repo_root()
        from gasto_estado.extractors import (
            bdns_api,
            boe_sumario,
            consejo_ministros,
            dir3,
            igae_mensual,
            pge_organica,
            placsp_atom,
        )
        from gasto_estado.extractors.base import SourceBlockedError

        try:
            if source == "igae":
                saved = igae_mensual.extract(periodo=periodo)
            elif source == "placsp":
                saved = placsp_atom.extract(anio=anio, paginas=paginas)
            elif source == "bdns":
                hasta_d = date.fromisoformat(hasta) if hasta else date.today()
                desde_d = date.fromisoformat(desde) if desde else hasta_d - timedelta(days=7)
                saved = bdns_api.extract(desde=desde_d, hasta=hasta_d, ambito=ambito)
            elif source in ("boe", "consejo_ministros"):
                fecha_dia = date.fromisoformat(fecha) if fecha else None
                hasta_v = date.fromisoformat(hasta) if hasta else None
                desde_v = date.fromisoformat(desde) if desde else None
                extractor_fn = boe_sumario.extract if source == "boe" else consejo_ministros.extract
                saved = extractor_fn(fecha=fecha_dia, desde=desde_v, hasta=hasta_v)
            else:
                extractor = {"dir3": dir3.extract, "pge_organica": pge_organica.extract}[source]
                saved = extractor()
        except SourceBlockedError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        for path in saved:
            typer.echo(f"{source}: guardado {path}")
        return

    typer.echo(
        f"extract --source {source} --latest={latest}: no implementado — Fase 4 (alta frecuencia)"
    )


def _run_load(operacion: str) -> None:
    _bootstrap_repo_root()
    from config import settings

    from gasto_estado.db import load as db_load
    from gasto_estado.quality.checks import CoherenceError

    try:
        runner = {"build": db_load.build, "update": db_load.update}[operacion]
        stats = runner(settings.WAREHOUSE_PATH, settings.RAW_DIR)
    except (db_load.OrphanOrganicError, CoherenceError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for periodo, filas in stats.items():
        typer.echo(f"{operacion}: {periodo} -> {filas} filas")
    if not stats:
        typer.echo(f"{operacion}: sin periodos nuevos en raw; warehouse al día.")
    typer.echo(f"{operacion}: warehouse en {settings.WAREHOUSE_PATH}")


@app.command()
def build() -> None:
    """Reconstruye el warehouse completo desde la capa raw + seeds."""
    _run_load("build")


@app.command()
def update() -> None:
    """Carga incremental de los periodos de raw aún no presentes."""
    _run_load("update")


@app.command()
def check(
    periodo: str | None = typer.Option(
        None, "--periodo", help="Periodo (YYYY-MM) a validar; por defecto, todos los cargados."
    ),
    json_out: str | None = typer.Option(
        None, "--json", help="Ruta donde volcar además el informe estructurado (JSON)."
    ),
) -> None:
    """Ejecuta las validaciones de coherencia contable (CLAUDE.md §7).

    Código de salida 1 si alguna regla está en FAIL (para CI, Fase 7).
    """
    _bootstrap_repo_root()
    import duckdb
    from config import settings

    from gasto_estado.quality import checks

    if not settings.WAREHOUSE_PATH.exists():
        typer.echo("error: no existe el warehouse; ejecuta 'gasto-estado build'.", err=True)
        raise typer.Exit(code=1)
    with duckdb.connect(str(settings.WAREHOUSE_PATH), read_only=True) as con:
        try:
            resultados = checks.run_checks(con, [periodo] if periodo else None)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    checks.render_consola(resultados, typer.echo)
    if json_out is not None:
        Path(json_out).write_text(checks.a_json(resultados), encoding="utf-8")
        typer.echo(f"check: informe JSON en {json_out}")
    if any(r.estado == checks.FAIL for r in resultados):
        raise typer.Exit(code=1)


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", "--host", help="Host de escucha del servidor."),
    port: int = typer.Option(8000, "--port", help="Puerto de escucha del servidor."),
) -> None:
    """Levanta la API local (FastAPI, solo lectura) para el frontal web."""
    _bootstrap_repo_root()
    import uvicorn
    from config import settings

    from gasto_estado.api.app import create_app

    if not settings.WAREHOUSE_PATH.exists():
        typer.echo(
            "aviso: no existe el warehouse; la API arrancará pero /salud lo reflejará "
            "y los endpoints de datos darán 503. Ejecuta 'gasto-estado build' primero.",
            err=True,
        )
    typer.echo(f"api: sirviendo en http://{host}:{port} (read-only; docs en /docs)")
    uvicorn.run(create_app(), host=host, port=port)
