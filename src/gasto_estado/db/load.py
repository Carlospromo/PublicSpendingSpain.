"""Carga idempotente del warehouse DuckDB (Fase 3).

Semántica documentada en docs/modelo_datos.md §5: reemplazo de partición por
``(periodo, fuente_cod)`` en el hecho, dimensiones resueltas-o-derivadas que
nunca se borran, y *fail loud* ante anclas orgánicas huérfanas. ``build``
reconstruye el fichero entero desde raw + seeds; ``update`` carga solo los
periodos de raw aún no presentes.
"""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from gasto_estado.parsers.igae import parse_periodo
from gasto_estado.parsers.placsp import discover_capturas, parse_capture_dir
from gasto_estado.parsers.schemas import igae_anexo_i_schema
from gasto_estado.quality.checks import FAIL, CoherenceError, run_checks
from gasto_estado.transform.placsp_anclaje import ANCLAJE_COLUMNS, anclar_contratos

MODELO_SQL = Path(__file__).with_name("modelo.sql")
SEEDS_DIR = Path(__file__).with_name("seeds")

# Materialización de "sin desglose territorial" (NULL del parser) como valor
# categórico: la clave natural del hecho no admite NULL (docs/modelo_datos.md §4).
PROVINCIA_NO_TERRITORIALIZADO = "NT"

# Magnitudes que cada fuente aporta de forma autoritativa (docs/modelo_datos.md
# §1b). NULL en una magnitud listada aquí = "cubierta pero sin dato ('-')";
# NULL en una no listada = "no cubierta por esta fuente".
COBERTURA_FUENTE = {
    "igae_anexo_i": "credito_inicial,credito_definitivo,orn",
}

_NIVEL_ECONOMICA = {1: "capitulo", 2: "articulo", 3: "concepto", 5: "subconcepto", 7: "partida"}


class OrphanOrganicError(RuntimeError):
    """Un hecho no resuelve contra ``dim_seccion_servicio`` ni puede derivarla.

    Sin entrada en el seed PGE y sin ``servicio_denominacion`` en el propio
    fichero no hay ancla orgánica nominada posible: la carga se detiene
    (CLAUDE.md §7.6, sin huérfanos silenciosos).
    """


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Abre (creando si hace falta) el warehouse en ``db_path``."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Aplica el DDL (idempotente) de ``modelo.sql``."""
    con.execute(MODELO_SQL.read_text(encoding="utf-8"))


def load_seeds(con: duckdb.DuckDBPyConnection) -> None:
    """Carga los seeds versionados. Idempotente; el seed siempre es autoritativo.

    ``INSERT OR REPLACE``: recargar pisa la versión anterior de la misma clave
    (p. ej. una entrada antes derivada del Anexo I que el seed pase a cubrir),
    sin borrar nunca filas que los hechos puedan estar referenciando.
    """
    seccion_servicio = pd.read_csv(
        SEEDS_DIR / "dim_seccion_servicio.csv",
        dtype={"seccion_cod": str, "servicio_cod": str},
    )
    con.register("_seed_ss", seccion_servicio)
    con.execute(
        """
        INSERT OR REPLACE INTO dim_seccion_servicio
        SELECT ejercicio, seccion_cod, servicio_cod, seccion_denominacion,
               servicio_denominacion, presupuesto, 'seed_pge'
        FROM _seed_ss
        """
    )
    con.unregister("_seed_ss")

    organica = pd.read_csv(
        SEEDS_DIR / "dim_organica.csv",
        dtype={"seccion_cod": str, "servicio_cod": str},
        parse_dates=["fecha_inicio", "fecha_fin"],
    )
    con.register("_seed_org", organica)
    con.execute(
        """
        INSERT OR REPLACE INTO dim_organica
        SELECT seccion_cod, servicio_cod, dir3_cod, denominacion, dir3_padre_cod,
               ministerio_dir3_cod, ministerio_denominacion, nivel_jerarquico,
               nivel_organico, nivel_organico_senal, tipo_entidad, estado,
               fecha_inicio::DATE, fecha_fin::DATE
        FROM _seed_org
        """
    )
    con.unregister("_seed_org")


