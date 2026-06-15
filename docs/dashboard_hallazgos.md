# Hallazgos del dashboard — huecos del contrato v1

> Documento generado al construir el dashboard Streamlit (Fase 8) consumiendo
> exclusivamente la API v1. Cada hallazgo es un hueco detectado en el contrato:
> algo que el dashboard necesitó y la API no sirvió óptimamente. Son la
> especificación de mejoras para la **v2 del contrato** y para el **frontal
> definitivo**. No son bugs — son el resultado esperado de validar el contrato
> con un consumidor real.

---

## Hallazgo 1 — Sin filtro `seccion_cod` en `/v1/ejecucion/grado?nivel=servicio`

**Problema:** Para el drill-down de ministerio → servicios, el dashboard necesita
los datos de ejecución de los servicios de una sección concreta. La API devuelve
TODOS los servicios AGE (hasta 500+) y el filtrado se hace en el cliente.

**Impacto:** Transferencia de datos innecesaria. Con 37+ secciones y hasta ~200
servicios, la respuesta es grande y el filtrado en cliente es frágil (depende de
que el campo `seccion_cod` esté en la respuesta, que lo está, pero no está
garantizado como campo de filtro).

**Solución para v2:** Añadir parámetro `seccion` a `/v1/ejecucion/grado` y
`/v1/ejecucion/modificaciones` para filtrar server-side:
```
GET /v1/ejecucion/grado?periodo=2026-04&nivel=servicio&seccion=06
```

**Severidad:** Media. El dashboard funciona, pero lento con muchas secciones.

---

## Hallazgo 2 — Las evidencias usan un DSL `ref` que el frontal debe parsear

**Problema:** Las evidencias de las alertas incluyen un campo `ref` con formato
tipo DSL propio (`"v_ejecucion periodo=2026-04 seccion_cod=06 servicio_cod=01"`).
El dashboard implementa `parse_evidencia_ref()` para descomponerlo, pero es una
deuda: si el formato del `ref` cambia (añadir parámetros, cambiar el separador),
el parser del frontal queda desincronizado silenciosamente.

**Impacto:** El ciclo "alerta → evidencia → vista concreta" funciona, pero
depende de un contrato implícito no documentado formalmente y sin tests de
contratos de cadena.

**Solución para v2:** Hacer explícita la referencia de evidencia con un subtipo:
```json
{
  "tipo": "aplicaciones",
  "ref": "v_ejecucion periodo=2026-04 seccion_cod=06 servicio_cod=01",
  "page_params": {
    "page": "ejecucion",
    "periodo": "2026-04",
    "seccion_cod": "06",
    "servicio_cod": "01"
  }
}
```
El campo `page_params` (dict estructurado) elimina la necesidad de parsear `ref`.

**Severidad:** Alta para el frontal definitivo. El dashboard tiene workaround.

---

## Hallazgo 3 — Sin endpoint para listar los periodos disponibles de BOE/CdM

**Problema:** Para la vista de decisiones políticas, el usuario necesita elegir
un periodo o ejercicio. La API no expone qué ejercicios/periodos tienen datos
de BOE o CdM. El dashboard usa `ejercicios()` (que lista los ejercicios IGAE)
como proxy, pero BOE/CdM pueden tener datos en ejercicios sin datos IGAE, o al
revés.

**Impacto:** El selector de ejercicio en la página de decisiones puede ofrecer
opciones que devuelven datos vacíos (o no ofrecer opciones con datos reales).

**Solución para v2:** Añadir parámetro `fuente` a `/v1/estructura/ejercicios`:
```
GET /v1/estructura/ejercicios?fuente=boe
GET /v1/estructura/ejercicios?fuente=cdm
```
O alternativamente, incluir en `/v1/frescura` el `ejercicio_cubierto` además del
`periodo_cubierto`.

**Severidad:** Baja-Media. La UI es subóptima pero funcional.

---

## Hallazgo 4 — La concentración no expone los nombres de los adjudicatarios

**Problema:** `/v1/contratos/concentracion` devuelve HHI, `top_n_cuota_pct` y
`n_adjudicatarios`, pero no los nombres de los adjudicatarios que concentran la
cuota. El dashboard puede mostrar que "el servicio 01 de la sección 06 tiene
HHI 4.200 con 2 adjudicatarios", pero no puede decir quiénes son.

**Impacto:** La alerta de concentración es la más importante para auditoría
(permite investigar quién contrata con quién), pero queda truncada: el analista
ve que hay concentración pero no puede identificar al adjudicatario concreto sin
ir a la fuente primaria (PLACSP datos abiertos).

**Solución para v2:** Añadir un sub-endpoint o un campo opcional en la respuesta
de concentración:
```
GET /v1/contratos/concentracion?ejercicio=2026&nivel=servicio&incluir_adjudicatarios=true
```
Con `data[i].top_adjudicatarios = [{nombre, nif, importe, cuota_pct}, ...]`.

