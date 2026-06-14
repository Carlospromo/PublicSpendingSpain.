# API de gasto-estado — contrato v1

> Documento autosuficiente para construir el frontal **sin leer el código del
> backend**. Describe la API de solo lectura que expone el gasto del Estado
> español a nivel de servicio presupuestario / dirección general, con sus tres
> velocidades, cruces y alertas. La API genera además su esquema **OpenAPI** en
> `/openapi.json` y documentación interactiva en `/docs`.

## 1. Visión general

- **Solo lectura.** La API nunca escribe; sirve un warehouse DuckDB en modo
  `read_only` (una conexión por proceso, un cursor por petición).
- **Capa fina.** No contiene lógica de negocio: invoca las funciones puras de
  `analytics/metrics.py` y `analytics/alerts.py` (catálogos en
  [`docs/metricas.md`](metricas.md) y [`docs/alertas.md`](alertas.md)) y propaga
  sus metadatos de fiabilidad intactos.
- **Honestidad como contrato.** Cada cifra viaja con su **naturaleza**
  (exacta/aproximada/indiciaria), su **cobertura de anclaje**, sus
  **advertencias** y la **frescura** de sus fuentes. Estos metadatos son
  ciudadanos de primera clase del esquema (en `meta`), no añadidos opcionales.

## 2. Cómo levantar y consumir

```bash
uv run gasto-estado build            # construye el warehouse (si no existe)
uv run gasto-estado api --port 8000  # FastAPI de solo lectura
# Documentación interactiva: http://127.0.0.1:8000/docs
# Esquema OpenAPI:           http://127.0.0.1:8000/openapi.json
```

Todas las peticiones son `GET`. CORS está abierto (`*`) para que el frontal,
servido en otro origen, pueda consumirla. La raíz `/` devuelve la versión y los
enlaces a la documentación.

## 3. Versionado y política de compatibilidad

Toda la superficie vive bajo el prefijo **`/v1/`** (versionado por ruta: es lo
más simple para que el frontal fije la versión que consume). A partir de aquí la
forma de las respuestas es un **compromiso**:

- **Cambio COMPATIBLE** (no sube de versión): añadir un campo *opcional*, un
  endpoint nuevo, o un valor nuevo a un enum documentado como extensible.
- **Cambio INCOMPATIBLE** (exige **`/v2/`**): renombrar o quitar un campo,
  cambiar su tipo o su semántica, o volver obligatorio un campo opcional.

El consumidor debe ignorar con tolerancia los campos que no conozca (para que
añadir campos siga siendo compatible).

## 4. Envoltura común `{ data, meta }`

**Todas** las respuestas tienen la misma forma:

```jsonc
{
  "data": <carga útil: lista o objeto>,
  "meta": {
    "generado_en": "2026-06-14T08:12:37.701304+00:00",  // ISO-8601
    "version": "v1",
    "nivel": "seccion",          // nivel de agregación servido (o null)
    "naturaleza": "exacta",      // exacta | aproximada | indiciaria | null
    "magnitudes": ["credito_definitivo", "orn", "credito_inicial"],
    "fuentes": ["igae_anexo_i"],
    "frescura": { "fuentes": [...], "ultima_actualizacion": "2026-06-13",
                  "periodo_cubierto": ["2015-12", "2026-04"] },
    "cobertura_anclaje": { ... } | null,
    "advertencias": ["El dato IGAE es ACUMULADO ...", ...],
    "paginacion": { "total": 37, "pagina": 1, "tamano": 200, "hay_siguiente": true }
  }
}
```

- En endpoints de **métrica**, `meta` lleva `naturaleza`, `magnitudes`,
  `fuentes`, `frescura`, `cobertura_anclaje` y `advertencias`.
- En endpoints de **colección** simple (catálogos, estructura), `meta` lleva
  `paginacion` (y `frescura` cuando aplica); `naturaleza` es `null`.
