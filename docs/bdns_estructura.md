# BDNS / SNPSAP — estructura de la fuente y modelo canónico de concesiones

> Reconocimiento hecho con llamadas reales a la API el **2026-06-12**
> (endpoint de búsqueda de concesiones, varias ventanas y ámbitos). La muestra
> real reducida vive en `tests/fixtures/bdns_concesiones_page*.json` (el NIF de
> personas físicas llega **ya enmascarado de origen**; no hay dato personal
> adicional que proteger en el fixture).

## 1. Qué publica el SNPSAP

El Sistema Nacional de Publicidad de Subvenciones y Ayudas Públicas
(`infosubvenciones.es`, antes BDNS) publica **convocatorias** y **concesiones**
de TODO el sector público (estatal, autonómico y local). Es la segunda pata de
la capa de "compromisos jurídicos" (CLAUDE.md §3): la concesión anticipa la ORN
del capítulo 4/7 igual que la adjudicación PLACSP anticipa la del 2/6.

Volumen observado (2026-06): **~26,8 M de concesiones** totales, de las que
**~17 M son estatales** — dominadas por microayudas instrumentadas vía
ICO/Red.es. Por eso el raw NO se versiona en git (ver `.gitignore`) y la
descarga se acota por ventana de fechas.

## 2. API y entrega (verificadas)

Base: `https://www.infosubvenciones.es/bdnstrans/api` — pública, sin clave.

- **Endpoint**: `GET /concesiones/busqueda`, paginación estilo Spring:
  `page` (base 0) y `pageSize` (honrado hasta **10000**).
- **Filtros verificados**:
  - `tipoAdministracion`: `C`=Estado, `A`=autonómica, `L`=local (v1 usa `C`;
    el resto queda etiquetado `fuera_perimetro` si aparece, no descartado).
  - `fechaDesde` / `fechaHasta` en **DD/MM/AAAA**, ventana **inclusiva** sobre
    la **fecha de concesión** → es la palanca de la descarga incremental
    (diaria/semanal) y del histórico por años.
- **Envelope** de respuesta: `content` (lote), `totalElements`, `totalPages`,
  `last`, `first`, `number`, `size`. La paginación itera hasta `last: true`.
- *Soft-200*: el WAF del host (BIG-IP de la Administración Presupuestaria)
  devuelve HTML de rechazo con HTTP 200. El extractor valida que cada página es
  JSON con `content` ANTES de escribirla en raw (fail loud).
- El aviso legal se reserva "medidas restrictivas" ante abuso del API: el
  extractor aplica una pausa cortés entre páginas y los reintentos con backoff
  de la primitiva común de `extractors/base.py`.

El raw se guarda en
`data/raw/bdns/<fecha_captura>/concesiones/<ámbito>_<desde>_<hasta>/page_NNNNN.json`,
una página por fichero. Una página ya presente no se re-descarga ni se modifica
(idempotencia + inmutabilidad); repetir una ventana otro día crea otro
directorio de captura.

## 3. Anatomía de una concesión (JSON observado)

```json
{
  "id": 153038882,                  // id numérico de plataforma: CLAVE estable
  "codConcesion": "SB153038882",    // = "SB" + id
  "fechaConcesion": "2026-06-02",   // fecha del compromiso jurídico
  "fechaAlta": "2026-06-05",        // alta en la plataforma (≥ fechaConcesion)
  "beneficiario": "A10736791 ASTILLEROS RÍA DE VIGO, S.A.",
  "idPersona": 17717588,            // id estable del beneficiario en plataforma
  "instrumento": "SUBVENCIÓN y ENTREGA DINERARIA SIN CONTRAPRESTACIÓN ",
  "importe": 2421206.45,
  "ayudaEquivalente": 2421206.45,
  "urlBR": "https://www.boe.es/...",
  "tieneProyecto": false,
  "numeroConvocatoria": "840944",   // código BDNS de la convocatoria
  "idConvocatoria": 1042505,
  "convocatoria": "Real Decreto 485/2025, de 17 de junio, ...",
  "nivel1": "ESTADO",               // ámbito de administración (texto)
  "nivel2": "MINISTERIO DE INDUSTRIA Y TURISMO",
  "nivel3": "DIRECCIÓN GENERAL DE PROGRAMAS INDUSTRIALES",
  "codigoInvente": null             // INVENTE (no DIR3); suele venir nulo aquí
}
```

