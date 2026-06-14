"""Router de alertas analíticas.

Sirve el informe consolidado de un periodo y una consulta filtrable y paginada.
Cada alerta llega con TODO lo que la capa analítica le puso —severidad, confianza,
naturaleza, cobertura, contexto y evidencias enlazadas (identificadores de
aplicaciones/contratos/acuerdos para "ver por qué")— y con su lenguaje
descriptivo-no-acusatorio intacto. La API solo filtra, pagina y envuelve.
"""

from __future__ import annotations

from dataclasses import asdict

import duckdb
from fastapi import APIRouter, Depends, Query

from gasto_estado.analytics import alerts
from gasto_estado.api.deps import PeriodoQuery, get_db, paginacion_params
from gasto_estado.api.models import (
    AlertaModel,
    Envelope,
    InformeData,
    Severidad,
    TipoAlerta,
    VelocidadAlerta,
)
from gasto_estado.api.respuestas import envolver_coleccion, envolver_objeto

router = APIRouter(prefix="/alertas", tags=["alertas"])

# Velocidad → tipos de alerta (para el filtro del frontal).
_VELOCIDAD_TIPOS = {
    VelocidadAlerta.contable: {"ritmo_ejecucion", "modificacion_atipica"},
    VelocidadAlerta.compromisos: {"concentracion_adjudicatarios"},
    VelocidadAlerta.cruce: {"anticipacion_compromiso"},
}


@router.get(
    "/informe",
    response_model=Envelope[InformeData],
    summary="Informe de alertas de un periodo (disparadas + omitidas + cobertura)",
)
def informe(
    periodo: str = PeriodoQuery,
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[InformeData]:
    return envolver_objeto(InformeData(**alerts.informe(con, periodo)))


@router.get(
    "",
    response_model=Envelope[list[AlertaModel]],
    summary="Alertas filtrables (severidad, tipo, velocidad, ámbito)",
)
def listar(
    periodo: str = PeriodoQuery,
    severidad: Severidad | None = Query(None),
    tipo: TipoAlerta | None = Query(None),
    velocidad: VelocidadAlerta | None = Query(None),
    seccion: str | None = Query(None, description="Filtra por sección del ámbito."),
    pag: tuple[int, int] = Depends(paginacion_params),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> Envelope[list[AlertaModel]]:
    tipos_velocidad = _VELOCIDAD_TIPOS.get(velocidad) if velocidad is not None else None
    items: list[AlertaModel] = []
    for a in alerts.run_alerts(con, [periodo]):
        if a.estado != alerts.ALERTA:
            continue
        if severidad is not None and a.severidad != severidad.value:
            continue
        if tipo is not None and a.tipo != tipo.value:
            continue
        if tipos_velocidad is not None and a.tipo not in tipos_velocidad:
            continue
        if seccion is not None and a.ambito.get("seccion_cod") != seccion:
            continue
        items.append(AlertaModel(**asdict(a)))
    return envolver_coleccion(items, pagina=pag[0], tamano=pag[1])