def _upsert_dim_periodo(con: duckdb.DuckDBPyConnection, periodo: str) -> None:
    ejercicio, mes = int(periodo[:4]), int(periodo[5:7])
    fin_mes = date(ejercicio, mes, calendar.monthrange(ejercicio, mes)[1])
    # Etiqueta de presupuesto: solo asertada si el seed PGE cubre el ejercicio.
    fila = con.execute(
        """
        SELECT min(presupuesto) FROM dim_seccion_servicio
        WHERE ejercicio = ? AND origen = 'seed_pge'
        """,
        [ejercicio],
    ).fetchone()
    presupuesto = fila[0] if fila is not None else None
    con.execute(
        "INSERT OR REPLACE INTO dim_periodo VALUES (?, ?, ?, ?, ?)",
        [periodo, ejercicio, mes, presupuesto, fin_mes],
    )


def _ensure_seccion_servicio(
    con: duckdb.DuckDBPyConnection, detalle: pd.DataFrame, ejercicio: int
) -> None:
    """Resuelve cada (seccion, servicio) del lote o deriva la entrada del Anexo I.

    Orden resolver→derivar→fail-loud de docs/modelo_datos.md §2. La derivada
    toma la ``servicio_denominacion`` mínima lexicográfica (determinista) y
    deja sección/presupuesto a NULL: el Anexo I no los trae.
    """
    usados = (
        detalle[["seccion_cod", "servicio_cod", "servicio_denominacion"]]
        .groupby(["seccion_cod", "servicio_cod"], as_index=False)
        .agg(servicio_denominacion=("servicio_denominacion", "min"))
    )
    existentes = con.execute(
        "SELECT seccion_cod, servicio_cod FROM dim_seccion_servicio WHERE ejercicio = ?",
        [ejercicio],
    ).df()
    faltan = usados.merge(
        existentes, on=["seccion_cod", "servicio_cod"], how="left", indicator=True
    )
    faltan = faltan[faltan["_merge"] == "left_only"].drop(columns="_merge")
    if faltan.empty:
        return

    sin_nombre = faltan[faltan["servicio_denominacion"].isna()]
    if not sin_nombre.empty:
        claves = ", ".join(
            f"{ejercicio}/{s}.{v}"
            for s, v in zip(sin_nombre["seccion_cod"], sin_nombre["servicio_cod"], strict=True)
        )
        raise OrphanOrganicError(
            f"Anclas orgánicas sin entrada en dim_seccion_servicio ni denominación "
            f"derivable del Anexo I: {claves}. Revisa el seed o el fichero raw."
        )

    derivadas = faltan.assign(ejercicio=ejercicio)
    con.register("_derivadas_ss", derivadas)
    con.execute(
        """
        INSERT OR IGNORE INTO dim_seccion_servicio
        SELECT ejercicio, seccion_cod, servicio_cod, NULL, servicio_denominacion,
               NULL, 'derivado_igae'
        FROM _derivadas_ss
        """
    )
    con.unregister("_derivadas_ss")


def _ensure_programas(con: duckdb.DuckDBPyConnection, detalle: pd.DataFrame) -> None:
    programas = pd.DataFrame({"programa_cod": detalle["programa_cod"].unique()})
    con.register("_programas", programas)
    con.execute(
        """
        INSERT OR IGNORE INTO dim_programa
        SELECT programa_cod, programa_cod[1:1], programa_cod[1:2],
               programa_cod[1:3], programa_cod[1:4], NULL
        FROM _programas
        """
    )
    con.unregister("_programas")


