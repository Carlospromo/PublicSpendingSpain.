"""Tests de regresión del parser PLACSP (sindicación 643, CODICE 2.x).

La muestra real reducida (tests/fixtures/placsp_643_page*.atom, capturada del
feed vivo el 2026-06-11) fija la maquetación que el vintage ``codice2`` debe
seguir parseando igual aunque la fuente evolucione (CLAUDE.md §2).
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

from gasto_estado.parsers.placsp import parse_captura
from gasto_estado.parsers.placsp.detect import VINTAGE_CODICE2, detect_vintage

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = FIXTURES / "placsp_643_page1.atom"
PAGE2 = FIXTURES / "placsp_643_page2.atom"
CAPTURA = date(2026, 6, 11)

# Plantilla de feed sintético para los casos que la muestra real no contiene
# (republicaciones de la misma licitación, lápidas de sindicación).
_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
      xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
      xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
      xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"
      xmlns:at="http://purl.org/atompub/tombstones/1.0">
<id>urn:test</id><title>fixture sintetico</title><updated>2026-06-11T00:00:00Z</updated>
{entries}
</feed>"""

_ENTRY = """<entry>
  <id>https://contrataciondelestado.es/sindicacion/licitacionesPerfilContratante/{lic}</id>
  <updated>{updated}</updated>
  <cac-place-ext:ContractFolderStatus>
    <cbc:ContractFolderID>{exp}</cbc:ContractFolderID>
    <cbc-place-ext:ContractFolderStatusCode>{estado}</cbc-place-ext:ContractFolderStatusCode>
    {cuerpo}
  </cac-place-ext:ContractFolderStatus>
</entry>"""

_RESULTADO = """<cac:TenderResult>
  <cbc:ResultCode>8</cbc:ResultCode>
  <cbc:AwardDate>{fecha}</cbc:AwardDate>
  <cac:AwardedTenderedProject>
    <cbc:ProcurementProjectLotID>{lote}</cbc:ProcurementProjectLotID>
    <cac:LegalMonetaryTotal><cbc:PayableAmount>{importe}</cbc:PayableAmount></cac:LegalMonetaryTotal>
  </cac:AwardedTenderedProject>
</cac:TenderResult>"""