- En endpoints de **objeto único** (`/salud`, `/alertas/informe`), no hay
  `paginacion`.

**Nulo ≠ 0.** Un importe ausente o un `-` del fichero oficial es `null`, nunca
cero (CLAUDE.md §8). El frontal debe distinguirlos: "sin dato" no es "cero euros".

## 5. Paginación, filtros y ordenación

- **Paginación** (endpoints de colección): parámetros `pagina` (≥1, por defecto
  1) y `tamano` (por defecto **200**, máximo **1000**). Los metadatos van en
  `meta.paginacion`: `total`, `pagina`, `tamano`, `hay_siguiente`. Un `tamano`
  fuera de rango devuelve 422.
- **Filtros** uniformes por nombre y semántica: `periodo` (YYYY-MM), `ejercicio`
  (int), `nivel`, `seccion`, `severidad`, `tipo`, `velocidad`, `top_n`. No todos
  aplican a todos los endpoints (ver catálogo).
- **Ordenación**: las colecciones de métrica se devuelven **ordenadas por su
  magnitud principal descendente** (ORN, importe…); las alertas, por severidad.
  La ordenación declarable por campo se añadirá de forma compatible si el frontal
  la necesita.

## 6. Contrato de errores

Todo error tiene el mismo cuerpo:

```jsonc
{ "error": { "codigo": "no_encontrado", "mensaje": "Periodo IGAE no cargado: 1999-01.", "detalle": null } }
```

| HTTP | `codigo`                 | Cuándo |
|------|--------------------------|--------|
| 404  | `no_encontrado`          | periodo/ejercicio/fuente no cargado, o ruta inexistente |
| 422  | `entrada_invalida`       | parámetro mal formado, `nivel`/`velocidad`/`tamano` inválidos |
| 503  | `servicio_no_disponible` | el warehouse no está construido |
| 500  | `error_interno`          | fallo no previsto |

`detalle` puede llevar contexto (p. ej. la lista de errores de validación).

## 7. Catálogo de endpoints

> Todos bajo `/v1`. Respuestas envueltas en `{data, meta}` (se omite `meta` en
> los ejemplos por brevevdad salvo donde es ilustrativo).

### Salud y frescura

| Método y ruta | Descripción |
|---|---|
| `GET /v1/salud` | Estado del warehouse. **Responde 200 siempre**; si no hay datos, `data.accesible=false`. |
| `GET /v1/frescura` | Por fuente: `ultima_actualizacion`, `periodo_cubierto`, `n_filas`, velocidad. |

`GET /v1/salud` → `data`: `{accesible, ejercicios, n_periodos_igae,
ultima_actualizacion, perimetro, cobertura_dg_nota}`.

### Estructura y catálogos

| Ruta | Parámetros | `data` |
|---|---|---|
| `GET /v1/estructura/ejercicios` | — | lista de años con ejecución |
| `GET /v1/estructura/secciones` | `ejercicio` (req.) | `[SeccionModel]` |
| `GET /v1/estructura/secciones/{seccion_cod}/servicios` | `ejercicio` (req.) | `[ServicioModel]` (con DG nominal) |
| `GET /v1/catalogos/programas` | paginación | `[ProgramaModel]` |
| `GET /v1/catalogos/economicas` | paginación | `[EconomicaModel]` (1584 filas: pagina) |
| `GET /v1/catalogos/fuentes` | — | `[FuenteModel]` (con `velocidad`) |

### Ejecución (IGAE) — velocidad contable

| Ruta | Parámetros | Descripción |
|---|---|---|
| `GET /v1/ejecucion/grado` | `periodo` (req.), `nivel` | Grado de ejecución = ORN/definitivo |
| `GET /v1/ejecucion/ritmo` | `ejercicio` (req.), `nivel` | Serie intra-anual mes a mes |
| `GET /v1/ejecucion/interanual` | `periodo` (req.), `nivel` | Mismo-mes del año anterior |
| `GET /v1/ejecucion/modificaciones` | `periodo` (req.), `nivel` | Modificaciones derivadas (definitivo − inicial) |

