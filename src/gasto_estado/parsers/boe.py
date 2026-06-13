"""Parser del BOE: sumario diario + disposiciones de interés → canónico.

SOLO raw → DataFrame canónico (CLAUDE.md §2). GRANO = una fila por disposición
de interés (clave natural = ``identificador`` BOE). El sumario aporta el árbol
sección → departamento (ministerio proponente) → item (id, título, ``url_html``)
y prefiltra los candidatos; la disposición individual confirma con
``analisis/tipo`` (clasificación oficial, p. ej. 63 = Subvenciones SNPS), el
texto en párrafos, el ``BDNS(Identif.)`` de los extractos y el importe embebido.

NO es contabilidad (CLAUDE.md §3): es señal de "decisiones políticas". La
extracción degrada con elegancia (CLAUDE.md §9): lo no derivable queda nulo y
el ``texto_bruto`` se conserva para revisión humana; el importe sale con su
grado de confianza, nunca un cero falso. Clasificación y formato de la fuente:
docs/boe_estructura.md.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd

from gasto_estado.extractors.boe_sumario import es_disposicion_interes
from gasto_estado.parsers.importe_texto import SIN_IMPORTE, extraer_importe
from gasto_estado.parsers.schemas import boe_disposicion_schema
from gasto_estado.transform.text import normalize as _norm

FUENTE = "boe_sumario"

# Tipos de disposición (enum cerrado, columna tipo_disposicion). docs §5.
TIPO_CONVOCATORIA = "convocatoria_subvencion"
TIPO_SUBVENCION_DIRECTA = "subvencion_directa"
TIPO_CREDITO_EXTRAORDINARIO = "credito_extraordinario"
TIPO_SUPLEMENTO_CREDITO = "suplemento_credito"
TIPO_TRANSFERENCIA_CREDITO = "transferencia_credito"
TIPO_MODIFICACION_CREDITO = "modificacion_credito"
TIPO_OTRO = "otro"

TIPOS_DISPOSICION = (
    TIPO_CONVOCATORIA,
    TIPO_SUBVENCION_DIRECTA,
    TIPO_CREDITO_EXTRAORDINARIO,
    TIPO_SUPLEMENTO_CREDITO,
    TIPO_TRANSFERENCIA_CREDITO,
    TIPO_MODIFICACION_CREDITO,
    TIPO_OTRO,
)

# Clasificación oficial del BOE (analisis/tipo) que marca un extracto SNPS.
_ANALISIS_TIPO_SUBVENCION = "63"

# Patrones de título (sobre texto normalizado: minúsculas, sin acentos). El
# orden de evaluación va de lo más específico a lo más genérico.
_RE_CREDITO_EXTRA = re.compile(r"credito(s)? extraordinario")
_RE_SUPLEMENTO = re.compile(r"suplemento(s)? de credito")
_RE_TRANSFERENCIA = re.compile(r"transferencia(s)? de credito")
_RE_SUBVENCION_DIRECTA = re.compile(r"concesion directa de (una |la |unas |las )?subvencion")
_RE_CONVOCATORIA = re.compile(
    r"se convocan? .{0,40}(subvencion|ayudas)|convocatoria de (subvencion|ayudas)"
)
_RE_MODIFICACION = re.compile(
    r"(ampliacion|generacion|incorporacion) de credito|modificacion .{0,40}credito"
)

# "BDNS(Identif.):742455" — puente con la concesión/convocatoria BDNS.
_BDNS_RE = re.compile(r"BDNS\s*\(\s*Identif\.?\s*\)\s*:?\s*(\d+)", re.IGNORECASE)

BOE_COLUMNS = [
    "periodo",
    "fuente",
    "fecha_captura",
    "identificador",
    "fecha",
    "seccion_boe",
    "departamento",
    "tipo_disposicion",
    "titulo",
    "bdns_id",
    "importe",
    "importe_confianza",
    "url_oficial",
    "texto_bruto",
]

_FLOAT_COLS = ["importe"]
_OBJECT_COLS = {"fecha_captura", "fecha"}
_DTYPES: dict[str, Any] = {
    c: "str" for c in BOE_COLUMNS if c not in _OBJECT_COLS and c not in _FLOAT_COLS
}
_DTYPES |= dict.fromkeys(_FLOAT_COLS, "float64")
_DTYPES |= dict.fromkeys(_OBJECT_COLS, "object")


def classify_tipo(titulo: str | None, analisis_tipo: str | None) -> str:
    """Clasifica la disposición por su título y el tipo oficial del BOE.

    El ``analisis/tipo`` es fiable cuando está (subvenciones); los RD/RDL no lo
    rellenan, por eso la decisión NO depende solo de ese campo (docs §5, §7).
    """
    n = _norm(titulo)
    if _RE_CREDITO_EXTRA.search(n):
        return TIPO_CREDITO_EXTRAORDINARIO
    if _RE_SUPLEMENTO.search(n):
        return TIPO_SUPLEMENTO_CREDITO
    if _RE_TRANSFERENCIA.search(n):
        return TIPO_TRANSFERENCIA_CREDITO
    if _RE_SUBVENCION_DIRECTA.search(n):
        return TIPO_SUBVENCION_DIRECTA
    if (
        analisis_tipo == _ANALISIS_TIPO_SUBVENCION
        or n.startswith("extracto")
        or _RE_CONVOCATORIA.search(n)
    ):
        return TIPO_CONVOCATORIA
    if _RE_MODIFICACION.search(n):
        return TIPO_MODIFICACION_CREDITO
    return TIPO_OTRO


def _periodo(fecha: date | None) -> str | None:
    return None if fecha is None else f"{fecha.year:04d}-{fecha.month:02d}"


def _fecha_yyyymmdd(txt: str | None) -> date | None:
    if not txt or len(txt) < 8 or not txt[:8].isdigit():
        return None
    return date(int(txt[:4]), int(txt[4:6]), int(txt[6:8]))


def parse_sumario(content: bytes) -> tuple[date | None, list[dict[str, Any]]]:
    """(fecha del boletín, candidatos de interés) de un sumario XML.

    Un candidato = ``{identificador, seccion_boe, departamento, titulo,
    url_html}``. El prefiltro de interés es el MISMO del extractor (sección +
    título): no se ingiere personal, contratación ni justicia.
    """
    raiz = ET.fromstring(content)
    fecha = _fecha_yyyymmdd(raiz.findtext(".//sumario/metadatos/fecha_publicacion"))
    candidatos: list[dict[str, Any]] = []
    for seccion in raiz.iter("seccion"):
        seccion_cod = seccion.get("codigo") or ""
        for depto in seccion.iter("departamento"):
            depto_nombre = depto.get("nombre")
            for item in depto.iter("item"):
                ident = item.findtext("identificador")
                titulo = item.findtext("titulo") or ""
                if not ident or not es_disposicion_interes(seccion_cod, titulo):
                    continue
                candidatos.append(
                    {
                        "identificador": ident,
                        "seccion_boe": seccion_cod,
                        "departamento": depto_nombre,
                        "titulo": titulo.strip() or None,
                        "url_html": item.findtext("url_html"),
                    }
                )
    return fecha, candidatos


def parse_disposicion(content: bytes) -> dict[str, Any]:
    """Campos derivados del texto de una disposición individual.

    Devuelve ``analisis_tipo``, ``subseccion``, ``bdns_id``, ``importe`` +
    ``importe_confianza`` y ``texto_bruto`` (los párrafos, conservados).
    """
    doc = ET.fromstring(content)
    tipo_el = doc.find(".//analisis/tipo")
    analisis_tipo = tipo_el.get("codigo") if tipo_el is not None else None
    parrafos = ["".join(p.itertext()).strip() for p in doc.findall(".//texto/p")]
    parrafos = [p for p in parrafos if p]
    texto_bruto = "\n".join(parrafos) or None
    plano = " ".join(parrafos)
    bdns = _BDNS_RE.search(plano)
    importe, confianza = extraer_importe(plano)
    return {
        "analisis_tipo": (analisis_tipo or None),
        "subseccion": (doc.findtext(".//metadatos/subseccion") or None),
        "bdns_id": (bdns.group(1) if bdns else None),
        "importe": importe,
        "importe_confianza": confianza,
        "texto_bruto": texto_bruto,
    }


def _fila(
    candidato: dict[str, Any],
    disposicion: dict[str, Any] | None,
    *,
    fecha: date | None,
    fecha_captura: date | None,
) -> dict[str, Any]:
    disp = disposicion or {}
    importe = disp.get("importe")
    confianza = disp.get("importe_confianza", SIN_IMPORTE)
    return {
        "periodo": _periodo(fecha),
        "fuente": FUENTE,
        "fecha_captura": fecha_captura,
        "identificador": candidato["identificador"],
        "fecha": fecha,
        "seccion_boe": candidato.get("seccion_boe") or None,
        "departamento": candidato.get("departamento"),
        "tipo_disposicion": classify_tipo(candidato.get("titulo"), disp.get("analisis_tipo")),
        "titulo": candidato.get("titulo"),
        "bdns_id": disp.get("bdns_id"),
        "importe": importe,
        "importe_confianza": confianza,
        "url_oficial": candidato.get("url_html"),
        "texto_bruto": disp.get("texto_bruto"),
    }


def parse_dia(
    sumario_path: Path, disposiciones_dir: Path | None, *, fecha_captura: date | None
) -> list[dict[str, Any]]:
    """Filas canónicas de un día: sumario + disposiciones presentes en disco.

    Una disposición de interés cuyo XML no esté en disco aún se emite (con los
    campos del texto a nulo): el sumario ya da identificador, departamento y
    título — degradación elegante, no se pierde la señal.
    """
    fecha, candidatos = parse_sumario(sumario_path.read_bytes())
    filas: list[dict[str, Any]] = []
    for cand in candidatos:
        disp: dict[str, Any] | None = None
        if disposiciones_dir is not None:
            disp_path = disposiciones_dir / f"{cand['identificador']}.xml"
            if disp_path.exists():
                disp = parse_disposicion(disp_path.read_bytes())
        filas.append(_fila(cand, disp, fecha=fecha, fecha_captura=fecha_captura))
    return filas


def _frame(filas: list[dict[str, Any]]) -> pd.DataFrame:
    detalle = pd.DataFrame(filas, columns=BOE_COLUMNS).astype(_DTYPES)
    if len(detalle):
        # Un identificador puede repetirse si un rango re-descarga el mismo día
        # en capturas distintas: una sola fila por disposición (clave natural).
        detalle = detalle.drop_duplicates(subset=["identificador"], keep="last").reset_index(
            drop=True
        )
    return boe_disposicion_schema.validate(detalle)


def discover_capturas(raw_dir: Path) -> list[str]:
    """Fechas de captura BOE disponibles en raw, ascendentes."""
    base = raw_dir / "boe"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def parse_capture_dir(capture_dir: Path, *, fecha_captura: date | None = None) -> pd.DataFrame:
    """Parsea todos los días (sumario + disposiciones) de una captura BOE."""
    if fecha_captura is None:
        try:
            fecha_captura = date.fromisoformat(capture_dir.name)
        except ValueError:
            fecha_captura = None
    sumarios = sorted(capture_dir.glob("*/sumario.xml"))
    if not sumarios:
        raise FileNotFoundError(
            f"Sin sumarios BOE (<AAAAMMDD>/sumario.xml) en {capture_dir}. "
            "¿Descargaste con 'extract --source boe'?"
        )
    filas: list[dict[str, Any]] = []
    for sumario_path in sumarios:
        disp_dir = sumario_path.parent / "disposiciones"
        filas.extend(
            parse_dia(
                sumario_path,
                disp_dir if disp_dir.is_dir() else None,
                fecha_captura=fecha_captura,
            )
        )
    return _frame(filas)
