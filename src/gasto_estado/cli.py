"""CLI de gasto-estado (typer).

Fase 0: solo stubs. Cada comando imprime la fase en la que se implementará.
Comandos canónicos (CLAUDE.md §6): extract, build, update, check, api.
"""

import typer

app = typer.Typer(
    name="gasto-estado",
    help="Monitorización y auditoría del gasto del Estado español.",
    no_args_is_help=True,
)


@app.command()
def extract(
    source: str = typer.Option(
        ...,
        "--source",
        help="Fuente a extraer: igae, pge, placsp, bdns, boe, consejo_ministros, dir3, invente.",
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help="Descargar solo el último dato disponible (en lugar del histórico).",
    ),
) -> None:
    """Descarga datos de una fuente oficial a la capa raw (inmutable)."""
    typer.echo(
        f"extract --source {source} --latest={latest}: "
        "no implementado — Fase 2 (IGAE) / Fase 4 (alta frecuencia)"
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
