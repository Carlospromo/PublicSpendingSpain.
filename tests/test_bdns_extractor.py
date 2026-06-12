"""Tests del extractor BDNS (sin red): paginación, ventana y capa raw."""

import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from gasto_estado.extractors import base, bdns_api

_API = "https://www.infosubvenciones.es/bdnstrans/api"
_ENDPOINT = "concesiones/busqueda"


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bdns_api,
        "_source_config",
        lambda: {"url_api_base": _API, "endpoint_concesiones": _ENDPOINT, "page_size": 2},
    )


def _envelope(numero: int, *, last: bool, n_filas: int = 2) -> bytes:
    contenido = [{"id": numero * 10 + i} for i in range(n_filas)]
    return json.dumps({"content": contenido, "last": last, "number": numero}).encode()


def _respuesta(url: str, content: bytes) -> httpx.Response:
    return httpx.Response(200, content=content, request=httpx.Request("GET", url))


@pytest.mark.usefixtures("config")
def test_pagina_hasta_last_y_guarda_en_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pedidas: list[str] = []

    def fake_get(url: str, **_: Any) -> httpx.Response:
        pedidas.append(url)
        numero = int(parse_qs(urlparse(url).query)["page"][0])
        return _respuesta(url, _envelope(numero, last=numero == 2))

    monkeypatch.setattr(base, "_get", fake_get)
    rutas = bdns_api.extract(
        desde=date(2026, 6, 1),
        hasta=date(2026, 6, 12),
        raw_dir=tmp_path,
        capture_date=date(2026, 6, 12),
        pausa=0,
    )
    ventana = tmp_path / "bdns" / "2026-06-12" / "concesiones" / "C_2026-06-01_2026-06-12"
    assert [r.relative_to(ventana).name for r in rutas] == [
        "page_00000.json",
        "page_00001.json",
        "page_00002.json",
    ]
    # Parámetros verificados del API: fechas DD/MM/AAAA y ámbito estatal.
    params = parse_qs(urlparse(pedidas[0]).query)
    assert params["fechaDesde"] == ["01/06/2026"]
    assert params["fechaHasta"] == ["12/06/2026"]
    assert params["tipoAdministracion"] == ["C"]
    assert params["pageSize"] == ["2"]


@pytest.mark.usefixtures("config")
def test_pagina_existente_no_se_redescarga(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ventana = tmp_path / "bdns" / "2026-06-12" / "concesiones" / "C_2026-06-01_2026-06-12"
    ventana.mkdir(parents=True)
    (ventana / "page_00000.json").write_bytes(_envelope(0, last=False))
    (ventana / "page_00001.json").write_bytes(_envelope(1, last=True))

    def fake_get(url: str, **_: Any) -> httpx.Response:
        raise AssertionError(f"no debería haber red: {url}")

    monkeypatch.setattr(base, "_get", fake_get)
    rutas = bdns_api.extract(
        desde=date(2026, 6, 1),
        hasta=date(2026, 6, 12),
        raw_dir=tmp_path,
        capture_date=date(2026, 6, 12),
        pausa=0,
    )
    assert len(rutas) == 2  # reanudación íntegra desde el raw ya capturado


@pytest.mark.usefixtures("config")
def test_soft_200_html_no_contamina_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # El WAF (BIG-IP) devuelve HTML de rechazo con HTTP 200: fail loud.
    monkeypatch.setattr(
        base, "_get", lambda url, **_: _respuesta(url, b"<html>The requested URL was rejected")
    )
    with pytest.raises(base.SourceBlockedError, match="WAF"):
        bdns_api.extract(
            desde=date(2026, 6, 1),
            hasta=date(2026, 6, 12),
            raw_dir=tmp_path,
            capture_date=date(2026, 6, 12),
            pausa=0,
        )
    assert not (tmp_path / "bdns").exists()


@pytest.mark.usefixtures("config")
def test_json_sin_content_falla_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "_get", lambda url, **_: _respuesta(url, b'{"error": "x"}'))
    with pytest.raises(base.SourceBlockedError, match="content"):
        bdns_api.extract(
            desde=date(2026, 6, 1),
            hasta=date(2026, 6, 12),
            raw_dir=tmp_path,
            capture_date=date(2026, 6, 12),
            pausa=0,
        )
    assert not (tmp_path / "bdns").exists()


@pytest.mark.usefixtures("config")
def test_parametros_invalidos_fallan(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invertida"):
        bdns_api.extract(desde=date(2026, 6, 12), hasta=date(2026, 6, 1), raw_dir=tmp_path)
    with pytest.raises(ValueError, match="mbito"):
        bdns_api.extract(
            desde=date(2026, 6, 1), hasta=date(2026, 6, 12), ambito="X", raw_dir=tmp_path
        )
