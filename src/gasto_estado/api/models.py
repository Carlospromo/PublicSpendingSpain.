"""Contrato de datos v1 de la API (Fase 6 / Prompt 15).

Este módulo CONGELA la forma de las respuestas: a partir de aquí es una promesa de
estabilidad hacia el frontal (CLAUDE.md §5). No cambia ningún cálculo — solo la
forma. Política de compatibilidad (ver API.md):

- COMPATIBLE (no sube de versión): añadir un campo OPCIONAL, un endpoint nuevo, un
  valor nuevo a un enum abierto documentado como tal.
- INCOMPATIBLE (exige /v2): renombrar/quitar un campo, cambiar su tipo o su
  semántica, volver obligatorio un opcional.

Toda respuesta usa la envoltura común ``{data, meta}``: ``data`` es la carga
útil; ``meta`` transporta —como ciudadanos de primera clase, no como añadidos
opcionales— los metadatos de fiabilidad que hacen honesta a la herramienta
(naturaleza, frescura, cobertura de anclaje, advertencias) y la paginación. Los
enumerados se exponen como enums estables, no strings libres. Nulo ≠ 0: un importe
ausente o un "-" del fichero es ``null``, nunca cero (CLAUDE.md §8).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums estables del contrato (congelados; nombres canónicos de CLAUDE.md §8)
# ---------------------------------------------------------------------------


class Naturaleza(StrEnum):
    """Fiabilidad epistémica de una cifra (heredada de la métrica)."""

    exacta = "exacta"
    aproximada = "aproximada"
    indiciaria = "indiciaria"


class Severidad(StrEnum):
    informativa = "informativa"
    a_revisar = "a_revisar"
    destacada = "destacada"


class Confianza(StrEnum):
    alta = "alta"
    media = "media"
    baja = "baja"


class EstadoAlerta(StrEnum):
    ALERTA = "ALERTA"
    SKIPPED = "SKIPPED"


class TipoAlerta(StrEnum):
    ritmo_ejecucion = "ritmo_ejecucion"
    modificacion_atipica = "modificacion_atipica"
    concentracion_adjudicatarios = "concentracion_adjudicatarios"
    anticipacion_compromiso = "anticipacion_compromiso"


class Velocidad(StrEnum):
    """Las tres velocidades de CLAUDE.md §3 (catálogo de fuentes)."""

    contable = "contable"
    compromisos_juridicos = "compromisos_juridicos"
    decisiones_politicas = "decisiones_politicas"


class VelocidadAlerta(StrEnum):
    """Agrupación de tipos de alerta por velocidad (filtro del frontal)."""

    contable = "contable"
    compromisos = "compromisos"
    cruce = "cruce"


class NivelAgregacion(StrEnum):
    AGE = "AGE"
    seccion = "seccion"
    servicio = "servicio"
    dg = "dg"
    programa = "programa"
    economica = "economica"
    capitulo = "capitulo"


class NivelOrganico(StrEnum):
    MINISTERIO = "MINISTERIO"
    SECRETARIA_ESTADO = "SECRETARIA_ESTADO"
    SUBSECRETARIA = "SUBSECRETARIA"
    DIRECCION_GENERAL = "DIRECCION_GENERAL"
    ORGANISMO = "ORGANISMO"
    OTRO = "OTRO"
    residual = "residual"


# ---------------------------------------------------------------------------
# Envoltura común {data, meta}
# ---------------------------------------------------------------------------


class Paginacion(BaseModel):
    """Metadatos de paginación de una colección (en ``meta.paginacion``)."""

    total: int = Field(description="Total de elementos antes de paginar.")
    pagina: int = Field(description="Página solicitada (1-indexada).")
    tamano: int = Field(description="Tamaño de página aplicado.")
    hay_siguiente: bool = Field(description="¿Hay más elementos tras esta página?")


class Frescura(BaseModel):
    """Frescura de una fuente: hasta dónde llega el dato (objetivo 5)."""

    fuentes: list[str] | None = None
    ultima_actualizacion: str | None = None  # ISO-8601 o None si no hay dato
    periodo_cubierto: list[str] | None = None  # [min, max] YYYY-MM


class Meta(BaseModel):
    """Metadatos comunes a TODA respuesta. Lo que no aplique va a ``null``.

    Los campos de fiabilidad (``naturaleza``, ``cobertura_anclaje``,
    ``advertencias``) viajan SIEMPRE que la carga sea una métrica/alerta: la API
    nunca despoja al dato de su contexto.
    """

    generado_en: str = Field(description="Instante de generación de la respuesta (ISO-8601).")
    version: str = Field(default="v1", description="Versión del contrato.")
    nivel: str | None = Field(default=None, description="Nivel de agregación servido.")
    naturaleza: Naturaleza | None = Field(
        default=None, description="Fiabilidad epistémica de la cifra (si aplica)."
    )
    magnitudes: list[str] | None = None
    fuentes: list[str] | None = None
    frescura: dict[str, Any] | None = Field(
        default=None, description="Frescura por fuente implicada (Frescura, o anidada en cruces)."
    )
    cobertura_anclaje: dict[str, Any] | None = Field(
        default=None, description="Qué fracción del importe/gasto se atribuye (anclaje)."
    )
    advertencias: list[str] = Field(default_factory=list)
    paginacion: Paginacion | None = None


class Envelope[DataT](BaseModel):
    """Envoltura común de respuesta: ``data`` + ``meta``."""

    data: DataT
    meta: Meta


# ---------------------------------------------------------------------------
# Contrato de errores (cuerpo uniforme)
# ---------------------------------------------------------------------------


class ErrorDetalle(BaseModel):
    codigo: str = Field(description="Código estable de error (no el HTTP).")
    mensaje: str = Field(description="Mensaje legible para el usuario.")
    detalle: Any | None = Field(default=None, description="Contexto adicional (validación, etc.).")


class ErrorRespuesta(BaseModel):
    """Cuerpo uniforme de error (mapea a 404/422/503; ver API.md)."""

    error: ErrorDetalle


# ---------------------------------------------------------------------------
# Modelos de filas/objetos tipados (data de cada endpoint)
# ---------------------------------------------------------------------------


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
    dg_nivel_organico: NivelOrganico | None = None
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
    velocidad: Velocidad
    periodicidad: str
    fase: int


class FrescuraFuenteModel(BaseModel):
    fuente_cod: str
    velocidad: Velocidad | None = None
    periodicidad: str | None = None
    n_filas: int
    ultima_actualizacion: str | None = None
    periodo_cubierto: list[str] | None = None
    materializado_en: str | None = None
    ultima_captura_disponible: str | None = None
    ultima_ejecucion_intentada: str | None = None
    ultima_ejecucion_correcta: str | None = None
    particion_cubierta: str | None = None
    estado_fuente: str | None = None
    advertencia_o_error_activo: str | None = None


class SaludModel(BaseModel):
    accesible: bool
    ejercicios: list[int]
    n_periodos_igae: int
    ultima_actualizacion: str | None = None
    perimetro: str
    cobertura_dg_nota: str


class AlertaModel(BaseModel):
    """Una alerta, sin despojarla de su contexto (severidad, confianza, evidencias)."""

    tipo: TipoAlerta
    estado: EstadoAlerta
    periodo: str
    ambito: dict[str, Any]
    naturaleza: Naturaleza
    severidad: Severidad | None = None
    confianza: Confianza | None = None
    valor_observado: float | None = None
    referencia: dict[str, Any] = Field(default_factory=dict)
    contexto: str = ""
    cobertura: dict[str, Any] = Field(default_factory=dict)
    evidencias: list[dict[str, Any]] = Field(default_factory=list)
    magnitudes: dict[str, Any] = Field(default_factory=dict)
    motivo: str | None = None


class InformeData(BaseModel):
    """Carga del informe de alertas de un periodo (data de /alertas/informe)."""

    periodo: str
    cobertura_global: dict[str, Any]
    resumen: dict[str, Any]
    alertas: list[AlertaModel]
    skipped: list[AlertaModel]
