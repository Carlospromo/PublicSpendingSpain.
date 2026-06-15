"""Página 5: Alertas analíticas.

Informe consolidado con navegación a evidencias por alerta.
La funcionalidad clave: pinchar una alerta → llegar a los contratos/aplicaciones concretos.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_client as api
import components as C
import pandas as pd
import streamlit as st

st.title("🚨 Alertas analíticas")
st.caption(
    "Hipótesis señaladas para revisión humana — nunca veredictos de irregularidad. "
    "Cada alerta incluye severidad, confianza, contexto y evidencias navegables."
)

# ---------------------------------------------------------------------------
# Selectores
# ---------------------------------------------------------------------------

try:
    ejercicios = api.ejercicios()
except api.APINoDisponible:
    st.error("❌ API no disponible.")
    st.stop()

if not ejercicios:
    st.warning("Warehouse vacío.")
    st.stop()

ejercicio_sel = st.selectbox("Ejercicio", ejercicios, index=0)
periodos = C.periodos_de_ejercicio(ejercicio_sel)
periodo_sel = st.selectbox("Periodo", periodos[::-1], index=0)

col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    sev_filter = st.selectbox(
        "Severidad", ["todas", "destacada", "a_revisar", "informativa"], index=0
    )
with col_f2:
    vel_filter = st.selectbox("Velocidad", ["todas", "contable", "compromisos", "cruce"], index=0)
with col_f3:
    tipo_filter = st.selectbox(
        "Tipo",
        [
            "todos",
            "ritmo_ejecucion",
            "modificacion_atipica",
            "concentracion_adjudicatarios",
            "anticipacion_compromiso",
        ],
        index=0,
    )

# ---------------------------------------------------------------------------
# Informe de cobertura global
# ---------------------------------------------------------------------------

try:
    informe, meta_inf = api.alertas_informe(periodo_sel)
except api.APIError as exc:
    st.warning(f"Sin informe de alertas: {exc}")
    informe = {}

if informe:
    cobertura = informe.get("cobertura_global", {})
    resumen = informe.get("resumen", {})

    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    pct_dg = cobertura.get("pct_orn_vigilable_a_nivel_dg")
    col_c1.metric(
        "Cobertura a nivel DG",
        C.fmt_pct(pct_dg),
        help="~27% de la ORN se gestiona por unidades con anclaje DIR3. "
        "El resto (Deuda, Clases Pasivas, transferencias) se vigila solo a nivel sección.",
    )
    n_alerta = resumen.get("n_alertas", 0)
    n_skip = resumen.get("n_skipped", 0)
    col_c2.metric("Alertas disparadas", n_alerta)
    col_c3.metric(
        "Reglas SKIPPED",
        n_skip,
        help="Reglas no evaluables por falta de histórico/datos",
    )

    n_dest = resumen.get("n_destacada", 0) or resumen.get("destacada", 0)
    col_c4.metric(
        "Destacadas",
        n_dest,
        delta=None,
        delta_color="inverse",
    )

    st.caption(
        f"⚠️ Solo ~{pct_dg:.0f}% de la ORN se vigila a nivel DG. "
        "Las alertas restantes cubren secciones completas."
        if pct_dg
        else ""
    )
    st.divider()

# ---------------------------------------------------------------------------
# Lista de alertas con filtros
# ---------------------------------------------------------------------------

try:
    alertas_data, meta_al = api.alertas_lista(
        periodo_sel,
        severidad=sev_filter if sev_filter != "todas" else None,
        tipo=tipo_filter if tipo_filter != "todos" else None,
        velocidad=vel_filter if vel_filter != "todas" else None,
    )
except api.APIError as exc:
    st.warning(f"Error al cargar alertas: {exc}")
    alertas_data = []

if not alertas_data:
    st.info(
        f"Sin alertas para el periodo {periodo_sel} con los filtros aplicados. "
        "Prueba a cambiar el periodo o los filtros."
    )
    st.stop()

st.subheader(f"{len(alertas_data)} alerta(s) — {periodo_sel}")

# ---------------------------------------------------------------------------
# Renderizar cada alerta con sus evidencias navegables
# ---------------------------------------------------------------------------

_SEV_ORDER = {"destacada": 0, "a_revisar": 1, "informativa": 2}
alertas_ordenadas = sorted(
    alertas_data,
    key=lambda a: (_SEV_ORDER.get(a.get("severidad", "informativa"), 3), a.get("tipo", "")),
)

for _i, alerta in enumerate(alertas_ordenadas):
    sev = alerta.get("severidad", "informativa")
    tipo = alerta.get("tipo", "")
    confianza = alerta.get("confianza")
    naturaleza = alerta.get("naturaleza", "exacta")
    ambito = alerta.get("ambito", {})
    contexto = alerta.get("contexto", "")
    valor_obs = alerta.get("valor_observado")
    referencia = alerta.get("referencia", {})
    evidencias = alerta.get("evidencias", [])
    cobertura_al = alerta.get("cobertura", {})
    magnitudes = alerta.get("magnitudes", {})

    # Color de fondo según severidad
    color = {"destacada": "🔴", "a_revisar": "🟡", "informativa": "🔵"}.get(sev, "⚫")
    seccion_label = ambito.get("seccion_cod", "")
    servicio_label = ambito.get("servicio_cod", "")
    denominacion = ambito.get("denominacion", "")
    ambito_str = denominacion or (
        f"Sección {seccion_label}" + (f" / Srv. {servicio_label}" if servicio_label else "")
    )

    with st.expander(
        f"{color} **{tipo.replace('_', ' ').upper()}** — {ambito_str} "
        f"| {C.badge_severidad(sev)} | {C.badge_confianza(confianza)}",
        expanded=(sev == "destacada"),
    ):
        # Contexto (lenguaje descriptivo, nunca acusatorio)
        st.markdown(f"**Contexto:** {contexto}")

        # Magnitudes (para alertas indiciarias: ambas magnitudes por separado)
        if magnitudes:
            st.markdown("**Magnitudes (ambas por separado):**")
            for k, v in magnitudes.items():
                if v is not None:
                    label = k.replace("_", " ").capitalize()
                    if "eur" in k.lower():
                        st.caption(f"• {label}: `{C.fmt_eur(v)}`")
                    else:
                        st.caption(f"• {label}: `{v}`")

        # Referencia / umbral
        col_ref1, col_ref2 = st.columns(2)
        with col_ref1:
            if valor_obs is not None:
                st.metric("Valor observado", f"{valor_obs:.1f}")
        with col_ref2:
            if referencia:
                ref_items = []
                for k, v in list(referencia.items())[:4]:
                    if isinstance(v, float):
                        ref_items.append(f"{k}: {v:.1f}")
                    else:
                        ref_items.append(f"{k}: {v}")
                st.caption("Referencia: " + " | ".join(ref_items))

        # Cobertura del ámbito
        if cobertura_al:
            pct_cob = cobertura_al.get("pct_del_credito_age") or cobertura_al.get(
                "pct_anclado_a_servicio"
            )
            nota_cob = cobertura_al.get("nota", "")
            if pct_cob is not None:
                st.caption(f"Cobertura: **{pct_cob:.1f}%** del total AGE. {nota_cob}")

        # Naturaleza + confianza (metadatos de fiabilidad visibles)
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.caption(f"Naturaleza: **{C.badge_naturaleza(naturaleza)}**")
        with col_m2:
            if confianza:
                st.caption(f"Confianza: **{C.badge_confianza(confianza)}**")

        # ---------------------------------------------------------------------------
        # EVIDENCIAS NAVEGABLES (funcionalidad clave del dashboard)
        # ---------------------------------------------------------------------------

        if evidencias:
            st.markdown("**Evidencias:**")
            for evid in evidencias:
                tipo_evid = evid.get("tipo", "")
                ref_evid = evid.get("ref", "")

                if tipo_evid == "serie_historica":
                    # Gráfico de la serie histórica base de la norma
                    periodos_hist = evid.get("mismo_mes", [])
                    grados_hist = evid.get("grados_pct", [])
                    if periodos_hist and grados_hist:
                        import plotly.graph_objects as go

                        df_hist = pd.DataFrame({"periodo": periodos_hist, "grado_pct": grados_hist})
                        fig_hist = go.Figure(
                            go.Bar(
                                x=df_hist["periodo"],
                                y=df_hist["grado_pct"],
                                name="Histórico mismo mes",
                                marker_color="steelblue",
                            )
                        )
                        if valor_obs is not None:
                            fig_hist.add_hline(
                                y=valor_obs,
                                line_color="red",
                                line_dash="dash",
                                annotation_text=f"Actual: {valor_obs:.1f}%",
                            )
                        fig_hist.update_layout(
                            title="Histórico mismo mes (norma de comparación)",
                            yaxis_title="Grado ejecución (%)",
                            height=250,
                            margin={"t": 40, "b": 20},
                        )
                        st.plotly_chart(fig_hist, use_container_width=True)

                elif tipo_evid == "aplicaciones":
                    # Enlace navegable a la página de ejecución
                    params = C.parse_evidencia_ref(ref_evid)
                    seccion = params.get("seccion_cod", seccion_label)
                    servicio = params.get("servicio_cod", servicio_label)
                    periodo_evid = params.get("periodo", alerta.get("periodo", ""))

                    st.caption(
                        f"📎 Aplicaciones presupuestarias: sección `{seccion}`"
                        + (f", servicio `{servicio}`" if servicio else "")
                        + (f", periodo `{periodo_evid}`" if periodo_evid else "")
                    )
                    st.page_link(
                        "pages/ejecucion.py",
                        label="→ Ver en Ejecución presupuestaria (selecciona la sección allí)",
                        icon="📊",
                    )

                elif tipo_evid == "contratos":
                    # Enlace navegable a la página de compromisos
                    params = C.parse_evidencia_ref(ref_evid)
                    seccion = params.get("seccion_cod", seccion_label)
                    servicio = params.get("servicio_cod", servicio_label)
                    periodo_al = alerta.get("periodo", "2026-01")
                    ejercicio_evid = params.get("ejercicio", str(C.periodo_a_ejercicio(periodo_al)))

                    st.caption(
                        f"📎 Contratos PLACSP: sección `{seccion}`"
                        + (f", servicio `{servicio}`" if servicio else "")
                        + (f", ejercicio `{ejercicio_evid}`" if ejercicio_evid else "")
                    )
                    # Cargar y mostrar inline la concentración para este servicio
                    try:
                        ej_int = int(ejercicio_evid)
                        datos_conc, _ = api.concentracion(
                            ejercicio=ej_int, nivel="servicio", top_n=5
                        )
                        if datos_conc:
                            df_conc = pd.DataFrame(datos_conc)
                            if "servicio_cod" in df_conc.columns and servicio:
                                df_conc_srv = df_conc[
                                    df_conc["servicio_cod"].astype(str) == servicio
                                ]
                                if not df_conc_srv.empty:
                                    st.dataframe(
                                        df_conc_srv,
                                        use_container_width=True,
                                        hide_index=True,
                                    )
                    except (api.APIError, ValueError):
                        pass

                    st.page_link(
                        "pages/compromisos.py",
                        label="→ Ver en Compromisos jurídicos",
                        icon="📋",
                    )

                elif tipo_evid == "cruces":
                    st.page_link(
                        "pages/cruces.py",
                        label="→ Ver en Cruces entre velocidades",
                        icon="🔗",
                    )

                else:
                    # Evidencia de tipo desconocido: mostrar como texto
                    if ref_evid:
                        st.caption(f"📎 {tipo_evid}: `{ref_evid}`")
