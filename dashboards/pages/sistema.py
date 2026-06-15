"""Página 6: Estado del sistema.

Frescura por fuente, salud del warehouse, y aviso cuando una fuente está desactualizada.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import UTC, datetime

import api_client as api
import components as C
import pandas as pd
import streamlit as st

st.title("⚙️ Estado del sistema")
st.caption(
    "Frescura por fuente, salud del warehouse y alertas de desactualización. "
    "Objetivo 5 de CLAUDE.md §1: siempre con los últimos datos disponibles, y que se vea."
)

# ---------------------------------------------------------------------------
# Salud del warehouse
# ---------------------------------------------------------------------------

st.subheader("Salud del warehouse")

try:
    salud_data, _ = api.salud()
except api.APINoDisponible:
    st.error("❌ La API no está disponible. Lanza: `uv run gasto-estado api --port 8000`")
    st.stop()
except api.APIError as exc:
    st.error(f"Error: {exc}")
    st.stop()

accesible = salud_data.get("accesible", False)

if not accesible:
    st.error(
        "❌ **Warehouse no disponible.** El warehouse DuckDB no existe o está vacío. "
        "Ejecuta: `uv run gasto-estado build`"
    )
    st.code("uv run gasto-estado build", language="bash")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric(
    "Estado",
    "✅ Disponible",
    help=salud_data.get("perimetro", ""),
)
ejercicios_disp = salud_data.get("ejercicios", [])
col2.metric(
    "Ejercicios cargados",
    str(len(ejercicios_disp)),
    delta=f"{min(ejercicios_disp)} → {max(ejercicios_disp)}" if ejercicios_disp else "—",
)
col3.metric(
    "Periodos IGAE",
    salud_data.get("n_periodos_igae", 0),
)

if salud_data.get("cobertura_dg_nota"):
    st.info(salud_data["cobertura_dg_nota"], icon="ℹ️")

if salud_data.get("ultima_actualizacion"):
    st.caption(f"Última actualización del warehouse: `{salud_data['ultima_actualizacion']}`")

# ---------------------------------------------------------------------------
# Frescura por fuente
# ---------------------------------------------------------------------------

st.subheader("Frescura por fuente")
st.caption(
    "Verde: actualizado dentro del periodo esperado. "
    "Naranja: desfase moderado. Rojo: fuente posiblemente desactualizada."
)

try:
    fuentes_data = api.frescura()
except api.APIError as exc:
    st.error(f"Error cargando frescura: {exc}")
    fuentes_data = []

_PERIODICIDAD_MAX_DIAS = {
    "mensual": 45,
    "diaria": 3,
    "semanal": 10,
    "continua": 10,
}

_VELOCIDAD_LABEL = {
    "contable": "🕐 Contable (mensual)",
    "compromisos_juridicos": "⚡ Compromisos (diaria)",
    "decisiones_politicas": "📅 Decisiones (semanal)",
}

hoy = datetime.now(UTC).date()

if fuentes_data:
    df_frescura = pd.DataFrame(fuentes_data)

    # Clasificar por velocidad
    velocidades = (
        df_frescura["velocidad"].dropna().unique().tolist()
        if "velocidad" in df_frescura.columns
        else []
    )

    for vel in velocidades or [None]:
        if vel:
            st.markdown(f"#### {_VELOCIDAD_LABEL.get(vel, vel)}")
            df_vel = df_frescura[df_frescura["velocidad"] == vel]
        else:
            df_vel = df_frescura

        for _, row in df_vel.iterrows():
            fuente = row.get("fuente_cod", "?")
            ultima = row.get("ultima_actualizacion")
            periodo_cubierto = row.get("periodo_cubierto") or []
            periodicidad = row.get("periodicidad", "mensual")
            n_filas = row.get("n_filas", 0)
            materializado_en = row.get("materializado_en")
            max_dias = _PERIODICIDAD_MAX_DIAS.get(periodicidad, 45)

            # Calcular estado de frescura
            if ultima:
                try:
                    fecha_ultima = datetime.fromisoformat(str(ultima)).date()
                    dias_desde = (hoy - fecha_ultima).days
                    if dias_desde <= max_dias:
                        icono = "🟢"
                        estado = f"Al día ({dias_desde}d)"
                    elif dias_desde <= max_dias * 2:
                        icono = "🟡"
                        estado = f"Desfase moderado ({dias_desde}d — esperado ≤{max_dias}d)"
                    else:
                        icono = "🔴"
                        estado = f"Desactualizado ({dias_desde}d — esperado ≤{max_dias}d)"
                except (ValueError, TypeError):
                    icono, estado = "⚪", "Fecha no disponible"
            else:
                icono, estado = "⚫", "Sin datos cargados"

            periodo_str = (
                f"{periodo_cubierto[0]} → {periodo_cubierto[1]}"
                if len(periodo_cubierto) == 2
                else "—"
            )

            col_ic, col_info, col_extra = st.columns([0.1, 1, 1])
            with col_ic:
                st.markdown(f"## {icono}")
            with col_info:
                st.markdown(f"**{fuente}**")
                st.caption(f"Estado: {estado}")
            with col_extra:
                st.caption(f"Periodos: `{periodo_str}`")
                st.caption(
                    f"Filas: {C.fmt_num(n_filas)}"
                    + (f"  \nMaterializado: {materializado_en}" if materializado_en else "")
                )

    # Tabla resumen
    st.markdown("#### Resumen tabular")
    cols_tab = {
        "fuente_cod": "Fuente",
        "velocidad": "Velocidad",
        "periodicidad": "Periodicidad",
        "n_filas": "Filas",
        "ultima_actualizacion": "Última actualización",
        "materializado_en": "Materializado en",
    }
    cols_disp = [c for c in cols_tab if c in df_frescura.columns]
    st.dataframe(
        df_frescura[cols_disp].rename(columns=cols_tab),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.warning("Sin datos de frescura.")

# ---------------------------------------------------------------------------
# Comandos operativos
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Comandos operativos")
st.markdown(
    """
```bash
# Reconstruir warehouse desde raw
uv run gasto-estado build

# Levantar la API
uv run gasto-estado api --port 8000

# Levantar este dashboard (con la API en otra terminal)
uv run streamlit run dashboards/app.py

# Extracción incremental + carga + checks
uv run gasto-estado update

# Tests
uv run pytest

# Calidad de código
uv run ruff check src/ && uv run mypy src/
```
"""
)

# ---------------------------------------------------------------------------
# Programación de workflows CI
# ---------------------------------------------------------------------------

st.subheader("Cadencia de actualización automática (CI)")
st.table(
    pd.DataFrame(
        [
            {
                "Workflow": "monthly.yml",
                "Cron": "0 7 20-31 * *",
                "Disparo": "Días 20-31 de cada mes, 07:00 UTC",
                "Fuente": "IGAE Anexo I",
            },
            {
                "Workflow": "weekly.yml",
                "Cron": "0 6 * * 1",
                "Disparo": "Lunes 06:00 UTC",
                "Fuente": "PLACSP, BDNS, BOE, CdM",
            },
            {
                "Workflow": "health_check.yml",
                "Cron": "0 8 * * 0",
                "Disparo": "Domingo 08:00 UTC",
                "Fuente": "Verificación de URLs",
            },
        ]
    )
)
