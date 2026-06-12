"""Tests del parser BDNS: páginas JSON reales → canónico validado.

Fixture real reducido del SNPSAP (10 filas, 9 concesiones únicas): incluye una
republicación del mismo ``id`` con ``fechaAlta`` posterior e importe corregido
(dedup), una concesión autonómica (perímetro) y NIF de persona física
enmascarado de origen.
"""

from datetime import date
from pathlib import Path

import pytest

from gasto_estado.parsers import bdns

FIXTURES = Path(__file__).parent / "fixtures"
PAGINAS = [
    FIXTURES / "bdns_concesiones_page1.json",
    FIXTURES / "bdns_concesiones_page2.json",
]
_CAPTURA = date(2026, 6, 13)


def test_parse_captura_canonico() -> None:
    detalle = bdns.parse_captura(PAGINAS, fecha_captura=_CAPTURA)
    assert list(detalle.columns) == bdns.BDNS_COLUMNS
    # 10 filas brutas, 9 concesiones únicas tras dedup de la republicación.
    assert len(detalle) == 9
    assert detalle["concesion_id"].is_unique
    assert (detalle["fuente"] == "bdns").all()
    assert (detalle["fecha_captura"] == _CAPTURA).all()


def test_dedup_republicacion_gana_mayor_fecha_alta() -> None:
    detalle = bdns.parse_captura(PAGINAS, fecha_captura=_CAPTURA)
    fila = detalle[detalle["concesion_id"] == "153038882"].iloc[0]
    # La foto de la página 2 (alta 2026-06-13) corrige el importe: …,46.
    assert fila["fecha_alta"] == date(2026, 6, 13)
    assert fila["importe"] == pytest.approx(2421206.46)


def test_periodo_es_el_mes_de_la_concesion() -> None:
    detalle = bdns.parse_captura(PAGINAS, fecha_captura=_CAPTURA)
    assert set(detalle["periodo"]) == {"2026-06"}
    fila = detalle[detalle["concesion_id"] == "153038875"].iloc[0]
    assert fila["fecha_concesion"] == date(2026, 6, 2)
    assert fila["convocatoria_cod"] == "840944"
    assert fila["convocatoria_id"] == "1042505"


def test_beneficiarios_separados_y_clasificados() -> None:
    detalle = bdns.parse_captura(PAGINAS, fecha_captura=_CAPTURA).set_index("concesion_id")
    juridica = detalle.loc["153038875"]
    assert juridica["beneficiario_nif"] == "A10736791"
    assert juridica["beneficiario_nombre"] == "ASTILLEROS RÍA DE VIGO, S.A."
    assert juridica["beneficiario_tipo"] == bdns.PERSONA_JURIDICA
    fisica = detalle.loc["153661007"]
    assert fisica["beneficiario_nif"] == "***4231**"  # enmascarado de origen
    assert fisica["beneficiario_tipo"] == bdns.PERSONA_FISICA


def test_split_beneficiario_no_inventa_separacion() -> None:
    assert bdns.split_beneficiario("B16176703 SERVINET SLU") == (
        "B16176703",
        "SERVINET SLU",
        bdns.PERSONA_JURIDICA,
    )
    assert bdns.split_beneficiario("***8323** LAURA P.") == (
        "***8323**",
        "LAURA P.",
        bdns.PERSONA_FISICA,
    )
    assert bdns.split_beneficiario("12345678Z SIN RESTO") == (
        "12345678Z",
        "SIN RESTO",
        bdns.PERSONA_FISICA,
    )
    # Primer token sin forma de NIF: todo el texto es nombre, nif/tipo nulos.
    assert bdns.split_beneficiario("AYUNTAMIENTO DE CUENCA") == (
        None,
        "AYUNTAMIENTO DE CUENCA",
        None,
    )
    assert bdns.split_beneficiario(None) == (None, None, None)
    assert bdns.split_beneficiario("  ") == (None, None, None)
    assert bdns.split_beneficiario(float("nan")) == (None, None, None)


def test_jerarquia_administrativa_se_conserva_tal_cual() -> None:
    detalle = bdns.parse_captura(PAGINAS, fecha_captura=_CAPTURA).set_index("concesion_id")
    autonomica = detalle.loc["153759275"]
    assert autonomica["nivel1"] == "AUTONOMICA"
    assert autonomica["nivel2"] == "COMUNIDAD FORAL DE NAVARRA"
    estatal = detalle.loc["153038875"]
    assert estatal["nivel1"] == "ESTADO"
    assert estatal["nivel3"] == "DIRECCIÓN GENERAL DE PROGRAMAS INDUSTRIALES"


def test_pagina_sin_content_falla_loud() -> None:
    with pytest.raises(ValueError, match="content"):
        bdns.parse_pagina(b'{"error": "rechazo"}')


def test_parse_capture_dir(tmp_path: Path) -> None:
    captura = tmp_path / "2026-06-13"
    ventana = captura / "concesiones" / "C_2026-06-01_2026-06-13"
    ventana.mkdir(parents=True)
    for num, pagina in enumerate(PAGINAS):
        (ventana / f"page_{num:05d}.json").write_bytes(pagina.read_bytes())
    detalle = bdns.parse_capture_dir(captura)
    assert len(detalle) == 9
    # La fecha de captura se infiere del nombre del directorio (ISO).
    assert (detalle["fecha_captura"] == date(2026, 6, 13)).all()


def test_parse_capture_dir_vacio_falla_loud(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Sin páginas BDNS"):
        bdns.parse_capture_dir(tmp_path / "2026-06-13")
