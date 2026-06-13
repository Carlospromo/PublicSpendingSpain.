"""Extractor del Consejo de Ministros — referencias de La Moncloa (HTML).

SOLO descarga y escritura inmutable (CLAUDE.md §2). URLs verificadas con
descargas reales el 2026-06-12 (docs/consejo_ministros_estructura.md):

- Vintage actual (2024+): ``…/<AAAA>/<AAAAMMDD>-referencia-rueda-de-prensa-ministros.aspx``
- Vintage antiguo (2018-~2021): ``…/<AAAA>/refc<AAAAMMDD>.aspx``

La referencia se publica tras la reunión semanal (normalmente martes); los demás
días devuelven 404. Por eso ``extract`` admite un rango y omite los días sin
referencia. Para una fecha, se prueba primero el slug actual y, si no existe, el
antiguo (cubre la descarga de históricos).

*Fail loud por contenido* (no hay magic binario en HTML): una descarga que no
contenga el marcador de una referencia (``Consejo de Ministros`` + bloque
``SUMARIO``) se rechaza sin escribir en raw (probable página de error / WAF).

Raw (versionado; el HTML es pequeño):
``data/raw/consejo_ministros/<captura>/<AAAAMMDD>/referencia.html``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from . import base
from .base import DEFAULT_HEADERS, DEFAULT_TIMEOUT, SourceBlockedError

FUENTE = "consejo_ministros"

# Marcadores de una referencia válida (insensible a mayúsculas/acentos no
# relevantes aquí): el título del documento y el bloque SUMARIO.
_MARCADORES = (b"Consejo de Ministros", b"SUMARIO")


def _source_config() -> dict[str, Any]:
    from config import settings

    return settings.load_sources()["consejo_ministros"]


def _es_referencia(content: bytes) -> bool:
    return all(m in content for m in _MARCADORES)


def _urls_candidatas(cfg: dict[str, Any], dia: date) -> list[str]:
    clave = dia.strftime("%Y%m%d")
    anio = f"{dia.year:04d}"
    urls = [str(cfg["url_referencia_patron"]).format(anio=anio, fecha=clave)]
    legacy = cfg.get("url_referencia_patron_legacy")
    if legacy:
        urls.append(str(legacy).format(anio=anio, fecha=clave))
    return urls


def _descargar_referencia(urls: list[str], destino: Path) -> Path | None:
    """Prueba las URLs candidatas; guarda la primera que sea una referencia.

    404 (día sin consejo o vintage equivocado) → se prueba la siguiente. Una
    respuesta 200 que NO sea una referencia se rechaza *fail loud* (no es un
    404 honesto: probable WAF/portal caído).
    """
    for url in urls:
        try:
            response = base._get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue
            raise
        if response.status_code == 404:
            continue
        response.raise_for_status()
        content = response.content
        if not _es_referencia(content):
            raise SourceBlockedError(
                f"La descarga del Consejo de Ministros ({url}) no es una referencia "
                f"(faltan marcadores {[m.decode() for m in _MARCADORES]}; {len(content)} "
                f"bytes). Probable página de error o WAF. Aporta el HTML en "
                f"'{destino.parent}' y reintenta."
            )
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(content)
        return destino
    return None


def _rango_fechas(desde: date, hasta: date) -> list[date]:
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]


def extract(
    *,
    fecha: date | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    raw_dir: Path | None = None,
    capture_date: date | None = None,
) -> list[Path]:
    """Descarga la(s) referencia(s) del rango a la capa raw.

    ``fecha`` cubre un único día; ``desde``/``hasta`` un rango inclusivo (por
    defecto, los 7 días hasta hoy: capta la referencia semanal). Devuelve las
    rutas guardadas. Lo ya presente en raw no se re-descarga. Los días sin
    referencia (la mayoría) se omiten en silencio.
    """
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    capture_date = capture_date or date.today()
    cfg = _source_config()

    if fecha is not None:
        fechas = [fecha]
    else:
        hasta = hasta or date.today()
        desde = desde or hasta - timedelta(days=7)
        if desde > hasta:
            raise ValueError(f"Ventana invertida: desde={desde} > hasta={hasta}.")
        fechas = _rango_fechas(desde, hasta)

    rutas: list[Path] = []
    for dia in fechas:
        clave = dia.strftime("%Y%m%d")
        destino = raw_dir / FUENTE / capture_date.isoformat() / clave / "referencia.html"
        if destino.exists():
            rutas.append(destino)
            continue
        guardada = _descargar_referencia(_urls_candidatas(cfg, dia), destino)
        if guardada is not None:
            rutas.append(guardada)
    if fecha is not None and not rutas:
        raise SourceBlockedError(
            f"No se encontró referencia del Consejo de Ministros para {fecha} "
            f"(probada(s): {_urls_candidatas(cfg, fecha)}). ¿Día sin consejo o "
            f"cambio de maquetación de URL?"
        )
    return rutas
