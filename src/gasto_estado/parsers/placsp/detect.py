"""Detección de la época ("vintage") del CODICE de PLACSP.

Igual que en el Anexo I de la IGAE (CLAUDE.md §2): no un parser único frágil,
sino una familia por vintage con detección de formato. PLACSP publica en CODICE,
cuyos espacios de nombres versionan la maquetación:

- ``codice2`` (familia ``urn:dgpe:names:draft:codice:schema:xsd:*-2``): el formato
  vigente verificado (cabecera 2026 y ZIP anuales 2012-2026 comparten estos
  espacios de nombres). Las listas de códigos internas (``…-2.04``, ``…-2.09``)
  evolucionan dentro de la misma familia; eso NO cambia la gramática estructural,
  así que enrutan al mismo parser.

La detección va por el espacio de nombres del feed, no por la URL ni el año: es
lo robusto frente a futuros volcados (un eventual CODICE 3 / eForms se añadiría
como nuevo vintage sin tocar el parser de ``codice2``).
"""

from __future__ import annotations

from lxml import etree

VINTAGE_CODICE2 = "codice2"

# Marca de la familia CODICE 2.x (componentes básicos comunes).
_CODICE2_NS = "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
_ATOM_NS = "http://www.w3.org/2005/Atom"


def detect_vintage(root: etree._Element) -> str:
    """Devuelve el vintage CODICE del feed cuya raíz es ``root``.

    *Fail loud* (CLAUDE.md §2): si no es un feed Atom o no declara la familia
    CODICE 2.x, se aborta en vez de adivinar un parser.
    """
    if not root.tag == f"{{{_ATOM_NS}}}feed":
        raise ValueError(
            f"La raíz no es un feed Atom de PLACSP (tag={root.tag!r})."
        )
    namespaces = set(root.nsmap.values())
    if _CODICE2_NS in namespaces:
        return VINTAGE_CODICE2
    raise ValueError(
        "Feed PLACSP de vintage CODICE desconocido: no declara la familia "
        f"{_CODICE2_NS!r} (espacios de nombres: {sorted(namespaces)[:6]}…)."
    )
