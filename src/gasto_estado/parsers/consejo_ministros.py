"""Parser de las referencias del Consejo de Ministros (HTML) → canónico.

SOLO raw → DataFrame canónico (CLAUDE.md §2). GRANO = una fila por acuerdo del
bloque SUMARIO (la lista COMPLETA; AMPLIACIÓN solo desarrolla algunos). Clave
natural sintética ``acuerdo_id = <fecha>#<índice>``: la referencia no da un id
estable por acuerdo, así que la carga reemplaza el bloque entero de la fecha
(docs/consejo_ministros_estructura.md §7-8).

Familia de parsers por vintage (CLAUDE.md §2): el invariante entre maquetaciones
es robusto (bloque SUMARIO, ``<h3>`` = ministerio proponente, items de lista cuyo
texto empieza por el tipo de acuerdo), así que un único recorrido del DOM cubre
ambos vintages observados; ``detect_vintage`` falla *loud* ante una página que no
sea una referencia. NO es contabilidad (CLAUDE.md §3): señal de decisiones
políticas, con importe + confianza y ``texto_bruto`` conservado.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from lxml import html as lxml_html

from gasto_estado.parsers.importe_texto import extraer_importe
from gasto_estado.parsers.schemas import cdm_acuerdo_schema
from gasto_estado.transform.text import normalize as _norm

FUENTE = "consejo_ministros"

# Vintages observados (docs §4). La detección va por marcadores del HTML, no por
# la URL: robusta frente a futuros rediseños del portal de La Moncloa.
VINTAGE_V2018 = "v2018_2021"
VINTAGE_V2024 = "v2024_plus"

# Patrones de URL oficial por vintage (espejo de config/sources.yaml; el parser
# es la capa que conoce el vintage y reconstruye el enlace a la referencia).
_URL_V2024 = (
    "https://www.lamoncloa.gob.es/consejodeministros/referencias/Paginas/"
    "{anio}/{fecha}-referencia-rueda-de-prensa-ministros.aspx"
)
_URL_V2018 = (
    "https://www.lamoncloa.gob.es/consejodeministros/referencias/Paginas/{anio}/refc{fecha}.aspx"
)

# Tipos de acuerdo (enum cerrado, columna tipo_acuerdo). docs §5.
TIPO_AUTORIZACION_GASTO = "autorizacion_gasto"
TIPO_SUBVENCION = "subvencion"
TIPO_TRANSFERENCIA_CREDITO = "transferencia_credito"
TIPO_CREDITO_SUPLEMENTO = "credito_suplemento"
TIPO_CONVENIO = "convenio"
TIPO_NORMA = "norma"
TIPO_PERSONAL = "personal"
TIPO_OTRO = "otro"

TIPOS_ACUERDO = (
    TIPO_AUTORIZACION_GASTO,
    TIPO_SUBVENCION,
    TIPO_TRANSFERENCIA_CREDITO,
    TIPO_CREDITO_SUPLEMENTO,
    TIPO_CONVENIO,
    TIPO_NORMA,
    TIPO_PERSONAL,
    TIPO_OTRO,
)

# Cabecera del bloque que abre el SUMARIO.
_MARCA_SUMARIO = "sumario"


class ReferenciaNoReconocida(ValueError):
    """El HTML no es una referencia del Consejo (no trae el bloque SUMARIO)."""


def _texto(el: Any) -> str:
    """Texto visible de un elemento, con espacios colapsados."""
    return re.sub(r"\s+", " ", el.text_content()).strip()


def _es_marcador_fin(n: str) -> bool:
    """¿Cabecera que cierra el SUMARIO (AMPLIACIÓN/biografías/más información)?"""
    return (
        n.startswith("ampliacion de contenido")
        or n.startswith("biografia")
        or "mas informacion" in n
    )


def _es_marcador_personal(n: str) -> bool:
    """¿Cabecera de bloque de personal/condecoraciones (no es un ministerio)?"""
    return (
        n.startswith("acuerdos de personal")
        or n.startswith("condecoraciones")
        or n == "personal"
        or "nombramiento" in n
    )


def detect_vintage(content: bytes) -> str:
    """Vintage de maquetación de la referencia; *fail loud* si no lo es."""
    if b"RefCDepar" in content or b"ListaUL" in content:
        return VINTAGE_V2018
    if b"SUMARIO" in content or b"sumario" in content.lower():
        return VINTAGE_V2024
    raise ReferenciaNoReconocida(
        "El HTML no es una referencia del Consejo de Ministros reconocible "
        "(sin bloque SUMARIO ni marcadores de vintage conocidos)."
    )


def classify_tipo(descripcion: str | None, *, en_bloque_personal: bool) -> str:
    """Clasifica un acuerdo por su texto (y si cuelga del bloque de personal).

    Orden de precedencia (docs §5): crédito > transferencia > subvención >
    convenio > norma > autorización de gasto > otro. El bloque de personal
    fuerza ``personal`` con independencia del texto.
    """
    if en_bloque_personal:
        return TIPO_PERSONAL
    n = _norm(descripcion)
    if not n:
        return TIPO_OTRO
    if "credito extraordinario" in n or "suplemento de credito" in n:
        return TIPO_CREDITO_SUPLEMENTO
    if "transferencia de credito" in n or "transferencias de credito" in n:
        return TIPO_TRANSFERENCIA_CREDITO
    if "subvencion" in n or "ayudas" in n:
        return TIPO_SUBVENCION
    primera = n.split(" ", 1)[0]
    if primera == "convenio":
        return TIPO_CONVENIO
    if (
        n.startswith("real decreto")
        or n.startswith("reales decretos")
        or n.startswith("proyecto de ley")
        or n.startswith("anteproyecto")
    ):
        return TIPO_NORMA
    if n.startswith("acuerdo") and any(
        marca in n for marca in ("gasto", "contrat", "celebracion", "adquisicion", "compromisos")
    ):
        return TIPO_AUTORIZACION_GASTO
    return TIPO_OTRO


def _url_oficial(vintage: str, fecha: date | None) -> str | None:
    if fecha is None:
        return None
    patron = _URL_V2018 if vintage == VINTAGE_V2018 else _URL_V2024
    return patron.format(anio=f"{fecha.year:04d}", fecha=fecha.strftime("%Y%m%d"))


CDM_COLUMNS = [
    "periodo",
    "fuente",
    "fecha_captura",
    "acuerdo_id",
    "fecha",
    "ministerio",
    "tipo_acuerdo",
    "descripcion",
    "importe",
    "importe_confianza",
    "vintage",
    "url_oficial",
    "texto_bruto",
]

_FLOAT_COLS = ["importe"]
_OBJECT_COLS = {"fecha_captura", "fecha"}
_DTYPES: dict[str, Any] = {
    c: "str" for c in CDM_COLUMNS if c not in _OBJECT_COLS and c not in _FLOAT_COLS
}
_DTYPES |= dict.fromkeys(_FLOAT_COLS, "float64")
_DTYPES |= dict.fromkeys(_OBJECT_COLS, "object")


def parse_referencia(
    content: bytes, *, fecha: date | None, fecha_captura: date | None = None
) -> list[dict[str, Any]]:
    """Acuerdos del SUMARIO de una referencia (lista de filas canónicas).

    Recorre el DOM en orden de documento desde la cabecera ``SUMARIO`` hasta el
    cierre del bloque (AMPLIACIÓN/biografías): cada ``<h3>`` fija el ministerio
    proponente; cada ítem de lista hoja es un acuerdo. Las cabeceras de personal
    /condecoraciones cambian el bloque (sus ítems salen como ``personal``).
    """
    vintage = detect_vintage(content)
    root = lxml_html.fromstring(content)
    url = _url_oficial(vintage, fecha)
    periodo = None if fecha is None else f"{fecha.year:04d}-{fecha.month:02d}"

    filas: list[dict[str, Any]] = []
    en_sumario = False
    en_personal = False
    ministerio: str | None = None
    indice = 0

    for el in root.iter("h2", "h3", "li"):
        tag = el.tag
        if tag == "h2":
            n = _norm(_texto(el))
            if n == _MARCA_SUMARIO:
                en_sumario, en_personal = True, False
            elif en_sumario and _es_marcador_fin(n):
                break
            elif en_sumario and _es_marcador_personal(n):
                en_personal = True
            continue
        if not en_sumario:
            continue
        if tag == "h3":
            n = _norm(_texto(el))
            if _es_marcador_personal(n):
                en_personal, ministerio = True, None
            else:
                ministerio = _texto(el) or None
            continue
        if tag == "li":
            if el.find(".//li") is not None:  # contenedor de sub-lista, no hoja
                continue
            descripcion = _texto(el)
            if not descripcion:
                continue
            importe, confianza = extraer_importe(descripcion)
            filas.append(
                {
                    "periodo": periodo,
                    "fuente": FUENTE,
                    "fecha_captura": fecha_captura,
                    "acuerdo_id": None if fecha is None else f"{fecha.isoformat()}#{indice:03d}",
                    "fecha": fecha,
                    "ministerio": ministerio,
                    "tipo_acuerdo": classify_tipo(descripcion, en_bloque_personal=en_personal),
                    "descripcion": descripcion,
                    "importe": importe,
                    "importe_confianza": confianza,
                    "vintage": vintage,
                    "url_oficial": url,
                    "texto_bruto": descripcion,
                }
            )
            indice += 1
    return filas


def _frame(filas: list[dict[str, Any]]) -> pd.DataFrame:
    detalle = pd.DataFrame(filas, columns=CDM_COLUMNS).astype(_DTYPES)
    if len(detalle):
        detalle = detalle.drop_duplicates(subset=["acuerdo_id"], keep="last").reset_index(drop=True)
    return cdm_acuerdo_schema.validate(detalle)


def _fecha_de_dir(nombre: str) -> date | None:
    if len(nombre) == 8 and nombre.isdigit():
        return date(int(nombre[:4]), int(nombre[4:6]), int(nombre[6:8]))
    return None


def discover_capturas(raw_dir: Path) -> list[str]:
    """Fechas de captura del Consejo de Ministros en raw, ascendentes."""
    base = raw_dir / FUENTE
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def parse_capture_dir(capture_dir: Path, *, fecha_captura: date | None = None) -> pd.DataFrame:
    """Parsea todas las referencias (una por día) de una captura."""
    if fecha_captura is None:
        try:
            fecha_captura = date.fromisoformat(capture_dir.name)
        except ValueError:
            fecha_captura = None
    referencias = sorted(capture_dir.glob("*/referencia.html"))
    if not referencias:
        raise FileNotFoundError(
            f"Sin referencias del Consejo (<AAAAMMDD>/referencia.html) en {capture_dir}. "
            "¿Descargaste con 'extract --source consejo_ministros'?"
        )
    sin_sumario: list[str] = []
    filas: list[dict[str, Any]] = []
    for ruta in referencias:
        fecha = _fecha_de_dir(ruta.parent.name)
        try:
            filas.extend(
                parse_referencia(ruta.read_bytes(), fecha=fecha, fecha_captura=fecha_captura)
            )
        except ReferenciaNoReconocida:
            # No es una referencia (página de error colada en raw): se anota y
            # se sigue; no se aborta toda la captura por un día corrupto.
            sin_sumario.append(ruta.parent.name)
    if not filas and sin_sumario:
        raise ReferenciaNoReconocida(
            f"Ninguna referencia reconocible en {capture_dir} (días: {sin_sumario})."
        )
    return _frame(filas)
