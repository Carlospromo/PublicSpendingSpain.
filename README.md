# gasto-estado

Sistema reproducible de **monitorización y auditoría del gasto del Estado español**,
con detalle de **dirección general / servicio presupuestario**, a partir de fuentes
oficiales (IGAE, PGE, PLACSP, BDNS, BOE, Consejo de Ministros, DIR3).

El proyecto:

1. **Extrae** datos de ejecución presupuestaria y gasto desde fuentes oficiales.
2. **Normaliza** todo a un modelo de datos unificado sobre la jerarquía orgánica:
   Ministerio (sección) → Servicio presupuestario → Dirección General (vía DIR3).
3. **Almacena** los datos de forma versionada e inmutable (raw, patrón *git-scraping*)
   y analítica (warehouse DuckDB + Parquet).
4. **Expone** una API limpia (FastAPI) para un frontal web claro y dinámico.
5. **Se actualiza solo** con los últimos datos disponibles (GitHub Actions).

Además del dato, produce **alertas analíticas**: desviaciones de ritmo de ejecución,
modificaciones de crédito atípicas y concentración de adjudicatarios.

> Perímetro v1: AGE + organismos estatales. No cubre CCAA ni entidades locales.
> La guía operativa completa (modelo de datos, fuentes, reglas contables) está en
> [`CLAUDE.md`](CLAUDE.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (gestiona el entorno y descarga Python 3.12
  automáticamente si no está instalado).

## Instalación

```bash
git clone <url-del-repo>
cd gasto-estado
uv sync
```

## Comandos canónicos

```bash
uv run gasto-estado extract --source igae --latest    # descargar último dato disponible
uv run gasto-estado build                              # reconstruir warehouse desde raw
uv run gasto-estado update                             # extract incremental + load + checks
uv run gasto-estado check                              # validaciones de coherencia contable
uv run gasto-estado api                                # levantar API local
uv run pytest                                          # tests + regresión de parsers
uv run ruff check . && uv run mypy src/                # calidad
```

> **Estado actual: Fases 0–4 completas.** Las tres velocidades de datos están
> operativas (contable IGAE; compromisos PLACSP+BDNS; decisiones políticas
> BOE+Consejo de Ministros) sobre la espina orgánica común, con carga idempotente
> y validaciones contables. `extract`, `build`, `update` y `check` son
> funcionales; `api` (Fase 6) sigue siendo un stub. El detalle de cobertura,
> profundidad de anclaje y limitaciones por fuente está en
> [`docs/cobertura_fuentes.md`](docs/cobertura_fuentes.md); el estado por fase, en
> [`CLAUDE.md`](CLAUDE.md) §10.

## Estructura del repositorio

```
config/            # sources.yaml (catálogo de fuentes) y settings.py
src/gasto_estado/  # extractors / parsers / transform / db / quality / analytics / api / cli
data/raw/          # capa raw INMUTABLE: <fuente>/<fecha_captura>/<fichero>
tests/             # tests + fixtures reales de muestra
dashboards/        # prototipo interno hasta el frontal web
.github/workflows/ # automatización mensual (IGAE) y semanal (alta frecuencia)
```
