# Crosswalks orgánicos

El crosswalk `servicio presupuestario ↔ DIR3` es el activo central del proyecto
(CLAUDE.md §2): ancla la clasificación orgánica del PGE a las unidades reales
del Estado. **La correspondencia no es 1:1** y cambia con cada remodelación,
por eso se modela como tabla de relación con tipo de match explícito y un
registro histórico de equivalencias.

## Ficheros

| Fichero | Tipo | Contenido |
|---|---|---|
| `servicio_dir3.py` | código | Constructor del crosswalk (matching + overrides) |
| `overrides_servicio_dir3.csv` | editable a mano | Correspondencias manuales; prevalecen siempre |
| `historico.py` / `historico_secciones.csv` | código + editable | Equivalencias de secciones entre ejercicios |
| `../../db/seeds/crosswalk_servicio_dir3.csv` | generado | Crosswalk materializado del ejercicio vigente |

## Tipos de match (columna `match_tipo`)

- **exacto** — denominación normalizada idéntica dentro del subárbol DIR3 del
  ministerio de la sección. Normalización: minúsculas, sin acentos ni
  puntuación, abreviaturas DIR3 expandidas (`D.G.` → dirección general,
  `S. de E.` → secretaría de estado, `S.Gral.` → secretaría general; **no** se
  expande `S.G.`, que en DIR3 es Subdirección General).
- **por_denominacion** — coincidencia derivada del nombre, con el método en
  `match_detalle`: `tokens_significativos` (mismo conjunto de palabras
  ignorando preposiciones), `prefijo_unico` (la unidad añade un sufijo, p. ej.
  "Secretaría General Técnica (MEFPD)"; solo si hay un único candidato) o
  `regla_servicios_generales` (el servicio `.01` "Ministerio, Subsecretaría y
  Servicios Generales" agrupa la cúpula del departamento → raíz del ministerio
  + su Subsecretaría; lectura literal de la denominación oficial).
- **manual** — fijado en `overrides_servicio_dir3.csv` (una fila por par; la
  columna `nota` documenta el porqué). Al regenerar, los overrides sustituyen
  por completo el resultado automático de ese servicio.
- **sin_match** — sin correspondencia. La fila se conserva con `dir3_cod`
  vacío; **nunca se descartan servicios**. `match_detalle` distingue:
  - `seccion_sin_ministerio_dir3` (estructural): secciones no ministeriales
    (Casa Real, Cortes, órganos constitucionales, Deuda, Clases Pasivas,
    fondos, secciones 34-38). No existen en el listado DIR3 de unidades AGE.
  - `servicio_instrumental_prtr` (estructural): el servicio `.50` "Mecanismo
    de Recuperación y Resiliencia", vehículo presupuestario sin unidad orgánica.
  - `sin_candidato_en_subarbol` (real): el matching no encontró unidad. Son los
    candidatos a override manual.

## Umbral de calidad

`sin_candidato` (sin_match real) debe quedar **≤ 10 %** de los servicios
matcheables (los de secciones ministeriales, excluido el instrumental PRTR).
Justificación: con el PGE prorrogado vigente (2025-P, 215 servicios) el
matching automático deja un 3,3 % (5 servicios); el umbral del 10 % da margen
a pequeñas variaciones de denominación en futuros ejercicios sin dejar pasar
una ruptura del matching (p. ej. un cambio de formato de la fuente). El test
`tests/test_pge_crosswalk.py` lo verifica sobre el seed comprometido.

## Casos conflictivos conocidos (ejercicio 2026, presupuesto 2025-P)

Sin candidato automático; pendientes de override manual si se necesitan:

- `13.05` / `13.06` "Secretaría General para la Innovación y Calidad del
  Servicio Público de Justicia. Fiscalía General / Ministerio Fiscal":
  denominaciones compuestas (servicio = unidad + apéndice institucional);
  la Fiscalía no es unidad DIR3 de la AGE.
- `13.08` "Secretariado del Gobierno y Relaciones con las Cortes": en DIR3
  existe "Secretaría General Técnica-Secretariado del Gobierno" (E00135706),
  pero la equivalencia no es literal; decidir con criterio de dominio.
- `14.02` "Cuartel General del EMAD": en DIR3 es "Cuartel General del Estado
  Mayor de la Defensa" (E02810603); el acrónimo EMAD no se expande
  automáticamente (no inventamos equivalencias en código).
- `28.07` "Dirección General de Planificación de la Investigación": sin unidad
  DIR3 vigente con esa denominación en la captura 2026-06-10.

Override ya aplicado: `13.07` "Presidente del Gobierno" → `EA0008567`
(Presidencia del Gobierno tiene raíz DIR3 propia fuera del Mº de la Presidencia).

## Histórico de secciones (`historico_secciones.csv`)

Una fila por arista `origen → destino` con `tipo_cambio` controlado
(`continuidad_renombre`, `fusion`, `escision`, `creacion`, `supresion`); las
relaciones n:m se expresan con varias filas. Cargado: la remodelación
2023→2024 (RD 829/2023; verificada por diff de los índices PGE-ROM oficiales
PGE2023Ley vs PGE2024Prorroga) y 2024→2025 (sin cambios, sin filas). Para
retrocargar ejercicios anteriores: añadir tandas de filas por transición
siguiendo el mismo método (diff de índices + RD de reestructuración).

Nota: las secciones 60 (Seguridad Social) y 98 (Ingresos del Estado) aparecen
en el árbol 2023Ley y no en las prórrogas por diferencias de presentación de
subsectores, no por remodelación: no son aristas del histórico.

## Pendiente (fases siguientes)

- Equivalencias a nivel de **servicio** (no solo sección) entre ejercicios.
- Crosswalk con órgano de contratación (PLACSP) y órgano concedente (BDNS).
