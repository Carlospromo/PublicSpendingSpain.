"""Tests de la primitiva de extracción (sin red): inmutabilidad y *fail loud*."""

from datetime import date
from pathlib import Path

import httpx
import pytest

from gasto_estado.extractors import base


def _fake_response(content: bytes, content_type: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.test/file.xlsx"),
    )


def test_download_writes_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter(
        [
            _fake_response(base.XLSX_MAGIC + b"primero", "application/vnd.ms-excel"),
            _fake_response(base.XLSX_MAGIC + b"segundo", "application/vnd.ms-excel"),
        ]
    )
    monkeypatch.setattr(base, "_get", lambda *a, **k: next(responses))

    target = base.download_to_raw(
        "https://example.test/file.xlsx",
        fuente="dir3",
        filename="f.xlsx",
        raw_dir=tmp_path,
        capture_date=date(2026, 6, 10),
    )
    assert target.exists()
    assert target.read_bytes() == base.XLSX_MAGIC + b"primero"
    assert target == tmp_path / "dir3" / "2026-06-10" / "f.xlsx"

    # Segunda llamada: no debe sobrescribir (inmutabilidad del raw).
    again = base.download_to_raw(
        "https://example.test/file.xlsx",
        fuente="dir3",
        filename="f.xlsx",
        raw_dir=tmp_path,
        capture_date=date(2026, 6, 10),
    )
    assert again == target
    assert target.read_bytes() == base.XLSX_MAGIC + b"primero"


def test_download_fails_loud_on_waf_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        base,
        "_get",
        lambda *a, **k: _fake_response(b"<html>Request Rejected</html>", "text/html"),
    )

    with pytest.raises(base.SourceBlockedError):
        base.download_to_raw(
            "https://example.test/file.xlsx",
            fuente="dir3",
            filename="f.xlsx",
            raw_dir=tmp_path,
            capture_date=date(2026, 6, 10),
        )

    # No se escribe nada en la capa raw ante una respuesta inválida.
    assert not (tmp_path / "dir3").exists()
