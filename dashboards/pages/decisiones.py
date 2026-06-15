"""Página 3: Decisiones políticas (BOE + Consejo de Ministros).

Timeline de acuerdos y disposiciones con sus importes por confianza.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_client as api
import components as C
import pandas as pd
import streamlit as st

st.title("📜 Decisiones políticas (BOE + Consejo de Ministros)")
st.caption(
    "Velocidad decisiones — naturaleza **aproximada**: los importes proceden de "
    "extracción de texto. Se muestran siempre desglosados por confianza (alta/media). "
    "Nunca se presentan como totales cerrados."
)

# ---------------------------------------------------------------------------
# Selectores globales
# ---------------------------------------------------------------------------

try:
    ejercicios = api.ejercicios()
except api.APINoDisponible:
    st.error("❌ API no disponible.")
    st.stop()

if not ejercicios:
    st.warning("Warehouse vacío.")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    ejercicio_sel = st.selectbox("Ejercicio", ejercicios, index=0)
with col2:
    fuente_sel = st.selectbox("Fuente", ["boe", "cdm"], index=0)
with col3:
    nivel_sel = st.selectbox("Nivel", ["seccion", "dg"], index=0)

fuente_nombre = "BOE" if fuente_sel == "boe" else "Consejo de Ministros"

# ---------------------------------------------------------------------------
# Volumen de decisiones
# ---------------------------------------------------------------------------

st.subheader(f"Acuerdos y disposiciones — {fuente_nombre}")

try:
    datos_d, meta_d = api.decisiones_volumen(fuente_sel, ejercicio=ejercicio_sel, nivel=nivel_sel)
except api.APIError as exc:
    st.warning(f"Sin datos de decisiones: {exc}")
    datos_d, meta_d = [], {}

C.show_meta(meta_d)

if datos_d:
    df_d = pd.DataFrame(datos_d)

    # Mostrar advertencia de naturaleza aproximada
    naturaleza = meta_d.get("naturaleza", "")
    if naturaleza == "aproximada":
        st.info(
            "ℹ️ Los importes son de **extracción automática de texto** (NLP sobre el BOE/"
            "Moncloa). Se muestran desglosados por confianza. Verifícalos en la fuente "
            "oficial antes de citar como cifra firme.",
            icon="⚠️",
        )

    # Columnas de importe desglosado por confianza
    imp_alta = next((c for c in ["importe_alta", "importe_alta_eur"] if c in df_d.columns), None)
    imp_media = next((c for c in ["importe_media", "importe_media_eur"] if c in df_d.columns), None)
    n_sin_imp = next(
        (c for c in ["n_sin_importe", "n_acuerdos_sin_importe"] if c in df_d.columns), None
    )
    n_total = next((c for c in ["n_acuerdos", "n_total", "n"] if c in df_d.columns), None)
    lbl_col = next(
        (
            c
            for c in ["seccion_denominacion", "dg_denominacion", "denominacion"]
            if c in df_d.columns
        ),
        None,
    )
    cod_col = next((c for c in ["seccion_cod", "dg_cod"] if c in df_d.columns), None)

    # Gráfico: importe por sección (desglosado alta/media confianza)
    if (imp_alta or imp_media) and lbl_col:
        df_graf = df_d.copy()
        barras = []
        if imp_alta and df_graf[imp_alta].notna().any():
            barras.append((imp_alta, "Importe confianza alta (€)", "darkblue"))
        if imp_media and df_graf[imp_media].notna().any():
            barras.append((imp_media, "Importe confianza media (€)", "steelblue"))
        if barras:
            df_plot = df_graf.sort_values(barras[0][0], ascending=False, na_position="last").head(
                15
            )
            import plotly.graph_objects as go

            fig = go.Figure()
            for col, nombre, color in barras:
                fig.add_bar(
                    x=df_plot[lbl_col] if lbl_col in df_plot.columns else df_plot.index,
                    y=df_plot[col],
                    name=nombre,
                    marker_color=color,
                )
            fig.update_layout(
                barmode="stack",
                title=(
                    f"{fuente_nombre} — importe por {nivel_sel}"
                    f" (confianza desglosada) — {ejercicio_sel}"
                ),
                xaxis_title="",
                yaxis_title="Importe (€)",
                xaxis_tickangle=-45,
            )
            st.plotly_chart(fig, use_container_width=True)

    # Tabla completa
    cols_tab = {}
    if cod_col:
        cols_tab[cod_col] = "Código"
    if lbl_col:
        cols_tab[lbl_col] = "Sección/Organismo"
    if n_total:
        cols_tab[n_total] = "Nº acuerdos"
    if imp_alta:
        cols_tab[imp_alta] = "Importe alta conf. (€)"
    if imp_media:
        cols_tab[imp_media] = "Importe media conf. (€)"
    if n_sin_imp:
        cols_tab[n_sin_imp] = "Sin importe"

    # Tipo de decisión si está disponible
    tipo_cols = [c for c in df_d.columns if "tipo" in c.lower()]
    for tc in tipo_cols[:2]:
        cols_tab[tc] = tc.replace("_", " ").capitalize()

    df_tab = df_d[[c for c in cols_tab if c in df_d.columns]].rename(columns=cols_tab)
    df_tab = df_tab.sort_values(
        list(cols_tab.values())[2] if len(cols_tab) > 2 else df_tab.columns[0],
        ascending=False,
        na_position="last",
    )
    st.dataframe(df_tab, use_container_width=True, hide_index=True)

    # Tipos de decisiones disponibles
    if tipo_cols:
        st.markdown("#### Tipos de decisiones disponibles")
        for tc in tipo_cols[:3]:
            tipos = df_d[tc].dropna().unique().tolist()
            st.caption(f"• **{tc}**: {', '.join(str(t) for t in tipos[:10])}")
else:
    st.info(
        f"Sin datos de {fuente_nombre} para el ejercicio {ejercicio_sel}. "
        "¿La extracción semanal/diaria ha cargado datos de este periodo?"
    )

# ---------------------------------------------------------------------------
# Nota sobre URLs oficiales
# ---------------------------------------------------------------------------

st.divider()
st.markdown("#### Fuentes oficiales")
col_a, col_b = st.columns(2)
with col_a:
    st.markdown(
        "🔗 **BOE sumario diario**: [boe.es/buscar/act.php](https://www.boe.es/buscar/act.php)"
    )
with col_b:
    st.markdown(
        "🔗 **Consejo de Ministros**: "
        "[lamoncloa.gob.es/consejodeministros](https://www.lamoncloa.gob.es/consejodeministros/)"
    )

st.caption(
    "Hallazgo: la API no expone el URL individual de cada disposición BOE ni la referencia "
    "de La Moncloa. Para navegar a la fuente primaria, usar las URL base y buscar por fecha."
)
