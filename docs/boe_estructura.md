# BOE — sumario diario y disposiciones (estructura y modelo canónico)

> Reconocimiento hecho con llamadas reales a la API de datos abiertos del BOE el
> **2026-06-12** (sumarios de varias fechas y disposiciones individuales). Las
> muestras reales reducidas viven en `tests/fixtures/boe_sumario_muestra.xml`,
> `tests/fixtures/boe_disposicion_subvencion_extracto.xml` y
> `tests/fixtures/boe_disposicion_subvencion_rd.xml`.

## 1. Qué es y qué papel juega

El BOE es la tercera velocidad de CLAUDE.md §3 (**decisiones políticas**), junto
al Consejo de Ministros. NO es contabilidad auditable: es **texto
semiestructurado** del que extraemos **trazabilidad y alerta temprana** —
detectar que se ha publicado una convocatoria de subvención, una concesión
directa por Real Decreto o una modificación de crédito con título explícito,
atribuirla al **ministerio proponente** (→ sección presupuestaria cuando sea
derivable) y registrarla con enlace oficial y texto bruto. El anclaje es **a
nivel de sección**, no de servicio/DG: el texto del BOE no da el servicio
presupuestario.

## 2. API y entrega (verificadas)

- **Sumario diario**: `GET https://www.boe.es/datosabiertos/api/boe/sumario/<AAAAMMDD>`
  con `Accept: application/xml`. Devuelve XML; histórico amplio.
- **Disposición individual**: `GET https://www.boe.es/diario_boe/xml.php?id=<ID>`
  (ID tipo `BOE-A-AAAA-N` para disposiciones, `BOE-B-AAAA-N` para anuncios).
- Acceso público, sin clave. *Fail loud*: ambos endpoints devuelven XML que
  empieza por `<?xml`; cualquier otra cosa (HTML de error, soft-200) se rechaza
  con la guardia `XML_MAGIC` de `extractors/base.py` y no contamina el raw.
- NOTA raw: los sumarios y disposiciones son pequeños (sumario ~150-300 KB,
  disposición ~5-40 KB) → SÍ se versionan en git (a diferencia de PLACSP/BDNS).

## 3. Estructura del sumario (verificada)

```
response > data > sumario > diario(@numero) >
  seccion(@codigo, @nombre) >
    departamento(@codigo, @nombre) >
      [epigrafe(@nombre) >]      # opcional; los items pueden colgar directos
        item >
          identificador          # BOE-A-AAAA-N
          titulo
          url_pdf / url_html / url_xml
```

- **Secciones** (códigos reales): `1` (I. Disposiciones generales), `2A`/`2B`
  (II. Personal), `3` (III. Otras disposiciones), `4` (IV. Justicia),
  `5A` (V-A. Contratación), `5B` (V-B. Otros anuncios), `5C` (V-C. Particulares).
- **departamento@nombre** = ministerio proponente (en mayúsculas, con prefijo
  "MINISTERIO DE …", o "JEFATURA DEL ESTADO" para leyes/RDL). Es la clave del
  anclaje a sección.

## 4. Estructura de la disposición (verificada)

```
documento >
  metadatos > identificador, titulo, departamento(@codigo), seccion,
              subseccion, fecha_publicacion, url_pdf, …
  analisis  > tipo(@codigo)   # clasificación OFICIAL del BOE; p. ej. 63 =
              "Subvenciones (SNPS)". A veces VACÍA (RD/RDL no la traen).
  texto     > p(@class)*       # cuerpo en párrafos
```

- En los **extractos de subvención** el primer párrafo es
  `BDNS(Identif.):<n>` → enlaza el dato BOE con la concesión/convocatoria BDNS
  (puente entre las dos patas de la señal).
- **Importes** en formato español dentro del texto: `1.000.000,00 €`,
  `8.000 euros`. Los expresados en letra (`un millón de euros`) NO se convierten.

## 5. Qué disposiciones interesan y cómo se clasifican

El extractor **prefiltra** en el sumario los candidatos por título/sección (para
no descargar el BOE entero) y el parser confirma con la disposición. La
clasificación (`tipo_disposicion`) combina `analisis/tipo` y patrones de título
verificados a mano:

| `tipo_disposicion`        | señal de detección                                                |
|---------------------------|-------------------------------------------------------------------|
| `convocatoria_subvencion` | `analisis/tipo`=63, o título "Extracto de…", o "se convoca(n) subvenciones/ayudas" |
| `subvencion_directa`      | "concesión directa de (una) subvención/subvenciones" (RD, sección I) |
| `credito_extraordinario`  | título "crédito(s) extraordinario(s)"                             |
| `suplemento_credito`      | título "suplemento(s) de crédito"                                 |
| `transferencia_credito`   | título "transferencia(s) de crédito"                              |
| `modificacion_credito`    | título "ampliación/generación/incorporación de crédito", "modificación … de crédito" |

Todo lo que no casa (personal, contratación —que ya cubre PLACSP—, justicia,
nombramientos…) se **descarta** en el prefiltro (no se ingiere).

## 6. Confianza del importe (degradación elegante)

La extracción es imperfecta por diseño (CLAUDE.md §9). `importe_confianza`:

- `alta`: importe junto a "importe (total/máximo) … euros" o entre paréntesis
  `(N €)` (caso típico de la concesión directa por RD).
- `media`: hay un importe en euros, pero no claramente la cifra titular.
- `sin_importe`: ninguna cifra en euros parseable (p. ej. importe en letra, o
  disposición sin cuantía) → `importe` NULO + **texto bruto conservado** para
  revisión humana. Nunca se inventa un cero.

## 7. Limitaciones conocidas (verificadas)

- **Modificaciones de crédito embebidas en RDL de medidas amplias**: el
  Real Decreto-ley 6/2024 (DANA) concede créditos extraordinarios pero su título
  no menciona "crédito" → cae en `otro` y **no** se clasifica como modificación.
  Es señal, no contabilidad: minar el texto de cada RDL queda fuera de alcance.
- **Escasez de títulos explícitos**: barriendo todo diciembre 2024 no apareció
  ni una disposición con título "crédito extraordinario / transferencia de
  crédito" en la sección del Estado; el grueso de la señal BOE útil son
  **convocatorias y concesiones directas de subvención**.
- `analisis/tipo` es fiable cuando está presente (subvenciones), pero los
  RD/RDL no la rellenan: por eso la clasificación NO depende solo de ese campo.

## 8. Modelo canónico (una fila por disposición de interés)

`fact_boe_disposiciones` (clave natural = `identificador` BOE): identificador,
fecha, sección/subsección, departamento proponente, `tipo_disposicion`, título,
`bdns_id` (si extracto SNPS), `importe` + `importe_confianza`, `url_oficial`
(url_html), `texto_bruto`, y el anclaje a sección (`anclaje_tipo`/`anclaje_senal`,
ver `docs/cobertura_fuentes.md`). Carga idempotente por `identificador`.
