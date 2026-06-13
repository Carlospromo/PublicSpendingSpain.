"""Extracción de importes en euros desde texto oficial semiestructurado.

Compartido por los parsers de la tercera velocidad (BOE y Consejo de Ministros,
CLAUDE.md §3): el importe vive embebido en prosa ("por importe total de
168.000.000 de euros", "(1.000.000,00 €)", "8.000 euros"). La extracción es
imperfecta POR DISEÑO y degrada con elegancia: cada importe sale con su grado
de confianza y, si no hay cifra parseable, queda nulo (nunca un cero falso) con
el texto bruto conservado aguas arriba para revisión humana.

Grados de confianza (enum cerrado, columna ``importe_confianza``):

- ``alta``: la cifra va ligada a un marcador titular ("importe/cuantía …
  euros") o entre paréntesis con símbolo ("(1.000.000,00 €)"), el patrón de la
  cuantía oficial en RD de concesión directa.
- ``media``: hay una cifra en euros en el texto, pero sin marcador titular
  (p. ej. el primer premio de una convocatoria, no necesariamente el total).
- ``sin_importe``: ninguna cifra en euros parseable. Los importes EN LETRA
  ("un millón de euros") NO se convierten: si no acompañan a una cifra, el
  registro queda sin importe — señal, no contabilidad.
"""

from __future__ import annotations

import re

CONFIANZA_ALTA = "alta"
CONFIANZA_MEDIA = "media"
SIN_IMPORTE = "sin_importe"

CONFIANZAS = (CONFIANZA_ALTA, CONFIANZA_MEDIA, SIN_IMPORTE)

# Cifra en formato español: miles con punto y decimales con coma. Exige
# separador de miles o decimales O 4+ dígitos pegados a "euros": una cifra
# corta suelta ("3 euros") se acepta, pero "2026" sin marca monetaria nunca
# entra (el sufijo euros/€ es obligatorio en todos los patrones).
_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"

_EUROS = r"(?:de\s+)?(?:euros|€)"

# Cifra titular: ligada a "importe"/"cuantía"/"valor estimado" (hasta ~120
# caracteres de prosa intermedia: "por un importe máximo conjunto de …"). El
# "valor estimado" es la cuantía titular de los contratos que el Consejo
# autoriza ("Valor estimado del contrato: 21.526.792,10 euros").
_TITULAR_RE = re.compile(
    rf"(?:importe|cuant[ií]a|valor\s+estimado)[^.;]{{0,120}}?({_NUM})\s*{_EUROS}",
    re.IGNORECASE,
)
# Cuantía oficial entre paréntesis: "(1.000.000,00 €)".
_PARENTESIS_RE = re.compile(rf"\(({_NUM})\s*(?:€|euros)\)", re.IGNORECASE)
# Cualquier cifra en euros (confianza media).
_CUALQUIERA_RE = re.compile(rf"({_NUM})\s*{_EUROS}", re.IGNORECASE)


def _a_float(cifra: str) -> float:
    return float(cifra.replace(".", "").replace(",", "."))


def extraer_importe(texto: str | None) -> tuple[float | None, str]:
    """(importe, confianza) del texto; (None, "sin_importe") si no hay cifra."""
    if not texto:
        return None, SIN_IMPORTE
    for patron, confianza in (
        (_TITULAR_RE, CONFIANZA_ALTA),
        (_PARENTESIS_RE, CONFIANZA_ALTA),
        (_CUALQUIERA_RE, CONFIANZA_MEDIA),
    ):
        m = patron.search(texto)
        if m:
            return _a_float(m.group(1)), confianza
    return None, SIN_IMPORTE
