# Cobertura de fuentes — las tres velocidades (cierre de Fase 4)

> Documento puente hacia la Fase 5 (analítica) y hacia el contrato de datos del
> frontal. Resume, por fuente: **periodicidad real conseguida**, **profundidad
> de anclaje** orgánico (DG / servicio / sección), **tasa de anclaje observada**
> y **limitaciones conocidas**. Se actualiza al incorporar o reverificar una
> fuente. Las cifras de tasa proceden de la verificación sobre datos reales
> (recon 2026-06-10/12) y de los fixtures de regresión del repo.

El sistema cubre las **tres velocidades** de CLAUDE.md §3 sobre la misma espina
orgánica (sección → servicio → DG vía DIR3):

| Velocidad | Fuentes | Naturaleza | Anclaje | Periodicidad |
|---|---|---|---|---|
| **Contable** (verdad) | IGAE Anexo I | tabla auditable | servicio (+ programa/económica) | mensual |
| **Compromisos jurídicos** | PLACSP, BDNS | tabla auditable | servicio/DG (DIR3) | diaria |
| **Decisiones políticas** | BOE, Consejo de Ministros | texto semiestructurado | **sección** | diaria / semanal |

La regla de oro de la tercera velocidad: **es señal y trazabilidad, no
contabilidad**. No se cuadra con la ORN, no entra en los checks contables de la
Fase 3, y la extracción degrada con elegancia (campo no derivable → nulo + texto
bruto conservado; importe con grado de confianza, nunca un cero falso).

---

## 1. IGAE — Ejecución AGE, Anexo I (`igae_anexo_i`)

- **Periodicidad real**: mensual, ~25–30 días tras el cierre de mes; histórico
  desde 2003. Acumulado del ejercicio (el periodo máximo cargado es la foto
  vigente).
- **Profundidad de anclaje**: máxima — **aplicación presupuestaria completa**
  (sección + servicio + programa + económica + territorialización). Es la propia
  estructura presupuestaria, no requiere crosswalk.
- **Tasa de anclaje**: 100 % por construcción (la fuente ES la espina orgánica);
  los servicios no presentes en el seed PGE se **derivan** del propio Anexo I.
- **Cobertura de magnitudes**: crédito inicial, crédito definitivo y ORN. NO
  trae comprometido ni pagos (llegarán de Anexo II/Cuadros). Por eso el check
  "pagos ≤ ORN" no aplica a esta fuente.
- **Limitaciones**: parsers por *vintage* (la maquetación cambia entre
  ejercicios); el `.xls` de 2015–abril 2016 exige `xlrd`.

## 2. PLACSP — adjudicaciones, sindicación 643 (`placsp`)

- **Periodicidad real**: diaria (incremental ATOM) + ZIP anuales desde 2012 para
  retrocarga.
- **Profundidad de anclaje**: **servicio/DG** — el órgano de contratación trae
  su DIR3 directo; se asciende por la cadena de padres hasta el servicio del
  crosswalk. Frontera de entes instrumentales (presupuesto propio →
  `organica_sin_servicio`).
- **Tasa de anclaje**: depende del perímetro del volcado; el grueso AGE ancla a
  servicio por DIR3 directo o por ancestro. Lo no AGE (CCAA/local/universidades)
  se etiqueta `fuera_perimetro`; sin DIR3 → `sin_anclar`. Todo se conserva y se
  cuenta (nada se descarta).
- **Limitaciones**: el dato bruto CODICE es ruidoso; la robustez vive en la
  normalización y el anclaje. El `ContractFolderID` no es único entre órganos
  (la clave estable es el id numérico de plataforma).

## 3. BDNS / SNPSAP — concesiones de subvención (`bdns`)

- **Periodicidad real**: diaria, por ventana de concesión.
- **Profundidad de anclaje**: **servicio/DG por denominación** — la API NO
  publica DIR3 (verificado 2026-06-12): el órgano concedente llega como texto
  `nivel1/nivel2/nivel3`. Se resuelve `nivel3` → DIR3 dentro del subárbol del
  ministerio (`nivel2`) y de ahí al servicio, con un crosswalk de overrides para
  los casos difíciles.
- **Tasa de anclaje**: lo estatal (`nivel1 = ESTADO`) ancla por denominación;
  la inmensa mayoría de la subvención española es autonómica/local →
  `fuera_perimetro` (correcto, es señal de perímetro, no pérdida).
- **Limitaciones**: NIF de personas físicas enmascarado de origen (RGPD); la
  resolución por nombre puede fallar en colisiones no cubiertas por overrides →
  `sin_anclar` (etiquetado).

## 4. BOE — sumario diario, disposiciones de interés (`boe_sumario`)

- **Periodicidad real**: diaria (API de datos abiertos; verificado 2026-06-12).
  Sumarios y disposiciones < 300 KB → se versionan en git (git-scraping).
- **Profundidad de anclaje**: **sección** — el departamento proponente del
  sumario (forma oficial "MINISTERIO DE …") resuelve a sección presupuestaria.
  NO se fuerza un servicio que el texto no da.
