# Modelo de datos del warehouse (Fase 3)

> Decisiones de modelado de la capa analítica (DuckDB) y semántica de carga
> idempotente. Las validaciones de coherencia contable globales (CLAUDE.md §7:
> Σ servicios = sección, ORN ≤ definitivo agregado, etc.) están documentadas en
> `docs/validaciones.md` e implementadas en `quality/checks.py`; se ejecutan
> dentro de la transacción de carga y bajo demanda con `gasto-estado check`.

El warehouse es autocontenido y reproducible (CLAUDE.md §2, §6): `gasto-estado
build` lo reconstruye desde cero a partir del `raw/` inmutable + los seeds
versionados, con un único comando.

-----

## 1. Las tres decisiones de modelado (Paso 1)

### a) Naturaleza ACUMULADA del Anexo I de la IGAE

Cada Anexo I mensual es el **acumulado del ejercicio a esa fecha**, no un
incremento del mes. El modelo lo refleja así:

- La granularidad del hecho es **(clave natural de aplicación) × periodo ×
  fuente**, donde `periodo = 'YYYY-MM'` con `YYYY` = ejercicio presupuestario y
  `MM` = mes de referencia del acumulado.
- Cada `(aplicación, periodo)` es **una fila**. Los distintos meses del mismo
  ejercicio conviven como filas distintas con el mismo `ejercicio` y distinto
  `periodo` → esto permite la **serie temporal intra-ejercicio** (evolución mes
  a mes del acumulado).
- **"El último dato disponible"** de un ejercicio es el `periodo` máximo cargado
  para ese `ejercicio`. Se expone como la vista `v_ejecucion_vigente`
  (`max(periodo) per ejercicio`), calculada dinámicamente para que siga siendo
  correcta a medida que se cargan periodos nuevos, sin flags que mantener.

No se restan meses ni se derivan incrementos: el dato se almacena tal cual lo
publica la IGAE (acumulado), que es la magnitud sobre la que se calcula
`% ejecución = ORN / crédito definitivo`.

### b) COBERTURA de magnitudes (qué fuente llena qué)

El Anexo I solo aporta `credito_inicial`, `credito_definitivo` y `orn`. **No**
trae `comprometido` ni `pagos` (llegarán de Cuadros/Anexo II en la Fase 4), ni
`modificaciones` como campo propio. Para representar esto **sin ceros falsos ni
nulos ambiguos**:

1. Todas las columnas de magnitud del hecho son **nullable**. El `'-'` del
   fichero (sin dato) se carga como **NULL**, que es distinto de `0`.
2. La fuente es **parte de la clave natural** del hecho (`fuente_cod`). Cada
   fuente escribe **su propia fila** para una aplicación+periodo, rellenando
   solo las magnitudes que cubre.
3. La columna `cobertura` registra, por fila, qué magnitudes aporta esa fuente
   de forma autoritativa (p. ej. `credito_inicial,credito_definitivo,orn` para
   el Anexo I). Así se distingue un NULL **"no cubierto por esta fuente"** de un
   NULL **"cubierto pero sin dato (`-`)"**.

Consecuencia para la Fase 4: cuando el Anexo II/Cuadros aporte
`comprometido`/`pagos`, se cargará como **filas nuevas** con
`fuente_cod = 'igae_anexo_ii'` y su propia `cobertura`, **sin reescribir** las
filas del Anexo I (CLAUDE.md §2, inmutabilidad de lo ya cargado). La foto
unificada por aplicación se compone en la capa analítica coalesciendo fuentes
por precedencia documentada (no es responsabilidad de esta fase).

### c) IDENTIDAD orgánica a lo largo del tiempo

Las secciones de 2015 (27 secciones) no son las de 2025-P (37): el mismo código
de sección significa ministerios distintos en ejercicios distintos (p. ej. la
sección 27 fue "Asuntos Económicos y Transformación Digital" hasta 2023 y
"Economía, Comercio y Empresa" desde 2024). El modelo:

- Almacena en el hecho el `seccion_cod`/`servicio_cod` **tal como vinieron** en
  cada periodo (fidelidad al origen).
- Ancla cada fila a la dimensión orgánica **vigente en su ejercicio**: la FK
  lógica del hecho a `dim_seccion_servicio` resuelve por `(ejercicio,
  seccion_cod, servicio_cod)`. Una aplicación de 2015 enlaza con la entrada de
  `dim_seccion_servicio` de **ejercicio 2015**, no con la de 2026.

Aquí **no se reconcilian estructuras** (qué sección de 2015 equivale a cuál de
2025): eso vive en `transform/crosswalks/historico_secciones.csv` y es trabajo
de análisis posterior. La Fase 3 solo respeta la vigencia temporal.

-----