def _pagina(tmp_path: Path, nombre: str, entries: str) -> Path:
    path = tmp_path / nombre
    path.write_text(_FEED.format(entries=entries), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Detección de vintage
# ---------------------------------------------------------------------------


def test_detect_vintage_codice2_en_fixture_real() -> None:
    root = etree.parse(str(PAGE1)).getroot()
    assert detect_vintage(root) == VINTAGE_CODICE2


def test_detect_falla_loud_en_feed_no_codice() -> None:
    root = etree.fromstring(b'<feed xmlns="http://www.w3.org/2005/Atom"><id>x</id></feed>')
    with pytest.raises(ValueError, match="vintage CODICE desconocido"):
        detect_vintage(root)


def test_detect_falla_loud_en_raiz_no_atom() -> None:
    with pytest.raises(ValueError, match="no es un feed Atom"):
        detect_vintage(etree.fromstring(b"<html/>"))


# ---------------------------------------------------------------------------
# Regresión sobre la muestra real (2 páginas, 6 licitaciones, 8 filas)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def detalle() -> pd.DataFrame:
    return parse_captura([PAGE1, PAGE2], fecha_captura=CAPTURA)


def test_grano_y_claves(detalle: pd.DataFrame) -> None:
    assert len(detalle) == 8
    assert sorted(detalle["licitacion_id"].unique()) == [
        "17907624", "19046011", "19565414", "19663725", "19853788", "19853789",
    ]
    # Exactamente UNA cabecera por licitación (suma sin doble conteo).
    assert (detalle.groupby("licitacion_id")["es_cabecera_expediente"].sum() == 1).all()
    assert (detalle["fuente"] == "placsp").all()
    assert (detalle["fecha_captura"] == CAPTURA).all()


def test_adjudicacion_age_con_dir3(detalle: pd.DataFrame) -> None:
    fila = detalle[detalle["licitacion_id"] == "19663725"].iloc[0]
    assert fila["expediente_id"] == "20260000019X"
    assert fila["organo_dir3_cod"] == "E05024401"
    assert fila["organo_id_esquema"] == "DIR3"
    assert fila["estado_cod"] == "ADJ"
    assert fila["resultado_cod"] == "8"
    assert fila["lote_id"] == "0"  # sin lotes
    # El periodo del hecho es el mes del compromiso jurídico (AwardDate).
    assert fila["fecha_adjudicacion"] == date(2026, 6, 9)
    assert fila["periodo"] == "2026-06"
    assert fila["presupuesto_sin_iva"] == 39552.0
    assert fila["presupuesto_con_iva"] == 47857.92
    assert fila["importe_adjudicacion"] == 29040.0
    assert fila["adjudicatario_nombre"] == "AMBIBLUE SL"
    assert fila["adjudicatario_es_pyme"] is True


def test_multilote_importes_aditivos_sin_doble_conteo(detalle: pd.DataFrame) -> None:
    lotes = detalle[detalle["licitacion_id"] == "19046011"].sort_values("lote_id")
    assert list(lotes["lote_id"]) == ["1", "3", "4"]  # IDs oficiales de lote
    # gasto comprometido = Σ importe_adjudicacion en TODAS las filas…
    assert lotes["importe_adjudicacion"].sum() == pytest.approx(316924.53)
    # …y presupuesto licitado solo en la cabecera (resto a nulo, no a 0).
    cabecera = lotes[lotes["es_cabecera_expediente"]]
    assert len(cabecera) == 1
    assert cabecera.iloc[0]["presupuesto_sin_iva"] == 431666.41
    assert lotes[~lotes["es_cabecera_expediente"]]["presupuesto_sin_iva"].isna().all()
    # Periodo del expediente = última adjudicación (2026-05-29).
    assert (lotes["periodo"] == "2026-05").all()
    assert lotes["fecha_adjudicacion"].max() == date(2026, 5, 29)


def test_desierto_y_pendiente_conservados(detalle: pd.DataFrame) -> None:
    # Desierta (ResultCode 3): fila con resultado pero SIN importe (nulo, no 0).
    desierta = detalle[detalle["licitacion_id"] == "19565414"].iloc[0]
    assert desierta["resultado_cod"] == "3"
    assert pd.isna(desierta["importe_adjudicacion"])
    assert pd.isna(desierta["organo_dir3_cod"])  # órgano solo con NIF
    assert desierta["organo_id_esquema"] == "NIF"
    # Publicada sin adjudicar: fila cabecera que conserva el presupuesto.
    pub = detalle[detalle["licitacion_id"] == "19853789"].iloc[0]
    assert pub["estado_cod"] == "PUB"
    assert pd.isna(pub["resultado_cod"])
    assert pub["presupuesto_sin_iva"] == 15000.0
    assert pub["periodo"] == "2026-06"  # sin AwardDate: mes del atom:updated


def test_formalizacion_y_periodo_historico(detalle: pd.DataFrame) -> None:
    fila = detalle[detalle["licitacion_id"] == "17907624"].iloc[0]
    assert fila["fecha_adjudicacion"] == date(2025, 10, 24)
    assert fila["fecha_formalizacion"] == date(2025, 10, 29)
    assert fila["periodo"] == "2025-10"
    assert fila["organo_dir3_cod"] == "L01180896"  # local: lo ancla la Fase 4


# ---------------------------------------------------------------------------
# Deduplicación de republicaciones y lápidas (feeds sintéticos)
# ---------------------------------------------------------------------------


def test_dedup_se_queda_con_la_foto_mas_reciente(tmp_path: Path) -> None:
    vieja = _ENTRY.format(
        lic="111", exp="X-1", estado="ADJ", updated="2026-06-01T10:00:00Z",
        cuerpo=_RESULTADO.format(fecha="2026-05-30", lote="1", importe="100")
        + _RESULTADO.format(fecha="2026-05-30", lote="2", importe="200"),
    )
    nueva = _ENTRY.format(
        lic="111", exp="X-1", estado="RES", updated="2026-06-10T10:00:00Z",
        cuerpo=_RESULTADO.format(fecha="2026-05-30", lote="1", importe="100"),
    )
    paths = [_pagina(tmp_path, "p1.atom", nueva), _pagina(tmp_path, "p2.atom", vieja)]
    detalle = parse_captura(paths, fecha_captura=CAPTURA)
    # Gana el bloque ENTERO más reciente: la foto vieja (2 lotes) desaparece.
    assert len(detalle) == 1
    assert detalle.iloc[0]["estado_cod"] == "RES"
    assert detalle.iloc[0]["fecha_actualizacion"] == date(2026, 6, 10)
    # El orden de los paths no altera el resultado (determinismo).
    invertido = parse_captura(list(reversed(paths)), fecha_captura=CAPTURA)
    pd.testing.assert_frame_equal(detalle, invertido)


def test_lapida_emite_fila_baja(tmp_path: Path) -> None:
    lapida = (
        '<at:deleted-entry ref="https://contrataciondelestado.es/sindicacion/'
        'licitacionesPerfilContratante/222" when="2026-06-05T09:00:00Z"/>'
    )
    detalle = parse_captura([_pagina(tmp_path, "p.atom", lapida)], fecha_captura=CAPTURA)
    assert len(detalle) == 1
    fila = detalle.iloc[0]
    assert fila["licitacion_id"] == "222"
    assert fila["estado_cod"] == "BAJA"
    assert fila["periodo"] == "2026-06"
    assert pd.isna(fila["importe_adjudicacion"])