def _ensure_economicas(con: duckdb.DuckDBPyConnection, detalle: pd.DataFrame) -> None:
    """Inserta las económicas observadas y sintetiza sus ancestros (artículo).

    El capítulo ya existe (catálogo estático de modelo.sql); concepto/subconcepto
    intermedios solo se materializan si algún hecho los usa como nivel propio.
    """
    codigos: set[str] = set(detalle["economica_cod"].unique())
    codigos |= {c[:2] for c in codigos}  # ancestro artículo
    economicas = pd.DataFrame(sorted(codigos), columns=["economica_cod"])
    economicas["nivel"] = economicas["economica_cod"].str.len().map(_NIVEL_ECONOMICA)
    con.register("_economicas", economicas)
    con.execute(
        """
        INSERT OR IGNORE INTO dim_economica
        SELECT economica_cod, nivel, economica_cod[1:1],
               CASE WHEN len(economica_cod) >= 2 THEN economica_cod[1:2] END,
               CASE WHEN len(economica_cod) >= 3 THEN economica_cod[1:3] END,
               NULL, NULL
        FROM _economicas
        """
    )
    con.unregister("_economicas")


def _refresh_economica_denominaciones(con: duckdb.DuckDBPyConnection) -> None:
    """Recalcula las denominaciones derivadas como modal sobre TODOS los hechos.

    Determinista (desempate: mayor frecuencia, luego orden lexicográfico) e
    independiente del orden de carga (docs/modelo_datos.md §5). Nunca pisa el
    catálogo estático.
    """
    con.execute(
        """
        WITH conteo AS (
            SELECT economica_cod, aplicacion_denominacion AS denominacion, count(*) AS n
            FROM fact_ejecucion
            WHERE aplicacion_denominacion IS NOT NULL
            GROUP BY ALL
        ),
        modal AS (
            SELECT economica_cod, denominacion
            FROM conteo
            QUALIFY row_number() OVER (
                PARTITION BY economica_cod ORDER BY n DESC, denominacion
            ) = 1
        )
        UPDATE dim_economica
        SET denominacion = modal.denominacion, denominacion_origen = 'derivado_anexo_i'
        FROM modal
        WHERE dim_economica.economica_cod = modal.economica_cod
          AND coalesce(dim_economica.denominacion_origen, '') != 'catalogo_estatico'
        """
    )


def load_periodo(con: duckdb.DuckDBPyConnection, detalle: pd.DataFrame) -> int:
    """Carga un lote canónico del Anexo I: upsert por partición (periodo, fuente).

    Valida el contrato de entrada, puebla/deriva dimensiones, reemplaza la
    partición del hecho y ejecuta las validaciones contables (CLAUDE.md §7)
    sobre el periodo. Devuelve el nº de filas cargadas.

    Fail loud por TRANSACCIÓN (no cuarentena): dimensiones, partición,
    denominaciones derivadas y checks comparten una única transacción; si los
    checks marcan FAIL se hace ROLLBACK y se lanza ``CoherenceError``. Así el
    warehouse queda exactamente en el último estado íntegro — en particular,
    la recarga fallida de una revisión IGAE conserva la versión buena anterior
    de la partición, cosa que una cuarentena post-commit no garantizaría.
    """
    detalle = igae_anexo_i_schema.validate(detalle)

    periodos = detalle["periodo"].unique()
    fuentes = detalle["fuente"].unique()
    if len(periodos) != 1 or len(fuentes) != 1:
        raise ValueError(
            f"load_periodo espera un único (periodo, fuente); recibidos {periodos=} {fuentes=}"
        )
    periodo, fuente = str(periodos[0]), str(fuentes[0])
    ejercicio = int(periodo[:4])
    cobertura = COBERTURA_FUENTE[fuente]

    hechos = detalle.assign(
        ejercicio=ejercicio,
        provincia_cod=detalle["provincia_cod"].fillna(PROVINCIA_NO_TERRITORIALIZADO),
        cobertura=cobertura,
    )
    con.execute("BEGIN")
    try:
        _upsert_dim_periodo(con, periodo)
        _ensure_seccion_servicio(con, detalle, ejercicio)
        _ensure_programas(con, detalle)
        _ensure_economicas(con, detalle)
        con.execute(
            "DELETE FROM fact_ejecucion WHERE periodo = ? AND fuente_cod = ?",
            [periodo, fuente],
        )
        con.register("_hechos", hechos)
        con.execute(
            """
            INSERT INTO fact_ejecucion
            SELECT periodo, fuente, ejercicio, seccion_cod, servicio_cod,
                   programa_cod, economica_cod, provincia_cod,
                   aplicacion_denominacion,
                   credito_inicial, credito_definitivo,
                   NULL,  -- modificaciones: no cubierta por el Anexo I
                   NULL,  -- comprometido:   no cubierta por el Anexo I
                   orn,
                   NULL,  -- pagos:          no cubierta por el Anexo I
                   cobertura, fecha_captura
            FROM _hechos
            """
        )
        con.unregister("_hechos")
        _refresh_economica_denominaciones(con)
        fallos = [r for r in run_checks(con, [periodo]) if r.estado == FAIL]
        if fallos:
            raise CoherenceError(periodo, fallos)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(hechos)