**Severidad:** Alta. Es la pieza que cierra el ciclo "concentración → quién".

---

## Hallazgo 5 — Sin URL individual de disposición BOE ni referencia de La Moncloa

**Problema:** La vista de decisiones políticas no puede enlazar al texto original
de cada disposición BOE (p. ej. `https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-XXXX`)
ni al acuerdo de La Moncloa. El dashboard enlaza a las páginas de búsqueda
genérica, no al documento concreto.

**Impacto:** El ciclo "decisión → texto oficial" se rompe. El analista ve que hay
un acuerdo de autorización de gasto pero no puede ir al documento sin búsqueda
manual.

**Solución para v2:** Exponer en los datos de decisiones el identificador BOE
(`boe_id`, `diario_fecha`) o la URL directa al texto, y la referencia de La
Moncloa (URL de la nota de prensa):
```json
{ "boe_id": "BOE-A-2026-12345", "url_boe": "https://boe.es/..." }
```

**Severidad:** Alta para la utilidad auditora. La URL al texto oficial es la
evidencia primaria irrefutable.

---

## Hallazgo 6 — El endpoint de ritmo a nivel servicio es lento para el drill-down

**Problema:** Para mostrar la serie temporal de ejecución de un servicio concreto
dentro del drill-down (página de ejecución), el dashboard llama a
`/v1/ejecucion/ritmo?ejercicio=X&nivel=servicio`, que devuelve TODOS los servicios
AGE mes a mes. Con 12 meses y 200+ servicios, son >2.400 filas.

**Impacto:** Latencia visible en el drill-down del primer servicio de una sección.

**Solución para v2:** Parámetro `seccion` en `/v1/ejecucion/ritmo`:
```
GET /v1/ejecucion/ritmo?ejercicio=2026&nivel=servicio&seccion=06
```

**Severidad:** Baja. Performance, no correctitud.

---

## Hallazgo 7 — La paginación no está completamente integrada en el dashboard

**Problema:** El dashboard usa `tamano=500` para obtener todos los registros en
una sola llamada. Para secciones con muchos servicios (sección 06 Deuda tiene
relativamente pocos, pero la AGE completa en nivel servicio puede superar 200),
el dashboard depende de que `tamano=500` cubra todos los registros.

**Impacto:** Si hay >500 registros en algún nivel, el dashboard muestra datos
incompletos sin advertirlo. La `meta.paginacion.hay_siguiente` no se está
verificando.

**Solución para el dashboard:** Verificar `hay_siguiente` y añadir paginación
con `st.button("Cargar más")` o iterar automáticamente.

**Severidad:** Baja con los datos actuales (~37 secciones, ~200 servicios),
pero crecería con más data.

---

## Hallazgo 8 — No hay endpoint de "servicio completo con todo el contexto"

**Problema:** El drill-down de un servicio requiere varias llamadas paralelas:
(1) estructura, (2) grado de ejecución, (3) ritmo, (4) interanual, (5)
modificaciones, (6) concentración. Esto son 5-6 roundtrips en secuencia.

**Impacto:** Latencia acumulada notable en el drill-down de servicio.

**Solución para v2:** Endpoint de "snapshot de servicio":
```
GET /v1/servicios/{seccion_cod}/{servicio_cod}/snapshot?periodo=2026-04
```
Que devuelva en una sola respuesta: grado actual, ritmo del ejercicio,
comparativa interanual y modificaciones. El frontal solo haría una llamada.

**Severidad:** Media. Importante para la UX del frontal definitivo.

---

## Resumen para la v2 del contrato

| # | Hallazgo | Prioridad | Tipo de cambio |
|---|----------|-----------|----------------|
| 1 | Filtro `seccion` en grado/modificaciones nivel servicio | Media | Añadir param compatible |
| 2 | Evidencias con `page_params` explícito | Alta | Añadir campo opcional compatible |
| 3 | `ejercicios` por fuente (BOE/CdM) | Baja | Añadir param compatible |
| 4 | Adjudicatarios en concentración | Alta | Añadir param+campo opcionales |
| 5 | URL oficial en decisiones BOE/CdM | Alta | Añadir campos opcionales |
| 6 | Filtro `seccion` en ritmo nivel servicio | Baja | Añadir param compatible |
| 7 | Verificar `hay_siguiente` en dashboard | Baja | Fix dashboard (no API) |
| 8 | Endpoint snapshot de servicio | Media | Endpoint nuevo |

Todos los cambios de prioridad alta son **compatibles** bajo v1 (añaden campos o
parámetros opcionales). No requieren romper el contrato. Pueden publicarse como
actualizaciones incrementales de v1 antes de que el frontal definitivo entre en
producción.
