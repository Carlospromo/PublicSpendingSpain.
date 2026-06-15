"""Cliente HTTP para consumir la API v1 de gasto-estado.

Todas las peticiones son GET. Nunca importa módulos internos del proyecto.
Si el dashboard necesita algo que la API no ofrece, eso es un hallazgo
que se registra en docs/dashboard_hallazgos.md, no un bypass.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

BASE_URL = os.environ.get("GASTO_ESTADO_API_URL", "http://127.0.0.1:8000")
_TIMEOUT = 20.0


class APIError(Exception):
    def __init__(self, status: int, mensaje: str) -> None:
        self.status = status
        super().__init__(f"[HTTP {status}] {mensaje}")


class APINoDisponible(APIError):
    """La API no responde (no levantada o caída)."""

    def __init__(self, url: str, exc: Exception) -> None:
        super().__init__(0, f"No se puede conectar a {url}: {exc}")


def _get(path: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    """GET a /v1{path}. Devuelve (data, meta). Lanza APIError si hay problema."""
    url = f"{BASE_URL}/v1{path}"
    try:
        r = httpx.get(url, params=params, timeout=_TIMEOUT)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise APINoDisponible(BASE_URL, exc) from exc
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("mensaje", r.text[:200])
        except Exception:
            msg = r.text[:200]
        raise APIError(r.status_code, msg)
    body = r.json()
    return body.get("data"), body.get("meta", {})


# ---------------------------------------------------------------------------
# Salud y frescura
# ---------------------------------------------------------------------------


def salud() -> tuple[dict[str, Any], dict[str, Any]]:
    data, meta = _get("/salud")
    return data or {}, meta


def frescura() -> list[dict[str, Any]]:
    data, _ = _get("/frescura", {"tamano": 100})
    return data or []


# ---------------------------------------------------------------------------
# Estructura
# ---------------------------------------------------------------------------


def ejercicios() -> list[int]:
    data, _ = _get("/estructura/ejercicios", {"tamano": 100})
    return sorted(data or [], reverse=True)


def secciones(ejercicio: int) -> list[dict[str, Any]]:
    data, _ = _get("/estructura/secciones", {"ejercicio": ejercicio, "tamano": 500})
    return data or []


def servicios(seccion_cod: str, ejercicio: int) -> list[dict[str, Any]]:
    data, _ = _get(
        f"/estructura/secciones/{seccion_cod}/servicios",
        {"ejercicio": ejercicio, "tamano": 500},
    )
    return data or []


# ---------------------------------------------------------------------------
# Ejecución (IGAE)
# ---------------------------------------------------------------------------


def grado_ejecucion(
    periodo: str, nivel: str = "seccion"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = _get("/ejecucion/grado", {"periodo": periodo, "nivel": nivel, "tamano": 500})
    return data or [], meta


def ritmo_ejecucion(
    ejercicio: int, nivel: str = "AGE"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = _get("/ejecucion/ritmo", {"ejercicio": ejercicio, "nivel": nivel, "tamano": 500})
    return data or [], meta


def interanual(periodo: str, nivel: str = "seccion") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = _get("/ejecucion/interanual", {"periodo": periodo, "nivel": nivel, "tamano": 500})
    return data or [], meta


def modificaciones(
    periodo: str, nivel: str = "seccion"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = _get(
        "/ejecucion/modificaciones", {"periodo": periodo, "nivel": nivel, "tamano": 500}
    )
    return data or [], meta


# ---------------------------------------------------------------------------
# Compromisos (PLACSP / BDNS)
# ---------------------------------------------------------------------------


def contratos_volumen(
    ejercicio: int | None = None,
    periodo: str | None = None,
    nivel: str = "seccion",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {"nivel": nivel, "tamano": 500}
    if ejercicio is not None:
        params["ejercicio"] = ejercicio
    if periodo is not None:
        params["periodo"] = periodo
    data, meta = _get("/contratos/volumen", params)
    return data or [], meta


def subvenciones_volumen(
    ejercicio: int | None = None,
    periodo: str | None = None,
    nivel: str = "seccion",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {"nivel": nivel, "tamano": 500}
    if ejercicio is not None:
        params["ejercicio"] = ejercicio
    if periodo is not None:
        params["periodo"] = periodo
    data, meta = _get("/subvenciones/volumen", params)
    return data or [], meta


def concentracion(
    ejercicio: int | None = None,
    periodo: str | None = None,
    nivel: str = "servicio",
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {"nivel": nivel, "top_n": top_n, "tamano": 500}
    if ejercicio is not None:
        params["ejercicio"] = ejercicio
    if periodo is not None:
        params["periodo"] = periodo
    data, meta = _get("/contratos/concentracion", params)
    return data or [], meta


# ---------------------------------------------------------------------------
# Decisiones (BOE / CdM)
# ---------------------------------------------------------------------------


def decisiones_volumen(
    fuente: str,
    ejercicio: int | None = None,
    periodo: str | None = None,
    nivel: str = "seccion",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {"nivel": nivel, "tamano": 500}
    if ejercicio is not None:
        params["ejercicio"] = ejercicio
    if periodo is not None:
        params["periodo"] = periodo
    data, meta = _get(f"/decisiones/{fuente}/volumen", params)
    return data or [], meta


# ---------------------------------------------------------------------------
# Cruces (indiciarios)
# ---------------------------------------------------------------------------


def compromiso_vs_ejecucion(
    periodo: str, nivel: str = "seccion"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = _get(
        "/cruces/compromiso-ejecucion", {"periodo": periodo, "nivel": nivel, "tamano": 500}
    )
    return data or [], meta


def decisiones_vs_compromiso(
    ejercicio: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = _get("/cruces/decisiones-compromiso", {"ejercicio": ejercicio, "tamano": 500})
    return data or [], meta


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------


def alertas_informe(periodo: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data, meta = _get("/alertas/informe", {"periodo": periodo})
    return data or {}, meta


def alertas_lista(
    periodo: str,
    severidad: str | None = None,
    tipo: str | None = None,
    velocidad: str | None = None,
    seccion: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: dict[str, Any] = {"periodo": periodo, "tamano": 500}
    if severidad:
        params["severidad"] = severidad
    if tipo:
        params["tipo"] = tipo
    if velocidad:
        params["velocidad"] = velocidad
    if seccion:
        params["seccion"] = seccion
    data, meta = _get("/alertas", params)
    return data or [], meta