def discover_periodos(raw_dir: Path) -> list[str]:
    """Periodos IGAE disponibles en raw, ascendentes (determinismo de carga)."""
    base = raw_dir / "igae_mensual"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and _es_periodo(p.name))


def _es_periodo(nombre: str) -> bool:
    return len(nombre) == 7 and nombre[4] == "-" and nombre.replace("-", "").isdigit()


# Columnas (y orden) del INSERT en fact_contratos: canónicas PLACSP + anclaje.
# entry_id y organo_tipo_cod son internas del parser y no se persisten.
_CONTRATOS_INSERT_COLS = [
    "licitacion_id",
    "lote_id",
    "fuente",
    "periodo",
    "ejercicio",
    "expediente_id",
    "es_cabecera_expediente",
    "organo_id",
    "organo_id_esquema",
    "organo_dir3_cod",
    "organo_denominacion",
    "seccion_cod",
    "servicio_cod",
    "anclaje_dir3_cod",
    "anclaje_tipo",
    "anclaje_senal",
    "tipo_contrato_cod",
    "subtipo_contrato_cod",
    "procedimiento_cod",
    "cpv_cod",
    "estado_cod",
    "resultado_cod",
    "presupuesto_sin_iva",
    "presupuesto_con_iva",
    "valor_estimado",
    "importe_adjudicacion",
    "num_ofertas",
    "adjudicatario_id",
    "adjudicatario_id_esquema",
    "adjudicatario_nombre",
    "adjudicatario_es_pyme",
    "fecha_adjudicacion",
    "fecha_formalizacion",
    "fecha_actualizacion",
    "fecha_captura",
]


def load_contratos(con: duckdb.DuckDBPyConnection, anclado: pd.DataFrame) -> int:
    """Carga un lote PLACSP anclado: upsert "última foto" por licitación.

    ``anclado`` = salida de ``parse_captura`` (ya validada contra
    ``placsp_adjudicacion_schema``) tras ``anclar_contratos``. Se borra el
    bloque COMPLETO de cada licitación presente en el lote y se reinserta su
    foto nueva: una republicación con menos lotes no deja filas zombis y
    recargar el mismo raw es idempotente (CLAUDE.md §2). El historial de fotos
    vive en la capa raw versionada, no en el warehouse.

    Sin checks contables: §7 aplica a la verdad contable IGAE; aquí el contrato
    de entrada es el esquema pandera + el anclaje etiquetado (nunca NULL).
    """
    faltan = [c for c in ANCLAJE_COLUMNS if c not in anclado.columns]
    if faltan:
        raise ValueError(
            f"Lote PLACSP sin anclar (faltan {faltan}); pasa por anclar_contratos antes."
        )
    if anclado.empty:
        return 0
    hechos = anclado.assign(ejercicio=anclado["periodo"].str.slice(0, 4).astype(int))

    con.execute("BEGIN")
    try:
        for periodo in sorted(hechos["periodo"].unique()):
            _upsert_dim_periodo(con, str(periodo))
        con.register("_contratos", hechos)
        con.execute(
            """
            DELETE FROM fact_contratos
            WHERE licitacion_id IN (SELECT DISTINCT licitacion_id FROM _contratos)
            """
        )
        cols = ", ".join(_CONTRATOS_INSERT_COLS)
        con.execute(f"INSERT INTO fact_contratos SELECT {cols} FROM _contratos")
        con.unregister("_contratos")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(hechos)


