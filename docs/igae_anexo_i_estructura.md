# IGAE — Anexo I mensual: inventario de estructura (reconocimiento Fase 2)

> Verificado contra el fichero real `MENSUAL ABRIL 2026 ANEXO I.xlsx`
> (descargado 2026-06-11, 635 KB, XLSX 2007+). Este documento guía el parser
> del Prompt 5; aquí NO se parsea nada.

## Localización confirmada (peticiones reales 2026-06-11)

- **Página navegable** (año en curso): `https://www.igae.pap.hacienda.gob.es/sitios/igae/es-ES/Contabilidad/ContabilidadPublica/CPE/EjecucionPresupuestaria/Paginas/imejecucionpresupuesto.aspx`
  (se llega desde la página índice de Ejecución Presupuestaria → "Ejecución del
  Presupuesto. Administración General del Estado").
- **Históricos**: misma URL con sufijo de año: `imejecucionpresupuesto<YYYY>.aspx`
  (enlaces "Ejercicios anteriores" en la propia página; verificados 2012–2025;
  el selector llega hasta 2001).
- **Patrón de fichero (vintage actual)**:
  `…/CPE/EjecucionPresupuestaria/Documents/MENSUAL%20<MES>%20<AÑO>%20ANEXO%20I.xlsx`
  - `<MES>`: mayúsculas en español, sin tildes en los probados (ENERO, FEBRERO,
    MARZO, ABRIL, DICIEMBRE…); espacios codificados `%20`.
  - Verificado que resuelve: 2019, 2020, 2021, 2025, 2026. **No** resuelve 2018
    ni anteriores.
- **Variantes antiguas documentadas** (solo reconocimiento; parsers en Prompts 5/6):
  - 2018: sufijo ` (EXCEL)` → `MENSUAL%20ABRIL%202018%20ANEXO%20I%20%28EXCEL%29.xlsx`,
    **inconsistente dentro del mismo año** (DICIEMBRE 2018 sin sufijo). Conclusión:
    para históricos ≤2018 hay que scrapear la página del año, no derivar la URL.
  - Mismo directorio `Documents/` publica también `MENSUAL <MES> <AÑO>.xlsx`
    (Cuadros), `… ANEXO II.xlsx` y el PDF `MENSUAL MM-YY.pdf`.
- **Último disponible a 2026-06-11**: ABRIL 2026 (MAYO da 404) — coherente con la
  cadencia de ~25–30 días tras cierre de mes. El descubrimiento del último mes
  se hace sondeando el patrón hacia atrás desde el mes corriente, con scraping
  de la página como fallback.

## Maquetación del libro (vintage "2021+", aplica al menos desde 2019)

**38 hojas**: `S5` (resumen) + `S01`…`S38` (una por sección presupuestaria;
casan con las 37 secciones del presupuesto prorrogado 2025-P, estructura
post-RD 829/2023 — no hay hoja S11).

### Hoja `S5` — resumen por secciones

- Fila 0: residuo ("Euros" en una celda). Fila 1: cabecera. Datos desde fila 2.
- 40 filas: 2 de cabecera + 37 secciones + fila final `TOTALES`.
- Columnas: `0` = `NN-DENOMINACIÓN` (código y denominación de sección en una
  sola celda, separados por guion), `1..3` = magnitudes.

### Hojas `SNN` — detalle por sección

- Fila 0: residuo ("Euros"). Fila 1: cabecera (col0 incluye el nombre del
  ministerio con salto de línea). Datos desde fila 2.
- **Col 0**: denominación del SERVICIO presupuestario, repetida en todas las
  filas de su bloque (no hay celdas combinadas reales: el valor se repite fila
  a fila). Sin código de servicio: el código va embebido en las filas de
  aplicación (ver abajo). Las denominaciones usan abreviaturas tipo DIR3
  ("D. G. DE …") → reutilizar `transform/text.normalize` para casar con
  `dim_seccion_servicio`.
- **Col 1** (`APLICACIÓN PGE`), cuatro tipos de fila intercalados:
  1. Cabecera de programa: `923M-Dirección y Servicios Generales de…`
     (subtotal de programa; lleva magnitudes pero NO es detalle).
  2. Aplicación: `1501  923M   12100  -Complemento de destino` →
     **orgánica completa `SSNN`** (sección 15 + servicio 01) + programa +
     económica + denominación. **Atención a las variantes reales** (todas
     verificadas en abril 2026, ver el parser `v2021_plus.py`):
     - Económica de **3 (concepto), 5 (subconcepto) o 7 dígitos (partida)**.
     - Separador económica↔denominación `  -` (2+ espacios) salvo en la
       económica de 7 dígitos, donde va pegado: `2210201-GAS NATURAL`.
     - **Desglose territorial por provincia**: orgánica+provincia(2)+programa
       pegados sin espacios → `120111142A` = órg. 1201 + prov. 11 + prog. 142A.
       Imprescindible capturar la provincia: dos filas pueden diferir solo en
       ella (07 vs 44) y se perderían por clave duplicada.
     - **Territorialización de Defensa**: el programa lleva un 5º carácter
       (dígito o letra): `121M2`, `121MC`. Se conserva en `programa_cod`
       (el grupo de programa estándar es `programa_cod[:4]`).
     - El programa puede contener `Ñ` (`46ÑF`).
     - La denominación puede empezar por dígito (`-16ª Reposición del Fondo…`).
  3. Fila en blanco (separador entre programas).
  4. Subtotal: `TOTAL SERVICIO` (cierra cada bloque de servicio).
  Conviven, por tanto, niveles de agregación mezclados en la misma hoja; el
  parser se queda con las filas de aplicación y valida que su suma cuadra con
  el `TOTAL SERVICIO` (validación interna del parseo, §7 de CLAUDE.md).
- Ejemplo de volumetría: S15 (Hacienda) = 597 filas, 15 bloques de servicio
  (incluido `MECANISMO DE RECUPERACIÓN Y RESILIENCIA` = servicio .50).

### Magnitudes (las mismas en todas las hojas)

| Col (SNN) | Etiqueta exacta (con salto de línea interno) | Canónica |
|---|---|---|
| 2 | `CRÉDITOS          INICIALES\n(1)` | `credito_inicial` |
| 3 | `CRÉDITOS  DEFINITIVOS\n(2)` | `credito_definitivo` |
| 4 | `OBLIGACIONES RECONOCIDAS NETAS\n(3)` | `orn` |

- En `S5` las mismas tres magnitudes en columnas 1–3.
- Tipos: numéricos nativos (int/float)… **salvo el texto `"-"`** cuando no hay
  dato (visto en ORN del MRR). El parser deberá tratar `-` explícitamente.
- **El Anexo I NO trae** comprometido/dispuesto ni pagos: esas magnitudes están
  en los Cuadros (`MENSUAL <MES> <AÑO>.xlsx`) y Anexo II (fuera de alcance aquí).
- Espacios irregulares y saltos de línea DENTRO de las etiquetas de cabecera:
  no matchear cabeceras por igualdad literal.

## Vintage

El fichero de abril 2026 pertenece al vintage **"2021+"** (mismo patrón de URL
y maquetación verificados en 2019–2026 por tamaño/respuesta; la maquetación
≤2018 queda pendiente de reconocimiento cuando se aborde el histórico).

## Fixture

`tests/fixtures/igae_anexo_i_muestra.xlsx`: hojas `S5`, `S01`, `S04` y `S15`
del fichero real, conservando cabeceras y maquetación original (el resto de
hojas eliminadas para reducir tamaño). El test de regresión del parser
(Prompt 5) dependerá de esta maquetación.
