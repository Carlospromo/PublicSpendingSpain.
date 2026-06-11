"""CLI de gasto-estado (typer): raíz de composición del proyecto.

Comandos canónicos (CLAUDE.md §6): extract, build, update, check, api.
Los aún no implementados imprimen la fase en la que se implementarán.
"""

import sys
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
) -> None:
    """Descarga datos de una fuente oficial a la capa raw (inmutable)."""
    if source in ("dir3", "pge_organica", "igae"):
        _bootstrap_repo_root()
        from gasto_estado.extractors import dir3, igae_mensual, pge_organica
        from gasto_estado.extractors.base import SourceBlockedError

        try:
            if source == "igae":
                saved = igae_mensual.extract(periodo=periodo)
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


@app.command()
def build() -> None:
    """Reconstruye el warehouse completo desde la capa raw."""
    typer.echo("build: no implementado — Fase 3")


@app.command()
def update() -> None:
    """Extracción incremental + carga + validaciones contables."""
    typer.echo("update: no implementado — Fase 3")


@app.command()
def check() -> None:
    """Ejecuta las validaciones de coherencia contable (CLAUDE.md §7)."""
    typer.echo("check: no implementado — Fase 3")


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", "--host", help="Host de escucha del servidor."),
    port: int = typer.Option(8000, "--port", help="Puerto de escucha del servidor."),
) -> None:
    """Levanta la API local (FastAPI) para el frontal web."""
    typer.echo(f"api ({host}:{port}): no implementado — Fase 6")
