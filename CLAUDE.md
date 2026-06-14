# CLAUDE.md — gasto-estado

> Guía operativa para Claude Code. Léela entera antes de tocar nada.
> Este proyecto monitoriza y audita en qué gasta el dinero el Estado español,
> con el nivel de detalle de **dirección general / servicio presupuestario**,
> a partir de fuentes oficiales actualizadas con la mayor frecuencia posible.

-----

## 1. Objetivo del proyecto

Construir un sistema reproducible que:

1. **Extraiga** datos de ejecución presupuestaria y de gasto del Estado desde fuentes oficiales (IGAE, PGE, PLACSP, BDNS, BOE, Consejo de Ministros).
1. **Normalice** todo a un **modelo de datos unificado y coherente**, articulado sobre la jerarquía orgánica: Ministerio (sección) → Servicio presupuestario → Dirección General (vía DIR3).
1. **Almacene** los datos de forma versionada e inmutable (raw) y analítica (warehouse).
1. **Exponga** una API/capa de datos limpia, lista para ser consumida por **un frontal web claro y dinámico** (fase final).
1. **Se actualice siempre con los últimos datos disponibles** sin intervención manual (GitHub Actions: mensual para IGAE, semanal/diario para el resto).

El usuario (Carlos) es politólogo y consultor; el sistema debe producir, además del dato, **alertas analíticas** (desviaciones de ritmo de ejecución, modificaciones de crédito atípicas, concentración de adjudicatarios).

### No-objetivos (de momento)

- No cubrimos CCAA ni entidades locales en v1 (solo AGE + organismos estatales).
- No mezclamos contabilidad presupuestaria (devengo) con contabilidad nacional (SEC-2010 / déficit): se almacenan por separado y etiquetadas.
- No hacemos scraping de fuentes no oficiales.

-----

## 2. Principios de diseño (no negociables)

- **Idempotencia**: ejecutar dos veces el mismo pipeline produce el mismo estado. Toda carga es upsert por clave natural.
- **Inmutabilidad del raw**: los ficheros originales descargados NUNCA se modifican ni se borran. Se guardan tal cual con su fecha de captura.
- **Reproducibilidad total**: cualquiera debe poder clonar el repo y reconstruir el warehouse desde cero con un comando.
- **Versionado del dato**: el historial de git es parte del producto (patrón *git-scraping*). Cada actualización es un commit; las revisiones silenciosas de la IGAE quedan registradas en el diff.
- **Fail loud**: si una validación de coherencia contable falla, el pipeline se detiene y avisa. Nunca se cargan datos que no cuadran.
- **Parsers por época (“vintage”)**: los Excel oficiales cambian de maquetación entre ejercicios. No hay un parser único; hay una familia de parsers con detección de formato y tests de regresión.
- **Separación estricta de capas**: extracción ≠ parseo ≠ transformación ≠ carga ≠ exposición. Ningún módulo cruza responsabilidades.
- **El crosswalk orgánico es el activo central**: `servicio_presupuestario ↔ DIR3 ↔ órgano de contratación ↔ órgano concedente`. Toda fuente se ancla a la dimensión orgánica.

-----

## 3. Modelo conceptual de datos

### Jerarquía orgánica (espina dorsal)

```
Sección (2 díg.)         → Ministerio
  Servicio (2 díg.)      → Secretaría de Estado / Dirección General / unidad
    [DIR3]               → código real de unidad orgánica (crosswalk)
```

La correspondencia servicio↔DG **no es 1:1** y **cambia con cada remodelación ministerial**, por eso toda dimensión orgánica usa **vigencia temporal (SCD tipo 2)**: `fecha_inicio`, `fecha_fin`.

### Clasificaciones presupuestarias

- **Orgánica**: sección + servicio.
- **Por programas**: área de gasto → política → grupo de programas → programa.
- **Económica**: capítulo → artículo → concepto → subconcepto.

### Las tres velocidades sobre la misma espina orgánica

1. **Contable oficial** (mensual, IGAE): créditos, comprometido, ORN (obligaciones reconocidas netas), pagos. → métrica reina: `% ejecución = ORN / crédito definitivo`.
1. **Compromisos jurídicos** (diaria, PLACSP/BDNS): adjudicaciones y concesiones. Anticipan la ORN.
1. **Decisiones políticas** (semanal, Consejo de Ministros / BOE): gasto autorizado, modificaciones de crédito, créditos extraordinarios.

### Distinciones contables que NO se deben mezclar

- Crédito inicial **legal** vs **operativo** (relevante en años de prórroga presupuestaria).
- Caja vs devengo vs contabilidad nacional (SEC-2010).
- Derechos/obligaciones reconocidas ≠ déficit SEC.

-----

## 4. Fuentes de datos

### Núcleo mensual (verdad contable) — IGAE

Página índice: `https://www.igae.pap.hacienda.gob.es/sitios/igae/es-ES/Contabilidad/ContabilidadPublica/CPE/EjecucionPresupuestaria/Paginas/EjecucionPresupuestaria.aspx`

