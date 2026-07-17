# Reproducibilidad y trazabilidad de capturas

Este documento delimita qué puede reproducirse desde un clon y el contrato
mínimo para reproducir un estado histórico del warehouse. No incorpora todavía
almacenamiento externo, Git LFS ni DVC.

## Dos niveles de reproducibilidad

### Transformación reproducible

Con el mismo commit de código, el mismo `uv.lock` y las mismas capturas raw, el
comando `uv run gasto-estado build` debe reconstruir el mismo warehouse. Las
capturas que sí están en Git conservan la evidencia de origen dentro de
`data/raw/<fuente>/<fecha_captura>/`.

### Estado histórico exacto

Un clon no contiene los raw masivos de PLACSP ni BDNS, que se excluyen en
`.gitignore` por volumen. Por ello, un clon por sí solo no puede reconstruir de
forma exacta un warehouse que dependa de esas capturas. Puede regenerar datos
nuevos desde las fuentes oficiales, pero la fuente puede haber cambiado desde la
fecha original.

Para reproducir un estado histórico exacto se necesita, además del commit de
código, una copia inmutable de cada captura no versionada y su manifiesto. La
ubicación de esa copia queda deliberadamente fuera de esta fase; puede ser un
artefacto, un archivo institucional o un almacenamiento de objetos posterior.

## Regenerar PLACSP y BDNS

Las capturas se vuelven a obtener mediante los extractores y las ventanas de
fechas definidas por el pipeline. Antes de regenerarlas, conserva el manifiesto
de la ejecución anterior. Tras descargar, calcula el hash del archivo o conjunto
de archivos y registra la nueva captura antes de cargarla en el warehouse.

La regeneración es adecuada para actualizar el sistema. No sustituye una copia
inmutable cuando se necesita auditar exactamente una publicación pasada.

## Contrato mínimo de manifiesto

Cada captura, incluida una captura masiva no versionada, debe tener un manifiesto
JSON versionado en `data/manifiestos/`. El raw puede vivir fuera de Git, pero el
manifiesto no. Un manifiesto por fuente, fecha de extracción y lote debe incluir
como mínimo:

```json
{
  "schema_version": 1,
  "fuente": "placsp",
  "fecha_extraccion": "2026-07-17T06:00:00Z",
  "rango_cubierto": {"desde": "2026-07-10", "hasta": "2026-07-17"},
  "url_origen": "https://…",
  "sha256": "<hash de la captura o del manifiesto de archivos>",
  "commit_codigo": "<commit que ejecutó la carga>",
  "commit_warehouse": "<commit que publicó el resultado>",
  "ubicacion_inmutable": "<identificador o ruta externa de la copia>"
}
```

- `sha256` permite comprobar que la captura recuperada es la misma.
- `commit_codigo` identifica el parser y la lógica de carga empleados.
- `commit_warehouse` identifica el estado publicado que produjo la ejecución.
- `ubicacion_inmutable` es un identificador, no una credencial; nunca se guardan
  secretos de acceso en el manifiesto.

Si una captura contiene varios archivos, el campo `sha256` debe referenciar un
manifiesto de archivos con sus hashes individuales, también versionado.

## Próximos pasos compatibles

Una fase posterior puede automatizar la creación y validación de manifiestos y
elegir un almacenamiento externo. Debe preservar este contrato o versionarlo de
forma explícita; no debe cambiar retrospectivamente hashes, fechas, URLs ni
commits ya publicados.
