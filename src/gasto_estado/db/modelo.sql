-- ============================================================================
-- modelo.sql — DDL del warehouse analítico (DuckDB)
--
-- Decisiones de modelado documentadas en docs/modelo_datos.md. Resumen:
--   * fact_ejecucion unificado (crédito + ejecución comparten grano y clave);
--     cada fuente escribe SUS filas y declara su cobertura de magnitudes.
--   * El Anexo I es ACUMULADO del ejercicio: cada (aplicación, periodo) es una
--     fila; el "último dato" de un ejercicio es su periodo máximo cargado.
--   * Ancla orgánica del hecho: dim_seccion_servicio por (ejercicio, seccion,
--     servicio). dim_organica (DIR3, SCD2) es referencia, no FK del hecho,
--     mientras su crosswalk presupuesto<->DIR3 siga pendiente.
--   * Los hechos de la Fase 4 (fact_contratos, fact_subvenciones,
--     fact_acuerdos_cdm) NO se crean aquí: su esquema se fijará tras
--     inspeccionar las fuentes reales (CLAUDE.md §9). dim_fuente ya reserva
--     sus códigos y velocidades.
--
-- Idempotente: CREATE ... IF NOT EXISTS en todo; ejecutable sobre un fichero
-- nuevo (build) o existente (update).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Dimensiones
-- ----------------------------------------------------------------------------

-- Fuentes de datos: las tres velocidades de CLAUDE.md §3. Catálogo cerrado,
-- poblado aquí (es contrato del modelo, no dato).
CREATE TABLE IF NOT EXISTS dim_fuente (
    fuente_cod    VARCHAR PRIMARY KEY,
    denominacion  VARCHAR NOT NULL,
    velocidad     VARCHAR NOT NULL CHECK (
        velocidad IN ('contable', 'compromisos_juridicos', 'decisiones_politicas')
    ),
    periodicidad  VARCHAR NOT NULL,
    fase          INTEGER NOT NULL  -- fase del proyecto que la incorpora
);

INSERT OR IGNORE INTO dim_fuente VALUES
    ('igae_anexo_i',  'IGAE — Ejecución AGE, Anexo I (orgánica/programa/económica)',
     'contable', 'mensual', 3),
    -- Reservas de la Fase 4 (capa de alta frecuencia):
    ('igae_anexo_ii', 'IGAE — Ejecución AGE, Anexo II', 'contable', 'mensual', 4),
    ('igae_cuadros',  'IGAE — Ejecución AGE, Cuadros',  'contable', 'mensual', 4),
    ('placsp',        'Plataforma de Contratación del Sector Público (CODICE)',
     'compromisos_juridicos', 'diaria', 4),
    ('bdns',          'Base de Datos Nacional de Subvenciones (SNPSAP)',
     'compromisos_juridicos', 'diaria', 4),
    ('boe_sumario',   'BOE — sumario diario (modificaciones de crédito, RD)',
     'decisiones_politicas', 'diaria', 4),
    ('consejo_ministros', 'Consejo de Ministros — acuerdos de gasto',
     'decisiones_politicas', 'semanal', 4);

-- Periodos cargados. presupuesto = etiqueta oficial del presupuesto que rige
-- el ejercicio ('2025-P' = prórroga del PGE 2025); NULL si no está asertada
-- para ese ejercicio en los seeds.
CREATE TABLE IF NOT EXISTS dim_periodo (
    periodo        VARCHAR PRIMARY KEY CHECK (periodo ~ '^\d{4}-\d{2}$'),
    ejercicio      INTEGER NOT NULL,
    mes            INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    presupuesto    VARCHAR,
    fecha_fin_mes  DATE NOT NULL
);

