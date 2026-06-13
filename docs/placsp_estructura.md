# PLACSP — estructura de la fuente y modelo canónico de adjudicaciones

> Reconocimiento hecho con descargas reales el **2026-06-12** (feed cabecera de
> la sindicación 643 y ZIP anuales 2012 y 2026). Si la plataforma cambia de
> maquetación, NO se modifica el parser `codice2`: se añade un vintage nuevo
> (CLAUDE.md §2). La muestra real reducida vive en
> `tests/fixtures/placsp_643_page*.atom`.

## 1. Qué publica la plataforma

`contrataciondelsectorpublico.gob.es → Datos Abiertos` ofrece tres datasets en
ATOM/XML CODICE:

| Dataset | Sindicación | v1 |
|---|---|---|
| Licitaciones de los perfiles del contratante en PLACSP (sin menores) | **643** | **SÍ** |
| Agregación de plataformas autonómicas | 1044 | No (CCAA fuera de perímetro) |
| Contratos menores | — | No (grano distinto; se añadirá con su propio fixture) |

La 643 es la capa de "compromisos jurídicos" (CLAUDE.md §3): las adjudicaciones
anticipan la ORN y el órgano de contratación se identifica (idealmente) por
DIR3, que es lo que permite anclar a la espina presupuestaria.

## 2. Entrega y URLs (verificadas)

- **ZIP anual** (volcado masivo, 2012-año en curso):
  `…/sindicacion_643/licitacionesPerfilesContratanteCompleto3_<AÑO>.zip`.
  Contiene uno o varios `.atom` con la misma gramática que el feed.
- **Feed incremental**: `…/licitacionesPerfilesContratanteCompleto3.atom`
  (cabecera, se renueva a diario) paginando hacia atrás con
  `atom:link@rel="next"`; máx. 500 entradas por fichero (cabecera real
  observada: 338).
- El nombrado mensual (`…_YYYYMM.zip`) resuelve pero devuelve >150 MB no
  acotados al mes: **no se usa**; el año en curso se cubre con su ZIP anual.
- *Soft-200*: nombres inexistentes devuelven HTML con HTTP 200. El extractor
  exige la firma del contenido (`PK\x03\x04` para ZIP, `<?xm` para ATOM) y
  aborta sin escribir si no coincide.

El raw se guarda en `data/raw/placsp/<fecha_captura>/643/{anual|incremental}/`.
A diferencia de IGAE (<1,5 MB por fichero), una captura pesa 10-160 MB: el raw
PLACSP **no se versiona en git** (ver `.gitignore`); lo regenera el extractor.

## 3. Anatomía de una entrada CODICE 2.x

Cada `atom:entry` es la foto completa de un expediente. Lo que usa el parser:

```
entry
├── id                                  → licitacion_id (tramo final numérico)
├── updated                             → fecha_actualizacion
└── cac-place-ext:ContractFolderStatus
    ├── cbc:ContractFolderID            → expediente_id (¡NO único entre órganos!)
    ├── cbc-place-ext:ContractFolderStatusCode → estado_cod (PUB|EV|ADJ|RES|ANUL|…)
    ├── cac-place-ext:LocatedContractingParty
    │   ├── cbc:ContractingPartyTypeCode → organo_tipo_cod
    │   └── cac:Party/cac:PartyIdentification/cbc:ID
    │       @schemeName ∈ {DIR3, NIF, ID_PLATAFORMA} → organo_id / organo_dir3_cod
    ├── cac:ProcurementProject          → tipo/subtipo, CPV, cac:BudgetAmount
    │   (TaxExclusiveAmount=sin IVA, TotalAmount=con IVA, EstimatedOverall…=valor estimado)
    ├── cac:TenderResult (0..n, uno por lote adjudicado)
    │   ├── cbc:ResultCode (8/9=adjudicado/formalizado, 3=desierto…)
    │   ├── cbc:AwardDate, cbc:ReceivedTenderQuantity, cbc:SMEAwardedIndicator
    │   ├── cac:WinningParty            → adjudicatario (ID + esquema + nombre)
    │   ├── cac:Contract/cbc:IssueDate  → fecha_formalizacion
    │   └── cac:AwardedTenderedProject
    │       ├── cbc:ProcurementProjectLotID → lote_id
    │       └── cac:LegalMonetaryTotal/cbc:PayableAmount → importe_adjudicacion
    └── cac:TenderingProcess/cbc:ProcedureCode → procedimiento_cod
```

Las bajas de sindicación llegan como lápidas `at:deleted-entry` (tombstones
Atom): se conservan como fila mínima con `estado_cod='BAJA'`.

## 4. Grano del modelo canónico

**Una fila por (licitación, lote adjudicado)**; los expedientes sin
adjudicación (en plazo, evaluación, desiertos) emiten UNA fila con
resultado/importe nulos para no perderse.

- `licitacion_id` = id numérico de plataforma del `atom:id`. VERIFICADO sobre
  el ZIP 2012 (19.000 entradas, 11.262 licitaciones, 5.646 ids republicados):
  es estable entre republicaciones. El `ContractFolderID` NO sirve de clave
  ("12/2026" se repite entre órganos distintos).
- `lote_id` = `ProcurementProjectLotID` oficial; `'0'` si el expediente no
  tiene lotes; numeración sintética posicional si la fuente lo omite en
  multi-lote.
- `es_cabecera_expediente`: exactamente una fila por licitación lleva las
  magnitudes de expediente (presupuestos, valor estimado). Reglas de oro:
  - gasto comprometido = Σ `importe_adjudicacion` (todas las filas);
  - presupuesto licitado = Σ `presupuesto_*` WHERE `es_cabecera_expediente`.
- `periodo` = mes de la última `AwardDate` (momento del compromiso jurídico);
  en su defecto, mes del `atom:updated`.
- Importes con/sin IVA SEPARADOS; toda ausencia es nulo explícito, nunca 0.

El contrato de entrada lo valida `placsp_adjudicacion_schema` (pandera). El
anclaje orgánico (`transform/placsp_anclaje.py`) añade
`seccion_cod/servicio_cod` + `anclaje_tipo/anclaje_senal`: nada se descarta,
lo no resoluble queda etiquetado (`fuera_perimetro`, `sin_anclar`) y contado.

## 5. Republicaciones y semántica de carga

PLACSP republica la misma licitación cada vez que cambia de estado
(PUB → EV → ADJ → RES); un feed/ZIP contiene varias fotos de la misma
licitación y la más reciente es la vigente.

- **Dentro de una captura** (parser): se conserva el bloque ENTERO de filas de
  la foto con mayor `fecha_actualizacion` por `licitacion_id`.
- **En el warehouse** (carga): upsert "última foto" — se borra el bloque
  completo de cada licitación presente en el lote y se reinserta. Así una
  republicación con menos lotes no deja filas zombis y recargar el mismo raw
  es idempotente.
- **El historial de fotos** no vive en el warehouse: queda en la capa raw
  versionada y/o regenerable (git-scraping).
- `update` carga solo las capturas de `data/raw/placsp/` posteriores a
  `max(fecha_captura)` ya aplicada; `build` las recarga todas en orden
  ascendente (la más reciente gana).