- **Ejecución del Presupuesto. AGE** → PDF + XLSX (“Cuadros”, “Anexo I”, “Anexo II”). **Anexo I = gasto por orgánica/programa/económica** (pieza clave).
  - Patrón de URL (verificar siempre, cambia ligeramente): `.../Documents/MENSUAL%20<MES>%20<AÑO>%20ANEXO%20I.xlsx`
  - Periodicidad: mensual, ~25–30 días tras cierre de mes. Histórico desde 2003.
- **Extracto de ejecución** y **Avance comentado de pagos**: síntesis mensual.
- **Ejecución del Presupuesto. Organismos**: OOAA y otros organismos.
- **Contabilidad Nacional / CIGAE**: déficit SEC-2010, mensual (serie SEPARADA).
- **Informes PMP / Registro Contable de Facturas**: plazos de pago por ministerio, mensual XLSX.

### PGE inicial

- SEPG / datos.gob.es: créditos iniciales al máximo detalle, CSV, anual (o prórroga).

### Capa de alta frecuencia

- **PLACSP datos abiertos** (`contrataciondelsectorpublico.gob.es/wps/portal/DatosAbiertos`): ATOM/XML CODICE. Actualización **diaria**. ZIP por año (desde 2012) o por mes del año en curso. Tres datasets: perfiles propios, agregación CCAA, contratos menores. Paginación: seguir `atom:link@rel="next"`; cada fichero tiene máx. 500 entradas. Sindicación 643 = licitaciones perfil PLACSP sin contratos menores.
- **BDNS / infosubvenciones.es (SNPSAP)**: API REST, convocatorias y concesiones, órgano concedente a nivel DG. Diaria.
- **BOE**: API XML del sumario diario. Modificaciones de crédito, RD de concesión de créditos, convocatorias. Diaria.
- **Consejo de Ministros** (`lamoncloa.gob.es`): HTML estructurado, semanal (martes). Acuerdos de autorización de gasto, transferencias de crédito, convenios.

### Dimensiones de referencia

- **DIR3** (Directorio Común de Unidades Orgánicas): CSV en datos.gob.es, actualización continua. Árbol ministerio → secretaría de Estado → DG con códigos únicos.
- **INVENTE** (Inventario de Entes del Sector Público estatal): perímetro de entidades.

> Cuando una URL o patrón no esté confirmado en el código, **verifícalo con una petición real antes de codificar el parser**. No asumas formatos.

-----

## 5. Arquitectura del repositorio

```
gasto-estado/
├── CLAUDE.md                      # este archivo
├── README.md
├── pyproject.toml                 # gestión con uv; deps fijadas
├── config/
│   ├── sources.yaml               # URLs, patrones, periodicidad por fuente
│   └── settings.py                # rutas, constantes, perímetro
├── src/gasto_estado/
│   ├── extractors/                # SOLO descarga. Un módulo por fuente.
│   │   ├── base.py                # interfaz común (fetch, reintentos, caché raw)
│   │   ├── igae_mensual.py
│   │   ├── placsp_atom.py
│   │   ├── bdns_api.py
│   │   ├── consejo_ministros.py
│   │   ├── boe_sumario.py
│   │   └── dir3.py
│   ├── parsers/                   # SOLO raw → DataFrame canónico.
│   │   ├── igae/                  # un parser por vintage de formato
│   │   │   ├── detect.py          # detección de época/maquetación
│   │   │   ├── v2021_plus.py
│   │   │   └── v2015_2020.py
│   │   ├── placsp.py
│   │   └── schemas.py             # esquemas pandera (validación de entrada)
│   ├── transform/
│   │   ├── normalize.py           # a modelo canónico
│   │   └── crosswalks/            # servicio↔DIR3, mapeos históricos de secciones
│   ├── db/
│   │   ├── modelo.sql             # DDL del warehouse
│   │   ├── load.py                # upserts idempotentes
│   │   └── seeds/                 # dim_organica, dim_programa, dim_economica
│   ├── quality/                   # tests de coherencia CONTABLE (no unit tests)
│   │   └── checks.py
│   ├── analytics/                 # métricas y alertas
│   │   ├── metrics.py             # % ejecución, ritmo, comparativas interanuales
│   │   └── alerts.py              # desviaciones, modificaciones atípicas, concentración
│   ├── api/                       # capa de exposición para el frontal (FASE final)
│   │   └── app.py                 # FastAPI: endpoints limpios y documentados
│   └── cli.py                     # punto de entrada: typer
├── data/
│   ├── raw/                       # INMUTABLE. <fuente>/<fecha_captura>/<fichero>
│   └── warehouse.duckdb           # almacén analítico (o parquet particionado)
├── tests/
│   ├── fixtures/                  # ficheros reales de muestra (pocos, pequeños)
│   └── test_parsers_regresion.py
├── dashboards/                    # prototipo interno (Streamlit/Datasette) hasta el frontal
└── .github/workflows/
    ├── monthly.yml                # sondea IGAE entre día 20–31
    └── weekly.yml                 # PLACSP, BDNS, BOE, CdM (lunes)
```

