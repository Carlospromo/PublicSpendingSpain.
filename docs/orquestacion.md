# Orquestación con Dagster (Fase 7)

## Diseño general

El pipeline de datos tiene **tres velocidades** sobre la misma espina orgánica (CLAUDE.md §3):

| Velocidad | Fuentes | Cadencia |
|-----------|---------|----------|
| Contable (mensual) | IGAE Anexo I | ~25-30 días tras cierre de mes |
| Compromisos (diaria) | PLACSP, BDNS | Diaria |
| Decisiones (semanal) | BOE, Consejo de Ministros | Semanal (martes) |

Estas velocidades se reflejan en el grafo de assets de Dagster.

## Grafo de assets

```
seeds_dimensiones ─────────────────────────────────────────────────────┐
crosswalk_servicio_dir3 ──────────────────────────────────────┐        │
                                                              ↓        ↓
                                                   dimensiones (reference layer)
                                                              ↓        ↓        ↓        ↓        ↓
                                               fact_ejecucion  fact_contratos  fact_subvenciones  fact_boe  fact_acuerdos_cdm
                                                    ↓                ↓                ↓
                                           validacion_contable       └───────────────────────────────┐
                                                    ↓                                                ↓
                                                    └──────────────── frescura_publicada ────────────┘
```

### Grupos y particiones

- **`seeds_dimensiones`** y **`crosswalk_servicio_dir3`**: fuentes observables (*observable source assets*). Su versión de datos es el hash del fichero en `db/seeds/`. Si el fichero cambia, Dagster marca los assets aguas abajo como obsoletos (*stale*).

- **`dimensiones`**: carga el esquema + seeds (dim_organica, dim_seccion_servicio, dim_economica). Sin partición.

- **`fact_ejecucion`**: partición mensual (`MonthlyPartitionsDefinition`, desde 2015-01-01). Clave: `YYYY-MM-01`.

- **`fact_contratos`**, **`fact_subvenciones`**, **`fact_boe`**, **`fact_acuerdos_cdm`**: partición diaria (`DailyPartitionsDefinition`, desde 2012-01-01). Clave: `YYYY-MM-DD`.

- **`validacion_contable`**: gate de calidad contable. Depende de `fact_ejecucion`. Re-ejecuta todos los checks de `quality/checks.py`; falla ruidosamente si alguno es FAIL.

- **`frescura_publicada`**: snapshot del ledger de materialización. Depende de todos los hechos y de la validación. Cierra el grafo.

### Invalidación en cascada

`crosswalk_servicio_dir3` es una fuente observable: su versión de datos = SHA-256 del fichero `db/seeds/crosswalk_servicio_dir3.csv`. `fact_contratos` y `fact_subvenciones` dependen de él (lo usan para el anclaje servicio↔DIR3). Si el crosswalk cambia, Dagster los marca *stale*: el siguiente disparo de CI los re-materializa aunque su partición ya existiera.

`fact_boe` y `fact_acuerdos_cdm` **no** dependen del crosswalk (anclan a sección, no a DIR3).

## Modelo de ejecución

No hay servidor Dagster permanente. El pipeline funciona así:

1. **GitHub Actions** (cron) lanza `gasto-estado materialize <grupo> [--particion ...]`.
2. El CLI invoca `dagster.materialize()` con los assets del grupo y la partición del día.
3. Dagster ejecuta el subgrafo en proceso: descarga → parse → carga → validación → frescura.
4. La ejecución termina; el runner publica cambios permitidos en `data/`, crea
   manifiestos compactos de las capturas y hace commit/push. Las exclusiones de
   `.gitignore` para raw masivo PLACSP/BDNS nunca se fuerzan.

No hay daemon, no hay servicio de metadatos, no hay infraestructura adicional.

## Dos caminos de materialización

El sistema mantiene dos caminos que conviven:

### 1. `gasto-estado build` (transformación reproducible con raw disponible)

Reconstruye el warehouse desde la capa raw disponible + seeds, sin Dagster. Con
el mismo commit, `uv.lock` y las mismas capturas produce el mismo resultado. Un
clon por sí solo no recupera las capturas masivas no versionadas de PLACSP y
BDNS; para una reconstrucción histórica exacta hace falta su copia inmutable y
el manifiesto descrito en `docs/reproducibilidad.md`.

```bash
uv run gasto-estado build   # reconstruye desde raw/
```

### 2. `gasto-estado materialize` (operación incremental/orquestada)

Invoca Dagster para materializar un grupo de assets para una partición concreta. El disparo real es CI (GitHub Actions); también se puede ejecutar manualmente.

```bash
# Grupo mensual (partición = mes en curso por defecto)
uv run gasto-estado materialize mensual

# Grupo mensual con partición explícita
uv run gasto-estado materialize mensual --particion 2026-03-01

# Grupo de alta frecuencia (partición = hoy por defecto)
uv run gasto-estado materialize alta_frecuencia

# Alta frecuencia sin descargar (raw ya en caché)
uv run gasto-estado materialize alta_frecuencia --no-descargar
```

## Ledger de materialización

Cada materialización escribe una entrada en `data/materializacion.json` (junto al warehouse):

```json
{
  "igae_anexo_i": {
    "particion": "2026-04",
    "filas": 10097,
    "materializado_en": "2026-05-28T07:12:34.123456+00:00"
  },
  "placsp": {
    "particion": "2026-06-14",
    "filas": 523,
    "materializado_en": "2026-06-16T06:08:11.000000+00:00"
  }
}
```

La API (`/v1/frescura`) incluye `materializado_en` en cada entrada cuando el ledger existe. Si no existe (camino `gasto-estado build` sin Dagster), el campo es `null`: degradación graceful sin romper el contrato.

