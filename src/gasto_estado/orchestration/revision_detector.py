"""Detección de revisiones silenciosas de la IGAE (Fase 7, resiliencia operativa).

La IGAE revisa a veces un fichero ya publicado sin cambiar la URL (mismo mes,
misma URL, distinto contenido). El extractor descarga inmutable con fecha de
captura, así que ambas versiones coexisten en raw. Este módulo detecta esa
situación: cuando el extractor descarga un periodo que ya existía, compara hash
o tamaño con la captura anterior. Si difiere, registra una nota de revisión en
el ledger de materialización y genera una incidencia, de modo que el operador
sepa que el dato cambió y pueda decidir si recargar.

**No recarga automáticamente**: una revisión silenciosa puede legítimamente
cambiar cifras y eso debe ser una decisión consciente (CLAUDE.md §2: fail loud).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from gasto_estado.orchestration import frescura
from gasto_estado.orchestration.notifications import Incidencia


@dataclass(frozen=True)
class Revision:
    """Revisión silenciosa detectada."""

    fuente: str
    periodo: str
    hash_anterior: str
    hash_nuevo: str
    ruta_anterior: Path
    ruta_nueva: Path


def _hash_fichero(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _buscar_capturas_periodo(raw_dir: Path, fuente: str, periodo: str) -> list[Path]:
    """Busca todos los ficheros raw de un periodo para una fuente IGAE."""
    base = raw_dir / fuente / periodo
    if not base.is_dir():
        return []
    return sorted(base.glob("*.xlsx")) + sorted(base.glob("*.xls"))


def detectar_revision_igae(
    raw_dir: Path,
    periodo: str,
    ruta_descargada: Path,
) -> Revision | None:
    """Compara el fichero recién descargado con las capturas anteriores del mismo periodo.

    Devuelve un ``Revision`` si el contenido difiere de alguna captura previa, None si no.
    Si el fichero es idéntico a uno existente (mismo hash), no hay revisión.
    """
    capturas = _buscar_capturas_periodo(raw_dir, "igae_mensual", periodo)
    if not capturas:
        return None

    hash_nuevo = _hash_fichero(ruta_descargada)
    for captura in capturas:
        if captura == ruta_descargada:
            continue
        hash_anterior = _hash_fichero(captura)
        if hash_anterior != hash_nuevo:
            return Revision(
                fuente="igae_mensual",
                periodo=periodo,
                hash_anterior=hash_anterior,
                hash_nuevo=hash_nuevo,
                ruta_anterior=captura,
                ruta_nueva=ruta_descargada,
            )
    return None


def registrar_revision(
    warehouse_path: Path,
    revision: Revision,
) -> Incidencia:
    """Registra la revisión en el ledger y genera la incidencia."""
    frescura.registrar(
        warehouse_path,
        f"{revision.fuente}_revision",
        particion=revision.periodo,
        filas=0,
    )
    return Incidencia(
        fuente=revision.fuente,
        particion=revision.periodo,
        tipo_fallo="revision_silenciosa",
        mensaje_diagnostico=(
            f"Revisión silenciosa detectada para {revision.periodo}:\n"
            f"  Hash anterior: {revision.hash_anterior} ({revision.ruta_anterior.name})\n"
            f"  Hash nuevo:    {revision.hash_nuevo} ({revision.ruta_nueva.name})\n"
            f"  La IGAE ha modificado el fichero sin cambiar la URL.\n"
            f"  Decide si recargar el periodo con el dato revisado."
        ),
        ruta_raw=revision.ruta_nueva,
    )
