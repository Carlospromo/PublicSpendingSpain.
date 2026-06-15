"""Página 1: Ejecución presupuestaria (velocidad contable — IGAE).

Visión macro AGE + tabla de ministerios + drill-down a servicios (≈DG).
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

st.title("📊 Ejecución presupuestaria (IGAE)")
st.caption(
    "Velocidad contable — IGAE Anexo I. Naturaleza: **exacta**. "
    "Períodos en prórroga (2025-P) advertidos en cada respuesta."
)

# ---------------------------------------------------------------------------
# Selectores globales
# ---------------------------------------------------------------------------

try:
    ejercicios = api.ejercicios()
except api.APINoDisponible:
    st.error("❌ La API no está disponible. Lanza: `uv run gasto-estado api --port 8000`")
    st.stop()
except api.APIError as exc:
    st.error(f"Error al cargar ejercicios: {exc}")
    st.stop()

if not ejercicios:
    st.warning("El warehouse está vacío. Ejecuta `uv run gasto-estado build` primero.")
    st.stop()

col1, col2 = st.columns([1, 2])
with col1:
    ejercicio_sel = st.selectbox("Ejercicio", ejercicios, index=0)
with col2:
    periodos_posibles = C.periodos_de_ejercicio(ejercicio_sel)
    # El periodo más reciente es el último disponible
    periodo_sel = st.selectbox(
        "Periodo (mes)",
        options=periodos_posibles[::-1],
        index=0,
        help="El IGAE publica ~25-30 días tras el cierre de mes. "
        "Los periodos sin dato devuelven datos vacíos.",
    )

# ---------------------------------------------------------------------------
# Visión macro AGE
# ---------------------------------------------------------------------------

st.subheader("Visión macro — AGE completa")

try:
    datos_age, meta_age = api.grado_ejecucion(periodo_sel, nivel="AGE")
    ritmo_age, meta_ritmo = api.ritmo_ejecucion(ejercicio_sel, nivel="AGE")
except api.APIError as exc:
    st.error(f"Error: {exc}")
    st.stop()

C.show_meta(meta_age)

if datos_age:
    row_age = datos_age[0]
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    col_k1.metric(
        "Grado de ejecución",
        C.fmt_pct(row_age.get("pct_ejecucion")),
        help="ORN / Crédito definitivo acumulado",
    )
    col_k2.metric(
        "ORN acumulada",
        C.fmt_eur(row_age.get("orn"), corto=True),
    )
    col_k3.metric(
        "Crédito definitivo",
        C.fmt_eur(row_age.get("credito_definitivo"), corto=True),
    )
    mod = row_age.get("modificaciones")
    col_k4.metric(
        "Modificaciones netas",
        C.fmt_eur(mod, corto=True) if mod else "—",
        help="Crédito definitivo − crédito inicial (derivado)",
    )
else:
    st.info(f"Sin dato IGAE para el periodo {periodo_sel}. ¿La IGAE aún no ha publicado este mes?")

# Gráfico ritmo intra-anual
if ritmo_age:
    df_ritmo = pd.DataFrame(ritmo_age)
    if "periodo" in df_ritmo.columns and "pct_ejecucion" in df_ritmo.columns:
        fig_ritmo = px.line(
            df_ritmo,
            x="periodo",
            y="pct_ejecucion",
            title=f"Ritmo de ejecución AGE — ejercicio {ejercicio_sel}",
            labels={"periodo": "Mes", "pct_ejecucion": "Grado ejecución (%)"},
            markers=True,
        )
        fig_ritmo.add_hline(y=100, line_dash="dot", line_color="red", annotation_text="100%")
        # Línea del ejercicio anterior si hay dato interanual
        try:
            ritmo_ant, _ = api.ritmo_ejecucion(ejercicio_sel - 1, nivel="AGE")
            if ritmo_ant:
                df_ant = pd.DataFrame(ritmo_ant)
                # Mapear los meses del año anterior a los del año actual para superponer
                if "periodo" in df_ant.columns:
                    df_ant["periodo_actual"] = df_ant["periodo"].str.replace(
                        str(ejercicio_sel - 1), str(ejercicio_sel)
                    )
                    fig_ritmo.add_scatter(
                        x=df_ant["periodo_actual"],
                        y=df_ant["pct_ejecucion"],
                        mode="lines",
                        name=f"Ejercicio {ejercicio_sel - 1}",
                        line={"dash": "dash", "color": "gray"},
                    )
        except api.APIError:
            pass
        st.plotly_chart(fig_ritmo, use_container_width=True)

# ---------------------------------------------------------------------------
# Tabla de secciones (ministerios)
# ---------------------------------------------------------------------------

st.subheader("Secciones presupuestarias (ministerios)")

try:
    datos_sec, meta_sec = api.grado_ejecucion(periodo_sel, nivel="seccion")
    inter_sec, _ = api.interanual(periodo_sel, nivel="seccion")
except api.APIError as exc:
    st.error(f"Error cargando secciones: {exc}")
    datos_sec, inter_sec = [], []

if datos_sec:
    df_sec = pd.DataFrame(datos_sec)
    # Añadir variación interanual si hay dato
    if inter_sec:
        df_inter = pd.DataFrame(inter_sec)
        cols_merge = [c for c in ["seccion_cod", "variacion_pp"] if c in df_inter.columns]
        if "seccion_cod" in df_inter.columns and "variacion_pp" in df_inter.columns:
            df_sec = df_sec.merge(
                df_inter[["seccion_cod", "variacion_pp"]], on="seccion_cod", how="left"
            )

    # Columnas a mostrar
    cols_display = {
        "seccion_cod": "Sección",
        "seccion_denominacion": "Ministerio",
        "credito_definitivo": "Crédito definitivo (€)",
        "orn": "ORN (€)",
        "pct_ejecucion": "Ejecución (%)",
    }
    if "variacion_pp" in df_sec.columns:
        cols_display["variacion_pp"] = "Var. interanual (pp)"

    df_mostrar = df_sec[[c for c in cols_display if c in df_sec.columns]].copy()
    df_mostrar = df_mostrar.rename(columns=cols_display)
    df_mostrar = df_mostrar.sort_values("Ejecución (%)", ascending=False)

    event = st.dataframe(
        df_mostrar,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Crédito definitivo (€)": st.column_config.NumberColumn(format="%.0f €"),
            "ORN (€)": st.column_config.NumberColumn(format="%.0f €"),
            "Ejecución (%)": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.1f%%"
            ),
        },
        selection_mode="single-row",
        on_select="rerun",
        key="tabla_secciones",
    )

    # ---------------------------------------------------------------------------
    # Drill-down: al seleccionar una sección, mostrar sus servicios
    # ---------------------------------------------------------------------------

    sel_rows = event.selection.rows if hasattr(event, "selection") else []
    if sel_rows:
        idx = sel_rows[0]
        row_sel = df_sec.iloc[idx]
        seccion_cod = str(row_sel.get("seccion_cod", ""))
        seccion_nombre = str(row_sel.get("seccion_denominacion", seccion_cod))

        st.markdown(f"---\n### Drill-down: {seccion_cod} — {seccion_nombre}")
        st.caption(
            "Nivel: servicio presupuestario (≈Dirección General). "
            "La equivalencia DG es nominal vía crosswalk 2026; "
            "puede ser aproximada para ejercicios anteriores."
        )

        try:
            datos_srv, meta_srv = api.grado_ejecucion(periodo_sel, nivel="servicio")
        except api.APIError as exc:
            st.error(f"Error cargando servicios: {exc}")
            datos_srv = []

        if datos_srv:
            df_srv = pd.DataFrame(datos_srv)
            # HALLAZGO: no hay filtro seccion_cod en /v1/ejecucion/grado?nivel=servicio
            # → filtramos en cliente
            if "seccion_cod" in df_srv.columns:
                df_srv = df_srv[df_srv["seccion_cod"].astype(str) == seccion_cod]

            # Enriquecer con info de estructura DG
            try:
                servicios_struct = api.servicios(seccion_cod, ejercicio_sel)
                if servicios_struct:
                    df_struct = pd.DataFrame(servicios_struct)
                    merge_cols = [
                        c
                        for c in [
                            "servicio_cod",
                            "dg_denominacion",
                            "dg_nivel_organico",
                            "dg_equivalencia_aproximada",
                            "dg_nota",
                        ]
                        if c in df_struct.columns
                    ]
                    if "servicio_cod" in df_struct.columns:
                        df_srv = df_srv.merge(
                            df_struct[merge_cols],
                            on="servicio_cod",
                            how="left",
                        )
            except api.APIError:
                pass

            cols_srv = {
                "servicio_cod": "Srv.",
                "servicio_denominacion": "Servicio",
                "dg_denominacion": "DG equivalente",
                "dg_nivel_organico": "Nivel org.",
                "credito_definitivo": "Crédito (€)",
                "orn": "ORN (€)",
                "pct_ejecucion": "Ejecución (%)",
            }
            df_srv_mostrar = df_srv[[c for c in cols_srv if c in df_srv.columns]].rename(
                columns=cols_srv
            )
            df_srv_mostrar = df_srv_mostrar.sort_values(
                "Ejecución (%)", ascending=False, na_position="last"
            )

            # Marcar DGs con equivalencia aproximada
            if "dg_equivalencia_aproximada" in df_srv.columns:
                apx_mask = df_srv["dg_equivalencia_aproximada"].fillna(False)
                if apx_mask.any():
                    st.caption(
                        f"⚠️ {apx_mask.sum()} servicio(s) con equivalencia DG aproximada "
                        f"(crosswalk 2026 aplicado a {ejercicio_sel})."
                    )

            C.show_meta(meta_srv, mostrar_advertencias=True, mostrar_cobertura=False)

            st.dataframe(
                df_srv_mostrar,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Crédito (€)": st.column_config.NumberColumn(format="%.0f €"),
                    "ORN (€)": st.column_config.NumberColumn(format="%.0f €"),
                    "Ejecución (%)": st.column_config.ProgressColumn(
                        min_value=0, max_value=100, format="%.1f%%"
                    ),
                },
            )

            # Serie temporal del servicio más grande de la sección
            if not df_srv.empty and "credito_definitivo" in df_srv.columns:
                st.markdown("#### Ritmo del servicio de mayor crédito")
                top_srv = df_srv.sort_values(
                    "credito_definitivo", ascending=False, na_position="last"
                ).iloc[0]
                srv_cod = str(top_srv.get("servicio_cod", ""))
                srv_nombre = str(
                    top_srv.get("servicio_denominacion", srv_cod)
                    or top_srv.get("dg_denominacion", srv_cod)
                )

                try:
                    ritmo_srv, _ = api.ritmo_ejecucion(ejercicio_sel, nivel="servicio")
                    if ritmo_srv:
                        df_r = pd.DataFrame(ritmo_srv)
                        if "servicio_cod" in df_r.columns:
                            df_r_srv = df_r[
                                (df_r["seccion_cod"].astype(str) == seccion_cod)
                                & (df_r["servicio_cod"].astype(str) == srv_cod)
                            ]
                            if not df_r_srv.empty:
                                fig_srv = px.line(
                                    df_r_srv,
                                    x="periodo",
                                    y="pct_ejecucion",
                                    title=f"Ritmo {srv_nombre[:50]}",
                                    labels={
                                        "periodo": "Mes",
                                        "pct_ejecucion": "Grado (%)",
                                    },
                                    markers=True,
                                )
                                st.plotly_chart(fig_srv, use_container_width=True)
                except api.APIError:
                    pass

        # Modificaciones del servicio en este periodo
        st.markdown("#### Modificaciones de crédito")
        try:
            datos_mod, meta_mod = api.modificaciones(periodo_sel, nivel="servicio")
            if datos_mod:
                df_mod = pd.DataFrame(datos_mod)
                if "seccion_cod" in df_mod.columns:
                    df_mod = df_mod[df_mod["seccion_cod"].astype(str) == seccion_cod]
                if not df_mod.empty:
                    C.show_meta(meta_mod, mostrar_advertencias=False)
                    cols_mod = {
                        "servicio_cod": "Srv.",
                        "servicio_denominacion": "Servicio",
                        "modificaciones": "Modificación (€)",
                        "modificaciones_pct": "Mod. sobre inicial (%)",
                    }
                    df_mod_show = df_mod[[c for c in cols_mod if c in df_mod.columns]].rename(
                        columns=cols_mod
                    )
                    st.dataframe(df_mod_show, use_container_width=True, hide_index=True)
                else:
                    st.caption("Sin modificaciones de crédito para esta sección en el periodo.")
        except api.APIError:
            pass
else:
    st.info(f"Sin datos de ejecución para el periodo {periodo_sel}.")