-- Espina orgánica presupuestaria: sección (ministerio) -> servicio. SCD por
-- ejercicio: el mismo código significa cosas distintas en ejercicios distintos
-- y cada hecho ancla con la entrada de SU ejercicio (docs/modelo_datos.md §1c).
-- origen: 'seed_pge' (estructura oficial PGE-ROM, autoritativa) o
-- 'derivado_igae' (creada por la carga desde el propio Anexo I cuando el seed
-- no cubre el ejercicio o el servicio — p. ej. servicio 50 MRR).
CREATE TABLE IF NOT EXISTS dim_seccion_servicio (
    ejercicio              INTEGER NOT NULL,
    seccion_cod            VARCHAR NOT NULL CHECK (seccion_cod ~ '^\d{2}$'),
    servicio_cod           VARCHAR NOT NULL CHECK (servicio_cod ~ '^\d{2}$'),
    seccion_denominacion   VARCHAR,           -- NULL en derivadas (el Anexo I no la trae)
    servicio_denominacion  VARCHAR NOT NULL,  -- sin nombre no hay ancla (fail loud en carga)
    presupuesto            VARCHAR,
    origen                 VARCHAR NOT NULL CHECK (origen IN ('seed_pge', 'derivado_igae')),
    PRIMARY KEY (ejercicio, seccion_cod, servicio_cod)
);

-- Árbol DIR3 (SCD tipo 2, Fase 1). Activo de referencia para el crosswalk
-- servicio<->DIR3 y el frontal; seccion_cod/servicio_cod siguen pendientes del
-- crosswalk, por eso NO es FK de fact_ejecucion.
CREATE TABLE IF NOT EXISTS dim_organica (
    seccion_cod              VARCHAR,
    servicio_cod             VARCHAR,
    dir3_cod                 VARCHAR NOT NULL,
    denominacion             VARCHAR NOT NULL,
    dir3_padre_cod           VARCHAR,
    ministerio_dir3_cod      VARCHAR,
    ministerio_denominacion  VARCHAR,
    nivel_jerarquico         INTEGER,
    nivel_organico           VARCHAR,
    nivel_organico_senal     VARCHAR,
    -- Tipo de entidad pública DIR3 (MN = estructura ministerial AGE; OA/AT/EE/
    -- SM/AP/… = ente con presupuesto propio): frontera de perímetro del anclaje.
    tipo_entidad             VARCHAR,
    estado                   VARCHAR,
    fecha_inicio             DATE NOT NULL,
    fecha_fin                DATE,
    PRIMARY KEY (dir3_cod, fecha_inicio)
);

-- Clasificación por programas (CLAUDE.md §3): área de gasto (1 díg.) ->
-- política (2) -> grupo de programas (3) -> programa (4 car.; el 5º opcional
-- es subprograma territorializado, p. ej. 121M2 de Defensa). La jerarquía se
-- deriva del propio código. denominacion: NULL — el Anexo I no nombra los
-- programas; se incorporará de fuente oficial (PGE-ROM) cuando se verifique.
CREATE TABLE IF NOT EXISTS dim_programa (
    programa_cod        VARCHAR PRIMARY KEY CHECK (programa_cod ~ '^[0-9A-ZÑ]{4,5}$'),
    area_gasto_cod      VARCHAR NOT NULL,  -- 1er carácter
    politica_cod        VARCHAR NOT NULL,  -- 2 primeros
    grupo_programas_cod VARCHAR NOT NULL,  -- 3 primeros
    programa_base_cod   VARCHAR NOT NULL,  -- 4 primeros (== programa_cod si 4 car.)
    denominacion        VARCHAR
);

-- Clasificación económica (CLAUDE.md §3): capítulo (1 díg.) -> artículo (2) ->
-- concepto (3) -> subconcepto (5) -> partida (7). El hecho referencia el nivel
-- que trae el fichero (3/5/7); los ancestros (capítulo, artículo) se
-- sintetizan para poder navegar/agregaar la jerarquía.
-- denominacion_origen: 'catalogo_estatico' (capítulos de gasto, estructura
-- normativa de los PGE, Ley 47/2003 / Orden EHA/657/2007), 'derivado_anexo_i'
-- (modal de aplicacion_denominacion: orientativa, una misma económica se
-- describe distinto según el programa) o NULL (sin denominación).
CREATE TABLE IF NOT EXISTS dim_economica (
    economica_cod       VARCHAR PRIMARY KEY CHECK (economica_cod ~ '^\d{1,3}$|^\d{5}$|^\d{7}$'),
    nivel               VARCHAR NOT NULL CHECK (
        nivel IN ('capitulo', 'articulo', 'concepto', 'subconcepto', 'partida')
    ),
    capitulo_cod        VARCHAR NOT NULL,  -- 1er dígito
    articulo_cod        VARCHAR,           -- 2 primeros (NULL en nivel capítulo)
    concepto_cod        VARCHAR,           -- 3 primeros (NULL por encima de concepto)
    denominacion        VARCHAR,
    denominacion_origen VARCHAR CHECK (
        denominacion_origen IN ('catalogo_estatico', 'derivado_anexo_i')
    )
);

