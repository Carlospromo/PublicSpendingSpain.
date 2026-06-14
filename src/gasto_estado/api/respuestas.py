"""Constructores de la envoltura común ``{data, meta}`` (contrato v1).

Centralizan la forma de respuesta para que TODOS los endpoints la produzcan
igual: una métrica, una colección o un objeto se envuelven aquí, no en cada
router. Así el frontal trata todas las respuestas de la misma manera y la
paginación/los metadatos de fiabilidad son uniformes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from gasto_estado.analytics.metrics import MetricResult
from gasto_estado.api.models import Envelope, Meta, Paginacion

# Paginación: tamaño por defecto y máximo (documentados en API.md). Generoso por
# defecto para que las agregaciones (≤ ~250 servicios) quepan en una página, sin
# dejar de acotar las colecciones grandes (catálogo económico).
TAMANO_DEFECTO = 200
TAMANO_MAXIMO = 1000


def _ahora() -> str:
    return datetime.now(UTC).isoformat()


def paginar[T](items: list[T], pagina: int, tamano: int) -> tuple[list[T], Paginacion]:
    """Recorta ``items`` a la página pedida y devuelve sus metadatos de paginación."""
    total = len(items)
    inicio = (pagina - 1) * tamano
    pagina_items = items[inicio : inicio + tamano]
    return pagina_items, Paginacion(
        total=total, pagina=pagina, tamano=tamano, hay_siguiente=inicio + tamano < total
    )


def envolver_metrica(
    resultado: MetricResult, *, pagina: int = 1, tamano: int = TAMANO_MAXIMO
) -> Envelope[list[dict[str, Any]]]:
    """Envuelve un ``MetricResult``: data = filas (paginadas); meta = fiabilidad + frescura."""
    payload = resultado.to_dict()
    filas, paginacion = paginar(payload["data"], pagina, tamano)
    meta = Meta(
        generado_en=_ahora(),
        nivel=resultado.nivel,
        naturaleza=resultado.naturaleza,  # type: ignore[arg-type]
        magnitudes=resultado.magnitudes,
        fuentes=resultado.fuentes,
        frescura=resultado.frescura,
        cobertura_anclaje=resultado.cobertura_anclaje,
        advertencias=list(resultado.advertencias),
        paginacion=paginacion,
    )
    return Envelope(data=filas, meta=meta)


def envolver_coleccion[T](
    items: list[T],
    *,
    pagina: int = 1,
    tamano: int = TAMANO_MAXIMO,
    frescura: dict[str, Any] | None = None,
    nivel: str | None = None,
) -> Envelope[list[T]]:
    """Envuelve una colección tipada (estructura/catálogos/alertas) con paginación."""
    filas, paginacion = paginar(items, pagina, tamano)
    return Envelope(
        data=filas,
        meta=Meta(generado_en=_ahora(), frescura=frescura, nivel=nivel, paginacion=paginacion),
    )


def envolver_objeto[T](obj: T, *, frescura: dict[str, Any] | None = None) -> Envelope[T]:
    """Envuelve un objeto único (salud, informe) sin paginación."""
    return Envelope(data=obj, meta=Meta(generado_en=_ahora(), frescura=frescura))
