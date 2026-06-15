"""Componentes de UI compartidos entre todas las páginas del dashboard.

Todas las funciones toman datos ya obtenidos de la API; no hacen peticiones
directamente (eso lo hace api_client.py con caché en cada página).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st

# ---------------------------------------------------------------------------
# Formateo de cifras
# ---------------------------------------------------------------------------

_MIL_MILLONES = 1_000_000_000
_MILLON = 1_000_000
_MIL = 1_000


def fmt_eur(valor: float | None, *, corto: bool = False) -> str:
    """Formatea euros: M€ o mm€ o €. None → 'sin dato'."""
    if valor is None:
        return "sin dato"
    if corto:
        if abs(valor) >= _MIL_MILLONES:
            return f"{valor / _MIL_MILLONES:.1f} mm€"
        if abs(valor) >= _MIL:
            return f"{valor / _MILLON:.0f} M€"
        return f"{valor:,.0f} €"
    if abs(valor) >= _MIL_MILLONES:
        return f"{valor / _MIL_MILLONES:,.2f} mm€"
    if abs(valor) >= _MILLON:
        return f"{valor / _MILLON:,.1f} M€"
    return f"{valor:,.0f} €"


def fmt_pct(valor: float | None, decimales: int = 1) -> str:
    if valor is None:
        return "—"
    return f"{valor:.{decimales}f}%"


def fmt_num(valor: int | float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor:,.0f}"


# ---------------------------------------------------------------------------
# Badges de metadatos
# ---------------------------------------------------------------------------

_NATURALEZA_COLOR = {
    "exacta": "green",
    "aproximada": "orange",
    "indiciaria": "red",
}

_NATURALEZA_TEXTO = {
    "exacta": "Exacta",
    "aproximada": "Aproximada ⚠️",
    "indiciaria": "Indiciaria ⚠️⚠️",
}

_SEV_COLOR = {
    "destacada": "🔴",
    "a_revisar": "🟡",
    "informativa": "🔵",
}

_CONF_COLOR = {
    "alta": "🟢",
    "media": "🟡",
    "baja": "🔴",
}


def badge_naturaleza(naturaleza: str | None) -> str:
    if not naturaleza:
        return ""
    return _NATURALEZA_TEXTO.get(naturaleza, naturaleza)


def badge_severidad(sev: str | None) -> str:
    if not sev:
        return ""
    icono = _SEV_COLOR.get(sev, "⚫")
    return f"{icono} {sev.replace('_', ' ').capitalize()}"


def badge_confianza(conf: str | None) -> str:
    if not conf:
        return ""
    icono = _CONF_COLOR.get(conf, "⚫")
    return f"{icono} Confianza {conf}"


# ---------------------------------------------------------------------------
# Cabecera de frescura (aparece en todas las páginas)
# ---------------------------------------------------------------------------

_PERIODICIDAD_MAX_DIAS = {
    "mensual": 45,
    "diaria": 3,
    "semanal": 10,
    "continua": 10,
}


def freshness_header(fuentes_data: list[dict[str, Any]]) -> None:
    """Muestra la frescura de las fuentes como cabecera compacta."""
    if not fuentes_data:
        st.caption("⚠️ Sin datos de frescura (API no disponible o warehouse vacío)")
        return

    hoy = datetime.now(UTC).date()
    cols = st.columns(len(fuentes_data))
    for col, f in zip(cols, fuentes_data, strict=False):
        fuente = f.get("fuente_cod", "?")
        ultima = f.get("ultima_actualizacion")
        periodo = f.get("periodo_cubierto") or []
        periodicidad = f.get("periodicidad", "mensual")
        max_dias = _PERIODICIDAD_MAX_DIAS.get(periodicidad, 45)

        if ultima:
            try:
                fecha = datetime.fromisoformat(ultima).date()
                dias = (hoy - fecha).days
                icono = "🟢" if dias <= max_dias else ("🟡" if dias <= max_dias * 2 else "🔴")
                detalle = f"{dias}d"
            except ValueError:
                icono, detalle = "⚪", "?"
        else:
            icono, detalle = "⚫", "sin dato"

        periodo_str = ""
        if periodo and len(periodo) == 2:
            periodo_str = f"  \n`{periodo[0]} → {periodo[1]}`"

        with col:
            st.caption(f"{icono} **{fuente}**  \n{detalle}{periodo_str}")

    st.divider()


# ---------------------------------------------------------------------------
# Panel de metadatos de respuesta API
# ---------------------------------------------------------------------------


def show_meta(
    meta: dict[str, Any],
    *,
    mostrar_advertencias: bool = True,
    mostrar_cobertura: bool = True,
) -> None:
    """Muestra metadatos de fiabilidad de una respuesta API (naturaleza, frescura, advertencias)."""
    naturaleza = meta.get("naturaleza")
    advertencias = meta.get("advertencias") or []
    cobertura = meta.get("cobertura_anclaje")

    cols = st.columns([1, 2, 2])
    with cols[0]:
        if naturaleza:
            color = _NATURALEZA_COLOR.get(naturaleza, "gray")
            st.markdown(
                f"<span style='background-color:{color};color:white;"
                f"padding:2px 8px;border-radius:4px;font-size:0.85em'>"
                f"{badge_naturaleza(naturaleza)}</span>",
                unsafe_allow_html=True,
            )
    with cols[1]:
        frescura_meta = meta.get("frescura") or {}
        if isinstance(frescura_meta, dict):
            ult = frescura_meta.get("ultima_actualizacion")
            if ult:
                st.caption(f"Última actualización: `{ult}`")
    with cols[2]:
        fuentes = meta.get("fuentes") or []
        if fuentes:
            st.caption(f"Fuente(s): {', '.join(fuentes)}")

    if mostrar_advertencias and advertencias:
        for adv in advertencias:
            st.warning(adv, icon="⚠️")

    if mostrar_cobertura and cobertura and isinstance(cobertura, dict):
        pct = cobertura.get("pct_anclado_a_servicio")
        nota = cobertura.get("nota", "")
        if pct is not None:
            color = "green" if pct >= 60 else ("orange" if pct >= 30 else "red")
            st.caption(
                f"Cobertura de anclaje: **{pct:.1f}%** del importe atribuido a servicio. {nota}"
            )


# ---------------------------------------------------------------------------
# Navegación entre páginas (evidencias navegables)
# ---------------------------------------------------------------------------


def parse_evidencia_ref(ref: str) -> dict[str, str]:
    """Parsea un 'ref' de evidencia tipo 'v_ejecucion periodo=X seccion_cod=Y' → dict."""
    parts = ref.split()
    result: dict[str, str] = {}
    if parts:
        result["_vista"] = parts[0]
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            result[k] = v
    return result


def enlace_evidencia(evidencia: dict[str, Any], label: str = "Ver evidencia") -> None:
    """Muestra un enlace navegable para una evidencia de alerta."""
    tipo = evidencia.get("tipo", "")
    ref = evidencia.get("ref", "")

    if tipo == "serie_historica":
        periodos = evidencia.get("mismo_mes", [])
        grados = evidencia.get("grados_pct", [])
        if periodos and grados:
            import pandas as pd
            import plotly.graph_objects as go

            df = pd.DataFrame({"periodo": periodos, "grado_pct": grados})
            fig = go.Figure(
                go.Bar(x=df["periodo"], y=df["grado_pct"], name="Grado histórico (mismo mes)")
            )
            fig.update_layout(
                title="Histórico mismo-mes (base de la norma)",
                yaxis_title="Grado ejecución (%)",
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True)

    elif tipo in ("aplicaciones", "contratos", "acuerdos"):
        params = parse_evidencia_ref(ref)
        vista = params.get("_vista", "")
        info_parts = []
        if params.get("seccion_cod"):
            info_parts.append(f"sección `{params['seccion_cod']}`")
        if params.get("servicio_cod"):
            info_parts.append(f"servicio `{params['servicio_cod']}`")
        if params.get("periodo"):
            info_parts.append(f"periodo `{params['periodo']}`")
        if params.get("ejercicio"):
            info_parts.append(f"ejercicio `{params['ejercicio']}`")

        destino_page = {
            "v_ejecucion": "pages/ejecucion.py",
            "v_contratos": "pages/compromisos.py",
            "v_decisiones": "pages/decisiones.py",
        }.get(vista)

        context = ", ".join(info_parts) if info_parts else "ver detalles"
        if destino_page:
            st.page_link(destino_page, label=f"🔗 {label} — {context}")
        else:
            st.caption(f"📎 Referencia: {ref}")


# ---------------------------------------------------------------------------
# Utilitario: periodo → año
# ---------------------------------------------------------------------------


def periodo_a_ejercicio(periodo: str) -> int:
    return int(periodo[:4])


def periodos_de_ejercicio(ejercicio: int) -> list[str]:
    """Genera la lista de periodos YYYY-MM para un ejercicio.

    Devuelve hasta el mes actual si es el año en curso.
    """
    hoy = datetime.now(UTC)
    meses = 12 if ejercicio < hoy.year else hoy.month
    return [f"{ejercicio}-{m:02d}" for m in range(1, meses + 1)]
