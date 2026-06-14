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
4. La ejecución termina; el runner guarda cambios en `data/` y hace commit/push.

No hay daemon, no hay servicio de metadatos, no hay infraestructura adicional.

## Dos caminos de materialización

El sistema mantiene dos caminos que conviven:

### 1. `gasto-estado build` (reproducibilidad total)

Reconstruye el warehouse completo desde la capa raw + seeds. Sin Dagster. Cualquiera puede clonar el repo y ejecutar `uv run gasto-estado build` para obtener el mismo warehouse.

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
