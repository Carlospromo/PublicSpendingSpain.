# gasto-estado

**Plataforma de inteligencia presupuestaria** para la monitorización y auditoría del gasto
del Estado español, con detalle de **dirección general / servicio presupuestario**, a partir
de seis fuentes oficiales (IGAE, PLACSP, BDNS, BOE, Consejo de Ministros, DIR3).

El sistema:

1. **Extrae** datos de ejecución presupuestaria y gasto desde fuentes oficiales.
2. **Normaliza** todo a un modelo de datos unificado sobre la jerarquía orgánica:
   Ministerio (sección) → Servicio presupuestario → Dirección General (vía DIR3).
3. **Almacena** de forma versionada e inmutable (raw, patrón *git-scraping*) y analítica
   (warehouse DuckDB).
4. **Expone** una API limpia (FastAPI) + un dashboard Streamlit para análisis inmediato.
5. **Se actualiza solo** sin intervención manual (GitHub Actions: mensual para IGAE,
   semanal para PLACSP/BDNS/BOE/CdM).
6. **Alerta** sobre desviaciones de ritmo de ejecución, modificaciones atípicas y
   concentración de adjudicatarios — con severidad, confianza y evidencias navegables.

> **Perímetro v1:** AGE + organismos estatales. No cubre CCAA ni entidades locales.  
> **Fases 0–8 completadas.** Ver [`CLAUDE.md §10`](CLAUDE.md) para el estado por fase.

---

## Requisitos

- [uv](https://docs.astral.sh/uv/) (gestiona el entorno y descarga Python 3.12
  automáticamente si no está instalado)

```bash
git clone <url-del-repo>
cd gasto-estado
uv sync              # instala dependencias del proyecto
uv sync --group dev  # + herramientas de calidad (ruff, mypy, pytest)
uv sync --group dashboard  # + streamlit y plotly para el dashboard
```

---

## Arranque rápido

### 1. Reconstruir el warehouse desde raw

```bash
uv run gasto-estado build
```

Reconstituye el warehouse DuckDB desde la capa raw. Reproducible: cualquiera puede
clonar el repo y ejecutar este comando para obtener el mismo warehouse.

### 2. Levantar la API

```bash
uv run gasto-estado api --port 8000
```

API de solo lectura en `http://127.0.0.1:8000`. Documentación interactiva en `/docs`.

### 3. Levantar el dashboard (en otra terminal)

```bash
uv run streamlit run dashboards/app.py
```

Dashboard Streamlit en `http://localhost:8501`. Requiere la API en ejecución.

---

## Comandos canónicos

```bash
# Extracción e integración
uv run gasto-estado extract --source igae --latest  # descargar último dato IGAE
uv run gasto-estado build                           # reconstruir warehouse desde raw
uv run gasto-estado update                          # extract incremental + load + checks
uv run gasto-estado check                           # validaciones de coherencia contable

# API y dashboard
uv run gasto-estado api --port 8000                 # FastAPI de solo lectura
uv run streamlit run dashboards/app.py              # dashboard (requiere API)

# Orquestación (Dagster)
uv run gasto-estado materialize mensual             # materializar grupo mensual (IGAE)
uv run gasto-estado materialize alta_frecuencia     # materializar alta frecuencia

# Calidad
uv run pytest                                       # 306 tests
uv run ruff check src/ && uv run mypy src/          # lint + tipado
```

---

## Las tres velocidades del dato

El sistema integra tres velocidades de información sobre la misma espina orgánica:

| Velocidad | Fuentes | Cadencia | Naturaleza |
|-----------|---------|----------|------------|
| **Contable** | IGAE Anexo I | Mensual | Exacta — aritmética sobre contabilidad oficial |
| **Compromisos** | PLACSP, BDNS | Semanal (CI) | Exacta — adjudicaciones y concesiones |
| **Decisiones** | BOE, Consejo de Ministros | Semanal (CI) | Aproximada — extracción de texto |

Los **cruces entre velocidades** (compromiso vs ORN, decisión vs adjudicación) son
**indiciarios**: no son identidades contables, incluyen IVA, plurianualidad y contratos
que no siempre llegan a ORN. El dashboard y la API los etiquetan explícitamente.

---

## Dashboard: vistas disponibles

| Página | Qué muestra |
|--------|-------------|
| **📊 Ejecución presupuestaria** | Grado de ejecución AGE, tabla ministerios, drill-down a servicios (≈DG), ritmo mensual, interanual, modificaciones |
| **📋 Compromisos jurídicos** | Adjudicaciones PLACSP + concesiones BDNS por ministerio/DG; HHI de concentración |
| **📜 Decisiones políticas** | Acuerdos CdM y disposiciones BOE con importes desglosados por confianza |
| **🔗 Cruces entre velocidades** | Compromiso vs ORN y decisiones vs adjudicación (indiciarios, ambas magnitudes siempre por separado) |
| **🚨 Alertas analíticas** | Informe con evidencias navegables: pinchar alerta → ver aplicaciones/contratos concretos → URL oficial |
| **⚙️ Estado del sistema** | Frescura por fuente, salud del warehouse, cadencia CI |

Los metadatos de fiabilidad (naturaleza, cobertura de anclaje, advertencias) son
visibles en cada vista — no ocultos en tooltips inaccessibles.

---

## API v1 — contrato estable

