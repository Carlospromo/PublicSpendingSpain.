# Catálogo de métricas (Fase 5)

> Métricas analíticas sobre el warehouse, en `src/gasto_estado/analytics/metrics.py`.
> Este documento es el contrato de cara a la Fase 6 (API) y al frontal. Las
> **alertas** (umbrales, anomalías, informe) NO están aquí: son el Prompt 13.

## Principios

- **Funciones puras sobre el warehouse.** Cada métrica es una función
  `metrica(con, …) -> MetricResult` que solo consulta DuckDB (y registra alguna
  vista temporal de apoyo). Sin acoplamiento a scheduler ni a la API: la Fase 6 y
  la Fase 7 (Dagster) se limitan a invocarlas.
- **Materialización elegida: funciones que devuelven `MetricResult`** (DataFrame
  + metadatos), no vistas SQL fijas. Motivo: una métrica no es solo un `SELECT`
  — lleva naturaleza, advertencias y cobertura de anclaje que una vista no puede
  expresar; y la parametrización (nivel, periodo, ventana) explotaría el número
  de vistas. El warehouse (`modelo.sql`) queda intacto; las métricas son una capa
  de lectura. Las consultas internas son reutilizables y la salida es
  JSON-serializable (`MetricResult.to_dict()`) para la API.
- **Naturaleza inseparable** (CLAUDE.md §3): `exacta` (aritmética sobre
  magnitudes auditables comparables), `aproximada` (importe de extracción falible
  —BOE/CdM— o anclaje parcial) o `indiciaria` (cruce de velocidades; NO es
  identidad contable). Nunca se cruzan magnitudes no comparables sin la marca.
- **Salida autoexplicativa** (`MetricResult`): `metrica`, `data`, `nivel`,
  `naturaleza`, `magnitudes`, `fuentes`, `frescura` (última actualización +
  periodo cubierto), `advertencias` y `cobertura_anclaje` (cuando aplica).

## Niveles de agregación

- **Ejecución (IGAE)**: `AGE`, `seccion`, `servicio`, `programa`, `economica`,
  `capitulo` y **`dg`** (dirección general / unidad DIR3). El nivel DG es el
  diferencial del proyecto: enlaza el servicio presupuestario con su unidad DIR3
  vía el crosswalk de la Fase 1, **deduplicado** a un DIR3 por servicio (prioridad
  por nivel orgánico) para conservar los totales. Los servicios sin DIR3
  ministerial (Deuda, Clases Pasivas, transferencias a entes/SS — ~73% de la ORN)
  caen en un **bucket residual por sección**, de modo que las DG de una sección
  **suman su sección padre** (verificado en tests).
- **Compromisos (PLACSP/BDNS)**: `AGE`, `seccion`, `servicio`, `dg`
  (`anclaje_dir3_cod`, ya resuelto en la Fase 4).
- **Decisiones (BOE/CdM)**: `seccion` o `ministerio` (estas fuentes anclan a
  sección, no a servicio/DG).

---

## Paso 1 — Ejecución presupuestaria (velocidad contable, IGAE)

| Métrica | Qué calcula | Magnitudes | Nivel | Naturaleza | Advertencias clave |
|---|---|---|---|---|---|
| `grado_ejecucion(con, periodo, nivel)` | ORN / crédito definitivo (métrica reina) | crédito definitivo, ORN, crédito inicial | cualquiera (incl. `dg`) | exacta | dato ACUMULADO (comparar, no sumar); prórroga; residual DG |
| `ritmo_ejecucion(con, ejercicio, nivel)` | serie intra-anual del grado mes a mes | crédito definitivo, ORN | cualquiera | exacta | acumulado; se comparan periodos, no se suman (ORN monótona, coherente con R8) |
| `comparativa_interanual(con, periodo, nivel)` | grado del mes vs **mismo mes** del año anterior | crédito definitivo, ORN, pct | cualquiera | exacta | estacionalidad; **prórroga 2025-P no homogénea** con PGE propio; empareja por código |
| `modificaciones_credito(con, periodo, nivel)` | crédito definitivo − inicial, absoluto y % s/inicial | crédito inicial/definitivo, modificaciones (derivada) | cualquiera | exacta | DERIVADA (el Anexo I no publica modificaciones explícitas); neto puede ser negativo |

**Prórroga (2025-P).** Cuando el periodo está en prórroga, el crédito inicial que
publica el Anexo I es el **operativo** (prorrogado), no el inicial **legal** de un
PGE propio del ejercicio (CLAUDE.md §3). La comparativa interanual entre un
ejercicio prorrogado y uno normal lleva una advertencia explícita: el grado
comparado es orientativo, porque las bases (crédito) no son homogéneas.

**Cifras macro verificadas** (calculadas por la métrica, no a mano): grado AGE
95,9 % en 2015-12, 18,1 % en 2026-03, 28,5 % en 2026-04.

---

## Paso 2 — Compromisos jurídicos (PLACSP + BDNS)