def _leer_seeds_anclaje() -> tuple[pd.DataFrame, pd.DataFrame]:
    dim_organica = pd.read_csv(
        SEEDS_DIR / "dim_organica.csv",
        dtype={"seccion_cod": str, "servicio_cod": str},
        parse_dates=["fecha_inicio", "fecha_fin"],
    )
    crosswalk = pd.read_csv(SEEDS_DIR / "crosswalk_servicio_dir3.csv", dtype=str)
    crosswalk["ejercicio"] = crosswalk["ejercicio"].astype(int)
    return dim_organica, crosswalk


def _cargar_raw_placsp(
    con: duckdb.DuckDBPyConnection, raw_dir: Path, capturas: list[str]
) -> dict[str, int]:
    """Parsea+ancla+carga cada captura, ascendente (la más reciente gana)."""
    if not capturas:
        return {}
    dim_organica, crosswalk = _leer_seeds_anclaje()
    stats: dict[str, int] = {}
    for captura in capturas:
        contratos = parse_capture_dir(raw_dir / "placsp" / captura)
        anclado = anclar_contratos(contratos, dim_organica, crosswalk)
        stats[f"placsp@{captura}"] = load_contratos(con, anclado)
    return stats


def _capturas_pendientes(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> list[str]:
    """Capturas raw posteriores a la última cargada (nombre de directorio ISO).

    fecha_captura solo se sobreescribe en las licitaciones republicadas, así
    que max(fecha_captura) marca la última captura aplicada al warehouse.
    """
    fila = con.execute("SELECT max(fecha_captura) FROM fact_contratos").fetchone()
    ultima = fila[0] if fila is not None else None
    capturas = discover_capturas(raw_dir)
    if ultima is None:
        return capturas
    return [c for c in capturas if c > ultima.isoformat()]


def _cargar_raw(
    con: duckdb.DuckDBPyConnection, raw_dir: Path, periodos: list[str]
) -> dict[str, int]:
    stats: dict[str, int] = {}
    for periodo in periodos:
        detalle = parse_periodo(periodo, raw_dir=raw_dir)
        stats[periodo] = load_periodo(con, detalle)
    return stats


def build(db_path: Path, raw_dir: Path) -> dict[str, int]:
    """Reconstruye el warehouse desde cero: raw inmutable + seeds (CLAUDE.md §2).

    Borra el fichero anterior (es un artefacto derivado, nunca la fuente de
    verdad) y carga todos los periodos disponibles en orden ascendente.
    Devuelve filas cargadas por periodo.
    """
    db_path.unlink(missing_ok=True)
    Path(f"{db_path}.wal").unlink(missing_ok=True)
    with connect(db_path) as con:
        init_schema(con)
        load_seeds(con)
        stats = _cargar_raw(con, raw_dir, discover_periodos(raw_dir))
        stats.update(_cargar_raw_placsp(con, raw_dir, discover_capturas(raw_dir)))
        return stats


def update(db_path: Path, raw_dir: Path) -> dict[str, int]:
    """Carga incremental: solo periodos de raw sin partición ya cargada.

    Sobre un fichero inexistente equivale a ``build``. Para recargar un periodo
    ya presente (revisión IGAE) usa ``build`` o ``load_periodo`` directamente.
    """
    if not db_path.exists():
        return build(db_path, raw_dir)
    with connect(db_path) as con:
        init_schema(con)
        load_seeds(con)
        cargados = {
            fila[0]
            for fila in con.execute(
                "SELECT DISTINCT periodo FROM fact_ejecucion WHERE fuente_cod = 'igae_anexo_i'"
            ).fetchall()
        }
        pendientes = [p for p in discover_periodos(raw_dir) if p not in cargados]
        stats = _cargar_raw(con, raw_dir, pendientes)
        stats.update(_cargar_raw_placsp(con, raw_dir, _capturas_pendientes(con, raw_dir)))
        return stats
