"""Notificación de fallos del pipeline en CI (Fase 7, resiliencia operativa).

Genera informes de incidencia estructurados cuando una materialización falla
(validación contable, error de descarga persistente, formato no reconocido,
revisión silenciosa). El informe se hace visible de dos formas:

1. **Step summary** de GitHub Actions (``$GITHUB_STEP_SUMMARY``): SIEMPRE que
   esté en CI. Sin configuración, aparece en la UI de Actions sin entrar a logs.
2. **Issue de GitHub** (etiqueta ``pipeline-failure``): OPT-IN con la variable
   de entorno ``GASTO_ESTADO_CREAR_ISSUES=1``. Los issues automáticos pueden ser
   ruidosos para fallos transitorios; el operador los activa explícitamente.

Punto de extensión: la misma estructura ``Incidencia`` sirve para Slack/email
si se añade un canal ``Notificador`` en el futuro.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Incidencia:
    """Informe de incidencia estructurado del pipeline."""

    fuente: str
    particion: str | None
    tipo_fallo: str
    mensaje_diagnostico: str
    ruta_raw: Path | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@runtime_checkable
class Notificador(Protocol):
    """Protocolo de notificación (punto de extensión para Slack/email/etc.)."""

    def notificar(self, incidencia: Incidencia) -> bool: ...


_ICONOS_TIPO = {
    "validacion_contable": "VALIDACION",
    "formato_cambiado": "FORMATO",
    "fuente_no_disponible": "RED",
    "respuesta_vacia": "VACIO",
    "error_carga": "CARGA",
    "error_publicacion": "PUBLICACION",
    "revision_silenciosa": "REVISION",
    # Alias heredados para que los informes previos sigan siendo legibles.
    "formato_no_reconocido": "FORMATO",
    "error_descarga": "RED",
    "url_caida": "URL",
}


def clasificar_fallo(error: BaseException) -> str:
    """Clasifica una excepción sin exponer su traza ni cambiar el flujo de carga."""
    nombre = type(error).__name__.lower()
    mensaje = str(error).lower()
    if "formatonoreconocido" in nombre or "formato" in nombre:
        return "formato_cambiado"
    if "coherence" in nombre or "validacion" in nombre or "contable" in mensaje:
        return "validacion_contable"
    if "empty" in nombre or "vac" in mensaje or "sin contenido" in mensaje:
        return "respuesta_vacia"
    if "transport" in nombre or "timeout" in nombre or "sourceblocked" in nombre:
        return "fuente_no_disponible"
    if "duckdb" in nombre or "load" in nombre or "carga" in mensaje:
        return "error_carga"
    return "error_publicacion"


def huella_incidencia(incidencia: Incidencia) -> str:
    """Identificador estable para no abrir dos issues del mismo fallo operativo."""
    particion = incidencia.particion or "sin-particion"
    return f"gasto-estado:failure:{incidencia.tipo_fallo}:{incidencia.fuente}:{particion}"


def _formato_incidencia(inc: Incidencia) -> str:
    """Formatea una incidencia como bloque markdown."""
    tipo_label = _ICONOS_TIPO.get(inc.tipo_fallo, inc.tipo_fallo.upper())
    lineas = [
        f"### [{tipo_label}] {inc.fuente}",
        "",
        f"- **Tipo**: {inc.tipo_fallo}",
        f"- **Fuente**: {inc.fuente}",
        f"- **Partición**: {inc.particion or 'N/A'}",
        f"- **Timestamp**: {inc.timestamp}",
    ]
    if inc.ruta_raw:
        lineas.append(f"- **Raw**: `{inc.ruta_raw}`")
    lineas.append("")
    lineas.append("**Diagnóstico**:")
    lineas.append("")
    lineas.append(f"```\n{inc.mensaje_diagnostico}\n```")
    return "\n".join(lineas)


def generar_step_summary(incidencias: list[Incidencia]) -> str:
    """Genera el markdown para ``$GITHUB_STEP_SUMMARY``."""
    if not incidencias:
        return "## Pipeline: sin incidencias\n\nTodos los assets se materializaron correctamente.\n"
    lineas = [
        f"## Pipeline: {len(incidencias)} incidencia(s)\n",
    ]
    for inc in incidencias:
        lineas.append(_formato_incidencia(inc))
        lineas.append("")
    return "\n".join(lineas)


def escribir_step_summary(incidencias: list[Incidencia]) -> None:
    """Escribe el step summary si estamos en GitHub Actions (no-op fuera de CI)."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    contenido = generar_step_summary(incidencias)
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(contenido)


def formatear_issue_body(incidencia: Incidencia) -> str:
    """Cuerpo de un issue de GitHub para una incidencia."""
    lineas = [
        f"<!-- {huella_incidencia(incidencia)} -->",
        _formato_incidencia(incidencia),
        "",
        "---",
        f"*Generado automáticamente por el pipeline de materialización ({incidencia.timestamp})*",
    ]
    return "\n".join(lineas)


def crear_issue_si_ci(incidencia: Incidencia) -> bool:
    """Crea un issue en GitHub si estamos en CI y el operador lo ha activado.

    Opt-in: ``GASTO_ESTADO_CREAR_ISSUES=1``. Los issues automáticos son ruidosos
    para fallos transitorios; el operador los activa explícitamente.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return False
    if os.environ.get("GASTO_ESTADO_CREAR_ISSUES") != "1":
        return False

    tipo_label = _ICONOS_TIPO.get(incidencia.tipo_fallo, incidencia.tipo_fallo)
    titulo = f"[pipeline-failure] {tipo_label}: {incidencia.fuente}"
    if incidencia.particion:
        titulo += f" ({incidencia.particion})"
    body = formatear_issue_body(incidencia)

    try:
        existente = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--state",
                "open",
                "--search",
                huella_incidencia(incidencia),
                "--json",
                "number",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if json.loads(existente.stdout):
            return False
        subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                titulo,
                "--body",
                body,
                "--label",
                "pipeline-failure",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True
    except (
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False


def notificar_incidencias(incidencias: list[Incidencia]) -> None:
    """Escribe el step summary y crea issues para las incidencias críticas."""
    if not incidencias:
        return
    escribir_step_summary(incidencias)
    for inc in incidencias:
        crear_issue_si_ci(inc)
