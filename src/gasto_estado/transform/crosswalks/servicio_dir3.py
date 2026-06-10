"""Crosswalk servicio presupuestario ↔ unidad DIR3 (activo central, CLAUDE.md §2).

La correspondencia NO es 1:1 (§3): un servicio puede corresponder a varias
unidades DIR3 y viceversa, por lo que la tabla resultante es de relación
(una fila por par servicio–unidad) con el tipo de match explícito:

- ``exacto``: denominación normalizada idéntica dentro del subárbol del
  ministerio de la sección.
- ``por_denominacion``: coincidencia por conjunto de tokens significativos, o
  regla documentada (servicios ``.01`` "Ministerio, Subsecretaría y Servicios
  Generales" → unidad raíz del ministerio + su Subsecretaría).
- ``manual``: par fijado en el fichero de overrides versionado
  (``overrides_servicio_dir3.csv``), que SIEMPRE prevalece sobre el automático.
- ``sin_match``: sin correspondencia; la fila se conserva con ``dir3_cod``
  vacío y el motivo en ``match_detalle`` (nunca se descartan servicios).

Las secciones no ministeriales (Casa Real, Cortes, Deuda Pública, fondos...)
no existen en el listado DIR3 de unidades AGE: quedan como ``sin_match`` con
detalle ``seccion_sin_ministerio_dir3`` y se contabilizan aparte.

No se inventan correspondencias: lo que el automático no resuelve va a
``sin_match`` o a un override manual documentado (ver README.md).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from gasto_estado.transform.text import normalize as _norm

OVERRIDES_FILE = Path(__file__).parent / "overrides_servicio_dir3.csv"

CROSSWALK_COLUMNS = [
    "ejercicio",
    "seccion_cod",
    "servicio_cod",
    "servicio_denominacion",
    "dir3_cod",
    "dir3_denominacion",
    "match_tipo",
    "match_detalle",
]

# Tokens sin carga semántica para la comparación de denominaciones.
_STOPWORDS = frozenset({"de", "del", "la", "las", "los", "el", "y", "e", "para", "en", "al", "a"})

_SERVICIOS_GENERALES_RE = re.compile(r"^ministerio.*(subsecretaria|servicios generales)")

# Servicio instrumental del Plan de Recuperación (código .50 en cada sección):
# es un vehículo presupuestario sin unidad orgánica propia en DIR3.
_PRTR_RE = re.compile(r"^mecanismo de recuperacion y resiliencia$")


def _tokens(norm_text: str) -> frozenset[str]:
    return frozenset(t for t in norm_text.split() if t not in _STOPWORDS)


def load_overrides(path: Path = OVERRIDES_FILE) -> pd.DataFrame:
    """Carga el CSV de overrides manuales (editable a mano, versionado)."""
    overrides = pd.read_csv(path, dtype=str, comment="#")
    overrides["ejercicio"] = overrides["ejercicio"].astype("int64")
    return overrides


def build_crosswalk(
    dim_seccion_servicio: pd.DataFrame,
    dim_organica: pd.DataFrame,
    overrides: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construye el crosswalk para los servicios del ejercicio dado.

    ``dim_organica`` debe ser el seed SCD2 de DIR3 (con ``ministerio_dir3_cod``
    y ``denominacion``); solo se consideran unidades vigentes (sin fecha_fin).
    """
    organica = dim_organica[dim_organica["fecha_fin"].isna()].copy()
    organica["norm"] = organica["denominacion"].map(_norm)

    # Sección → ministerio DIR3, por denominación normalizada de la raíz.
    raices = organica[organica["nivel_jerarquico"].astype(int) == 1]
    ministerio_por_norm = dict(zip(raices["norm"], raices["dir3_cod"], strict=True))

    rows: list[dict[str, object]] = []

    def add(servicio: pd.Series, unidad: pd.Series | None, tipo: str, detalle: str) -> None:
        rows.append(
            {
                "ejercicio": servicio["ejercicio"],
                "seccion_cod": servicio["seccion_cod"],
                "servicio_cod": servicio["servicio_cod"],
                "servicio_denominacion": servicio["servicio_denominacion"],
                "dir3_cod": None if unidad is None else unidad["dir3_cod"],
                "dir3_denominacion": None if unidad is None else unidad["denominacion"],
                "match_tipo": tipo,
                "match_detalle": detalle,
            }
        )

    for _, servicio in dim_seccion_servicio.iterrows():
        ministerio_cod = ministerio_por_norm.get(_norm(servicio["seccion_denominacion"]))
        if ministerio_cod is None:
            add(servicio, None, "sin_match", "seccion_sin_ministerio_dir3")
            continue

        subarbol = organica[organica["ministerio_dir3_cod"] == ministerio_cod]
        servicio_norm = _norm(servicio["servicio_denominacion"])

        exactas = subarbol[subarbol["norm"] == servicio_norm]
        if len(exactas):
            for _, unidad in exactas.iterrows():
                add(servicio, unidad, "exacto", "denominacion_normalizada")
            continue

        servicio_tokens = _tokens(servicio_norm)
        por_tokens = subarbol[subarbol["norm"].map(lambda n, st=servicio_tokens: _tokens(n) == st)]
        if len(por_tokens):
            for _, unidad in por_tokens.iterrows():
                add(servicio, unidad, "por_denominacion", "tokens_significativos")
            continue

        # Prefijo único: la unidad lleva un sufijo aclaratorio (p. ej.
        # "Secretaría General Técnica (MEFPD)"). Solo si hay UN candidato.
        prefijo = subarbol[subarbol["norm"].str.startswith(servicio_norm)]
        if len(prefijo) == 1:
            add(servicio, prefijo.iloc[0], "por_denominacion", "prefijo_unico")
            continue

        # Regla documentada: el servicio "Ministerio, Subsecretaría y
        # Servicios Generales" agrupa la cúpula del departamento → raíz del
        # ministerio + su Subsecretaría (lectura literal de la denominación).
        if _SERVICIOS_GENERALES_RE.match(servicio_norm):
            cupula = subarbol[
                (subarbol["dir3_cod"] == ministerio_cod)
                | (
                    subarbol["norm"].str.startswith("subsecretaria")
                    & (subarbol["nivel_jerarquico"].astype(int) == 2)
                )
            ]
            for _, unidad in cupula.iterrows():
                add(servicio, unidad, "por_denominacion", "regla_servicios_generales")
            if len(cupula):
                continue

        if _PRTR_RE.match(servicio_norm):
            add(servicio, None, "sin_match", "servicio_instrumental_prtr")
            continue

        add(servicio, None, "sin_match", "sin_candidato_en_subarbol")

    crosswalk = pd.DataFrame(rows, columns=CROSSWALK_COLUMNS)

    # Overrides manuales: prevalecen sobre el resultado automático del servicio.
    if overrides is not None and len(overrides):
        denominaciones = dict(zip(organica["dir3_cod"], organica["denominacion"], strict=True))
        servicios_idx = dim_seccion_servicio.set_index(["ejercicio", "seccion_cod", "servicio_cod"])
        manual_rows: list[dict[str, object]] = []
        for _, ov in overrides.iterrows():
            clave = (ov["ejercicio"], ov["seccion_cod"], ov["servicio_cod"])
            if clave not in servicios_idx.index:
                raise ValueError(f"Override para servicio inexistente: {clave}")
            if ov["dir3_cod"] not in denominaciones:
                raise ValueError(f"Override con dir3_cod fuera de dim_organica: {ov['dir3_cod']}")
            manual_rows.append(
                {
                    "ejercicio": ov["ejercicio"],
                    "seccion_cod": ov["seccion_cod"],
                    "servicio_cod": ov["servicio_cod"],
                    "servicio_denominacion": servicios_idx.loc[clave, "servicio_denominacion"],
                    "dir3_cod": ov["dir3_cod"],
                    "dir3_denominacion": denominaciones[ov["dir3_cod"]],
                    "match_tipo": "manual",
                    "match_detalle": ov.get("nota") or "override",
                }
            )
        manual = pd.DataFrame(manual_rows, columns=CROSSWALK_COLUMNS)
        clave_cols = ["ejercicio", "seccion_cod", "servicio_cod"]
        con_override = manual[clave_cols].apply(tuple, axis=1)
        sin_override = ~crosswalk[clave_cols].apply(tuple, axis=1).isin(set(con_override))
        crosswalk = pd.concat([crosswalk[sin_override], manual], ignore_index=True)

    return crosswalk.sort_values(
        ["ejercicio", "seccion_cod", "servicio_cod", "dir3_cod"]
    ).reset_index(drop=True)


def match_stats(crosswalk: pd.DataFrame) -> dict[str, float]:
    """Métricas de cobertura por servicio (no por par) para auditoría y tests.

    Distingue los ``sin_match`` estructurales (secciones sin ministerio en el
    DIR3 AGE; servicio instrumental PRTR) de los reales (``sin_candidato``),
    que son los que mide el umbral de calidad del crosswalk.
    """
    por_servicio = crosswalk.groupby(["ejercicio", "seccion_cod", "servicio_cod"]).agg(
        tipo=("match_tipo", "first"),
        detalle=("match_detalle", "first"),
    )
    total = len(por_servicio)
    sin_match = (por_servicio["tipo"] == "sin_match").sum()
    estructurales = (
        por_servicio["detalle"]
        .isin(["seccion_sin_ministerio_dir3", "servicio_instrumental_prtr"])
        .sum()
    )
    matcheables = total - estructurales
    sin_candidato = sin_match - estructurales
    return {
        "servicios_total": float(total),
        "sin_match_estructural": float(estructurales),
        "sin_match_total_pct": float(sin_match) / total * 100,
        "sin_candidato_pct": float(sin_candidato) / matcheables * 100,
    }
