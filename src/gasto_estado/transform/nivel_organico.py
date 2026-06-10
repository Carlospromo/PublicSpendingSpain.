"""Clasificación del nivel orgánico de una unidad DIR3.

DIR3 no expone un campo fiable de rango orgánico: ``C_ID_TIPO_ENT_PUBLICA`` lo
heredan todas las unidades de una entidad (una DG dentro de un organismo
autónomo también figura como "OA"), por lo que NO sirve para distinguir el nivel
de la unidad. Se deriva, por tanto, de (CLAUDE.md §9, verificado sobre el dato
real):

1. patrones de denominación sobre ``C_DNM_UD_ORGANICA`` (señal principal y más
   fiable: prefijos "Ministerio", "Secretaría de Estado", "Subsecretaría",
   "Dirección General"/"D.G."), y
2. la profundidad en el árbol como red de seguridad (nivel jerárquico 1 = raíz
   de la entidad).

Todo se etiqueta: lo no reconocido cae en ``OTRO`` (nunca se descarta). La señal
que determinó cada clasificación se guarda aparte para poder auditarla.
"""

from __future__ import annotations

import re

from gasto_estado.transform.text import normalize

# Valores normalizados del nivel orgánico (enum cerrado).
MINISTERIO = "MINISTERIO"
SECRETARIA_ESTADO = "SECRETARIA_ESTADO"
SUBSECRETARIA = "SUBSECRETARIA"
DIRECCION_GENERAL = "DIRECCION_GENERAL"
ORGANISMO = "ORGANISMO"
OTRO = "OTRO"

NIVELES_ORGANICOS = (
    MINISTERIO,
    SECRETARIA_ESTADO,
    SUBSECRETARIA,
    DIRECCION_GENERAL,
    ORGANISMO,
    OTRO,
)

# Señales de clasificación (para auditoría).
SIGNAL_DENOMINACION = "denominacion"
SIGNAL_PROFUNDIDAD = "profundidad"
SIGNAL_SIN_SENAL = "sin_senal"

# Reglas por denominación, en orden de prioridad. Ancladas a inicio (``^``) para
# que "Subdirección General" NO matchee "Dirección General", etc. Se aplican
# sobre la denominación normalizada (transform.text.normalize: sin acentos ni
# puntuación, abreviaturas "D.G."/"S. de E." ya expandidas).
_DENOMINACION_RULES: tuple[tuple[str, str], ...] = (
    (MINISTERIO, r"^ministerio\b|^presidencia del gobierno$"),
    (SECRETARIA_ESTADO, r"^secretaria de estado\b"),
    (SUBSECRETARIA, r"^subsecretaria\b"),
    (DIRECCION_GENERAL, r"^direccion general\b"),
    # Cabeceras de organismo público con denominación inequívoca. Conservador:
    # lo dudoso queda en OTRO antes que arriesgar un falso positivo.
    (
        ORGANISMO,
        r"^agencia estatal\b|^organismo autonomo\b|^entidad publica empresarial\b"
        r"|^entidad estatal\b|^consejo superior de\b|^autoridad portuaria\b",
    ),
)

_COMPILED_RULES = [(nivel, re.compile(pat)) for nivel, pat in _DENOMINACION_RULES]


def classify(denominacion: str | None, nivel_jerarquico: int) -> tuple[str, str]:
    """Devuelve ``(nivel_organico, señal)`` para una unidad DIR3.

    La señal indica qué regla decidió la etiqueta, para poder auditarla.
    """
    norm = normalize(denominacion)
    for nivel, pattern in _COMPILED_RULES:
        if pattern.search(norm):
            return nivel, SIGNAL_DENOMINACION
    # Red de seguridad: nivel jerárquico 1 = raíz de la entidad (ministerio /
    # Presidencia) que la denominación no haya capturado.
    if nivel_jerarquico == 1:
        return MINISTERIO, SIGNAL_PROFUNDIDAD
    return OTRO, SIGNAL_SIN_SENAL
