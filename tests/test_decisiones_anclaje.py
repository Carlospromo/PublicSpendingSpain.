"""Tests del anclaje a SECCIÓN por ministerio proponente (BOE/CdM, Fase 4).

Las fuentes de "decisiones políticas" anclan a sección, no a servicio/DG: el
texto no da el servicio. Se fija el contrato de AncladorSeccion: resolución por
denominación (oficial del BOE o forma corta del Consejo), vigencia por ejercicio
con respaldo del registro histórico, perímetro (CCAA/local → fuera_perimetro) y
no-mapeable etiquetado. Nada se descarta.
"""

import pandas as pd

from gasto_estado.transform.anclaje_organico import (
    ANCLA_FUERA_PERIMETRO,
    ANCLA_SECCION,
    ANCLA_SIN_ANCLAR,
    SENAL_MINISTERIO_DENOMINACION,
    SENAL_MINISTERIO_NO_MAPEABLE,
    SENAL_SIN_MINISTERIO,
    AncladorSeccion,
    anclar_por_ministerio,
)

# Estructura sintética: dos ejercicios para probar la vigencia.
_SECCIONES = pd.DataFrame(
    [
        (2026, "15", "MINISTERIO DE HACIENDA"),
        (2026, "23", "MINISTERIO PARA LA TRANSICIÓN ECOLÓGICA Y EL RETO DEMOGRÁFICO"),
        (2026, "14", "MINISTERIO DE DEFENSA"),
    ],
    columns=["ejercicio", "seccion_cod", "seccion_denominacion"],
)
_SECCIONES["servicio_cod"] = "01"
_SECCIONES["servicio_denominacion"] = _SECCIONES["seccion_denominacion"]

# Histórico: en 2023 la sección 15 se llamaba "Hacienda y Función Pública".
_HISTORICO = pd.DataFrame(
    [
        {
            "ejercicio_origen": "2023",
            "seccion_origen": "15",
            "denominacion_origen": "MINISTERIO DE HACIENDA Y FUNCIÓN PÚBLICA",
            "ejercicio_destino": "2026",
            "seccion_destino": "15",
            "denominacion_destino": "MINISTERIO DE HACIENDA",
            "tipo_cambio": "continuidad_renombre",
            "nota": "",
        }
    ]
)


def test_forma_oficial_del_boe() -> None:
    anc = AncladorSeccion(_SECCIONES, _HISTORICO)
    res = anc.anclar_ministerio("MINISTERIO DE HACIENDA", 2026)
    assert res["seccion_cod"] == "15"
    assert res["anclaje_tipo"] == ANCLA_SECCION
    assert res["anclaje_senal"] == SENAL_MINISTERIO_DENOMINACION


def test_forma_corta_del_consejo() -> None:
    anc = AncladorSeccion(_SECCIONES, _HISTORICO)
    # El h3 del Consejo va sin "Ministerio de" y con nombre largo.
    res = anc.anclar_ministerio("Para la Transición Ecológica y el Reto Demográfico", 2026)
    assert res["seccion_cod"] == "23"
    assert res["anclaje_tipo"] == ANCLA_SECCION


def test_vigencia_usa_historico_para_ejercicio_anterior() -> None:
    anc = AncladorSeccion(_SECCIONES, _HISTORICO)
    # En 2023 el departamento se llamaba "Hacienda y Función Pública": el
    # histórico lo ancla a la sección 15 aunque el seed (2026) ya no lo nombre así.
    res = anc.anclar_ministerio("Hacienda y Función Pública", 2023)
    assert res["seccion_cod"] == "15"
    assert res["anclaje_tipo"] == ANCLA_SECCION


def test_no_mapeable_se_etiqueta() -> None:
    anc = AncladorSeccion(_SECCIONES, _HISTORICO)
    res = anc.anclar_ministerio("Ministerio Inexistente del Más Allá", 2026)
    assert res["seccion_cod"] is None
    assert res["anclaje_tipo"] == ANCLA_SIN_ANCLAR
    assert res["anclaje_senal"] == SENAL_MINISTERIO_NO_MAPEABLE


def test_departamento_no_age_fuera_perimetro() -> None:
    anc = AncladorSeccion(_SECCIONES, _HISTORICO)
    res = anc.anclar_ministerio("COMUNIDAD AUTÓNOMA DE ANDALUCÍA", 2026)
    assert res["anclaje_tipo"] == ANCLA_FUERA_PERIMETRO


def test_sin_ministerio() -> None:
    anc = AncladorSeccion(_SECCIONES, _HISTORICO)
    res = anc.anclar_ministerio(None, 2026)
    assert res["anclaje_tipo"] == ANCLA_SIN_ANCLAR
    assert res["anclaje_senal"] == SENAL_SIN_MINISTERIO


def test_anclar_por_ministerio_batch_anade_columnas() -> None:
    df = pd.DataFrame(
        {
            "periodo": ["2026-06", "2026-06"],
            "ministerio": ["Hacienda", "Defensa"],
            "descripcion": ["x", "y"],
        }
    )
    out = anclar_por_ministerio(df, _SECCIONES, _HISTORICO, columna_ministerio="ministerio")
    assert list(out["seccion_cod"]) == ["15", "14"]
    assert (out["anclaje_tipo"] == ANCLA_SECCION).all()
    # No muta el de entrada ni pierde filas.
    assert "seccion_cod" not in df.columns
    assert len(out) == len(df)
