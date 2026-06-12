"""Parser de la BDNS / SNPSAP: páginas JSON de concesiones → canónico.

GRANO = **una fila por concesión** (el compromiso jurídico individual, donde
vive el importe). La convocatoria es un ATRIBUTO de la fila (id, código y
título), nunca una fila propia: sumar convocatorias y concesiones a la vez
sería doble conteo — el ``presupuestoTotal`` de la convocatoria es un techo de
licitación, no gasto comprometido, y por eso NO entra en este hecho (mismo
patrón que expediente↔lotes en PLACSP, docs/bdns_estructura.md §4).

El dato bruto es ruidoso y la robustez vive en la normalización y el anclaje:

- el órgano concedente llega SOLO como texto jerárquico ``nivel1/2/3`` (la API
  no publica DIR3; VERIFICADO 2026-06-12) — se conserva tal cual y el anclaje
  lo resuelve después;
- el beneficiario llega como ``"<NIF> <NOMBRE>"`` con el NIF de personas
  físicas enmascarado de origen (``***dddd**``): se separa NIF/nombre y se
  clasifica física/jurídica por la forma del identificador; ``idPersona`` es
  el id estable de plataforma;
- TODA ausencia es nulo explícito, nunca cero.

Republicaciones: la BDNS corrige/reinsertea concesiones (mismo ``id``); dentro
de una captura se conserva la foto con mayor ``fecha_alta`` (desempate
determinista por orden de página).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from gasto_estado.parsers.schemas import bdns_concesion_schema

FUENTE = "bdns"

# Contrato canónico (pre-anclaje). El anclaje orgánico añade seccion/servicio y
# las señales de fiabilidad en transform/anclaje_organico.py.
BDNS_COLUMNS = [
    "periodo",
    "fuente",
    "fecha_captura",
    "concesion_id",
    "concesion_cod",
    "convocatoria_id",
    "convocatoria_cod",
    "convocatoria_titulo",
    "nivel1",
    "nivel2",
    "nivel3",
    "codigo_invente",
    "instrumento",
    "importe",
    "ayuda_equivalente",
    "beneficiario_id",
    "beneficiario_nif",
    "beneficiario_nombre",
    "beneficiario_tipo",
    "tiene_proyecto",
    "url_br",
    "fecha_concesion",
    "fecha_alta",
]

# Formas del identificador del beneficiario (primer token del campo bruto):
# NIF de persona física enmascarado de origen por el SNPSAP (RGPD), DNI/NIE en
# claro (no observado, pero posible) y NIF de persona jurídica (en claro).
_NIF_ENMASCARADO_RE = re.compile(r"^\*+\w+\*+$")
_NIF_FISICA_RE = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")
_NIF_JURIDICA_RE = re.compile(r"^[A-HJNP-SUVW]\d{7}[0-9A-J]$")

PERSONA_FISICA = "fisica"
PERSONA_JURIDICA = "juridica"

# Dtypes del canónico: como en PLACSP, las columnas de texto toda-nulas
# quedarían como object y romperían la validación; se coercionan siempre.
_FLOAT_COLS = ["importe", "ayuda_equivalente"]
_OBJECT_COLS = {"fecha_captura", "tiene_proyecto", "fecha_concesion", "fecha_alta"}
_DTYPES: dict[str, Any] = {
    c: "str" for c in BDNS_COLUMNS if c not in _OBJECT_COLS and c not in _FLOAT_COLS
}
_DTYPES |= dict.fromkeys(_FLOAT_COLS, "float64")
# Y las object explícitas: un lote donde tiene_proyecto nunca es nulo se
# inferiría como bool y rompería el contrato (pandera espera object).
_DTYPES |= dict.fromkeys(_OBJECT_COLS, "object")


def split_beneficiario(bruto: object) -> tuple[str | None, str | None, str | None]:
    """Separa el campo bruto ``"<NIF> <NOMBRE>"`` → (nif, nombre, tipo).

    Si el primer token no tiene forma de NIF (ni enmascarado), no se inventa
    una separación: todo el texto queda como nombre y nif/tipo a nulo.
    """
    if bruto is None or (isinstance(bruto, float) and pd.isna(bruto)):
        return None, None, None
    texto = str(bruto).strip()
    if not texto:
        return None, None, None
    token, _, resto = texto.partition(" ")
    nombre = resto.strip() or None
    if _NIF_ENMASCARADO_RE.match(token) or _NIF_FISICA_RE.match(token):
        return token, nombre, PERSONA_FISICA
    if _NIF_JURIDICA_RE.match(token):
        return token, nombre, PERSONA_JURIDICA
    return None, texto, None


def _date_iso(txt: object) -> date | None:
    if txt is None:
        return None
    try:
        return date.fromisoformat(str(txt)[:10])
    except ValueError:
        return None


def _texto(valor: object) -> str | None:
    if valor is None:
        return None
    txt = str(valor).strip()
    return txt or None


def _importe(valor: object) -> float | None:
    """Importe → float; ausencia → None (nunca 0)."""
    if valor is None or isinstance(valor, str) and not valor.strip():
        return None
    try:
        return float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fila(concesion: dict[str, Any], *, fecha_captura: date | None) -> dict[str, object]:
    fecha_concesion = _date_iso(concesion.get("fechaConcesion"))
    fecha_alta = _date_iso(concesion.get("fechaAlta"))
    # Periodo del hecho: el mes del compromiso jurídico (fecha de concesión);
    # en su defecto, el alta en la plataforma.
    fecha_ref = fecha_concesion or fecha_alta or fecha_captura
    nif, nombre, tipo = split_beneficiario(concesion.get("beneficiario"))
    ident = concesion.get("id")
    return {
        "periodo": None if fecha_ref is None else f"{fecha_ref.year:04d}-{fecha_ref.month:02d}",
        "fuente": FUENTE,
        "fecha_captura": fecha_captura,
        "concesion_id": None if ident is None else str(ident),
        "concesion_cod": _texto(concesion.get("codConcesion")),
        "convocatoria_id": (
            None if concesion.get("idConvocatoria") is None else str(concesion["idConvocatoria"])
        ),
        "convocatoria_cod": _texto(concesion.get("numeroConvocatoria")),
        "convocatoria_titulo": _texto(concesion.get("convocatoria")),
        "nivel1": _texto(concesion.get("nivel1")),
        "nivel2": _texto(concesion.get("nivel2")),
        "nivel3": _texto(concesion.get("nivel3")),
        "codigo_invente": _texto(concesion.get("codigoInvente")),
        "instrumento": _texto(concesion.get("instrumento")),
        "importe": _importe(concesion.get("importe")),
        "ayuda_equivalente": _importe(concesion.get("ayudaEquivalente")),
        "beneficiario_id": (
            None if concesion.get("idPersona") is None else str(concesion["idPersona"])
        ),
        "beneficiario_nif": nif,
        "beneficiario_nombre": nombre,
        "beneficiario_tipo": tipo,
        "tiene_proyecto": concesion.get("tieneProyecto"),
        "url_br": _texto(concesion.get("urlBR")),
        "fecha_concesion": fecha_concesion,
        "fecha_alta": fecha_alta,
    }


def parse_pagina(content: bytes, *, fecha_captura: date | None = None) -> list[dict[str, object]]:
    """Parsea una página JSON del API (envelope con ``content``) a filas canónicas."""
    pagina = json.loads(content)
    lote = pagina.get("content") if isinstance(pagina, dict) else None
    if lote is None:
        raise ValueError(
            "Página BDNS sin el campo 'content': no es el envelope del API "
            f"(claves={sorted(pagina) if isinstance(pagina, dict) else type(pagina)})."
        )
    return [_fila(c, fecha_captura=fecha_captura) for c in lote]


def parse_captura(paths: list[Path], *, fecha_captura: date | None = None) -> pd.DataFrame:
    """Parsea las páginas raw de una captura y devuelve el canónico validado.

    Dedup de republicaciones: si el mismo ``concesion_id`` aparece varias veces
    (corrección publicada dentro de la ventana), gana la foto con mayor
    ``fecha_alta`` (desempate determinista por orden de lectura).
    """
    filas: list[dict[str, object]] = []
    for path in paths:
        filas.extend(parse_pagina(path.read_bytes(), fecha_captura=fecha_captura))
    detalle = pd.DataFrame(filas, columns=BDNS_COLUMNS).astype(_DTYPES)
    if len(detalle):
        fechas = detalle["fecha_alta"].map(lambda d: d or date.min)
        orden = pd.Series(range(len(detalle)), index=detalle.index)
        clave = pd.Series(zip(fechas, orden, strict=True), index=detalle.index)
        ultima = clave.groupby(detalle["concesion_id"]).transform("max")
        detalle = detalle[clave == ultima].reset_index(drop=True)
    return bdns_concesion_schema.validate(detalle)


def discover_capturas(raw_dir: Path) -> list[str]:
    """Fechas de captura BDNS disponibles en raw, ascendentes."""
    base = raw_dir / FUENTE
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def parse_capture_dir(capture_dir: Path, *, fecha_captura: date | None = None) -> pd.DataFrame:
    """Parsea todas las páginas de concesiones de un directorio de captura."""
    if fecha_captura is None:
        try:
            fecha_captura = date.fromisoformat(capture_dir.name)
        except ValueError:
            fecha_captura = None
    paths = sorted(capture_dir.glob("concesiones/**/page_*.json"))
    if not paths:
        raise FileNotFoundError(
            f"Sin páginas BDNS (concesiones/**/page_*.json) en {capture_dir}. "
            "¿Descargaste con 'extract --source bdns'?"
        )
    return parse_captura(paths, fecha_captura=fecha_captura)