- **Qué se ingiere**: el extractor **prefiltra** por sección + título y solo baja
  lo de interés (convocatorias y concesiones directas de subvención,
  modificaciones de crédito con título explícito). Personal, contratación
  (ya cubierta por PLACSP) y justicia se descartan en el prefiltro.
- **Tasa de anclaje (fixtures de regresión)**: 2/2 disposiciones ancladas a
  sección (Transportes → 17, Educación → 18). La forma oficial del departamento
  mapea de forma muy fiable contra el seed PGE.
- **Extracción de importe**: del texto, con confianza (alta = "importe/cuantía …
  euros" o `(N €)`; media = cifra suelta; sin_importe = sin cifra parseable). El
  `BDNS(Identif.)` de los extractos enlaza con la concesión/convocatoria BDNS.
- **Limitaciones verificadas**:
  - Las modificaciones de crédito **embebidas en RDL de medidas amplias** (p. ej.
    RDL 6/2024 de la DANA) no se nombran en el título → caen en `otro` y no se
    detectan como modificación. Es señal, no contabilidad: minar cada RDL queda
    fuera de alcance.
  - Barriendo diciembre 2024 no apareció ni un título explícito de "crédito
    extraordinario / transferencia de crédito" en la sección del Estado: el
    grueso de la señal BOE útil son **convocatorias y concesiones de subvención**.
  - `analisis/tipo` es fiable cuando está (subvenciones, tipo 63) pero los RD/RDL
    no lo rellenan; por eso la clasificación no depende solo de ese campo.

## 5. Consejo de Ministros — referencias de La Moncloa (`consejo_ministros`)

- **Periodicidad real**: semanal (normalmente martes). HTML < 300 KB → se
  versiona. A menudo **antecede incluso al compromiso jurídico** (autoriza el
  gasto antes de la adjudicación/concesión/RD).
- **Profundidad de anclaje**: **sección** por ministerio proponente. El `<h3>`
  va en **forma corta** ("Hacienda", "Para la Transición Ecológica y el Reto
  Demográfico"); el anclaje normaliza y compara por conjunto de tokens
  significativos (descontando "ministerio").
- **Qué se ingiere**: TODOS los acuerdos del bloque SUMARIO (lista completa).
  A diferencia del BOE, aquí nada se prefiltra: los irrelevantes quedan en
  `otro`/`personal` y se cuentan.
- **Tasa de anclaje (fixtures de regresión)**:
  - Referencia **2026** (vintage actual): **36/36** acuerdos anclados a sección.
  - Referencia **2018** (vintage antiguo): 6/33 ancladas (el resto,
    `ministerio_no_mapeable`): las denominaciones de 2018 ("Hacienda y Función
    Pública", "Energía, Turismo y Agenda Digital"…) no están en el seed PGE
    vigente; el **registro histórico de secciones** recupera las que llega a
    cubrir (p. ej. "Hacienda y Función Pública" → sección 15 vía la estructura
    de 2023). Ampliar la retrocarga del histórico subiría esta tasa.
- **Vigencia**: el anclaje y la denominación de sección de las vistas usan la
  estructura del ejercicio más cercano disponible (seed + histórico), no una
  estructura fija.
- **Limitaciones**:
  - Sin id oficial por acuerdo → clave sintética por **orden** en el SUMARIO; la
    carga reemplaza el bloque completo de la fecha (idempotente aunque cambie el
    nº de acuerdos).
  - Estructuras pre-2018 no verificadas: un vintage no reconocido falla *loud*.
  - La clasificación de tipo es léxica (señal, no certeza jurídica): un acuerdo
    ambiguo cae en `otro`, que se conserva.

---

## 6. Implicaciones para la Fase 5 (analítica) y el frontal

- **Cruce de velocidades por sección/servicio**: las tres velocidades comparten
  la espina orgánica, pero a **distinta profundidad** (servicio en IGAE/PLACSP/
  BDNS, sección en BOE/CdM). El análisis comparado debe **agregar a sección**
  para mezclar las tres; comparar a nivel de servicio solo es válido entre las
  dos primeras velocidades.
- **El importe de la tercera velocidad NO es aditivo con la ORN**: es un techo de
  intención/autorización; úsese como alerta temprana ("el Consejo autorizó X / el
  BOE publicó la convocatoria Y"), nunca como sumando del gasto ejecutado.
- **Metadatos de frescura para el frontal**: cada hecho conserva `fecha_captura`,
  `url_oficial` y `texto_bruto`; el frontal debe exponer la confianza del importe
  y el `anclaje_tipo/anclaje_senal` para que el dato sea autoexplicativo y
  auditable.
- **Puente BDNS↔BOE**: el `bdns_id` de los extractos del BOE enlaza con la
  convocatoria/concesión de la BDNS — base para conciliar señal (BOE) con
  compromiso (BDNS) en la Fase 5.
