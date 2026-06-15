"""Parsers de PLACSP (sindicación 643): detección de vintage CODICE y despacho.

Punto de entrada que toma el raw de una captura (páginas ``.atom`` del modo
incremental y/o ZIP anuales) y devuelve el DataFrame canónico de adjudicaciones,
eligiendo el parser según el vintage detectado (CLAUDE.md §2: familia de parsers
por época). Todos los vintages emiten el MISMO contrato canónico
(``placsp_adjudicacion_schema``).

Deduplicación de captura: PLACSP republica la misma licitación en sucesivas
entregas conforme cambia de estado (PUB → EV → ADJ → RES); VERIFICADO en el ZIP
2012 real: 19.000 entradas para 11.262 licitaciones. DENTRO de una captura nos
quedamos con la foto más reciente de cada ``licitacion_id`` (mayor
``fecha_actualizacion``); el historial entre capturas lo conserva la capa raw
y la semántica de upsert de la carga (docs/placsp_estructura.md §5).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from lxml import etree

from gasto_estado.parsers.schemas import placsp_adjudicacion_schema

from .detect import VINTAGE_CODICE2, detect_vintage
from .v_codice2 import PLACSP_COLUMNS
from .v_codice2 import parse_feed as _parse_codice2

_PARSERS = {
    VINTAGE_CODICE2: _parse_codice2,
}

# Protección contra zip-bomb: tamaño máximo descomprimido admitido por miembro.
_MAX_MEMBER_BYTES = 2_000_000_000

# Dtypes del canónico. pandas infiere el dtype de cadena solo si la columna trae
# ALGÚN valor: una columna toda-nula (p. ej. una página de solo lápidas, sin
# órgano) quedaría como object y rompería la validación; se coerciona siempre
# (None → NaN, nunca el literal "None"). Fechas/booleano-nullable van como
# object por diseño del esquema.
_FLOAT_COLS = [
    "presupuesto_sin_iva",
    "presupuesto_con_iva",
    "valor_estimado",
    "importe_adjudicacion",
]
_OBJECT_COLS = {
    "fecha_captura",
    "adjudicatario_es_pyme",
    "fecha_adjudicacion",
    "fecha_formalizacion",
    "fecha_actualizacion",
}
_DTYPES: dict[str, Any] = {
    c: "str"
    for c in PLACSP_COLUMNS
    if c not in _OBJECT_COLS and c not in _FLOAT_COLS and c != "es_cabecera_expediente"
}
_DTYPES |= dict.fromkeys(_FLOAT_COLS, "float64")
_DTYPES["es_cabecera_expediente"] = bool


def parse_atom(content: bytes, *, fecha_captura: date | None = None) -> list[dict[str, object]]:
    """Parsea un documento ATOM/CODICE (bytes) a filas canónicas."""
    root = etree.parse(io.BytesIO(content)).getroot()
    vintage = detect_vintage(root)
    return _PARSERS[vintage](root, fecha_captura=fecha_captura)


def _filas_de_fichero(path: Path, *, fecha_captura: date | None) -> list[dict[str, object]]:
    if path.suffix.lower() == ".zip":
        filas: list[dict[str, object]] = []
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if not info.filename.lower().endswith(".atom"):
                    continue
                if info.file_size > _MAX_MEMBER_BYTES:
                    raise ValueError(
                        f"Miembro sospechosamente grande en {path.name}: "
                        f"{info.filename} ({info.file_size} bytes)."
                    )
                filas.extend(parse_atom(zf.read(info), fecha_captura=fecha_captura))
        return filas
    return parse_atom(path.read_bytes(), fecha_captura=fecha_captura)


def parse_captura(paths: list[Path], *, fecha_captura: date | None = None) -> pd.DataFrame:
    """Parsea los ficheros raw de una captura y devuelve el canónico validado.

    Acepta páginas ``.atom`` y ZIP anuales mezclados. Dedup por expediente:
    última foto (mayor ``fecha_actualizacion``; desempate determinista por
    ``entry_id``). El orden de ``paths`` no afecta al resultado.
    """
    filas: list[dict[str, object]] = []
    for path in paths:
        filas.extend(_filas_de_fichero(path, fecha_captura=fecha_captura))
    detalle = pd.DataFrame(filas, columns=PLACSP_COLUMNS).astype(_DTYPES)
    if len(detalle):
        # Foto más reciente de cada licitación dentro de la captura. La clave es
        # licitacion_id (id numérico de plataforma): VERIFICADO sobre el ZIP
        # 2012 real (19.000 entries, 5.646 ids republicados) que es estable
        # entre republicaciones; el ContractFolderID NO es único entre órganos.
        # Las filas de una misma entrada (multi-lote) son contiguas: se segmenta
        # en bloques por cambio de (entry_id, fecha_actualizacion) y se conserva
        # ENTERO el bloque más reciente (mayor fecha_actualizacion; desempate
        # por posición del bloque — el orden de paths es determinista).
        fechas = detalle["fecha_actualizacion"].map(lambda d: d or date.min)
        cambio = (detalle["entry_id"] != detalle["entry_id"].shift()) | (fechas != fechas.shift())
        bloque = cambio.cumsum()
        clave = pd.Series(zip(fechas, bloque, strict=True), index=detalle.index)
        ultima = clave.groupby(detalle["licitacion_id"]).transform("max")
        detalle = detalle[clave == ultima]
        # Fotos idénticas adyacentes (mismo entry repetido entre páginas) caen
        # en el mismo bloque: colapsa al ejemplar único por clave natural.
        detalle = detalle.drop_duplicates(subset=["licitacion_id", "lote_id"], keep="first")
        detalle = detalle.reset_index(drop=True)
    return placsp_adjudicacion_schema.validate(detalle)


def discover_capturas(raw_dir: Path) -> list[str]:
    """Fechas de captura PLACSP disponibles en raw, ascendentes."""
    base = raw_dir / "placsp"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def parse_capture_dir(capture_dir: Path, *, fecha_captura: date | None = None) -> pd.DataFrame:
    """Parsea todos los ficheros 643 (atom + zip) de un directorio de captura."""
    if fecha_captura is None:
        try:
            fecha_captura = date.fromisoformat(capture_dir.name)
        except ValueError:
            fecha_captura = None
    paths = sorted(capture_dir.glob("643/**/*.atom")) + sorted(capture_dir.glob("643/**/*.zip"))
    if not paths:
        raise FileNotFoundError(
            f"Sin ficheros PLACSP (643/*.atom|*.zip) en {capture_dir}. "
            "¿Descargaste con 'extract --source placsp'?"
        )
    return parse_captura(paths, fecha_captura=fecha_captura)
