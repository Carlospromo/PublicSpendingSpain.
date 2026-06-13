"""Tests de la extracción de importes desde texto oficial (BOE/CdM, Fase 4).

Fija el contrato de la degradación elegante (CLAUDE.md §9): cifra titular →
alta, cifra suelta → media, sin cifra (o importe en letra / en otra moneda) →
nulo + confianza ``sin_importe``. Nunca un cero falso.
"""

from gasto_estado.parsers.importe_texto import (
    CONFIANZA_ALTA,
    CONFIANZA_MEDIA,
    SIN_IMPORTE,
    extraer_importe,
)


def test_titular_importe_es_alta() -> None:
    importe, conf = extraer_importe("…por un importe máximo de 1.000.000,00 de euros, para…")
    assert importe == 1_000_000.0
    assert conf == CONFIANZA_ALTA


def test_titular_importe_total_grande() -> None:
    importe, conf = extraer_importe("…por importe total de 168.000.000 de euros.")
    assert importe == 168_000_000.0
    assert conf == CONFIANZA_ALTA


def test_valor_estimado_de_contrato_es_alta() -> None:
    # La cuantía titular de los contratos que autoriza el Consejo.
    importe, conf = extraer_importe("Valor estimado del contrato: 21.526.792,10 euros.")
    assert importe == 21_526_792.10
    assert conf == CONFIANZA_ALTA


def test_parentesis_con_simbolo_es_alta() -> None:
    importe, conf = extraer_importe("La cuantía asciende (1.000.000,00 €) según lo previsto.")
    assert importe == 1_000_000.0
    assert conf == CONFIANZA_ALTA


def test_cifra_suelta_es_media() -> None:
    # Un premio dentro del texto: hay euros, pero no es la cifra titular.
    importe, conf = extraer_importe("Primer Premio: 8.000 euros. Segundo Premio: 3.000 euros")
    assert importe == 8_000.0
    assert conf == CONFIANZA_MEDIA


def test_importe_en_letra_no_se_extrae() -> None:
    importe, conf = extraer_importe("…por un importe de un millón de euros, con cargo a…")
    assert importe is None
    assert conf == SIN_IMPORTE


def test_otra_moneda_no_es_euros() -> None:
    # Dólares: no es euros → no se contabiliza (caso real de condonación de deuda).
    importe, conf = extraer_importe("…por importe de 11.609.079,66 dólares estadounidenses.")
    assert importe is None
    assert conf == SIN_IMPORTE


def test_sin_texto() -> None:
    assert extraer_importe(None) == (None, SIN_IMPORTE)
    assert extraer_importe("") == (None, SIN_IMPORTE)


def test_anio_suelto_no_es_importe() -> None:
    # "2026" sin marca monetaria no debe colarse como importe.
    importe, conf = extraer_importe("Plan de actuación para el año 2026.")
    assert importe is None
    assert conf == SIN_IMPORTE