## 2. ¿Por qué `dim_seccion_servicio` y no `dim_organica` como ancla?

CLAUDE.md y el plan apuntan a `dim_organica` (árbol DIR3, SCD tipo 2 de la
Fase 1) como dimensión orgánica. Al inspeccionar el seed real:

- `dim_organica` (19.769 filas) tiene `seccion_cod` y `servicio_cod`
  **100 % nulos**: la Fase 1 dejó pendiente el crosswalk presupuesto↔DIR3, así
  que **no puede resolver** la clave orgánica `(seccion, servicio)` de un hecho.
- `dim_seccion_servicio` sí está keyed por `(ejercicio, seccion_cod,
  servicio_cod)` con denominaciones oficiales y la etiqueta de presupuesto
  (`2025-P` = prórroga del PGE 2025).

Por tanto, el **ancla orgánica del hecho es `dim_seccion_servicio`**.
`dim_organica` se carga igualmente (activo de referencia DIR3 para la Fase 8 y
el frontal), pero **no es FK del hecho** mientras su crosswalk siga vacío. El
puente servicio↔DIR3 (parcial, solo 2026) vive en el seed
`crosswalk_servicio_dir3.csv` y se incorporará cuando se complete.

### Resolver-o-derivar, y *fail loud* ante huérfanos