| Métrica | Qué calcula | Magnitudes | Nivel | Naturaleza | Cobertura |
|---|---|---|---|---|---|
| `volumen_adjudicacion(con, …, nivel)` | importe adjudicado (flujo acumulable) | importe_adjudicacion | AGE/seccion/servicio/dg | exacta | reparto por `anclaje_tipo`; % anclado a servicio |
| `volumen_concesion(con, …, nivel)` | importe concedido (flujo acumulable) | importe (subvención) | AGE/seccion/servicio/dg | exacta | ídem |
| `concentracion_adjudicatarios(con, nivel, top_n)` | cuota del top-N e índice **HHI** por órgano | importe_adjudicacion | servicio/seccion/dg | exacta | solo contratos anclados a servicio con adjudicatario |

- **Grano y no doble conteo**: `importe_adjudicacion` es aditivo por lote (las
  magnitudes de licitación viven solo en la cabecera del expediente). La suma de
  lotes = importe del expediente.
- **Fiabilidad de anclaje expuesta, no oculta** (CLAUDE.md / docs/cobertura): a
  nivel sección/servicio/DG solo entran las filas ancladas a servicio; el
  `cobertura_anclaje` informa qué % del importe quedó `fuera_perimetro` /
  `sin_anclar`. Una métrica de adjudicación por DG donde la mayor parte del
  importe no ancla **lo dice**.
- **HHI**: 0–10.000 (Σ cuota²·10⁴). Un órgano con poca contratación anclada da un
  HHI alto por construcción (pocos adjudicatarios), no necesariamente por captura;
  la advertencia lo recuerda. El umbral/alerta es el Prompt 13.

---

## Paso 3 — Decisiones políticas (BOE + CdM)

| Métrica | Qué calcula | Magnitudes | Nivel | Naturaleza |
|---|---|---|---|---|
| `volumen_decisiones(con, fuente, …, nivel)` | conteo y volumen por sección/ministerio y tipo | importe (alta), importe (media), conteo | seccion/ministerio | **aproximada** |

- `fuente` ∈ `{boe, cdm}`. El tipo (autorización de gasto, modificación de
  crédito, crédito extraordinario, convenio, subvención…) permite filtrar.
- **Confianza propagada**: el importe de estas fuentes es de **extracción
  falible** (docs/cobertura §4-5). NUNCA se presenta un importe agregado único:
  se desglosa en `importe_alta` (cuantía titular) e `importe_media` (cifra suelta)
  y se cuenta lo que quedó `n_sin_importe`. Anclaje a **sección** por ministerio
  proponente.

---

## Paso 4 — Cruce entre velocidades (indiciario)

| Métrica | Qué calcula | Magnitudes (separadas) | Nivel | Naturaleza |
|---|---|---|---|---|
| `compromiso_vs_ejecucion(con, periodo, nivel)` | adjudicación PLACSP vs ORN IGAE | ORN, importe_adjudicacion, ratio | seccion/servicio | **indiciaria** |
| `decisiones_vs_compromiso(con, ejercicio)` | autorización de gasto CdM vs adjudicación PLACSP | importe autorizado (falible), importe_adjudicacion | seccion | **indiciaria** |

Estas métricas dan el **valor de anticipación** del proyecto: el compromiso
jurídico antecede a la obligación reconocida, y la decisión política antecede al
compromiso. Llevan una **marca de aproximación inseparable**:

> NO es una identidad contable. Adjudicación y ORN no son subconjuntos: no todo lo
> adjudicado se ejecuta en el mismo periodo, hay **IVA** (la adjudicación suele
> incluirlo; la ORN no), **plurianualidad** (un contrato se ejecuta en varios
> ejercicios) y contratos que **no llegan a ORN**. Se exponen **ambas magnitudes
> por separado** además del ratio; el ratio es un indicio, no una conciliación.

`decisiones_vs_compromiso` lleva **doble** aproximación: el importe del Consejo es
de extracción falible (se expone también solo el de confianza alta) y la
autorización política no se corresponde 1:1 con adjudicaciones ni con su periodo.

---

## Contrato de salida (`MetricResult`)

```python
@dataclass(frozen=True)
class MetricResult:
    metrica: str            # nombre de la métrica
    data: pd.DataFrame      # el dato
    nivel: str              # nivel de agregación
    naturaleza: str         # exacta | aproximada | indiciaria
    magnitudes: list[str]   # magnitudes usadas
    fuentes: list[str]      # fuente(s) del warehouse
    frescura: dict          # ultima_actualizacion, periodo_cubierto (por fuente)
    advertencias: list[str] # notas metodológicas
    cobertura_anclaje: dict | None  # reparto/atribución del anclaje, si aplica
```

`MetricResult.to_dict()` devuelve la estructura JSON-serializable que la API
expondrá tal cual (datos como lista de registros + metadatos), de modo que el
frontal reciba la cifra **con su contexto** (frescura, nivel, fiabilidad,
naturaleza y advertencias) sin tener que re-derivarlo.
