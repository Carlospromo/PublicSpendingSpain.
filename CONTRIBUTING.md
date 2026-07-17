# Contribuir a gasto-estado

Gracias por contribuir. El proyecto mantiene una separación estricta entre
extracción, parseo, transformación, carga y exposición; conserva esa separación
al proponer cambios.

## Preparar el entorno

Se necesita [uv](https://docs.astral.sh/uv/) y Python 3.12. Desde la raíz:

```bash
uv sync --group dev
```

Para trabajar en el dashboard, añade el grupo correspondiente:

```bash
uv sync --group dashboard
```

## Verificaciones obligatorias

Antes de abrir un pull request, ejecuta:

```bash
uv run pytest
uv run ruff check src/ tests/
uv run mypy src/
```

El CI ejecuta estas mismas comprobaciones en cada `push` y pull request contra
`main`.

## Pull requests

- Crea una rama con un objetivo acotado y describe el problema, la solución y
  cómo la verificaste.
- Mantén los commits con el formato Conventional Commits.
- No mezcles refactorizaciones no relacionadas con cambios de dominio o datos.
- Los cambios de modelo de datos deben actualizar esquema, normalización y tests
  relacionados, según `CLAUDE.md`.

## Datos y fixtures

Los datos raw son inmutables: nunca modifiques ni borres una captura existente.
Incluye fixtures pequeños, reales y anonimizados solo cuando sean necesarios para
un test de regresión. No añadas los raw masivos de PLACSP ni BDNS: están ignorados
por volumen. Para cualquier captura no versionada, conserva o actualiza el
manifiesto descrito en [docs/reproducibilidad.md](docs/reproducibilidad.md).
