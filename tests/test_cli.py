"""Tests mínimos de Fase 0: el CLI importa y responde a --help."""

from typer.testing import CliRunner

from gasto_estado.cli import app

runner = CliRunner()

COMANDOS = ("extract", "build", "update", "check", "api")


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for comando in COMANDOS:
        assert comando in result.output


def test_cada_comando_tiene_help() -> None:
    for comando in COMANDOS:
        result = runner.invoke(app, [comando, "--help"])
        assert result.exit_code == 0, f"--help falla para {comando}"


def test_extract_boe_y_consejo_estan_conectados() -> None:
    # Una fecha inválida corta antes de cualquier red: prueba que la fuente
    # enruta al extractor real (Fase 4), no al stub "no implementado".
    for source in ("boe", "consejo_ministros"):
        result = runner.invoke(app, ["extract", "--source", source, "--fecha", "no-es-fecha"])
        assert result.exit_code == 1, source
        assert "no implementado" not in result.output, source