```
GET /v1/salud                                          # estado del warehouse
GET /v1/frescura                                       # frescura por fuente
GET /v1/estructura/ejercicios                          # años disponibles
GET /v1/estructura/secciones?ejercicio=2026            # ministerios
GET /v1/estructura/secciones/{sec}/servicios?ejercicio # servicios ≈ DGs
GET /v1/ejecucion/grado?periodo=2026-04&nivel=seccion  # grado ejecución
GET /v1/ejecucion/ritmo?ejercicio=2026                 # serie mensual
GET /v1/ejecucion/interanual?periodo=2026-04           # comparativa año anterior
GET /v1/ejecucion/modificaciones?periodo=2026-04       # modificaciones de crédito
GET /v1/contratos/volumen?ejercicio=2026               # adjudicaciones PLACSP
GET /v1/subvenciones/volumen?ejercicio=2026            # concesiones BDNS
GET /v1/contratos/concentracion?ejercicio=2026         # HHI por órgano
GET /v1/decisiones/boe/volumen?ejercicio=2026          # disposiciones BOE
GET /v1/decisiones/cdm/volumen?ejercicio=2026          # acuerdos CdM
GET /v1/cruces/compromiso-ejecucion?periodo=2026-04    # PLACSP vs ORN (indiciario)
GET /v1/cruces/decisiones-compromiso?ejercicio=2026    # CdM vs PLACSP (indiciario)
GET /v1/alertas/informe?periodo=2026-04                # informe consolidado de alertas
GET /v1/alertas?periodo=2026-04&severidad=destacada    # alertas filtrables
```

Toda respuesta envuelta en `{data, meta}`. Los metadatos de fiabilidad
(`naturaleza`, `cobertura_anclaje`, `advertencias`, `frescura`) son ciudadanos de
primera clase del esquema. Contrato completo: [`docs/API.md`](docs/API.md).

---

## Estructura del repositorio

```
gasto-estado/
├── CLAUDE.md                      # guía operativa del proyecto
├── README.md                      # este archivo
├── pyproject.toml                 # dependencias con uv
├── config/
│   ├── sources.yaml               # catálogo de fuentes (URLs, periodicidad)
│   └── settings.py                # rutas y constantes
├── src/gasto_estado/
│   ├── extractors/                # descarga por fuente
│   ├── parsers/                   # raw → DataFrame (con centinela de formato)
│   ├── transform/                 # normalización y crosswalks
│   ├── db/                        # DDL, carga idempotente, seeds
│   ├── quality/                   # validaciones contables (fail loud)
│   ├── analytics/                 # métricas y alertas
│   ├── api/                       # FastAPI (capa de exposición)
│   ├── orchestration/             # Dagster assets + notificaciones + centinela
│   └── cli.py                     # punto de entrada CLI
├── dashboards/
│   ├── app.py                     # dashboard Streamlit (punto de entrada)
│   ├── api_client.py              # cliente HTTP para la API v1
│   ├── components.py              # componentes UI compartidos
│   └── pages/                     # vistas multi-página
├── data/
│   ├── raw/                       # capa raw INMUTABLE
│   └── warehouse.duckdb           # almacén analítico
├── tests/                         # 306 tests + fixtures
├── docs/                          # documentación técnica y de dominio
│   ├── API.md                     # contrato v1 completo
│   ├── modelo_datos.md            # modelo conceptual
│   ├── metricas.md                # catálogo de métricas
│   ├── alertas.md                 # catálogo de alertas
│   ├── cobertura_fuentes.md       # cobertura y limitaciones por fuente
│   ├── orquestacion.md            # diseño de Dagster + resiliencia operativa
│   └── dashboard_hallazgos.md     # huecos del contrato v1 (especificación para v2)
└── .github/workflows/
    ├── monthly.yml                # IGAE: sondeo días 20-31 de cada mes
    ├── weekly.yml                 # PLACSP, BDNS, BOE, CdM: lunes
    └── health_check.yml           # verificación de URLs: domingo
```

---

## Mapa de documentación

| Documento | Para quién |
|-----------|-----------|
| [`CLAUDE.md`](CLAUDE.md) | Guía operativa completa (modelo de datos, fuentes, arquitectura, convenciones) |
| [`docs/API.md`](docs/API.md) | Contrato v1 de la API — autosuficiente para construir el frontal sin leer el backend |
| [`docs/modelo_datos.md`](docs/modelo_datos.md) | Esquema del warehouse (tablas, columnas, relaciones) |
| [`docs/metricas.md`](docs/metricas.md) | Catálogo de métricas y su naturaleza |
| [`docs/alertas.md`](docs/alertas.md) | Catálogo de alertas, umbrales y calibración |
| [`docs/cobertura_fuentes.md`](docs/cobertura_fuentes.md) | Cobertura y limitaciones por fuente y nivel orgánico |
| [`docs/orquestacion.md`](docs/orquestacion.md) | Diseño de Dagster, resiliencia operativa (centinela, notificaciones, health check) |
| [`docs/dashboard_hallazgos.md`](docs/dashboard_hallazgos.md) | Huecos del contrato v1 detectados al construir el dashboard (especificación para v2) |

---

## Honestidad como principio de diseño

Este sistema **no esconde la calidad del dato**. Toda cifra viaja con:

- **Naturaleza**: `exacta` (aritmética sobre contabilidad auditada), `aproximada`
  (extracción de texto con NLP), o `indiciaria` (cruce entre velocidades, no
  identidad contable).
- **Cobertura de anclaje**: qué fracción del importe/gasto se ha podido atribuir
  a un servicio o dirección general (~27% de la ORN tiene anclaje DIR3).
- **Advertencias** explícitas para prórroga presupuestaria, comparativas
  inter-ejercicio y aproximaciones DG.

Las alertas son **hipótesis para revisión humana**, nunca veredictos. El lenguaje
es siempre descriptivo, nunca acusatorio.