-- Capítulos de gasto: denominaciones normativas estables (estructura económica
-- de los estados de gastos de los PGE). Catálogo curado, no scraping.
INSERT OR IGNORE INTO dim_economica
    (economica_cod, nivel, capitulo_cod, articulo_cod, concepto_cod,
     denominacion, denominacion_origen)
VALUES
    ('1', 'capitulo', '1', NULL, NULL, 'Gastos de personal', 'catalogo_estatico'),
    ('2', 'capitulo', '2', NULL, NULL, 'Gastos corrientes en bienes y servicios', 'catalogo_estatico'),
    ('3', 'capitulo', '3', NULL, NULL, 'Gastos financieros', 'catalogo_estatico'),
    ('4', 'capitulo', '4', NULL, NULL, 'Transferencias corrientes', 'catalogo_estatico'),
    ('5', 'capitulo', '5', NULL, NULL, 'Fondo de contingencia y otros imprevistos', 'catalogo_estatico'),
    ('6', 'capitulo', '6', NULL, NULL, 'Inversiones reales', 'catalogo_estatico'),
    ('7', 'capitulo', '7', NULL, NULL, 'Transferencias de capital', 'catalogo_estatico'),
    ('8', 'capitulo', '8', NULL, NULL, 'Activos financieros', 'catalogo_estatico'),
    ('9', 'capitulo', '9', NULL, NULL, 'Pasivos financieros', 'catalogo_estatico');

-- ----------------------------------------------------------------------------
-- Hechos
-- ----------------------------------------------------------------------------

-- Ejecución presupuestaria por aplicación (detalle del Anexo I; en Fase 4,
-- también Anexo II/Cuadros como filas propias de esa fuente).
--
--  * Clave natural = aplicación presupuestaria completa x periodo x fuente.
--  * provincia_cod NO es nullable: 'NT' materializa "no territorializado"
--    (NULL en clave rompería la idempotencia: DuckDB trata cada NULL como
--    distinto). 'DT' = Diversos Territorios (valor real del histórico).
--  * Magnitudes nullable: NULL = sin dato ('-' del fichero) o magnitud no
--    cubierta por la fuente; `cobertura` distingue ambos casos. NUNCA ceros
--    falsos.
--  * ejercicio denormalizado desde periodo: es la mitad de la FK orgánica
--    por vigencia y el filtro más frecuente del frontal.
CREATE TABLE IF NOT EXISTS fact_ejecucion (
    periodo                  VARCHAR NOT NULL REFERENCES dim_periodo (periodo),
    fuente_cod               VARCHAR NOT NULL REFERENCES dim_fuente (fuente_cod),
    ejercicio                INTEGER NOT NULL,
    seccion_cod              VARCHAR NOT NULL,
    servicio_cod             VARCHAR NOT NULL,
    programa_cod             VARCHAR NOT NULL REFERENCES dim_programa (programa_cod),
    economica_cod            VARCHAR NOT NULL REFERENCES dim_economica (economica_cod),
    provincia_cod            VARCHAR NOT NULL CHECK (provincia_cod ~ '^\d{2}$|^DT$|^NT$'),
    aplicacion_denominacion  VARCHAR,
    credito_inicial          DOUBLE,
    credito_definitivo       DOUBLE,
    modificaciones           DOUBLE,
    comprometido             DOUBLE,
    orn                      DOUBLE,
    pagos                    DOUBLE,
    cobertura                VARCHAR NOT NULL,
    fecha_captura            DATE NOT NULL,
    PRIMARY KEY (periodo, fuente_cod, seccion_cod, servicio_cod,
                 programa_cod, economica_cod, provincia_cod),
    FOREIGN KEY (ejercicio, seccion_cod, servicio_cod)
        REFERENCES dim_seccion_servicio (ejercicio, seccion_cod, servicio_cod)
);

