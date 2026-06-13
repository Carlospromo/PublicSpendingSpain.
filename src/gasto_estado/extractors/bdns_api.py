"""Extractor de la BDNS / SNPSAP — concesiones de subvenciones (API REST).

SOLO descarga y escritura inmutable (CLAUDE.md §2). API pública verificada con
llamadas reales el 2026-06-12 (docs/bdns_estructura.md):

- ``GET {api}/concesiones/busqueda`` con paginación Spring (``page``,
  ``pageSize`` — hasta 10000 honrado), filtro de ámbito ``tipoAdministracion``
  (C=Estado, A=autonómica, L=local) y ventana ``fechaDesde``/``fechaHasta``
  (DD/MM/AAAA, inclusiva, sobre la fecha de concesión) para la descarga
  incremental diaria/semanal y el histórico por años.
- La respuesta es un envelope JSON con ``content`` (lote), ``last`` y
  ``totalPages``: la paginación itera hasta ``last``.

*Fail loud*: el WAF del host (BIG-IP de la Administración Presupuestaria)
devuelve HTML de rechazo con HTTP 200; cada página se valida como JSON con
``content`` ANTES de escribirla en raw. El aviso legal advierte de medidas
restrictivas ante abuso: entre páginas se aplica una pausa cortés y los
reintentos con backoff los aporta la primitiva de ``base``.

El raw se guarda en ``data/raw/bdns/<captura>/concesiones/<ámbito>_<desde>_<hasta>/``
con una página JSON por fichero. Como PLACSP, NO se versiona en git (una
ventana anual estatal son millones de filas; ver .gitignore): lo regenera el
extractor a partir de la ventana de fechas. La página ya guardada no se
re-descarga (idempotencia + inmutabilidad).
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from . import base
from .base import DEFAULT_HEADERS, DEFAULT_TIMEOUT, SourceBlockedError

FUENTE = "bdns"

# Ámbitos de administración del SNPSAP (parámetro tipoAdministracion).
AMBITOS = ("C", "A", "L", "O")  # Estado, autonómica, local, otros
AMBITO_ESTATAL = "C"

# Pausa cortés entre páginas (segundos): el aviso legal del SNPSAP se reserva
# medidas restrictivas ante abuso del API.
_PAUSA_ENTRE_PAGINAS = 0.5

# Tope duro de páginas por ventana: con pageSize=5000 son 50 M de filas, muy por
# encima de cualquier ventana razonable. Corta bucles ante un 'last' roto.
_MAX_PAGINAS = 10_000


def _source_config() -> dict[str, Any]:
    from config import settings

    return settings.load_sources()["bdns"]


def _fecha_api(d: date) -> str:
    """Formato de fecha del API (DD/MM/AAAA, verificado)."""
    return d.strftime("%d/%m/%Y")


def _parse_pagina(content: bytes, url: str) -> dict[str, Any]:
    """Valida que la respuesta es el envelope JSON esperado (fail loud)."""
    try:
        pagina = json.loads(content)
    except ValueError as exc:
        raise SourceBlockedError(
            f"La API BDNS ({url}) no devolvió JSON (probable rechazo del WAF "
            f"con HTTP 200). Primeros bytes: {content[:120]!r}"
        ) from exc
    if not isinstance(pagina, dict) or "content" not in pagina:
        raise SourceBlockedError(
            f"Respuesta JSON de la BDNS sin el campo 'content' esperado ({url}): "
            f"claves={sorted(pagina) if isinstance(pagina, dict) else type(pagina)}"
        )
    return pagina


def extract(
    *,
    desde: date,
    hasta: date,
    ambito: str = AMBITO_ESTATAL,
    raw_dir: Path | None = None,
    capture_date: date | None = None,
    page_size: int | None = None,
    pausa: float = _PAUSA_ENTRE_PAGINAS,
) -> list[Path]:
    """Descarga las concesiones de la ventana [desde, hasta] a la capa raw.

    Pagina hasta agotar resultados (``last`` del envelope). Devuelve las rutas
    guardadas. Una página ya presente en raw no se re-descarga ni se modifica;
    para repetir una ventana en otro día, la fecha de captura crea otro
    directorio (el historial entre capturas es la capa raw).
    """
    if ambito not in AMBITOS:
        raise ValueError(f"Ámbito BDNS desconocido: {ambito!r} (esperado uno de {AMBITOS}).")
    if desde > hasta:
        raise ValueError(f"Ventana invertida: desde={desde} > hasta={hasta}.")
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    capture_date = capture_date or date.today()
    cfg = _source_config()
    page_size = page_size or int(cfg.get("page_size", 5000))
    api = str(cfg["url_api_base"]).rstrip("/")
    endpoint = str(cfg.get("endpoint_concesiones", "concesiones/busqueda"))

    ventana = f"{ambito}_{desde.isoformat()}_{hasta.isoformat()}"
    target_dir = raw_dir / FUENTE / capture_date.isoformat() / "concesiones" / ventana

    rutas: list[Path] = []
    pagina_num = 0
    while pagina_num < _MAX_PAGINAS:
        target = target_dir / f"page_{pagina_num:05d}.json"
        if target.exists():
            pagina = _parse_pagina(target.read_bytes(), str(target))
        else:
            params = {
                "page": pagina_num,
                "pageSize": page_size,
                "tipoAdministracion": ambito,
                "fechaDesde": _fecha_api(desde),
                "fechaHasta": _fecha_api(hasta),
            }
            url = f"{api}/{endpoint}?{urlencode(params)}"
            # Vía el módulo (no import directo): es el punto de monkeypatch
            # compartido por los tests de todos los extractores.
            response = base._get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            pagina = _parse_pagina(response.content, url)  # valida ANTES de escribir
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            if pausa > 0:
                time.sleep(pausa)
        rutas.append(target)
        if pagina.get("last", True) or not pagina.get("content"):
            break
        pagina_num += 1
    return rutas