`nivel` ∈ `AGE | seccion | servicio | dg | programa | economica | capitulo`.

**Ejemplo** `GET /v1/ejecucion/grado?periodo=2026-04&nivel=seccion&tamano=1`:

```jsonc
{
  "data": [{
    "seccion_cod": "06", "seccion_denominacion": "DEUDA PÚBLICA",
    "credito_inicial": 128796841100.0, "credito_definitivo": 128796841100.0,
    "orn": 55798384345.99, "modificaciones": 0.0, "pct_ejecucion": 43.32
  }],
  "meta": {
    "nivel": "seccion", "naturaleza": "exacta",
    "magnitudes": ["credito_definitivo", "orn", "credito_inicial"],
    "fuentes": ["igae_anexo_i"],
    "frescura": {"ultima_actualizacion": "2026-06-13", "periodo_cubierto": ["2015-12","2026-04"]},
    "advertencias": ["El dato IGAE es ACUMULADO ...", "Periodo en PRÓRROGA ..."],
    "paginacion": {"total": 37, "pagina": 1, "tamano": 1, "hay_siguiente": true}
  }
}
```

### Compromisos (PLACSP / BDNS)

| Ruta | Parámetros | Descripción |
|---|---|---|
| `GET /v1/contratos/volumen` | `ejercicio` o `periodo`, `nivel` | Importe adjudicado |
| `GET /v1/subvenciones/volumen` | `ejercicio` o `periodo`, `nivel` | Importe concedido |
| `GET /v1/contratos/concentracion` | `ejercicio` o `periodo`, `nivel`, `top_n` | Top-N e índice HHI por órgano |

`nivel` ∈ `AGE | seccion | servicio | dg`. `meta.cobertura_anclaje` indica qué
fracción del importe se atribuyó a un servicio (ver §9).

### Decisiones (BOE / CdM) — velocidad política

| Ruta | Parámetros | Descripción |
|---|---|---|
| `GET /v1/decisiones/{fuente}/volumen` | `fuente` ∈ `boe\|cdm`, `periodo`/`ejercicio`, `nivel` | Conteo y volumen por tipo |

`meta.naturaleza` es **`aproximada`**: el importe se desglosa por confianza
(`importe_alta`, `importe_media`, `n_sin_importe`), nunca un agregado único.

### Cruces (indiciarios)

| Ruta | Parámetros | Descripción |
|---|---|---|
| `GET /v1/cruces/compromiso-ejecucion` | `periodo` (req.), `nivel` | Adjudicación PLACSP vs ORN IGAE |
| `GET /v1/cruces/decisiones-compromiso` | `ejercicio` (req.) | Autorización CdM vs adjudicación PLACSP |

`meta.naturaleza` es **`indiciaria`** y `meta.advertencias` lleva la marca
inseparable. Las filas exponen **ambas magnitudes por separado** además del ratio.

### Alertas

| Ruta | Parámetros | Descripción |
|---|---|---|
| `GET /v1/alertas/informe` | `periodo` (req.) | Informe consolidado (objeto único) |
| `GET /v1/alertas` | `periodo` (req.), `severidad`, `tipo`, `velocidad`, `seccion`, paginación | Lista filtrable |

`/v1/alertas/informe` → `data`: `{periodo, cobertura_global, resumen, alertas[],
skipped[]}`. Cada alerta lleva `severidad`, `confianza`, `naturaleza`,
`cobertura`, `contexto` y **`evidencias`** (identificadores de aplicaciones/
contratos/acuerdos para que el frontal permita "ver por qué"). El lenguaje es
descriptivo, **nunca acusatorio**.

## 8. Diccionario de enums (estables)

