"""Monitor de salud de URLs de fuentes (Fase 7, resiliencia operativa).

Verifica semanalmente que las URLs base de ``config/sources.yaml`` siguen
respondiendo. Para cada URL: HEAD request, esperando 200/302 (no 404/5xx ni HTML
inesperado). Las fuentes ``requerido: true`` generan issue si fallan; las
opcionales solo un aviso informativo en el step summary.

Se ejecuta como ``python -m gasto_estado.orchestration.health_check`` desde el
workflow ``health_check.yml``.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from gasto_estado.extractors.base import DEFAULT_HEADERS
from gasto_estado.orchestration.notifications import (
    Incidencia,
    notificar_incidencias,
)

_TIMEOUT = 30.0
_OK_CODES = {200, 301, 302, 303, 307, 308}


@dataclass(frozen=True)
class ResultadoURL:
    fuente: str
    url: str
    requerido: bool
    status: int | None
    tiempo_ms: int
    error: str | None


def _extraer_urls(sources: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Extrae (fuente, url, requerido) de sources.yaml."""
    resultado: list[tuple[str, str, bool]] = []
    for fuente, cfg in sources.items():
        if not isinstance(cfg, dict):
            continue
        requerido = True
        for key in ("url_base", "url_api_base", "url_index", "url_api"):
            url = cfg.get(key)
            if url and isinstance(url, str) and url.startswith("http"):
                resultado.append((fuente, url, requerido))
        archivos = cfg.get("files", [])
        if isinstance(archivos, list):
            for f in archivos:
                if isinstance(f, dict) and f.get("url"):
                    req = f.get("requerido", True)
                    resultado.append((fuente, f["url"], bool(req)))
    return resultado


def verificar_url(fuente: str, url: str, requerido: bool) -> ResultadoURL:
    """HEAD request a una URL; devuelve el resultado sin lanzar."""
    t0 = time.monotonic()
    try:
        r = httpx.head(url, headers=DEFAULT_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        ms = int((time.monotonic() - t0) * 1000)
        if r.status_code in _OK_CODES:
            return ResultadoURL(fuente, url, requerido, r.status_code, ms, None)
        return ResultadoURL(
            fuente,
            url,
            requerido,
            r.status_code,
            ms,
            f"Status inesperado: {r.status_code}",
        )
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return ResultadoURL(fuente, url, requerido, None, ms, str(exc))


def ejecutar(sources_path: Path | None = None) -> list[ResultadoURL]:
    """Verifica todas las URLs de sources.yaml y genera el informe."""
    if sources_path is None:
        sources_path = Path("config/sources.yaml")
    with open(sources_path, encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    urls = _extraer_urls(sources)
    resultados = [verificar_url(fuente, url, req) for fuente, url, req in urls]

    incidencias: list[Incidencia] = []
    for r in resultados:
        if r.error is not None and r.requerido:
            incidencias.append(
                Incidencia(
                    fuente=r.fuente,
                    particion=None,
                    tipo_fallo="fuente_no_disponible",
                    mensaje_diagnostico=(
                        f"URL caída: {r.url}\n"
                        f"Status: {r.status or 'sin respuesta'}\n"
                        f"Error: {r.error}\n"
                        f"Tiempo: {r.tiempo_ms} ms"
                    ),
                )
            )

    lineas = ["# Monitor de salud de fuentes\n"]
    ok = [r for r in resultados if r.error is None]
    ko = [r for r in resultados if r.error is not None]
    lineas.append(f"**{len(ok)}** URLs OK, **{len(ko)}** con problemas\n")
    if ko:
        lineas.append("## Problemas detectados\n")
        lineas.append("| Fuente | URL | Requerido | Status | Error |")
        lineas.append("|--------|-----|-----------|--------|-------|")
        for r in ko:
            req = "SI" if r.requerido else "no"
            lineas.append(
                f"| {r.fuente} | `{r.url[:80]}…` | {req} | {r.status or '-'} | {r.error} |"
            )
    lineas.append("\n## Todas las URLs\n")
    lineas.append("| Fuente | URL | Status | Tiempo (ms) |")
    lineas.append("|--------|-----|--------|-------------|")
    for r in resultados:
        estado = f"{r.status}" if r.error is None else f"FAIL ({r.error[:40]})"
        lineas.append(f"| {r.fuente} | `{r.url[:80]}` | {estado} | {r.tiempo_ms} |")

    summary = "\n".join(lineas)
    if incidencias:
        notificar_incidencias(incidencias)
    else:
        import os

        path_env = os.environ.get("GITHUB_STEP_SUMMARY")
        if path_env:
            with open(path_env, "a", encoding="utf-8") as f:
                f.write(summary)

    for r in resultados:
        marca = "OK" if r.error is None else "FAIL"
        print(f"  [{marca}] {r.fuente}: {r.url[:70]} ({r.tiempo_ms} ms)")
    return resultados


if __name__ == "__main__":
    resultados = ejecutar()
    fallos_requeridos = [r for r in resultados if r.error and r.requerido]
    sys.exit(1 if fallos_requeridos else 0)
