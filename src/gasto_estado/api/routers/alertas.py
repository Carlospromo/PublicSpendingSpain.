"""Router de alertas analíticas.

Sirve el informe consolidado de un periodo y una consulta filtrable. Cada alerta
llega con TODO lo que la capa analítica le puso —severidad, confianza, naturaleza,
cobertura, contexto y evidencias enlazadas (identificadores de aplicaciones/
contratos/acuerdos para que el frontal permita "ver por qué")— y con su lenguaje
descriptivo-no-acusatorio intacto. La API solo filtra y envuelve.
"""

from __future__ import annotations

from dataclasses import asdict

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from gasto_estado.analytics import alerts
from gasto_estado.api.deps import PeriodoQuery, get_db
from gasto_estado.api.models import AlertaModel, InformeAlertasModel

router = APIRouter(prefix="/alertas", tags=["alertas"])

# Velocidad → tipos de alerta (para el filtro del frontal).
_VELOCIDAD_TIPOS = {
    "contable": {"ritmo_ejecucion", "modificacion_atipica"},
    "compromisos": {"concentracion_adjudicatarios"},
    "cruce": {"anticipacion_compromiso"},
}


@router.get(
    "/informe", response_model=InformeAlertasModel, summary="Informe de alertas de un periodo"
)
def informe(
    periodo: str = PeriodoQuery,
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> InformeAlertasModel:
    return InformeAlertasModel(**alerts.informe(con, periodo))


@router.get(
    "",
    response_model=list[AlertaModel],
    summary="Alertas filtrables (severidad, tipo, velocidad, ámbito)",
)
def listar(
    periodo: str = PeriodoQuery,
    severidad: str | None = Query(None),
    tipo: str | None = Query(None),
    velocidad: str | None = Query(None),
    seccion: str | None = Query(None),
    con: duckdb.DuckDBPyConnection = Depends(get_db),
) -> list[AlertaModel]:
    if velocidad is not None and velocidad not in _VELOCIDAD_TIPOS:
        raise HTTPException(
            status_code=422,
            detail=f"velocidad inválida: {velocidad} (usa {list(_VELOCIDAD_TIPOS)}).",
        )
    tipos_velocidad = _VELOCIDAD_TIPOS.get(velocidad or "")
    resultado: list[AlertaModel] = []
    for a in alerts.run_alerts(con, [periodo]):
        if a.estado != alerts.ALERTA:
            continue
        if severidad is not None and a.severidad != severidad:
            continue
        if tipo is not None and a.tipo != tipo:
            continue
        if tipos_velocidad is not None and a.tipo not in tipos_velocidad:
            continue
        if seccion is not None and a.ambito.get("seccion_cod") != seccion:
            continue
        resultado.append(AlertaModel(**asdict(a)))
    return resultado
