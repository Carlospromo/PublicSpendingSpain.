# Consejo de Ministros — referencias de La Moncloa (estructura y modelo canónico)

> Reconocimiento hecho con descargas reales de `lamoncloa.gob.es` el
> **2026-06-12** (referencias de 2026, 2021, 2020 y 2018). Las muestras reales
> reducidas viven en `tests/fixtures/consejo_referencia_2026.html` (vintage
> actual) y `tests/fixtures/consejo_referencia_2018.html` (vintage antiguo).

## 1. Qué es y qué papel juega

La **referencia** del Consejo de Ministros es el acta-resumen que publica
La Moncloa tras la reunión semanal (normalmente martes). Es la otra mitad de la
tercera velocidad de CLAUDE.md §3 (**decisiones políticas**), y a menudo
**antecede incluso al compromiso jurídico**: el Consejo *autoriza* el gasto antes
de que se adjudique (PLACSP) o se conceda (BDNS) y antes de que se publique el RD
en el BOE. NO es contabilidad: es **texto semiestructurado**; extraemos
trazabilidad y alerta temprana, anclando al **ministerio proponente → sección**.

## 2. Entrega y URLs (verificadas)

- **Índice**: `…/consejodeministros/referencias/Paginas/index.aspx` (lista las
  referencias recientes con enlace a cada una).
- **Referencia (vintage actual, 2024+)**:
  `…/referencias/Paginas/<AAAA>/<AAAAMMDD>-referencia-rueda-de-prensa-ministros.aspx`
- **Referencia (vintage antiguo, 2018-~2021)**:
  `…/referencias/Paginas/<AAAA>/refc<AAAAMMDD>.aspx`
- HTML servido por SharePoint (`text/html; charset=utf-8`, ~100-180 KB). *Fail
  loud*: una página inesperada (404 disfrazado, portal caído) no trae el bloque
  `SUMARIO` → el parser avisa en vez de emitir filas vacías.
- NOTA raw: <300 KB → SÍ se versiona (git-scraping).

## 3. Estructura del documento (verificada, estable entre vintages)

```
<h1> Referencia del Consejo de Ministros
<h2> SUMARIO                     # lista COMPLETA de acuerdos (target del parser)
   <h3> {Ministerio proponente}  # p. ej. "Hacienda", "Para la Transición…"
   <ul><li> {ACUERDO …}          # un <li> por acuerdo; el texto empieza por el
   <div><ul><li> …               #   tipo (ACUERDO / REAL DECRETO / CONVENIO / …)
<h2> ACUERDOS DE PERSONAL        # nombramientos (se clasifican como 'personal')
<h2> AMPLIACIÓN DE CONTENIDO(S)  # desarrollo de un SUBCONJUNTO de acuerdos
   <h3> {Ministerio} <h4> {TÍTULO} <p> {cuerpo detallado}
<h2> BIOGRAFÍAS / Más información
```

- **Parser ancla en el SUMARIO**, no en AMPLIACIÓN: el SUMARIO es la lista
  *completa* (AMPLIACIÓN solo desarrolla algunos) y trae ministerio + tipo +
  importe + descripción en un único `<li>`.
- **`<h3>` = ministerio proponente**, en **forma corta sin "Ministerio de"**
  ("Hacienda", "Para la Transición Ecológica y el Reto Demográfico", "Asuntos
  Exteriores, Unión Europea y Cooperación"). El anclaje a sección normaliza y
  resuelve esa forma (ver `docs/cobertura_fuentes.md`).
- Cada `<li>` es **un acuerdo**; un ministerio puede tener varios.

## 4. Vintages observados

| Vintage     | Slug URL                         | Maquetación del SUMARIO                 |
|-------------|----------------------------------|----------------------------------------|
| 2018-~2021  | `refc<AAAAMMDD>.aspx`            | `<h3 class="RefCDepar">` + `<ul class="ListaUL"><li>` |
| 2024+       | `…-referencia-rueda-de-prensa-ministros.aspx` | `<h3>` + `<div><ul><li>` / `<li>` |

El **invariante** entre vintages es robusto: bloque `SUMARIO`, `<h3>` = ministerio,
items de lista cuyo texto empieza por el tipo de acuerdo. El parser detecta el
vintage por marcadores del HTML (clase `RefCDepar`, cabecera del bloque) y aplica
la familia de parsers por época (CLAUDE.md §2), sin un único parser frágil.

## 5. Tipos de acuerdo y clasificación

`tipo_acuerdo` se deriva del verbo/encabezado del `<li>` y del léxico:

| `tipo_acuerdo`         | señal                                                        |
|------------------------|--------------------------------------------------------------|
| `autorizacion_gasto`   | "ACUERDO por el que se autoriza … (gasto/contratación/celebración)" |
| `subvencion`           | "subvención(es)", "ayudas", "Fondo … de ayudas"             |
| `transferencia_credito`| "transferencia(s) de crédito"                               |
| `credito_suplemento`   | "crédito extraordinario", "suplemento de crédito"           |
| `convenio`             | "CONVENIO …", "convenio"                                     |
| `norma`                | "REAL DECRETO", "REAL DECRETO-LEY", "PROYECTO DE LEY", "ANTEPROYECTO" |
| `personal`             | bloque ACUERDOS DE PERSONAL / nombramientos                 |
| `otro`                 | el resto (se CONSERVA, no se descarta)                       |

A diferencia del BOE, en el Consejo **nada se descarta**: todos los acuerdos del
SUMARIO se ingieren (son señal de decisión política); los irrelevantes quedan en
`otro`/`personal` y se cuentan.

## 6. Importe y confianza (degradación elegante)

Importe embebido en el texto del `<li>`: "por importe (total/máximo) de
168.000.000 de euros", "29.339.882,79 euros". `importe_confianza`:

- `alta`: importe ligado a "importe (total/máximo) de … euros".
- `media`: cifra en euros presente, no claramente la titular.
- `sin_importe`: ninguna cifra en euros (la mayoría de acuerdos normativos y de
  personal) → `importe` NULO + **texto bruto conservado**. Nunca un cero falso.

## 7. Modelo canónico (una fila por acuerdo)

`fact_acuerdos_cdm` (clave natural sintética = `acuerdo_id` = `<fecha>#<índice>`,
porque la referencia NO da un id estable por acuerdo): fecha del consejo,
ministerio proponente (texto), `tipo_acuerdo`, descripción, `importe` +
`importe_confianza`, `url_oficial` (la referencia), `texto_bruto`, y el anclaje a
sección. Carga idempotente por `acuerdo_id` (se borra y reinserta el bloque de la
fecha: reparsear la misma referencia es idempotente aunque cambie el nº de
acuerdos).

## 8. Limitaciones conocidas

- Sin id oficial por acuerdo → la clave es sintética por **orden en el SUMARIO**;
  si La Moncloa reordenara una referencia ya publicada, el reparseo reasignaría
  índices (mitigado: se reemplaza el bloque completo de la fecha en cada carga).
- Estructuras muy antiguas (pre-2018) no verificadas: si aparece un vintage no
  reconocido, el detector falla *loud* en vez de adivinar.
- El ministerio en forma corta puede no resolver a sección en reestructuraciones
  históricas no cubiertas por el seed PGE vigente → `ministerio_no_mapeable`
  (etiquetado y contado, no descartado).