-----

## 6. Stack tecnológico

- **Python 3.12**, gestión de entorno y deps con **uv**.
- Descargas: `httpx` + `tenacity` (reintentos con backoff).
- Excel: `openpyxl` + `pandas`. XML/ATOM: `lxml`.
- Validación: `pandera`.
- Almacén analítico: **DuckDB + Parquet** (autocontenido, reproducible, columnar). Postgres solo si/ cuando el frontal lo requiera (export desde DuckDB).
- API: **FastAPI** (la fase final genera el contrato que consumirá el frontal web).
- CLI: **typer** (`gasto-estado <comando>`).
- Calidad de código: `ruff` (lint+format), `mypy` (tipado), `pytest`.
- CI/CD: GitHub Actions (git-scraping: descarga → parse → validate → commit del dato).

### Comandos canónicos (mantener actualizados)

```bash
uv sync                              # instalar entorno
uv run gasto-estado extract --source igae --latest    # descargar último dato disponible
uv run gasto-estado build                              # reconstruir warehouse desde raw
uv run gasto-estado update                             # extract incremental + load + checks
uv run gasto-estado check                              # validaciones de coherencia contable
uv run gasto-estado api                                # levantar API local
uv run pytest                                          # tests + regresión de parsers
uv run ruff check . && uv run mypy src/                # calidad
```

-----

## 7. Reglas de coherencia contable (validaciones obligatorias)

Toda carga DEBE pasar estos checks (en `quality/checks.py`). Si fallan: parar y avisar.

1. Σ(servicios) de una sección == total de la sección.
1. Σ(secciones) == total AGE.
1. ORN ≤ crédito definitivo, en cada nivel.
1. Crédito definitivo == crédito inicial + modificaciones netas.
1. Pagos ≤ ORN.
1. No hay servicios/secciones huérfanos sin entrada en `dim_organica` vigente para esa fecha.
1. Los importes son no negativos donde corresponde; las modificaciones pueden ser negativas.
1. Continuidad temporal: el dato de un mes no contradice acumulados ya cargados (salvo revisión oficial documentada en el diff).

-----

## 8. Convenciones

- **Idioma**: código, nombres de tablas/columnas y commits en **inglés**; denominaciones oficiales y comentarios de dominio en **español** (es la fuente). Documentación de cara a usuario en español.
- **Commits**: Conventional Commits. Los commits de datos automáticos: `data(igae): add execution 2026-05` etc.
- **Nombres de columnas canónicas**: `seccion_cod`, `servicio_cod`, `dir3_cod`, `programa_cod`, `economica_cod`, `credito_inicial`, `credito_definitivo`, `modificaciones`, `comprometido`, `orn`, `pagos`, `periodo` (YYYY-MM), `fuente`, `fecha_captura`.
- **Fechas**: ISO-8601. Períodos presupuestarios como `YYYY-MM`.
- **Importes**: euros, enteros en céntimos NO; usar `Decimal`/float64 con 2 decimales y documentar. Nunca redondear antes de validar.
- **No secrets en el repo**: claves de API (si las hubiera) en variables de entorno / GitHub Secrets.

-----

## 9. Flujo de trabajo para Claude Code

- Antes de implementar un parser de una fuente nueva: **descargar un fichero real**, inspeccionar su estructura, guardar una muestra en `tests/fixtures/`, y solo entonces escribir el parser + su test de regresión.
- Cualquier cambio en el modelo de datos se refleja a la vez en: `modelo.sql`, `schemas.py`, `normalize.py` y los tests.
- No introducir una dependencia nueva sin justificarla en el PR/commit.
- Cuando un formato oficial cambie, **añadir un nuevo parser de vintage**, no modificar el existente (los datos históricos deben seguir parseándose igual).
- Cada fase termina con: tests en verde, `ruff`/`mypy` limpios, y un comando CLI que demuestra el resultado.
- Pensar siempre en el consumidor final: el frontal web. Los datos expuestos por la API deben ser autoexplicativos, con metadatos de frescura (`ultima_actualizacion`, `fuente`, `periodo_cubierto`).

-----

## 10. Estado del proyecto

> Actualizar esta sección al cerrar cada fase.

- [x] Fase 0 — Andamiaje del repo
- [x] Fase 1 — Dimensiones orgánicas y crosswalk DIR3
- [x] Fase 2 — Extractor + parser IGAE mensual (Anexo I)
- [x] Fase 3 — Warehouse, carga idempotente y validaciones contables
- [x] Fase 4 — Capa de alta frecuencia (PLACSP, BDNS, BOE, CdM)
- [x] Fase 5 — Métricas y alertas analíticas
- [x] Fase 6 — API de exposición (FastAPI) para el frontal
- [ ] Fase 7 — Automatización CI/CD (git-scraping mensual + semanal)
- [ ] Fase 8 — Prototipo de dashboard y contrato de datos para el frontal web