Desde Fase 2 el ledger también puede incluir, siempre de forma opcional para
mantener v1, `ultima_captura_disponible`, `ultima_ejecucion_intentada`,
`ultima_ejecucion_correcta`, `particion_cubierta`, `estado_fuente` y
`advertencia_o_error_activo`. El último éxito no se borra cuando falla un intento
posterior; así el frontal puede mostrar simultáneamente cobertura conocida y un
aviso operativo.

## Schedules (cadencia)

Definidos en `definitions.py` y replicados en los workflows de GitHub Actions:

| Schedule | Cron | Grupo |
|----------|------|-------|
| `sonda_igae_mensual` | `0 6 20-31 * *` | mensual |
| `alta_frecuencia_semanal` | `0 5 * * 1` | alta_frecuencia |

La IGAE publica ~25-30 días tras el cierre de mes, con desfase variable. El sondeo diario en la ventana 20-31 garantiza captura sin intervención manual; la extracción idempotente descarta el run sin cambios si el dato aún no está publicado.

## Servidor Dagster opcional

Con `dagster dev -m gasto_estado.orchestration.definitions` se puede levantar la UI de Dagster para inspección y backfill manual. No es necesario para el funcionamiento del pipeline de producción.

## Añadir un nuevo asset

1. Implementar la función pura en `orchestration/pipeline.py`.
2. Envolver con `@asset` en `orchestration/assets.py` (cáscara fina; sin lógica de negocio).
3. Añadirlo al grupo correspondiente en `orchestration/run.py`.
4. Añadirlo a `defs` en `orchestration/definitions.py`.
5. Si es un hecho, añadir una entrada en `analytics/estructura.py::_FRESCURA_FUENTES`.

## Resiliencia operativa

### Fallo parcial

Los assets del grupo de alta frecuencia son independientes entre sí: `fact_contratos`, `fact_subvenciones`, `fact_boe` y `fact_acuerdos_cdm` no dependen unos de otros. Si PLACSP falla pero el resto no:

- Los assets que no dependen de PLACSP completan su materialización normalmente.
- El fallo de PLACSP genera una incidencia notificada (step summary + issue opcional).
- El warehouse sigue disponible con los datos del resto de fuentes.

El grupo mensual tiene un gate: `validacion_contable` depende de `fact_ejecucion`. Si la validación falla, solo queda sin cargar ese periodo; el resto del warehouse sigue disponible con los periodos anteriores.

### Centinela de formato (pre-parser)

Antes de parsear, el centinela (`parsers/format_sentinel.py`) verifica que el fichero descargado tiene la estructura esperada:

- **IGAE**: hojas S5 + SNN, cabeceras de magnitudes, vintage reconocido.
- **PLACSP**: ZIP válido con .atom, namespace CODICE 2.x, entries presentes.
- **BDNS**: JSON con `content`, campos requeridos en cada item.
- **BOE**: XML con estructura sumario/diario o documento/metadatos.
- **CdM**: HTML con bloque SUMARIO, h3 ministerios proponentes.

Si el centinela falla, produce un diagnóstico detallado ("las hojas ahora se llaman Sec01 en vez de S01, investigar posible nuevo vintage") y detiene el pipeline antes del parser. El centinela **nunca auto-repara**: un cambio de formato requiere decisión humana (¿es un nuevo vintage?).

### Notificaciones CI

Cuando una materialización falla, el sistema genera un informe de incidencia visible de dos formas:

1. **Step summary** (`$GITHUB_STEP_SUMMARY`): siempre, sin configuración.
2. **Issue de GitHub** (etiqueta `pipeline-failure`): opt-in con `GASTO_ESTADO_CREAR_ISSUES=1`.

Tipos de incidencia operativos: `fuente_no_disponible`, `formato_cambiado`,
`respuesta_vacia`, `validacion_contable`, `error_carga` y `error_publicacion`.
Cada incidencia incorpora fuente, partición y diagnóstico en el resumen. La
huella de esos tres valores evita abrir dos issues para el mismo fallo mientras
el anterior siga abierto.

Los tres workflows usan `concurrency` por grupo y un resumen uniforme con
fuente, partición/ventana, filas, fecha de captura, commit producido y resultado
de checks. Las actions están fijadas por SHA. Los permisos de escritura de
contenidos se limitan a materializaciones y los de issues a la notificación.

### Monitor de URLs

El workflow `health_check.yml` (domingo 08:00 UTC) verifica semanalmente que las URLs base de `config/sources.yaml` siguen respondiendo. Las fuentes marcadas `requerido: true` generan issue si fallan; las opcionales solo un aviso informativo.

### Revisiones silenciosas de la IGAE

La IGAE revisa a veces un fichero ya publicado sin cambiar la URL. El detector compara el hash del fichero recién descargado con las capturas anteriores del mismo periodo. Si difiere, registra una nota en el ledger y genera una incidencia. **No recarga automáticamente**: una revisión silenciosa puede legítimamente cambiar cifras, y eso debe ser una decisión consciente.

### Reintento y recuperación histórica

Para reintentar sin descargar de nuevo el raw ya conservado, usa una partición
explícita y `--no-descargar`:

```bash
uv run gasto-estado materialize mensual --particion 2026-04-01 --no-descargar
uv run gasto-estado materialize alta_frecuencia --particion 2026-07-17 --no-descargar
```

Para recuperar un estado histórico exacto, localiza el manifiesto en
`data/manifiestos/`, recupera la copia indicada por `ubicacion_inmutable`,
verifica su SHA-256 y usa los commits `commit_codigo` y `commit_warehouse` que
registra. Después reconstruye o re-materializa la partición. Si la copia no está
disponible, no se debe presentar una regeneración desde la fuente viva como una
recuperación histórica exacta.
