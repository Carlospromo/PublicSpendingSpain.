"""Página 4: Cruces entre velocidades (indiciarios).

Compromiso PLACSP vs ORN IGAE y decisiones CdM vs adjudicación PLACSP.
INDICIARIO: no es una identidad contable. Ambas magnitudes siempre por separado.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_client as api
import components as C
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.title("🔗 Cruces entre velocidades (indiciarios)")
st.error(
    "⚠️ **INDICIARIO**: estas comparaciones no son identidades contables. "
    "Los ratios compromiso/ORN y decisión/compromiso incluyen IVA, plurianualidad "
    "y contratos que no siempre llegan a ORN. Son indicios de ejecución por venir, "
    "no una conciliación.",
    icon="⚠️",
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

tab1, tab2 = st.tabs(["Compromiso PLACSP vs ORN IGAE", "Decisiones CdM vs Compromiso PLACSP"])

# ---------------------------------------------------------------------------
# Tab 1: Compromiso vs Ejecución
# ---------------------------------------------------------------------------

with tab1:
    st.subheader("Adjudicación PLACSP vs ORN IGAE por periodo")
    st.caption(
        "El valor de anticipación del proyecto: el compromiso jurídico precede "
        "en meses a la obligación reconocida. Se muestran **ambas magnitudes "
        "por separado**, nunca solo el ratio."
    )

    col1, col2 = st.columns(2)
    with col1:
        ejercicio_ce = st.selectbox("Ejercicio", ejercicios, index=0, key="ej_ce")
    with col2:
        periodos_ce = C.periodos_de_ejercicio(ejercicio_ce)
        periodo_ce = st.selectbox("Periodo", periodos_ce[::-1], index=0, key="per_ce")

    nivel_ce = st.selectbox("Nivel", ["seccion", "servicio"], index=0, key="niv_ce")

    try:
        datos_ce, meta_ce = api.compromiso_vs_ejecucion(periodo_ce, nivel=nivel_ce)
    except api.APIError as exc:
        st.warning(f"Sin datos: {exc}")
        datos_ce, meta_ce = [], {}

    C.show_meta(meta_ce)

    if datos_ce:
        df_ce = pd.DataFrame(datos_ce)

        # Identificar columnas
        adj_col = next(
            (
                c
                for c in ["adjudicado", "importe_adjudicacion", "adjudicado_eur"]
                if c in df_ce.columns
            ),
            None,
        )
        orn_col = next((c for c in ["orn", "orn_eur", "orn_igae"] if c in df_ce.columns), None)
        ratio_col = next(
            (c for c in ["ratio", "ratio_adj_orn", "ratio_adjudicado_orn"] if c in df_ce.columns),
            None,
        )
        lbl_col = next(
            (c for c in ["seccion_denominacion", "servicio_denominacion"] if c in df_ce.columns),
            None,
        )
        cod_col = next((c for c in ["seccion_cod", "servicio_cod"] if c in df_ce.columns), None)

        if adj_col and orn_col:
            df_ce_sorted = df_ce.dropna(subset=[adj_col]).sort_values(adj_col, ascending=False)
            top_ce = df_ce_sorted.head(20)
            y_col = lbl_col if lbl_col and lbl_col in top_ce.columns else cod_col

            fig = go.Figure()
            if adj_col in top_ce.columns:
                fig.add_bar(
                    x=top_ce[adj_col],
                    y=top_ce[y_col] if y_col else list(range(len(top_ce))),
                    name="Adjudicado PLACSP (€)",
                    orientation="h",
                    marker_color="steelblue",
                )
            if orn_col in top_ce.columns:
                fig.add_scatter(
                    x=top_ce[orn_col],
                    y=top_ce[y_col] if y_col else list(range(len(top_ce))),
                    mode="markers",
                    name="ORN IGAE (€)",
                    marker={"size": 10, "color": "orange", "symbol": "diamond"},
                )
            fig.update_layout(
                title=f"Compromiso PLACSP vs ORN IGAE — {nivel_ce} — {periodo_ce}",
                xaxis_title="Importe (€)",
                yaxis={"autorange": "reversed"},
                height=500,
            )
            st.plotly_chart(fig, use_container_width=True)

        # Ratio scatter (si hay tanto adj como orn)
        if adj_col and orn_col and ratio_col and ratio_col in df_ce.columns:
            df_ratio = df_ce.dropna(subset=[adj_col, orn_col, ratio_col])
            if not df_ratio.empty:
                fig_r = px.scatter(
                    df_ratio,
                    x=orn_col,
                    y=adj_col,
                    color=ratio_col,
                    text=lbl_col if lbl_col else cod_col,
                    title="Scatterplot: ORN vs Adjudicado (color = ratio adj/ORN)",
                    labels={
                        orn_col: "ORN IGAE (€)",
                        adj_col: "Adjudicado PLACSP (€)",
                        ratio_col: "Ratio",
                    },
                    color_continuous_scale="RdYlGn_r",
                )
                fig_r.add_shape(
                    type="line",
                    x0=0,
                    y0=0,
                    x1=df_ratio[orn_col].max(),
                    y1=df_ratio[orn_col].max(),
                    line={"dash": "dot", "color": "gray"},
                )
                st.plotly_chart(fig_r, use_container_width=True)

        # Tabla completa con ambas magnitudes (siempre)
        cols_t = {}
        if cod_col:
            cols_t[cod_col] = "Código"
        if lbl_col:
            cols_t[lbl_col] = "Denominación"
        if adj_col:
            cols_t[adj_col] = "Adjudicado PLACSP (€)"
        if orn_col:
            cols_t[orn_col] = "ORN IGAE (€)"
        if ratio_col:
            cols_t[ratio_col] = "Ratio adj/ORN"

        st.dataframe(
            df_ce[[c for c in cols_t if c in df_ce.columns]].rename(columns=cols_t),
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Ratio > 1 indica que el adjudicado supera la ORN reconocida. "
            "Esto es esperable si los contratos aún están en ejecución. "
            "No implica sobreejecución ni irregularidad."
        )
    else:
        st.info(
            "Sin datos de cruce para el periodo seleccionado. "
            "Se necesitan datos IGAE y PLACSP para el mismo periodo."
        )

# ---------------------------------------------------------------------------
# Tab 2: Decisiones vs Compromiso
# ---------------------------------------------------------------------------

with tab2:
    st.subheader("Autorización de gasto CdM vs adjudicación PLACSP")
    st.caption(
        "Señal política adelantada: los acuerdos de autorización de gasto del "
        "Consejo de Ministros preceden a la contratación formal. "
        "Importes CdM con naturaleza aproximada (extracción de texto)."
    )

    ejercicio_dc = st.selectbox("Ejercicio", ejercicios, index=0, key="ej_dc")

    try:
        datos_dc, meta_dc = api.decisiones_vs_compromiso(ejercicio_dc)
    except api.APIError as exc:
        st.warning(f"Sin datos: {exc}")
        datos_dc, meta_dc = [], {}

    C.show_meta(meta_dc)

    if datos_dc:
        df_dc = pd.DataFrame(datos_dc)
        lbl_col = next(
            (c for c in ["seccion_denominacion", "denominacion"] if c in df_dc.columns),
            None,
        )
        adj_col = next(
            (c for c in ["adjudicado", "importe_adjudicacion"] if c in df_dc.columns), None
        )
        cdm_col = next((c for c in ["importe_cdm", "importe_decision"] if c in df_dc.columns), None)

        if adj_col and cdm_col:
            df_sorted = df_dc.dropna(subset=[adj_col]).sort_values(adj_col, ascending=False)
            top_dc = df_sorted.head(15)
            y_col = lbl_col if lbl_col and lbl_col in top_dc.columns else "seccion_cod"

            fig_dc = go.Figure()
            if cdm_col in top_dc.columns:
                fig_dc.add_bar(
                    x=top_dc[cdm_col],
                    y=top_dc[y_col] if y_col in top_dc.columns else list(range(len(top_dc))),
                    name="Importe CdM (€, aprox.)",
                    orientation="h",
                    marker_color="tomato",
                )
            if adj_col in top_dc.columns:
                fig_dc.add_scatter(
                    x=top_dc[adj_col],
                    y=top_dc[y_col] if y_col in top_dc.columns else list(range(len(top_dc))),
                    mode="markers",
                    name="Adjudicado PLACSP (€)",
                    marker={"size": 10, "color": "steelblue", "symbol": "diamond"},
                )
            fig_dc.update_layout(
                title=f"Decisiones CdM vs Adjudicación PLACSP — {ejercicio_dc}",
                xaxis_title="Importe (€)",
                yaxis={"autorange": "reversed"},
            )
            st.plotly_chart(fig_dc, use_container_width=True)

        st.dataframe(df_dc, use_container_width=True, hide_index=True)
    else:
        st.info(
            f"Sin datos de cruce decisiones-compromiso para {ejercicio_dc}. "
            "Se necesitan datos de CdM y PLACSP para el mismo ejercicio."
        )