-- Índices de soporte a las consultas del frontal (filtros por sección/servicio,
-- programa y económica; el PK ya indexa el prefijo periodo+fuente).
CREATE INDEX IF NOT EXISTS idx_fact_ejecucion_organica
    ON fact_ejecucion (ejercicio, seccion_cod, servicio_cod);
CREATE INDEX IF NOT EXISTS idx_fact_ejecucion_programa
    ON fact_ejecucion (programa_cod);
CREATE INDEX IF NOT EXISTS idx_fact_ejecucion_economica
    ON fact_ejecucion (economica_cod);

-- Adjudicaciones PLACSP (velocidad "compromisos jurídicos", Fase 4). Esquema
-- fijado tras inspeccionar la fuente real (docs/placsp_estructura.md).
--
--  * Clave natural = (licitacion_id, lote_id): el id numérico de plataforma es
--    estable entre republicaciones (VERIFICADO sobre el ZIP 2012); el
--    expediente_id NO es único entre órganos. lote_id '0' = sin lotes.
--  * Semántica de upsert = ÚLTIMA FOTO de cada licitación (la recarga borra el
--    bloque completo de la licitación y lo reinserta): PLACSP republica el
--    mismo expediente con estado actualizado; el historial de fotos queda en
--    la capa raw versionada (git-scraping), no en el warehouse.
--  * Anclaje orgánico explícito (anclaje_tipo/anclaje_senal): servicio |
--    organica_sin_servicio | fuera_perimetro | sin_anclar. seccion/servicio
--    solo informados si ancla a servicio; "sin anclar" se CONSERVA y cuenta.
--  * es_cabecera_expediente: exactamente una fila por licitación lleva las
--    magnitudes de licitación (presupuesto_*, valor_estimado) para que sumen
--    sin doble conteo; importe_adjudicacion es aditivo en todas las filas.
--  * Importes: con/sin IVA SEPARADOS (presupuesto_con_iva incluye impuestos;
--    el importe de adjudicación CODICE es el PayableAmount del lote).
CREATE TABLE IF NOT EXISTS fact_contratos (
    licitacion_id            VARCHAR NOT NULL,
    lote_id                  VARCHAR NOT NULL,
    fuente_cod               VARCHAR NOT NULL REFERENCES dim_fuente (fuente_cod),
    periodo                  VARCHAR NOT NULL REFERENCES dim_periodo (periodo),
    ejercicio                INTEGER NOT NULL,
    expediente_id            VARCHAR,
    es_cabecera_expediente   BOOLEAN NOT NULL,
    organo_id                VARCHAR,
    organo_id_esquema        VARCHAR,
    organo_dir3_cod          VARCHAR,
    organo_denominacion      VARCHAR,
    seccion_cod              VARCHAR,
    servicio_cod             VARCHAR,
    anclaje_dir3_cod         VARCHAR,
    anclaje_tipo             VARCHAR NOT NULL CHECK (anclaje_tipo IN
        ('servicio', 'organica_sin_servicio', 'fuera_perimetro', 'sin_anclar')),
    anclaje_senal            VARCHAR NOT NULL,
    tipo_contrato_cod        VARCHAR,
    subtipo_contrato_cod     VARCHAR,
    procedimiento_cod        VARCHAR,
    cpv_cod                  VARCHAR,
    estado_cod               VARCHAR,
    resultado_cod            VARCHAR,
    presupuesto_sin_iva      DOUBLE,
    presupuesto_con_iva      DOUBLE,
    valor_estimado           DOUBLE,
    importe_adjudicacion     DOUBLE,
    num_ofertas              VARCHAR,
    adjudicatario_id         VARCHAR,
    adjudicatario_id_esquema VARCHAR,
    adjudicatario_nombre     VARCHAR,
    adjudicatario_es_pyme    BOOLEAN,
    fecha_adjudicacion       DATE,
    fecha_formalizacion      DATE,
    fecha_actualizacion      DATE,
    fecha_captura            DATE NOT NULL,
    PRIMARY KEY (licitacion_id, lote_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_contratos_organica
    ON fact_contratos (ejercicio, seccion_cod, servicio_cod);
CREATE INDEX IF NOT EXISTS idx_fact_contratos_adjudicatario
    ON fact_contratos (adjudicatario_id);
CREATE INDEX IF NOT EXISTS idx_fact_contratos_organo
    ON fact_contratos (organo_dir3_cod);

-- ----------------------------------------------------------------------------
-- Vistas de exposición
-- ----------------------------------------------------------------------------

-- Detalle desnormalizado con dimensiones vigentes y la métrica reina.
CREATE OR REPLACE VIEW v_ejecucion AS
SELECT
    f.periodo,
    f.ejercicio,
    p.mes,
    p.presupuesto,
    f.fuente_cod,
    f.seccion_cod,
    ss.seccion_denominacion,
    f.servicio_cod,
    ss.servicio_denominacion,
    ss.origen AS organica_origen,
    f.programa_cod,
    pr.area_gasto_cod,
    pr.politica_cod,
    pr.grupo_programas_cod,
    f.economica_cod,
    ec.nivel       AS economica_nivel,
    ec.capitulo_cod,
    ec.denominacion AS economica_denominacion,
    f.provincia_cod,
    f.aplicacion_denominacion,
    f.credito_inicial,
    f.credito_definitivo,
    f.modificaciones,
    f.comprometido,
    f.orn,
    f.pagos,
    CASE
        WHEN f.credito_definitivo IS NOT NULL AND f.credito_definitivo != 0
        THEN f.orn / f.credito_definitivo
    END AS pct_ejecucion,
    f.cobertura,
    f.fecha_captura
FROM fact_ejecucion f
JOIN dim_periodo p USING (periodo)
JOIN dim_seccion_servicio ss
    ON ss.ejercicio = f.ejercicio
   AND ss.seccion_cod = f.seccion_cod
   AND ss.servicio_cod = f.servicio_cod
JOIN dim_programa pr USING (programa_cod)
JOIN dim_economica ec USING (economica_cod);

-- Adjudicaciones desnormalizadas con su ancla orgánica (LEFT JOIN: las no
-- ancladas se exponen igualmente — "sin anclar contabilizado es información").
CREATE OR REPLACE VIEW v_contratos AS
SELECT
    c.licitacion_id,
    c.lote_id,
    c.expediente_id,
    c.periodo,
    c.ejercicio,
    p.mes,
    c.organo_dir3_cod,
    c.organo_denominacion,
    c.organo_id_esquema,
    c.seccion_cod,
    ss.seccion_denominacion,
    c.servicio_cod,
    ss.servicio_denominacion,
    c.anclaje_tipo,
    c.anclaje_senal,
    c.anclaje_dir3_cod,
    c.tipo_contrato_cod,
    c.subtipo_contrato_cod,
    c.procedimiento_cod,
    c.cpv_cod,
    c.estado_cod,
    c.resultado_cod,
    c.es_cabecera_expediente,
    c.presupuesto_sin_iva,
    c.presupuesto_con_iva,
    c.valor_estimado,
    c.importe_adjudicacion,
    c.num_ofertas,
    c.adjudicatario_id,
    c.adjudicatario_nombre,
    c.adjudicatario_es_pyme,
    c.fecha_adjudicacion,
    c.fecha_formalizacion,
    c.fecha_actualizacion,
    c.fecha_captura
FROM fact_contratos c
JOIN dim_periodo p USING (periodo)
LEFT JOIN dim_seccion_servicio ss
    ON ss.ejercicio = c.ejercicio
   AND ss.seccion_cod = c.seccion_cod
   AND ss.servicio_cod = c.servicio_cod;

-- "Último dato disponible": el periodo máximo cargado de cada ejercicio
-- (el Anexo I es acumulado, así que ese mes ES la foto vigente del ejercicio).
CREATE OR REPLACE VIEW v_ejecucion_vigente AS
SELECT v.*
FROM v_ejecucion v
JOIN (
    SELECT ejercicio, max(periodo) AS periodo
    FROM fact_ejecucion
    GROUP BY ejercicio
) ult USING (ejercicio, periodo);