`dim_seccion_servicio` seed solo cubre el ejercicio 2026, y **ni siquiera ahí
es exhaustivo**: la ejecución usa servicios que no están en el PGE inicial
(p. ej. servicio `50` = Mecanismo de Recuperación y Resiliencia / Next
Generation EU). Exigir match estricto contra el seed rompería la carga de datos
válidos. La carga, por tanto (Paso 4, "resolviendo o creando entradas
dimensionales"):

1. **Resuelve** `(ejercicio, seccion, servicio)` contra el seed (autoritativo,
   `origen = 'seed_pge'`).
2. Si falta, **deriva** la entrada desde el propio Anexo I (que sí trae
   `servicio_denominacion`), con `origen = 'derivado_igae'`. Así los ejercicios
   históricos (2015–2020), sin seed, obtienen su dimensión vigente.
3. **Fail loud** (sin huérfanos silenciosos): si no hay match en el seed **y**
   no hay `servicio_denominacion` para derivar una entrada nominada, la carga se
   detiene (`OrphanOrganicError`). No se escribe nunca un hecho con ancla
   orgánica colgante o sin nombre.

Las entradas derivadas dejan `seccion_denominacion` y `presupuesto` a NULL (el
Anexo I no trae el nombre de la sección): es honesto y queda marcado por
`origen`.

-----

## 3. ¿Hecho unificado o crédito/ejecución separados?

**Unificado: un solo `fact_ejecucion`.** Crédito (inicial/definitivo) y
ejecución (ORN, y más adelante comprometido/pagos) comparten **el mismo grano**
(la aplicación presupuestaria) y **la misma espina orgánica**. Separarlos
duplicaría la clave natural y obligaría a un join para la métrica reina
`% ejecución = ORN / crédito definitivo`, que necesita ambas en la misma fila.
La cobertura por fuente (§1b) ya resuelve el "una fuente llena unas magnitudes y
no otras" sin separar tablas.

Las **tres velocidades** de CLAUDE.md §3 conviven así:

- *Contable* (IGAE, mensual) → `fact_ejecucion` (esta fase).
- *Compromisos jurídicos* (PLACSP/BDNS, diaria) → `fact_contratos`,
  `fact_subvenciones`: **grano distinto** (contrato/concesión, no aplicación) →
  tablas propias en la Fase 4.
- *Decisiones políticas* (CdM/BOE, semanal) → `fact_acuerdos_cdm`: Fase 4.

Los hechos de Fase 4 se **documentan aquí** pero **no se crean** todavía: su
esquema depende de inspeccionar las fuentes reales (principio de CLAUDE.md §9:
descargar y mirar antes de modelar). `dim_fuente` ya reserva sus códigos y fija
el contrato de las tres velocidades.

-----

## 4. Catálogo de tablas

### Dimensiones

| Tabla | Clave | Notas |
|---|---|---|
| `dim_periodo` | `periodo` (YYYY-MM) | `ejercicio`, `mes`, `presupuesto` (etiqueta; NULL si no asertada para el ejercicio), `fecha_fin_mes`. |
| `dim_seccion_servicio` | `(ejercicio, seccion_cod, servicio_cod)` | SCD por ejercicio. `origen ∈ {seed_pge, derivado_igae}`. **Ancla orgánica del hecho.** |
| `dim_organica` | — (SCD2 DIR3) | Árbol DIR3 con vigencia `fecha_inicio`/`fecha_fin`. Referencia; no FK del hecho (seccion/servicio nulos). |
| `dim_programa` | `programa_cod` | Jerarquía área(1)→política(2)→grupo(3)→programa(4) derivada del código. `denominacion` NULL (el Anexo I no nombra programas). |
| `dim_economica` | `economica_cod` | `nivel ∈ {capitulo,articulo,concepto,subconcepto,partida}` por longitud (1/2/3/5/7). Ancestros sintetizados. `denominacion` derivada (modal) de `aplicacion_denominacion`. |
| `dim_fuente` | `fuente_cod` | Las tres velocidades (§3). Reserva los códigos de Fase 4. |

### Hechos

| Tabla | Grano | Estado |
|---|---|---|
| `fact_ejecucion` | aplicación × periodo × fuente | **Poblado** (IGAE Anexo I). |
| `fact_contratos` | contrato (PLACSP) | Fase 4 (no creado). |
| `fact_subvenciones` | concesión (BDNS) | Fase 4 (no creado). |
| `fact_acuerdos_cdm` | acuerdo (CdM/BOE) | Fase 4 (no creado). |

### `fact_ejecucion` — clave natural y columnas

Clave natural (PRIMARY KEY):
`(periodo, fuente_cod, seccion_cod, servicio_cod, programa_cod, economica_cod, provincia_cod)`.

- `provincia_cod` es **no-nulo** con dominio = provincias/agregados oficiales
  (01–99), `'DT'` (Diversos Territorios) y `'NT'` (No Territorializado = el
  nulo del parser, cuando la aplicación no tiene desglose territorial). Hacerlo
  no-nulo evita NULL en la clave (DuckDB trata cada NULL como distinto, lo que
  rompería la idempotencia) y materializa "no territorializado" como el valor
  categórico explícito que pide el dominio.
- Magnitudes (`credito_inicial`, `credito_definitivo`, `modificaciones`,
  `comprometido`, `orn`, `pagos`): todas `DOUBLE` nullable. El Anexo I rellena
  `credito_inicial`, `credito_definitivo`, `orn`; el resto NULL (no cubierto).
- `cobertura`: magnitudes que la fuente de esa fila aporta (§1b).
- `aplicacion_denominacion`, `fecha_captura`, `ejercicio` (denormalizado desde
  `periodo` para el join orgánico y el filtrado).

### Vistas

- `v_ejecucion`: hecho + dimensiones (periodo, seccion_servicio, programa,
  economica) desnormalizado, con `pct_ejecucion = orn / credito_definitivo`,
  listo para el frontal.
- `v_ejecucion_vigente`: subconjunto de `v_ejecucion` con el `periodo` máximo
  por `ejercicio` ("último dato disponible").

-----

## 5. Carga idempotente (Paso 4)

**Reemplazo de partición por `(periodo, fuente_cod)`**: `load_periodo` borra la
partición y reinserta el conjunto recién parseado. Propiedades:

- **Idempotente**: recargar el mismo periodo deja el warehouse idéntico (mismo
  conteo, mismo contenido).
- **Revisión IGAE**: recargar un periodo con datos corregidos **actualiza** esas
  filas (y elimina las aplicaciones que la revisión hubiera retirado), dejando
  rastro en el versionado git del dato.
- **Periodo nuevo**: se añade sin tocar los demás.

Las dimensiones se pueblan con `INSERT OR IGNORE` (programa, económica) o
resolución-o-derivación (seccion_servicio); nunca se borran. Las denominaciones
derivadas de la económica se recalculan al final del lote como función
determinista de los hechos cargados (modal de `aplicacion_denominacion`, con
desempate lexicográfico) → **reproducibilidad** independiente del orden.

### `build` vs `update`

- `gasto-estado build`: recrea el fichero DuckDB desde cero, carga seeds y
  **todos** los periodos disponibles en `raw/`, en orden ascendente. Reproduce
  el warehouse íntegro (CLAUDE.md §2). Tiempo aproximado con los 8 periodos
  actuales (~58k filas de hecho): **~2–4 s** en este entorno.
- `gasto-estado update`: carga **incremental** de los periodos presentes en
  `raw/` aún no cargados (si el fichero no existe, equivale a `build`). Ambos
  idempotentes.

-----

## 6. Reproducibilidad y determinismo

- Las dimensiones derivadas (programa, económica) son función del **conjunto**
  de hechos, no del orden de carga.
- Las entradas derivadas de `dim_seccion_servicio` se crean en el primer periodo
  (orden ascendente garantizado) que las introduce; dentro de un ejercicio la
  `servicio_denominacion` es estable entre meses.
- `build` ejecutado dos veces produce un warehouse con los mismos conteos y
  contenido por tabla (la `fecha_captura` se fija en la carga; el resto del
  contenido es función pura del `raw/` + seeds).
