# Catálogo de alertas analíticas (Fase 5)

> Motor de alertas en `src/gasto_estado/analytics/alerts.py`, construido SOBRE las
> métricas del catálogo `docs/metricas.md` (una alerta es interpretación de una
> métrica, no una métrica nueva). Análogo a `quality/checks.py` pero analítico.

## Qué es —y qué no es— una alerta

Una alerta es una **hipótesis señalada para revisión humana**, no un veredicto.
El destinatario es un analista que decide si la señal merece atención. Por eso
cada alerta:

- **explica por qué saltó**: la cifra observada, el umbral, el contexto comparativo;
- declara su **severidad** graduada (`informativa` / `a_revisar` / `destacada`),
  nunca binaria, y su **confianza** (`alta` / `media` / `baja`);
- hereda la **naturaleza** de su métrica base (`exacta` / `aproximada` / `indiciaria`);
- viaja con su **cobertura** (qué fracción del gasto cubre su ámbito);
- enlaza las **evidencias** (aplicaciones / contratos que la motivan);
- **nunca afirma irregularidad, intención ni ilegalidad** — describe una anomalía
  estadística o un patrón, no una acusación (verificado por test).

El motor distingue **ALERTA** de **SKIPPED** (regla no evaluable por falta de
datos o de histórico), con motivo explícito — como `checks.py` distingue FAIL de
SKIPPED. Funciones puras sobre el warehouse, sin acoplamiento a API ni scheduler
(Fase 6 las expone, Fase 7 las dispara).

## Cobertura (declarada, no oculta)

Las alertas IGAE se evalúan a nivel **servicio presupuestario**, que es la clave
estable interanual y se corresponde con la unidad gestora (dirección general /
secretaría de Estado / subsecretaría); se etiqueta con su unidad DIR3 y nivel
orgánico cuando el crosswalk lo resuelve. Como se documentó en la Fase 4/Prompt
12, solo **~27% de la ORN** se gestiona por unidades con anclaje DIR3 (el resto
—Deuda, Clases Pasivas, transferencias a entes/SS— no es una DG ministerial). El
encabezado de cada informe declara qué fracción se ha podido vigilar a nivel DG;
**ninguna alerta sugiere vigilar la totalidad del gasto**.

## Catálogo

| Tipo | Sobre la métrica | Ámbito | Naturaleza | Qué señala |
|---|---|---|---|---|
| `ritmo_ejecucion` | `grado_ejecucion` / `ritmo` | servicio (≈DG) | exacta | grado que se desvía de la **norma histórica mismo-mes del propio servicio** |
| `modificacion_atipica` | `modificaciones_credito` | sección | exacta | modificación (definitivo−inicial) inusual frente al **conjunto** del periodo |
| `concentracion_adjudicatarios` | `concentracion_adjudicatarios` | servicio/DG | exacta | HHI alto: un adjudicatario concentra cuota anómala |
| `anticipacion_compromiso` | `compromiso_vs_ejecucion` | servicio | **indiciaria** | compromiso PLACSP alto frente a la ORN: indicio de ejecución por venir |

### `ritmo_ejecucion` (Paso 2)

Método: para cada servicio, **mediana y MAD** de su grado de ejecución en los
mismos meses de años anteriores (banda robusta). Se señala si la desviación
robusta `z = (actual − mediana) / max(1.4826·MAD, piso)` supera `RITMO_Z_MIN`
(=3) **y** el salto en puntos supera `RITMO_GAP_MIN_PP` (=15 pp), con crédito
definitivo ≥ 1 M€. El **suelo de escala** (`RITMO_PISO_PP`=8 pp) evita que una
historia casi constante (MAD≈0) dispare z enormes ante variaciones triviales.
Sobre- y sub-ejecución son ambas señalables.

- **Comparación contra la propia norma**, nunca una media entre servicios
  distintos (no son comparables entre sí).
- **Histórico insuficiente** (< `RITMO_MIN_HIST`=3 mismos-meses) → **SKIPPED**, no
  falsa alarma. Con los datos reales solo noviembre (2016-2018→2020) es evaluable.
- **Prórroga** (2025-P): la norma histórica se construyó con ejercicios no
  prorrogados; la alerta baja a confianza `media` y lo advierte.

### `modificacion_atipica` (Paso 3)

Las modificaciones son **derivadas** (definitivo − inicial; el Anexo I no las
publica explícitas). Se señala una sección cuya modificación relativa supera
`MOD_PCT_MIN` (=15%) **y** absoluta `MOD_IMPORTE_MIN` (=100 M€) — materialidades
que, dado que casi todas las secciones modifican ~0% a la vez, la hacen atípica
frente al conjunto. Severidad `destacada` si ≥40% o ≥1.000 M€. Una modificación
grande **puede ser perfectamente legal** (p. ej. un suplemento de crédito); la
alerta la enmarca como "inusual respecto al patrón", con su z robusta de contexto.

### `concentracion_adjudicatarios` (Paso 4)

Sobre el HHI por órgano. Se señala HHI ≥ `CONC_HHI_MIN` (=2.500, estándar de
mercado concentrado) con importe ≥ `CONC_IMPORTE_MIN`. **No interpreta
concentración como amaño** — puede haber un único proveedor legítimo de un
suministro especializado; se describe como patrón a revisar. Propaga la **tasa de
anclaje** del ámbito: si gran parte del importe quedó sin anclar, la confianza
baja a `baja` y lo dice. Un único adjudicatario (estructural) sale `informativa`,
sin sugerir nada.

### `anticipacion_compromiso` (Paso 5)

El **valor de anticipación** del proyecto: el compromiso jurídico precede en meses
a la obligación reconocida. Se señala un servicio cuyo importe adjudicado PLACSP
del ejercicio supera la ORN reconocida (`ratio ≥ ANTIC_RATIO_MIN`=1) con importe
≥ `ANTIC_IMPORTE_MIN` (=5 M€). **INDICIARIA por construcción**: no es identidad
contable (IVA, plurianualidad, contratos que no llegan a ORN). Se exponen **ambas
magnitudes por separado** (`magnitudes.orn_igae_eur`, `magnitudes.adjudicado_placsp_eur`),
nunca solo el ratio; confianza siempre `baja`.

## Informe consolidado

`informe(con, periodo)` produce un dict (y `render_consola` / `a_json`):

- **encabezado de cobertura**: `pct_orn_vigilable_a_nivel_dg` del periodo;
- **resumen**: nº de alertas por severidad y nº de SKIPPED;
- **alertas** ordenadas por severidad (destacadas primero) y ámbito, cada una
  autoexplicativa con sus evidencias;
- apto para lectura directa por el analista y para consumo por la API (Fase 6).

## Volumen razonable (calibración)

Sobre los 8 periodos IGAE reales el motor produce **decenas** de alertas (no
miles): ~2-4 `modificacion_atipica` por periodo (las secciones con mayor swing de
crédito), unas pocas `ritmo_ejecucion` (solo noviembre tiene histórico mismo-mes),
y `concentracion`/`anticipacion` según los datos PLACSP cargados; el resto de
reglas salen **SKIPPED**. Los umbrales se calibraron empíricamente sobre estos
datos para que ni queden inertes (cero señales) ni produzcan una avalancha; el
test `test_volumen_razonable_sobre_8_periodos` fija ese rango (~8–90 alertas) como
salvaguarda de regresión. Los umbrales viven como constantes nombradas al inicio
del módulo: subirlos para silenciar señales legítimas o bajarlos para fabricarlas
sería traicionar el propósito.
