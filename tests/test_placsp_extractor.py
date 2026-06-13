"""Tests del extractor PLACSP (sin red): URLs, paginación y capa raw."""

from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from gasto_estado.extractors import base, placsp_atom

_ZIP_PATRON = (
    "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3_{anio}.zip"
)
_CABECERA = (
    "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3.atom"
)

_PAGINA_CON_NEXT = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<link rel="self" href="{self}"/><link rel="next" href="{next}"/>'
    "</feed>"
).format(
    self=_CABECERA,
    next="https://contrataciondelestado.es/sindicacion/sindicacion_643/pagina_anterior.atom",
)
_PAGINA_FINAL = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    '<feed xmlns="http://www.w3.org/2005/Atom"><link rel="self" href="x"/></feed>'
)


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        placsp_atom,
        "_source_config",
        lambda: {
            "url_atom_cabecera": _CABECERA,
            "url_zip_anual_patron": _ZIP_PATRON,
            "anio_minimo": 2012,
        },
    )


def _respuesta(url: str, content: bytes) -> httpx.Response:
    return httpx.Response(200, content=content, request=httpx.Request("GET", url))


def test_zip_url_anual() -> None:
    assert placsp_atom.zip_url_anual(2012, patron=_ZIP_PATRON) == _ZIP_PATRON.format(anio=2012)


@pytest.mark.usefixtures("config")
def test_anio_fuera_de_rango_falla(tmp_path: Path) -> None:
    for anio in (2011, 2027):
        with pytest.raises(ValueError, match="fuera de rango"):
            placsp_atom.extract(anio=anio, raw_dir=tmp_path, capture_date=date(2026, 6, 12))


@pytest.mark.usefixtures("config")
def test_paginas_invalidas_falla(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="paginas"):
        placsp_atom.extract(paginas=0, raw_dir=tmp_path)


@pytest.mark.usefixtures("config")
def test_modo_anual_guarda_zip_en_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        base, "_get", lambda url, **_: _respuesta(url, base.ZIP_MAGIC + b"contenido")
    )
    rutas = placsp_atom.extract(anio=2024, raw_dir=tmp_path, capture_date=date(2026, 6, 12))
    assert rutas == [
        tmp_path
        / "placsp"
        / "2026-06-12"
        / "643"
        / "anual"
        / "licitacionesPerfilesContratanteCompleto3_2024.zip"
    ]
    assert rutas[0].read_bytes().startswith(base.ZIP_MAGIC)


@pytest.mark.usefixtures("config")
def test_modo_incremental_sigue_rel_next(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paginas = {
        _CABECERA: _PAGINA_CON_NEXT.encode(),
        "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
        "pagina_anterior.atom": _PAGINA_FINAL.encode(),
    }
    pedidas: list[str] = []

    def fake_get(url: str, **_: Any) -> httpx.Response:
        pedidas.append(url)
        return _respuesta(url, paginas[url])

    monkeypatch.setattr(base, "_get", fake_get)
    # paginas=3 pero el feed se agota en 2: se detiene sin error.
    rutas = placsp_atom.extract(paginas=3, raw_dir=tmp_path, capture_date=date(2026, 6, 12))
    assert pedidas == list(paginas)
    assert [r.name for r in rutas] == [
        "licitacionesPerfilesContratanteCompleto3.atom",
        "pagina_anterior.atom",
    ]
    incremental = tmp_path / "placsp" / "2026-06-12" / "643" / "incremental"
    assert all(r.parent == incremental for r in rutas)


@pytest.mark.usefixtures("config")
def test_soft_200_html_no_contamina_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        base, "_get", lambda url, **_: _respuesta(url, b"<!DOCTYPE html><html>error</html>")
    )
    with pytest.raises(base.SourceBlockedError):
        placsp_atom.extract(anio=2024, raw_dir=tmp_path, capture_date=date(2026, 6, 12))
    assert not (tmp_path / "placsp").exists()
