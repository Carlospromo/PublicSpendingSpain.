"""Normalización de denominaciones oficiales para matching y clasificación.

DIR3 mezcla denominaciones con y sin acentos y usa abreviaturas de rango
orgánico. Expansiones VERIFICADAS contra el listado real de unidades AGE
(captura 2026-06-10):

- ``D.G. de la Guardia Civil``      → dirección general
- ``S. de E. de Seguridad``         → secretaría de estado
- ``S.Gral. de Politica de Defensa`` → secretaría general

NO se expande ``S.G.`` porque en DIR3 denota Subdirección General (294 casos):
expandirla a "secretaría general" produciría falsos positivos de rango.
"""

from __future__ import annotations

import re
import unicodedata

# Expansiones sobre el texto ya en minúsculas, sin acentos ni puntuación.
_ABREVIATURAS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^d\s*g\b"), "direccion general"),
    (re.compile(r"^direccion gral\b"), "direccion general"),
    (re.compile(r"^s de e\b"), "secretaria de estado"),
    (re.compile(r"^s\s*gral\b"), "secretaria general"),
)


def normalize(text: str | None) -> str:
    """Minúsculas, sin acentos ni puntuación, abreviaturas expandidas."""
    s = "".join(
        c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"[^\w\s]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    for pattern, replacement in _ABREVIATURAS:
        s = pattern.sub(replacement, s)
    return s