Hechos clave del reconocimiento:

- **La API NO publica el código DIR3 del órgano concedente** — solo la
  jerarquía administrativa como texto (`nivel1/nivel2/nivel3`) y, en
  convocatorias, un `codigoInvente` (inventario INVENTE, distinto de DIR3).
- El **beneficiario** llega como un único campo `"<NIF> <NOMBRE>"`. El NIF de
  personas físicas viene **enmascarado de origen** (`***dddd**`, RGPD); el de
  jurídicas, en claro. El parser separa NIF/nombre y clasifica física/jurídica
  por la forma del identificador; si el primer token no tiene forma de NIF,
  todo el texto queda como nombre (no se inventa separación).
- TODA ausencia es **nulo explícito, nunca cero** (importes incluidos).

## 4. Grano del modelo canónico

**Una fila por CONCESIÓN** (`fact_subvenciones`, clave natural `concesion_id`).
La convocatoria es un **atributo** de la fila (id, código BDNS y título), nunca
una fila propia: sumar convocatorias y concesiones a la vez sería doble conteo.
El `presupuestoTotal` de la convocatoria es un techo de licitación, no gasto
comprometido, y por eso **no entra en este hecho** (mismo patrón que
expediente↔lotes en PLACSP, `docs/placsp_estructura.md` §4).

`periodo` del hecho = mes de la **fecha de concesión** (el compromiso
jurídico); en su defecto, fecha de alta y, en último término, la de captura.

## 5. Anclaje orgánico sin DIR3

Al no haber DIR3, el anclaje (`transform/anclaje_organico.py`) resuelve el
órgano concedente **por denominación normalizada** (la normalización de la
Fase 1) y luego delega en el mismo motor DIR3 → (sección, servicio) que PLACSP:

1. `nivel1 != ESTADO` → `fuera_perimetro` / `no_estatal` (la inmensa mayoría
   de la subvención es autonómica/local).
2. Override manual (`db/seeds/crosswalk_organo_bdns_dir3.csv`, editable y
   versionado) → DIR3. Cubre los nombres que la BDNS escribe distinto del
   directorio (p. ej. el doble prefijo "AGENCIA ESTATAL AGENCIA ESPAÑOLA…").
3. Coincidencia exacta de `nivel3` dentro del subárbol del ministerio
   (`nivel2`) en `dim_organica`; después, coincidencia por conjunto de tokens
   (sin stopwords) en el mismo subárbol.
4. Sin ministerio resuelto: solo se acepta una coincidencia exacta y ÚNICA en
   todo el directorio.
5. Nada de lo anterior → `sin_anclar` / `organo_no_resuelto` (contabilizado,
   nunca descartado).

El DIR3 resuelto pasa por el motor común, así que las fronteras de perímetro
se aplican igual que en PLACSP: una unidad de un ente con presupuesto propio
(`tipo_entidad != MN`, p. ej. EPE Red.es, ICO, agencias) queda en
`organica_sin_servicio`/`entidad_instrumental` — su gasto nunca aparecerá en
la ORN del servicio del ministerio.

## 6. Republicaciones y semántica de carga

La BDNS **corrige y reinserta** concesiones con el mismo `id` (observado en el
fixture: mismo id con `fechaAlta` posterior e importe corregido).

- **Dentro de una captura** (parser): gana la foto con mayor `fecha_alta`
  (desempate determinista por orden de página).
- **En el warehouse** (carga): upsert "última foto" por `concesion_id` — se
  borra la fila previa de cada concesión presente en el lote y se reinserta.
  Recargar el mismo raw es idempotente (CLAUDE.md §2); el historial de fotos
  vive en la capa raw, no en el warehouse.
- **Sin checks contables**: las subvenciones NO tienen que cuadrar con la ORN
  (magnitudes distintas, no subconjuntos). El contrato de entrada es
  `bdns_concesion_schema` (pandera) + el anclaje etiquetado (nunca NULL).