| Enum | Valores |
|---|---|
| `naturaleza` | `exacta`, `aproximada`, `indiciaria` |
| `severidad` | `informativa`, `a_revisar`, `destacada` |
| `confianza` | `alta`, `media`, `baja` |
| `estado` (alerta) | `ALERTA`, `SKIPPED` |
| `tipo` (alerta) | `ritmo_ejecucion`, `modificacion_atipica`, `concentracion_adjudicatarios`, `anticipacion_compromiso` |
| `velocidad` (fuente) | `contable`, `compromisos_juridicos`, `decisiones_politicas` |
| `velocidad` (filtro alertas) | `contable`, `compromisos`, `cruce` |
| `nivel` (agregación) | `AGE`, `seccion`, `servicio`, `dg`, `programa`, `economica`, `capitulo` |
| `dg_nivel_organico` | `MINISTERIO`, `SECRETARIA_ESTADO`, `SUBSECRETARIA`, `DIRECCION_GENERAL`, `ORGANISMO`, `OTRO`, `residual` |

## 9. Cómo interpretar los metadatos de fiabilidad (crítico)

Esta herramienta es honesta porque **no esconde la calidad del dato**. El frontal
debe mostrar estos metadatos, no descartarlos.

### Naturaleza

- **`exacta`**: aritmética sobre magnitudes auditables y comparables (ejecución
  IGAE, volúmenes PLACSP/BDNS, HHI). Se puede presentar como cifra firme.
- **`aproximada`**: el importe procede de **extracción falible** de texto (BOE,
  Consejo de Ministros). Preséntalo SIEMPRE con su confianza (alta/media) y nunca
  como un total cerrado.
- **`indiciaria`**: **cruce de velocidades** (compromiso vs ORN, decisión vs
  compromiso). **No es una identidad contable** (hay IVA, plurianualidad,
  contratos que no llegan a ORN). Muestra ambas magnitudes por separado y trata
  el ratio como un indicio, no una conciliación.

### Cobertura de anclaje

En compromisos y nivel DG, `meta.cobertura_anclaje` dice **qué fracción del
importe/gasto se ha podido atribuir** a un servicio/unidad. Ejemplo: una
concentración por DG donde `pct_anclado_a_servicio` es bajo es una señal **débil**
— el frontal debe atenuarla, no presentarla como firme. Nunca interpretes una
cifra de cobertura parcial como si vigilara la totalidad.

### Servicio vs Dirección General (y la prórroga)

- La unidad **estable interanual** es el **servicio presupuestario**. La
  **dirección general** es su lectura **nominal** vía el crosswalk, que solo
  cubre el ejercicio del seed (**2026**).
- En `ServicioModel`, `dg_equivalencia_aproximada=true` (con `dg_nota`) marca que
  se está leyendo un servicio histórico con la estructura DG de 2026: la
  equivalencia es **aproximada** y el frontal debe señalarlo al navegar a años
  anteriores.
- **Cobertura DG**: solo ~**27% de la ORN** se gestiona por unidades con anclaje
  DIR3 (el resto —Deuda, Clases Pasivas, transferencias a entes/SS— no es una DG
  ministerial). El encabezado de los informes de alertas
  (`cobertura_global.pct_orn_vigilable_a_nivel_dg`) lo declara. **Ninguna
  respuesta vigila la totalidad del gasto a nivel DG.**
- **Prórroga 2025-P**: en ejercicios prorrogados, el crédito inicial es el
  *operativo* (prorrogado), no el inicial *legal* de un PGE propio; las
  comparativas interanuales contra un ejercicio prorrogado lo advierten en
  `meta.advertencias`. Muestra esa advertencia: la cifra comparada es orientativa.

## 10. Estabilidad

El esquema OpenAPI de los modelos clave (`Meta`, `Paginacion`, `SeccionModel`,
`ServicioModel`, `AlertaModel`, `ErrorDetalle`) está fijado por tests de
contrato: un cambio de campo rompe el test y obliga a una decisión consciente de
versión. El contrato fino seguirá evolucionando de forma **compatible** bajo v1;
lo incompatible irá a v2.
