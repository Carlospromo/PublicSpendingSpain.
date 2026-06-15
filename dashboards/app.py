"""Punto de entrada del dashboard gasto-estado (Fase 8).

Streamlit multi-página que consume EXCLUSIVAMENTE la API v1.
Arranca con: streamlit run dashboards/app.py

La API debe estar levantada: uv run gasto-estado api --port 8000
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="gasto-estado — Auditoría del gasto público español",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Importar componentes y cliente después del page_config
import api_client as api  # noqa: E402

# ---------------------------------------------------------------------------
# Cabecera permanente de frescura (en todas las páginas vía app.py)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🏛️ gasto-estado")
    st.caption("Auditoría del gasto público español")
    st.divider()

    api_url = st.text_input(
        "URL de la API",
        value=api.BASE_URL,
        help="La API debe estar levantada: uv run gasto-estado api --port 8000",
    )
    if api_url != api.BASE_URL:
        api.BASE_URL = api_url

    st.divider()
    st.caption("Frescura de fuentes")

    try:
        fuentes_data = api.frescura()
        for f in fuentes_data:
            fuente = f.get("fuente_cod", "?")
            ultima = f.get("ultima_actualizacion", "—")
            periodo = f.get("periodo_cubierto") or []
            periodo_str = f"{periodo[0]} → {periodo[1]}" if len(periodo) == 2 else "—"
            st.caption(f"• **{fuente}**: {ultima}  \n  `{periodo_str}`")
        _fuentes_ok = True
    except api.APINoDisponible:
        st.error("❌ API no disponible")
        _fuentes_ok = False
    except Exception as exc:
        st.warning(f"⚠️ {exc}")
        _fuentes_ok = False

# ---------------------------------------------------------------------------
# Navegación multi-página
# ---------------------------------------------------------------------------

ejecucion_page = st.Page(
    "pages/ejecucion.py",
    title="Ejecución presupuestaria",
    icon="📊",
    default=True,
)
compromisos_page = st.Page(
    "pages/compromisos.py",
    title="Compromisos jurídicos",
    icon="📋",
)
decisiones_page = st.Page(
    "pages/decisiones.py",
    title="Decisiones políticas",
    icon="📜",
)
cruces_page = st.Page(
    "pages/cruces.py",
    title="Cruces entre velocidades",
    icon="🔗",
)
alertas_page = st.Page(
    "pages/alertas.py",
    title="Alertas analíticas",
    icon="🚨",
)
sistema_page = st.Page(
    "pages/sistema.py",
    title="Estado del sistema",
    icon="⚙️",
)

pg = st.navigation(
    {
        "Análisis": [
            ejecucion_page,
            compromisos_page,
            decisiones_page,
            cruces_page,
            alertas_page,
        ],
        "Infraestructura": [sistema_page],
    }
)

pg.run()
