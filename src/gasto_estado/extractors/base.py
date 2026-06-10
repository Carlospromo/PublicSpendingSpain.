"""Interfaz común de extractores.

SOLO descarga y escritura inmutable en la capa raw. Sin parseo ni transformación
(CLAUDE.md §2: separación estricta de capas). Cada extractor concreto se apoya en
estas primitivas:

- descarga con ``httpx`` y reintentos ``tenacity`` (backoff exponencial),
- escritura inmutable en ``data/raw/<fuente>/<fecha_captura>/<fichero>``,
- *fail loud*: si la respuesta no es el binario esperado (p. ej. una página de
  rechazo de un WAF en vez del XLSX), se aborta con un error claro en lugar de
  guardar basura en la capa raw.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Cabeceras de navegador: algunas fuentes oficiales (p. ej. el host de descargas
# de DIR3, protegido por un WAF BIG-IP) rechazan clientes sin un User-Agent
# verosímil. No garantiza el acceso, pero es la opción menos frágil.
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Firma de los ficheros OOXML (xlsx/zip): "PK\x03\x04".
XLSX_MAGIC = b"PK\x03\x04"

DEFAULT_TIMEOUT = 60.0


class ExtractorError(Exception):
    """Error base de la capa de extracción."""


class SourceBlockedError(ExtractorError):
    """La fuente devolvió contenido inesperado (p. ej. rechazo de un WAF).

    Se lanza cuando la descarga no es el binario esperado, para no contaminar la
    capa raw con páginas de error. El mensaje indica cómo aportar el fichero a mano.
    """


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
)
def _get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
    """GET con reintentos (backoff 2→16 s) ante errores de transporte o 5xx."""
    response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    # Solo reintentamos los 5xx (transitorios); los 4xx se propagan sin reintento.
    if response.status_code >= 500:
        response.raise_for_status()
    return response


def capture_dir(raw_dir: Path, fuente: str, capture_date: date) -> Path:
    """Directorio inmutable de captura: ``<raw_dir>/<fuente>/<YYYY-MM-DD>/``."""
    return raw_dir / fuente / capture_date.isoformat()


def download_to_raw(
    url: str,
    *,
    fuente: str,
    filename: str,
    raw_dir: Path,
    capture_date: date | None = None,
    expected_magic: bytes | None = XLSX_MAGIC,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Descarga ``url`` y la guarda, inmutable, en la capa raw.

    Devuelve la ruta del fichero guardado. Si ya existe una captura para esa fecha,
    NO se sobrescribe (idempotencia + inmutabilidad del raw, CLAUDE.md §2).

    Si ``expected_magic`` se indica y el contenido no empieza por esa firma, se
    interpreta como respuesta inválida (WAF, HTML de error...) y se lanza
    ``SourceBlockedError`` sin escribir nada.
    """
    capture_date = capture_date or date.today()
    target_dir = capture_dir(raw_dir, fuente, capture_date)
    target = target_dir / filename

    if target.exists():
        return target

    response = _get(url, headers=headers or DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    content = response.content

    if expected_magic is not None and not content.startswith(expected_magic):
        content_type = response.headers.get("content-type", "desconocido")
        raise SourceBlockedError(
            f"La descarga de '{fuente}' ({url}) no devolvió el binario esperado "
            f"(content-type={content_type}, {len(content)} bytes). Probable bloqueo "
            f"de un WAF o cambio de URL. Aporta el fichero manualmente en "
            f"'{target_dir}' y reintenta."
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target
