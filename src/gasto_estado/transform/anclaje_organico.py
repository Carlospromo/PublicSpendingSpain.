"""Anclaje orgánico de los compromisos jurídicos a la espina presupuestaria.

Motor COMPARTIDO por las fuentes de alta frecuencia (CLAUDE.md §2, §3): el mismo
problema DIR3 → (sección, servicio) con ascenso por la cadena de padres y
frontera de entes instrumentales. Lo usan:

- **PLACSP** (``anclar_contratos``): el órgano de contratación trae su DIR3
  directo, así que ancla por código.
- **BDNS** (``anclar_concesiones``): el órgano concedente NO trae DIR3
  (VERIFICADO 2026-06-12: la API solo publica la jerarquía administrativa como
  texto ``nivel1/nivel2/nivel3`` y, en convocatorias, un ``codigoInvente``). Se
  resuelve primero la denominación del órgano (``nivel3``) a un DIR3 dentro del
  subárbol del ministerio (``nivel2``) — reutilizando la normalización de
  denominaciones de la Fase 1 — y luego se ancla ese DIR3 con el mismo motor.

Como en ``nivel_organico``, cada decisión queda etiquetada con su tipo de
anclaje y la señal que lo determinó (auditable; nada se descarta):

- ``servicio``: el DIR3 del órgano (o un ancestro de su cadena en
  ``dim_organica``) está en el crosswalk DEL EJERCICIO → hereda (seccion_cod,
  servicio_cod). Señales: ``dir3_directo`` / ``dir3_ancestro``.
- ``organica_sin_servicio``: el DIR3 existe en ``dim_organica`` pero no debe
  resolver a un servicio AGE. Señales: ``entidad_instrumental`` (unidad de un
  ente con presupuesto PROPIO: ``tipo_entidad`` distinto de MN — OOAA, agencias
  estatales, EPE, etc.; anclar su gasto al servicio del ministerio inflaría el
  comprometido frente a una ORN que nunca lo contendrá), ``sin_servicio_en_cadena``
  o ``ejercicio_sin_crosswalk``.
- ``fuera_perimetro``: el DIR3 no es AGE (CCAA, local, universidades) o, en
  BDNS, ``nivel1`` distinto de ESTADO (la inmensa mayoría de la subvención es
  autonómica/local). Señales: ``dir3_no_age`` / ``no_estatal``.
- ``sin_anclar``: no hay forma de obtener un DIR3 (PLACSP sin código o
  malformado; BDNS cuyo órgano concedente no se resuelve a una unidad DIR3).
  Contabilizado, nunca descartado.

Vigencia temporal: la fecha de referencia es la del compromiso jurídico
(``fecha_adjudicacion`` en PLACSP, ``fecha_concesion`` en BDNS); las versiones
SCD2 de ``dim_organica`` se filtran por esa fecha y el crosswalk por su ejercicio.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from gasto_estado.transform.text import normalize as _norm

# Tipos de anclaje (enum cerrado, columna anclaje_tipo).
ANCLA_SERVICIO = "servicio"
ANCLA_ORGANICA_SIN_SERVICIO = "organica_sin_servicio"
ANCLA_FUERA_PERIMETRO = "fuera_perimetro"
ANCLA_SIN_ANCLAR = "sin_anclar"

ANCLAJE_TIPOS = (
    ANCLA_SERVICIO,
    ANCLA_ORGANICA_SIN_SERVICIO,
    ANCLA_FUERA_PERIMETRO,
    ANCLA_SIN_ANCLAR,
)

# Señales del anclaje (para auditoría, como nivel_organico_senal).
SENAL_DIR3_DIRECTO = "dir3_directo"
SENAL_DIR3_ANCESTRO = "dir3_ancestro"
SENAL_DIR3_NO_AGE = "dir3_no_age"
SENAL_SIN_DIR3 = "sin_dir3"
SENAL_DIR3_MALFORMADO = "dir3_malformado"
SENAL_SIN_SERVICIO_EN_CADENA = "sin_servicio_en_cadena"
SENAL_EJERCICIO_SIN_CROSSWALK = "ejercicio_sin_crosswalk"
SENAL_ENTIDAD_INSTRUMENTAL = "entidad_instrumental"
# Señales propias de la resolución por denominación (BDNS, sin DIR3 directo).
SENAL_NO_ESTATAL = "no_estatal"
SENAL_ORGANO_NO_RESUELTO = "organo_no_resuelto"

# Tipo de entidad DIR3 cuyo gasto SÍ vive en los servicios presupuestarios AGE
# (estructura ministerial). Cualquier otro tipo informado = presupuesto propio.
_TIPO_ENTIDAD_AGE = "MN"

_DIR3_RE = re.compile(r"^[A-Z]{1,2}\d{7,8}$")

# Tope de saltos al subir por la cadena de padres (el árbol AGE real tiene
# ~6 niveles; el tope corta posibles ciclos del dato bruto).
_MAX_ASCENSO = 12

ANCLAJE_COLUMNS = [
    "seccion_cod",
    "servicio_cod",
    "anclaje_dir3_cod",
    "anclaje_tipo",
    "anclaje_senal",
]

# Marca textual de la administración estatal en BDNS (campo nivel1).
NIVEL1_ESTADO = "ESTADO"


def _vigente_en(unidad: pd.Series, fecha: date | None) -> bool:
    """¿La versión SCD2 de la unidad estaba vigente en ``fecha``?

    Sin fecha de contrato se admite la versión abierta (fecha_fin nula): mejor
    anclar contra la estructura actual que perder el compromiso.
    """
    fin = unidad["fecha_fin"]
    if fecha is None:
        return bool(pd.isna(fin))
    inicio = unidad["fecha_inicio"]
    empieza = pd.isna(inicio) or pd.Timestamp(inicio).date() <= fecha
    sigue = pd.isna(fin) or fecha <= pd.Timestamp(fin).date()
    return bool(empieza and sigue)


# Tokens sin carga semántica para comparar denominaciones de órganos (BDNS).
_STOPWORDS = frozenset({"de", "del", "la", "las", "los", "el", "y", "e", "para", "en", "al", "a"})


def _tokens(norm_text: str) -> frozenset[str]:
    return frozenset(t for t in norm_text.split() if t not in _STOPWORDS)


class Anclador:
    """Índices precalculados de dim_organica + crosswalk para anclar por fila."""

    def __init__(self, dim_organica: pd.DataFrame, crosswalk: pd.DataFrame) -> None:
        # dim_organica indexada por dir3_cod (puede haber varias versiones SCD2).
        self._versiones: dict[str, list[pd.Series]] = {}
        for _, fila in dim_organica.iterrows():
            self._versiones.setdefault(fila["dir3_cod"], []).append(fila)

        # Crosswalk: (ejercicio, dir3) -> (seccion, servicio). Solo pares con
        # dir3 asignado. Si un dir3 mapea a varios servicios (la correspondencia
        # no es 1:1) se toma el menor (seccion, servicio): determinista.
        con_dir3 = crosswalk[crosswalk["dir3_cod"].notna()]
        self._servicio_por_dir3: dict[tuple[int, str], tuple[str, str]] = {}
        for _, fila in con_dir3.sort_values(["seccion_cod", "servicio_cod"]).iterrows():
            clave = (int(fila["ejercicio"]), str(fila["dir3_cod"]))
            self._servicio_por_dir3.setdefault(
                clave, (str(fila["seccion_cod"]), str(fila["servicio_cod"]))
            )
        self._ejercicios = {ej for ej, _ in self._servicio_por_dir3}

        # Índices de resolución por denominación (BDNS): denominación normalizada
        # de la raíz → ministerio DIR3; y (ministerio, norm) → [dir3 vigentes].
        # Se construyen perezosamente la primera vez que se resuelve un nombre.
        self._dim_organica = dim_organica
        self._ministerio_por_norm: dict[str, str] | None = None
        self._dir3_por_norm_ministerio: dict[tuple[str, str], list[str]] | None = None
        self._dir3_por_norm_global: dict[str, list[str]] | None = None

    # -- núcleo: DIR3 → (sección, servicio) -------------------------------------

    def _version_vigente(self, dir3_cod: str, fecha: date | None) -> pd.Series | None:
        for version in self._versiones.get(dir3_cod, []):
            if _vigente_en(version, fecha):
                return version
        return None

    def anclar(
        self, dir3_cod: object, fecha: date | None, ejercicio: int | None = None
    ) -> dict[str, object]:
        """Columnas de anclaje (ANCLAJE_COLUMNS) para un órgano con DIR3.

        ``fecha`` filtra las versiones SCD2 de dim_organica; ``ejercicio`` elige
        el crosswalk (por defecto, el año de ``fecha``).
        """

        def out(
            tipo: str,
            senal: str,
            ancla: str | None = None,
            seccion: str | None = None,
            servicio: str | None = None,
        ) -> dict[str, object]:
            return {
                "seccion_cod": seccion,
                "servicio_cod": servicio,
                "anclaje_dir3_cod": ancla,
                "anclaje_tipo": tipo,
                "anclaje_senal": senal,
            }

        if dir3_cod is None or (isinstance(dir3_cod, float) and pd.isna(dir3_cod)):
            return out(ANCLA_SIN_ANCLAR, SENAL_SIN_DIR3)
        codigo = str(dir3_cod).strip().upper()
        if not _DIR3_RE.match(codigo):
            return out(ANCLA_SIN_ANCLAR, SENAL_DIR3_MALFORMADO)

        # Ejercicio presupuestario del compromiso; sin fecha ni ejercicio, el
        # último cubierto por el crosswalk (estructura más reciente disponible).
        if ejercicio is None:
            ejercicio = fecha.year if fecha is not None else max(self._ejercicios, default=0)
        cubierto = ejercicio in self._ejercicios

        # Ascenso por la cadena de padres dentro de dim_organica (AGE): el
        # primer eslabón con servicio en el crosswalk del ejercicio gana.
        # "en_organica" distingue AGE de fuera-de-perímetro aunque la versión
        # SCD2 no esté vigente en la fecha (unidad extinguida/anacrónica).
        actual: str | None = codigo
        saltos = 0
        en_organica = codigo in self._versiones
        entidad_propia = False
        while actual is not None and saltos < _MAX_ASCENSO:
            servicio = self._servicio_por_dir3.get((ejercicio, actual))
            if servicio is not None:
                # El crosswalk es autoritativo (incluye overrides manuales):
                # si mapea la unidad, ancla aunque sea cabecera de ente.
                return out(
                    ANCLA_SERVICIO,
                    SENAL_DIR3_DIRECTO if actual == codigo else SENAL_DIR3_ANCESTRO,
                    ancla=actual,
                    seccion=servicio[0],
                    servicio=servicio[1],
                )
            version = self._version_vigente(actual, fecha)
            if version is None:
                break
            # Frontera de perímetro: una unidad de un ente con presupuesto
            # propio (tipo_entidad informado y != MN) no asciende al servicio
            # del ministerio — su gasto no aparecerá en la ORN de ese servicio.
            tipo = version.get("tipo_entidad")
            if not pd.isna(tipo) and tipo != _TIPO_ENTIDAD_AGE:
                entidad_propia = True
                break
            padre = version.get("dir3_padre_cod")
            actual = None if pd.isna(padre) or padre == actual else str(padre)
            saltos += 1

        if entidad_propia:
            return out(ANCLA_ORGANICA_SIN_SERVICIO, SENAL_ENTIDAD_INSTRUMENTAL, ancla=codigo)
        if en_organica:
            senal = SENAL_SIN_SERVICIO_EN_CADENA if cubierto else SENAL_EJERCICIO_SIN_CROSSWALK
            return out(ANCLA_ORGANICA_SIN_SERVICIO, senal, ancla=codigo)
        return out(ANCLA_FUERA_PERIMETRO, SENAL_DIR3_NO_AGE, ancla=codigo)

    # -- resolución por denominación (BDNS) -------------------------------------

    def _build_indices_denominacion(self) -> None:
        organica = self._dim_organica
        norm = organica["denominacion"].map(_norm)
        nivel = organica["nivel_jerarquico"]
        raices = organica[nivel.astype("Int64") == 1]
        self._ministerio_por_norm = dict(
            zip(raices["denominacion"].map(_norm), raices["dir3_cod"], strict=True)
        )
        por_min: dict[tuple[str, str], list[str]] = {}
        por_global: dict[str, list[str]] = {}
        for n, ministerio, dir3, fin in zip(
            norm,
            organica["ministerio_dir3_cod"],
            organica["dir3_cod"],
            organica["fecha_fin"],
            strict=True,
        ):
            if not pd.isna(fin):  # solo unidades vigentes para el matching nominal
                continue
            por_global.setdefault(n, []).append(dir3)
            if not pd.isna(ministerio):
                por_min.setdefault((str(ministerio), n), []).append(dir3)
        self._dir3_por_norm_ministerio = por_min
        self._dir3_por_norm_global = por_global

    def resolver_denominacion(
        self,
        nivel2: object,
        nivel3: object,
        overrides: dict[str, str] | None = None,
    ) -> str | None:
        """DIR3 del órgano cuyo nombre es ``nivel3``, o None si no se resuelve.

        Estrategia (override > exacta en subárbol del ministerio > tokens en
        subárbol > nombre único global). Scoping por ``nivel2`` (ministerio):
        evita colisiones del mismo nombre entre departamentos. Los overrides
        (``crosswalk_organo_bdns_dir3.csv``) prevalecen y cubren los nombres que
        la BDNS escribe distinto del DIR3 (p. ej. el doble prefijo "AGENCIA
        ESTATAL AGENCIA ESPAÑOLA…").
        """
        if self._ministerio_por_norm is None:
            self._build_indices_denominacion()
        assert self._ministerio_por_norm is not None
        assert self._dir3_por_norm_ministerio is not None
        assert self._dir3_por_norm_global is not None

        nivel3_norm = _norm(None if nivel3 is None else str(nivel3))
        if not nivel3_norm:
            return None
        if overrides and nivel3_norm in overrides:
            return overrides[nivel3_norm]

        ministerio = self._ministerio_por_norm.get(_norm(None if nivel2 is None else str(nivel2)))
        if ministerio is not None:
            exactas = self._dir3_por_norm_ministerio.get((ministerio, nivel3_norm))
            if exactas:
                return sorted(exactas)[0]
            objetivo = _tokens(nivel3_norm)
            candidatos = [
                dir3
                for (min_cod, n), dir3s in self._dir3_por_norm_ministerio.items()
                if min_cod == ministerio and _tokens(n) == objetivo
                for dir3 in dir3s
            ]
            if candidatos:
                return sorted(candidatos)[0]

        # Sin ministerio resuelto (o sin candidato en el subárbol): solo se
        # acepta una coincidencia EXACTA y ÚNICA en todo el directorio.
        globales = self._dir3_por_norm_global.get(nivel3_norm)
        if globales and len(set(globales)) == 1:
            return globales[0]
        return None

    def anclar_organo_bdns(
        self,
        nivel1: object,
        nivel2: object,
        nivel3: object,
        fecha: date | None,
        ejercicio: int | None,
        overrides: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Anclaje de un órgano concedente BDNS (sin DIR3 directo).

        ``nivel1`` distinto de ESTADO ⇒ ``fuera_perimetro`` (autonómica/local,
        el grueso de la subvención). Estatal cuyo ``nivel3`` no se resuelve a
        una unidad DIR3 ⇒ ``sin_anclar`` (contabilizado). Resuelto ⇒ se delega
        en el motor DIR3 ``anclar``.
        """
        if _norm(None if nivel1 is None else str(nivel1)) != _norm(NIVEL1_ESTADO):
            return {
                "seccion_cod": None,
                "servicio_cod": None,
                "anclaje_dir3_cod": None,
                "anclaje_tipo": ANCLA_FUERA_PERIMETRO,
                "anclaje_senal": SENAL_NO_ESTATAL,
            }
        dir3 = self.resolver_denominacion(nivel2, nivel3, overrides)
        if dir3 is None:
            return {
                "seccion_cod": None,
                "servicio_cod": None,
                "anclaje_dir3_cod": None,
                "anclaje_tipo": ANCLA_SIN_ANCLAR,
                "anclaje_senal": SENAL_ORGANO_NO_RESUELTO,
            }
        return self.anclar(dir3, fecha, ejercicio)


def load_overrides_organo(path: Path) -> dict[str, str]:
    """Carga el CSV de overrides órgano-BDNS → DIR3 como mapa normalizado.

    El fichero es editable a mano y versionado (``crosswalk_organo_bdns_dir3.csv``);
    las claves se normalizan igual que las denominaciones en la resolución.
    """
    overrides = pd.read_csv(path, dtype=str, comment="#")
    return {
        _norm(organo): str(dir3)
        for organo, dir3 in zip(overrides["organo_bdns"], overrides["dir3_cod"], strict=True)
    }


# ---------------------------------------------------------------------------
# Aplicación por lote a cada fuente
# ---------------------------------------------------------------------------


def anclar_contratos(
    contratos: pd.DataFrame,
    dim_organica: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Añade a los contratos PLACSP las columnas de anclaje (ANCLAJE_COLUMNS).

    ``contratos``: canónico PLACSP (placsp_adjudicacion_schema), con
    ``organo_dir3_cod`` directo. Lo no resoluble queda etiquetado y contado.
    """
    anclador = Anclador(dim_organica, crosswalk)
    fechas = contratos["fecha_adjudicacion"].where(
        contratos["fecha_adjudicacion"].notna(), contratos["fecha_actualizacion"]
    )
    ejercicios = contratos["periodo"].str.slice(0, 4).astype(int)
    anclajes = [
        anclador.anclar(dir3, fecha if isinstance(fecha, date) else None, ejercicio)
        for dir3, fecha, ejercicio in zip(
            contratos["organo_dir3_cod"], fechas, ejercicios, strict=True
        )
    ]
    return _con_anclaje(contratos, anclajes)


def anclar_concesiones(
    concesiones: pd.DataFrame,
    dim_organica: pd.DataFrame,
    crosswalk: pd.DataFrame,
    overrides: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Añade a las concesiones BDNS las columnas de anclaje (ANCLAJE_COLUMNS).

    ``concesiones``: canónico BDNS (bdns_concesion_schema), con la jerarquía
    administrativa ``nivel1/nivel2/nivel3`` (sin DIR3). El anclaje resuelve el
    órgano concedente (``nivel3``) por denominación dentro del ministerio
    (``nivel2``). ``overrides``: mapa denominación-normalizada → DIR3.
    """
    anclador = Anclador(dim_organica, crosswalk)
    fechas = concesiones["fecha_concesion"].where(
        concesiones["fecha_concesion"].notna(), concesiones["fecha_alta"]
    )
    ejercicios = concesiones["periodo"].str.slice(0, 4).astype(int)
    anclajes = [
        anclador.anclar_organo_bdns(
            n1, n2, n3, fecha if isinstance(fecha, date) else None, ejercicio, overrides
        )
        for n1, n2, n3, fecha, ejercicio in zip(
            concesiones["nivel1"],
            concesiones["nivel2"],
            concesiones["nivel3"],
            fechas,
            ejercicios,
            strict=True,
        )
    ]
    return _con_anclaje(concesiones, anclajes)


def _con_anclaje(df: pd.DataFrame, anclajes: list[dict[str, object]]) -> pd.DataFrame:
    resultado = df.copy()
    for col in ANCLAJE_COLUMNS:
        resultado[col] = pd.Series([a[col] for a in anclajes], index=resultado.index)
    return resultado


def anclaje_stats(df: pd.DataFrame, unidad_col: str) -> dict[str, float]:
    """Cobertura del anclaje por unidad (``unidad_col``) para auditoría y tests.

    "Sin anclar contabilizado es información honesta": estas métricas son el
    contador. Se mide por unidad (expediente en PLACSP, concesión en BDNS) y no
    por fila para no sobreponderar las unidades multi-fila.
    """
    por_unidad = df.groupby(unidad_col)["anclaje_tipo"].first()
    total = len(por_unidad)
    conteo = por_unidad.value_counts()
    return {
        "unidades_total": float(total),
        **{f"{tipo}_pct": float(conteo.get(tipo, 0)) / total * 100 for tipo in ANCLAJE_TIPOS},
    }
