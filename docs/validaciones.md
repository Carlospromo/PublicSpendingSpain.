# Validaciones de coherencia contable (Fase 3)

> Catálogo de las reglas de CLAUDE.md §7 tal y como están implementadas en
> `src/gasto_estado/quality/checks.py`, con sus tolerancias, niveles de
> agregación y estados posibles. Complementa a `docs/modelo_datos.md` (modelo y
> carga); aquí se documenta **qué se valida y por qué**.

## 1. Dónde se ejecutan

1. **Dentro de la carga** (`db/load.py::load_periodo`): dimensiones, partición
   del hecho y checks comparten **una única transacción**. Si alguna regla
   marca FAIL se hace ROLLBACK y se lanza `CoherenceError` — fail loud por
   transacción, no cuarentena. En particular, la recarga fallida de una
   revisión IGAE conserva intacta la versión buena anterior de la partición.
2. **A posteriori, bajo demanda** (`gasto-estado check [--periodo YYYY-MM]
   [--json informe.json]`): revalida el warehouse ya poblado. Código de salida
   1 si hay algún FAIL (pensado para CI, Fase 7).

## 2. Motor consciente de cobertura

Cada regla declara qué magnitudes necesita (`requiere`). El motor consulta la
columna `cobertura` del hecho (docs/modelo_datos.md §1b) para saber qué
magnitudes aportan las fuentes cargadas de cada periodo:

- Si falta una magnitud → la regla sale **SKIPPED con motivo explícito**.
  Nunca PASS sobre nulos ni FAIL espurio contra ceros falsos (NULL ≠ 0).
- Las reglas de la Fase 4 (R5, identidad explícita de R4) **ya están
  implementadas**: se activan solas cuando una fuente declare `pagos`,
  `comprometido` o `modificaciones` en su cobertura. No hay código pendiente
  que recordar activar.

Estados posibles por resultado: `PASS` | `FAIL` | `SKIPPED`.

## 3. Niveles de agregación y vinculación jurídica

Los créditos vinculan por **bolsas** (art. 43 Ley 47/2003), no por aplicación
presupuestaria individual. Empíricamente (8 periodos reales, 2015–2026):

- ORN > crédito definitivo ocurre en **cientos de aplicaciones por periodo**:
  legítimo a nivel aplicación (la bolsa absorbe), violación real a nivel
  servicio o superior.
- Existe un crédito definitivo **negativo oficial** a nivel aplicación
  (−20.000 €, periodo 2017-11, aplicación 18.05.322L.22000): redistribución
  dentro de la bolsa.

Por eso R3 y el signo del definitivo se validan **de servicio hacia arriba**,
nunca a nivel aplicación.

## 4. Tolerancias de redondeo

Escaladas por nivel de agregación; la base ES la del cuadre interno del parser
(`TOLERANCIA_CUADRE = 0,5 €` por servicio, importes oficiales con 2 decimales):

| Nivel    | Tolerancia | Justificación                                      |
| -------- | ---------- | -------------------------------------------------- |
| Servicio | 0,50 €     | idéntica al cuadre aplicaciones↔SUBTOTAL del parser |
| Sección  | 5,00 €     | agrega ~decenas de servicios (×10)                 |
| AGE      | 50,00 €    | agrega ~37 secciones (×10)                         |

Sobre magnitudes de 10^11 €, 50 € son 5·10⁻¹⁰ en términos relativos: holgura
de redondeo, jamás un descuadre contable real.

## 5. Catálogo de reglas

| Regla | Qué valida | Ámbito | Requiere | Estado hoy (solo Anexo I) |
| ----- | ---------- | ------ | -------- | ------------------------- |
| R1 | Σ(servicios) de una sección == total de la sección, a través de la capa de exposición (`v_ejecucion` vs `fact_ejecucion`) | sección | — | activa |
| R2 | Σ(secciones) == total AGE, ídem | AGE | — | activa |
| R3 | ORN ≤ crédito definitivo, con propagación de NULL (bolsa sin definitivo publicado = no comparable, se reporta como nota) | servicio, sección, AGE | orn, definitivo | activa |
| R4a | Derivada `modificaciones = definitivo − inicial`: dominio calculable; reporta el neto AGE (el signo puede ser negativo: bajas) | derivada | inicial, definitivo | activa (informativa) |
| R4b | Identidad explícita `definitivo == inicial + modificaciones` | servicio | + modificaciones | SKIPPED hasta Fase 4 |
| R5 | pagos ≤ ORN | servicio | pagos, orn | SKIPPED hasta Fase 4 |
| R6 | Sin secciones/servicios huérfanos: toda fila ancla a `dim_seccion_servicio` vigente (red de seguridad; la carga ya lo previene con `OrphanOrganicError`) | ancla orgánica | — | activa |
| R7 | Signos: `credito_inicial ≥ 0` y `orn ≥ 0` por aplicación; `credito_definitivo ≥ 0` por servicio (= bolsa). Las modificaciones derivadas pueden ser negativas | por magnitud | según sub-check | activa |
| R8 | Continuidad intra-ejercicio del acumulado vs el periodo cargado inmediatamente anterior del ejercicio: la ORN acumulada no decrece, el crédito inicial no cambia, ningún servicio con acumulado desaparece | servicio | orn o inicial | activa |

Notas sobre R1/R2: el warehouse no almacena los totales impresos del fichero
(ese cuadre vive en el parser, en el momento del parseo). Aquí el "total"
independiente es `fact_ejecucion` agregado directo y la "suma de las partes"
es la misma agregación **a través de `v_ejecucion`** (joins con todas las
dimensiones): detecta pérdida o duplicación de filas en la capa de exposición,
exactamente lo que consumirá el frontal.

Nota sobre R8: un FAIL es una **anomalía a revisar**, no necesariamente un
error — puede ser una revisión oficial de la IGAE. La revisión queda
documentada en el diff git del raw (patrón git-scraping) y se decide caso a
caso; recargar el periodo revisado pasa, porque R8 contrasta el periodo que se
carga contra el anterior, no contra los posteriores.

## 6. Informes

- Consola: una línea por resultado (`ESTADO REGLA periodo ámbito — detalle`) y
  resumen final `N PASS, N SKIPPED, N FAIL`.
- `--json ruta.json`: informe estructurado con los descuadres detallados
  (máx. 20 por resultado; el resto se cuenta en el detalle).

## 7. Tests

`tests/test_quality_checks.py`: cada regla activable tiene un test que la hace
FAIL deliberadamente (inyectando corrupciones por UPDATE/DDL directo, porque la
carga fail-loud no deja entrar datos descuadrados), más un test de aceptación
que reconstruye el warehouse con los 8 periodos reales de `data/raw/` y exige
0 FAIL.
