"""Extractor del BOE — sumario diario + disposiciones de interés (datos abiertos).

SOLO descarga y escritura inmutable (CLAUDE.md §2). API pública verificada con
llamadas reales el 2026-06-12 (docs/boe_estructura.md):

- ``GET {api}/boe/sumario/<AAAAMMDD>`` → XML del sumario del día.
- ``GET {xml_disp}?id=<BOE-A-AAAA-N>`` → XML de una disposición individual.

El extractor descarga el sumario, **prefiltra** en él las disposiciones de
interés (subvenciones y modificaciones de crédito con título explícito; el resto
—personal, contratación, justicia— no se descarga) y baja el XML de cada una.
La clasificación fina y la extracción de importes viven en el parser; aquí solo
se resuelve QUÉ bajar (mismo papel que la paginación de PLACSP/BDNS).

*Fail loud*: ambos endpoints devuelven XML (``<?xml``); cualquier otra cosa
(HTML de error, soft-200 de un WAF) se rechaza con ``XML_MAGIC`` y no contamina
el raw. Entre disposiciones se aplica una pausa cortés.

Raw (versionado en git; los ficheros son pequeños):
``data/raw/boe/<captura>/<AAAAMMDD>/sumario.xml`` y
``data/raw/boe/<captura>/<AAAAMMDD>/disposiciones/<ID>.xml``.
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from .base import XML_MAGIC, SourceBlockedError, download_to_raw

FUENTE = "boe"

# Secciones del sumario donde viven las disposiciones presupuestarias de interés:
# I (disposiciones generales: RD/RDL, créditos), III (otras disposiciones:
# convocatorias, transferencias) y V-B (otros anuncios: extractos de subvención).
SECCIONES_INTERES = frozenset({"1", "3", "5B"})

# Prefiltro por título (se confirma/clasifica en el parser). Inclusivo pero
# acotado: evita descargar el BOE entero sin perder las clases de interés.
_INTERES_TITULO_RE = re.compile(
    r"subvenci[oó]n|subvenciones|\bayudas?\b|cr[eé]dito extraordinario"
    r"|suplemento de cr[eé]dito|transferencias?\s+de\s+cr[eé]dito"
    r"|ampliaci[oó]n de cr[eé]dito|generaci[oó]n de cr[eé]dito"
    r"|incorporaci[oó]n de cr[eé]dito|modificaci[oó]n.{0,40}cr[eé]dito"
    r"|^extracto\b",
    re.IGNORECASE,
)

# Pausa cortés entre descargas de disposiciones (segundos).
_PAUSA = 0.3
# Tope de disposiciones por día (corta sumarios anómalos).
_MAX_DISP_DIA = 2000


def _source_config() -> dict[str, Any]:
    from config import settings

    return settings.load_sources()["boe"]


def es_disposicion_interes(seccion_cod: str, titulo: str) -> bool:
    """¿El item del sumario es candidato a disposición de interés (prefiltro)?"""
    return seccion_cod in SECCIONES_INTERES and bool(_INTERES_TITULO_RE.search(titulo or ""))


def _items_candidatos(sumario_xml: bytes) -> list[tuple[str, str]]:
    """(identificador, url_xml) de las disposiciones de interés del sumario.

    Escaneo ligero (no canónico): el extractor solo necesita saber QUÉ bajar.
    """
    raiz = ET.fromstring(sumario_xml)
    candidatos: list[tuple[str, str]] = []
    for seccion in raiz.iter("seccion"):
        seccion_cod = seccion.get("codigo") or ""
        for item in seccion.iter("item"):
            titulo = item.findtext("titulo") or ""
            if not es_disposicion_interes(seccion_cod, titulo):
                continue
            ident = item.findtext("identificador")
            url_xml = item.findtext("url_xml")
            if ident and url_xml:
                candidatos.append((ident, url_xml))
    return candidatos


def _rango_fechas(desde: date, hasta: date) -> list[date]:
    dias = (hasta - desde).days
    return [desde + timedelta(days=i) for i in range(dias + 1)]


def extract(
    *,
    fecha: date | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    raw_dir: Path | None = None,
    capture_date: date | None = None,
    pausa: float = _PAUSA,
) -> list[Path]:
    """Descarga el/los sumario(s) del rango y las disposiciones de interés.

    ``fecha`` cubre un único día; ``desde``/``hasta`` un rango inclusivo (por
    defecto, el día de hoy). Devuelve las rutas guardadas (sumarios +
    disposiciones). Lo ya presente en raw no se re-descarga (idempotencia +
    inmutabilidad). Un día sin sumario (festivo/fin de semana, HTTP 404) se
    omite sin abortar el rango.
    """
    if raw_dir is None:
        from config import settings

        raw_dir = settings.RAW_DIR
    capture_date = capture_date or date.today()

    if fecha is not None:
        fechas = [fecha]
    else:
        hasta = hasta or date.today()
        desde = desde or hasta
        if desde > hasta:
            raise ValueError(f"Ventana invertida: desde={desde} > hasta={hasta}.")
        fechas = _rango_fechas(desde, hasta)

    cfg = _source_config()
    sumario_patron = str(cfg["url_sumario_patron"])
    disp_base = str(cfg["url_xml_disposicion"])

    rutas: list[Path] = []
    for dia in fechas:
        clave = dia.strftime("%Y%m%d")
        subdir = f"{capture_date.isoformat()}/{clave}"
        url = sumario_patron.format(fecha=clave)
        try:
            sumario_path = download_to_raw(
                url,
                fuente=FUENTE,
                filename="sumario.xml",
                raw_dir=raw_dir,
                subdir=subdir,
                expected_magic=XML_MAGIC,
            )
        except httpx.HTTPStatusError as exc:
            # 404 = no hubo boletín ese día (festivo); se omite, no se aborta.
            if exc.response.status_code == 404:
                continue
            raise
        rutas.append(sumario_path)

        for ident, url_xml in _items_candidatos(sumario_path.read_bytes())[:_MAX_DISP_DIA]:
            destino = raw_dir / FUENTE / subdir / "disposiciones" / f"{ident}.xml"
            if destino.exists():
                rutas.append(destino)
                continue
            disp_url = url_xml if url_xml.startswith("http") else f"{disp_base}?id={ident}"
            disp_path = download_to_raw(
                disp_url,
                fuente=FUENTE,
                filename=f"{ident}.xml",
                raw_dir=raw_dir,
                subdir=f"{subdir}/disposiciones",
                expected_magic=XML_MAGIC,
            )
            rutas.append(disp_path)
            if pausa > 0:
                time.sleep(pausa)
    if not rutas:
        raise SourceBlockedError(
            f"El BOE no devolvió ningún sumario para el rango pedido ({fechas[0]}"
            f"…{fechas[-1]}). ¿Fechas sin boletín o cambio del endpoint de datos abiertos?"
        )
    return rutas
