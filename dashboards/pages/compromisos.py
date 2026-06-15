"""Página 2: Compromisos jurídicos (PLACSP + BDNS).

Volumen de adjudicaciones y concesiones por ministerio/DG, concentración HHI.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_client as api
import components as C
import pandas as pd
import plotly.express as px
import streamlit as st

st.title("📋 Compromisos jurídicos (PLACSP + BDNS)")
st.caption(
    "Velocidad compromisos — adjudicaciones PLACSP y concesiones BDNS. "
    "Naturaleza: **exacta**. La cobertura de anclaje a servicio/DG se muestra en cada vista."
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

col1, col2 = st.columns(2)
with col1:
    ejercicio_sel = st.selectbox("Ejercicio", ejercicios, index=0)
with col2:
    nivel_sel = st.selectbox(
        "Nivel de agregación",
        ["seccion", "servicio", "dg"],
        index=0,
        help="'dg' usa el crosswalk DIR3 (solo cuando el anclaje lo resuelve)",
    )

# ---------------------------------------------------------------------------
# Contratos PLACSP
# ---------------------------------------------------------------------------

st.subheader("Adjudicaciones PLACSP")

try:
    datos_c, meta_c = api.contratos_volumen(ejercicio=ejercicio_sel, nivel=nivel_sel)
except api.APIError as exc:
    st.warning(f"Sin datos de contratos: {exc}")
    datos_c, meta_c = [], {}

C.show_meta(meta_c)

if datos_c:
    df_c = pd.DataFrame(datos_c)
    importe_col = next(
        (c for c in ["importe_adjudicacion", "importe_total", "importe"] if c in df_c.columns),
        None,
    )
    label_col = next(
        (
            c
            for c in ["seccion_denominacion", "servicio_denominacion", "dg_denominacion"]
            if c in df_c.columns
        ),
        None,
    )
    cod_col = next(
        (c for c in ["seccion_cod", "servicio_cod", "dg_cod"] if c in df_c.columns), None
    )

    if importe_col and df_c[importe_col].notna().any():
        df_c_sorted = df_c.sort_values(importe_col, ascending=False, na_position="last")
        top15 = df_c_sorted.head(15)
        x_label = label_col or cod_col or "organismo"
        fig = px.bar(
            top15,
            x=importe_col,
            y=x_label if x_label in top15.columns else top15.index,
            orientation="h",
            title=f"Top adjudicaciones por {nivel_sel} — {ejercicio_sel}",
            labels={importe_col: "Importe adjudicado (€)", x_label: ""},
        )
        fig.update_layout(yaxis={"autorange": "reversed"})
        st.plotly_chart(fig, use_container_width=True)

        cols_mostrar = {}
        if cod_col:
            cols_mostrar[cod_col] = "Código"
        if label_col:
            cols_mostrar[label_col] = "Denominación"
        if importe_col:
            cols_mostrar[importe_col] = "Importe adj. (€)"
        if "n_contratos" in df_c.columns:
            cols_mostrar["n_contratos"] = "Nº contratos"

        df_show = df_c_sorted[[c for c in cols_mostrar if c in df_c_sorted.columns]].rename(
            columns=cols_mostrar
        )
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        st.info("Sin importes de adjudicación disponibles para el nivel/periodo seleccionado.")
else:
    st.info("Sin datos de contratos PLACSP. ¿La extracción diaria aún no ha cargado datos?")

# ---------------------------------------------------------------------------
# Subvenciones BDNS
# ---------------------------------------------------------------------------

st.subheader("Concesiones BDNS")

try:
    datos_b, meta_b = api.subvenciones_volumen(ejercicio=ejercicio_sel, nivel=nivel_sel)
except api.APIError as exc:
    st.warning(f"Sin datos de subvenciones: {exc}")
    datos_b, meta_b = [], {}

C.show_meta(meta_b)

if datos_b:
    df_b = pd.DataFrame(datos_b)
    imp_col = next(
        (c for c in ["importe_concesion", "importe_total", "importe"] if c in df_b.columns), None
    )
    lbl_col = next(
        (
            c
            for c in ["seccion_denominacion", "servicio_denominacion", "dg_denominacion"]
            if c in df_b.columns
        ),
        None,
    )

    if imp_col and df_b[imp_col].notna().any():
        df_b_sorted = df_b.sort_values(imp_col, ascending=False, na_position="last")
        top15_b = df_b_sorted.head(15)
        x_lbl = lbl_col or "organismo"
        fig_b = px.bar(
            top15_b,
            x=imp_col,
            y=x_lbl if x_lbl in top15_b.columns else top15_b.index,
            orientation="h",
            title=f"Top concesiones BDNS por {nivel_sel} — {ejercicio_sel}",
            labels={imp_col: "Importe concedido (€)", x_lbl: ""},
        )
        fig_b.update_layout(yaxis={"autorange": "reversed"})
        st.plotly_chart(fig_b, use_container_width=True)

        st.dataframe(df_b_sorted.head(30), use_container_width=True, hide_index=True)
    else:
        st.info("Sin importes de concesión disponibles.")
else:
    st.info("Sin datos de subvenciones BDNS.")

# ---------------------------------------------------------------------------
# Concentración de adjudicatarios (HHI)
# ---------------------------------------------------------------------------

st.subheader("Concentración de adjudicatarios (HHI)")
st.caption(
    "El **Índice de Herfindahl-Hirschman (HHI)** mide la concentración. "
    "HHI > 2.500 = mercado concentrado (estándar antimonopolio). "
    "**Concentración no implica irregularidad**: puede haber un único proveedor legítimo."
)

top_n = st.slider("Top N adjudicatarios para el HHI", 3, 20, 5)

try:
    datos_hhi, meta_hhi = api.concentracion(ejercicio=ejercicio_sel, nivel=nivel_sel, top_n=top_n)
except api.APIError as exc:
    st.warning(f"Sin datos de concentración: {exc}")
    datos_hhi, meta_hhi = [], {}

C.show_meta(meta_hhi)

if datos_hhi:
    df_hhi = pd.DataFrame(datos_hhi)
    if "hhi" in df_hhi.columns:
        df_hhi_sorted = df_hhi.sort_values("hhi", ascending=False, na_position="last")

        # Gráfico HHI
        lbl_hhi = next(
            (
                c
                for c in ["seccion_denominacion", "servicio_denominacion", "dg_denominacion"]
                if c in df_hhi_sorted.columns
            ),
            None,
        )
        y_col = lbl_hhi if lbl_hhi else "servicio_cod"
        if y_col in df_hhi_sorted.columns:
            top_hhi = df_hhi_sorted.head(20)
            fig_hhi = px.bar(
                top_hhi,
                x="hhi",
                y=y_col,
                orientation="h",
                title=f"HHI por {nivel_sel} (top 20 más concentrados) — {ejercicio_sel}",
                color="hhi",
                color_continuous_scale=["green", "yellow", "red"],
                range_color=[0, 10000],
            )
            fig_hhi.add_vline(
                x=2500,
                line_dash="dot",
                line_color="orange",
                annotation_text="Umbral concentrado (2500)",
            )
            fig_hhi.update_layout(yaxis={"autorange": "reversed"})
            st.plotly_chart(fig_hhi, use_container_width=True)

        # Tabla
        cols_hhi = {}
        for c in ["seccion_cod", "servicio_cod", "dg_cod"]:
            if c in df_hhi_sorted.columns:
                cols_hhi[c] = c.replace("_cod", "").capitalize()
        if lbl_hhi:
            cols_hhi[lbl_hhi] = "Denominación"
        for c in ["hhi", "n_adjudicatarios", "importe_total", "top_n_cuota_pct"]:
            if c in df_hhi_sorted.columns:
                cols_hhi[c] = {
                    "hhi": "HHI",
                    "n_adjudicatarios": "Nº adj.",
                    "importe_total": "Importe (€)",
                    "top_n_cuota_pct": f"Top-{top_n} cuota (%)",
                }.get(c, c)

        st.dataframe(
            df_hhi_sorted[[c for c in cols_hhi if c in df_hhi_sorted.columns]].rename(
                columns=cols_hhi
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Sin datos de HHI disponibles.")
else:
    st.info("Sin datos de concentración para el ejercicio y nivel seleccionados.")

# Enlace a la página de alertas para concentración
st.divider()
st.page_link(
    "pages/alertas.py",
    label="→ Ver alertas de concentración en Alertas analíticas",
    icon="🚨",
)
