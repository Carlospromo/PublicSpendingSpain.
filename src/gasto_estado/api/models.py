"""Modelos de respuesta Pydantic de la API (capa de exposición, Fase 6).

No se devuelven DataFrames crudos: cada respuesta es un modelo explícito. Los
envoltorios de métricas/alertas propagan INTACTOS los metadatos de fiabilidad que
puso la capa analítica (naturaleza, confianza, cobertura, advertencias, frescura):
la API nunca despoja al dato de su contexto (CLAUDE.md §9). Las filas de datos van
como ``dict`` (su forma depende del nivel de agregación); el contrato fino y
estable es el Prompt 15, aquí no se congela.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MetricResponse(BaseModel):
    """Envoltorio de un ``MetricResult``: dato + metadatos de fiabilidad/frescura."""

    metrica: str
    nivel: str
    naturaleza: str  # exacta | aproximada | indiciaria
    magnitudes: list[str]
    fuentes: list[str]
    frescura: dict[str, Any]
    advertencias: list[str]
    cobertura_anclaje: dict[str, Any] | None = None
    data: list[dict[str, Any]]


class AlertaModel(BaseModel):
    """Una alerta tal como la emite el motor (sin despojarla de su contexto)."""

    tipo: str
    estado: str  # ALERTA | SKIPPED
    periodo: str
    ambito: dict[str, Any]
    naturaleza: str
    severidad: str | None = None
    confianza: str | None = None
    valor_observado: float | None = None
    referencia: dict[str, Any] = {}
    contexto: str = ""
    cobertura: dict[str, Any] = {}
    evidencias: list[dict[str, Any]] = []
    magnitudes: dict[str, Any] = {}
    motivo: str | None = None


class InformeAlertasModel(BaseModel):
    periodo: str
    cobertura_global: dict[str, Any]
    resumen: dict[str, Any]
    alertas: list[AlertaModel]
    skipped: list[AlertaModel]


# --- Estructura y catálogos --------------------------------------------------


class SeccionModel(BaseModel):
    nivel: str = "seccion"
    ejercicio: int
    seccion_cod: str
    denominacion: str | None = None
    n_servicios: int


class ServicioModel(BaseModel):
    nivel: str = "servicio"
    ejercicio: int
    seccion_cod: str
    servicio_cod: str
    denominacion: str | None = None
    # Lectura nominal DG vía crosswalk; aproximada fuera del ejercicio del seed.
    dg_dir3_cod: str | None = None
    dg_denominacion: str | None = None
    dg_nivel_organico: str | None = None
    dg_equivalencia_aproximada: bool = False
    dg_nota: str | None = None


class ProgramaModel(BaseModel):
    programa_cod: str
    area_gasto_cod: str | None = None
    politica_cod: str | None = None
    grupo_programas_cod: str | None = None
    denominacion: str | None = None


class EconomicaModel(BaseModel):
    economica_cod: str
    nivel: str
    capitulo_cod: str | None = None
    denominacion: str | None = None
    denominacion_origen: str | None = None


class FuenteModel(BaseModel):
    fuente_cod: str
    denominacion: str
    velocidad: str
    periodicidad: str
    fase: int


class FrescuraFuenteModel(BaseModel):
    fuente_cod: str
    velocidad: str | None = None
    periodicidad: str | None = None
    n_filas: int
    ultima_actualizacion: str | None = None
    periodo_cubierto: list[str] | None = None


class SaludModel(BaseModel):
    accesible: bool
    ejercicios: list[int]
    n_periodos_igae: int
    ultima_actualizacion: str | None = None
    perimetro: str
    cobertura_dg_nota: str
