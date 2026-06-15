"""Parser del CODICE 2.x de PLACSP (sindicación 643) → filas canónicas.

Convierte cada ``atom:entry`` (un expediente de contratación) en filas del
modelo canónico de adjudicaciones. Decisiones de grano (documentadas en
docs/placsp_estructura.md §4) — el dato bruto es ruidoso y la robustez está en
la normalización y el anclaje, no en confiar en el campo bruto:

GRANO = una fila por (expediente, resultado de adjudicación / lote). Así el
importe de adjudicación (``cbc:PayableAmount`` de cada ``cac:TenderResult``) es
ADITIVO sin doble conteo: cada lote adjudicado suma una vez. Para no perder los
expedientes aún sin adjudicar (en plazo, en evaluación, desiertos), estos emiten
UNA fila con resultado/importe nulos. Las magnitudes de licitación (presupuesto
con/sin IVA, valor estimado) son atributos de EXPEDIENTE: se marcan con
``es_cabecera_expediente`` en exactamente una fila por expediente para que sumen
sin doble conteo (el resto de filas-lote las llevan a nulo). Regla de oro:

- gasto comprometido (anticipa la ORN) = Σ ``importe_adjudicacion`` (todas las filas)
- presupuesto licitado                = Σ presupuesto_* WHERE es_cabecera_expediente

Ausencias → nulo explícito, nunca 0 (un importe ausente ≠ un importe de cero).
Las entradas-lápida (``at:deleted-entry``, baja de sindicación) se emiten como
fila mínima con ``estado_cod='BAJA'`` para no perder la señal de retirada.
"""

from __future__ import annotations

from datetime import date

from lxml import etree

FUENTE = "placsp"

_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "at": "http://purl.org/atompub/tombstones/1.0",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacx": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcx": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}

# Contrato canónico (pre-anclaje). El anclaje orgánico añade seccion/servicio y
# las señales de fiabilidad en transform/placsp_anclaje.py.
PLACSP_COLUMNS = [
    "periodo",
    "fuente",
    "fecha_captura",
    "licitacion_id",
    "expediente_id",
    "entry_id",
    "es_cabecera_expediente",
    "lote_id",
    "organo_id",
    "organo_id_esquema",
    "organo_dir3_cod",
    "organo_denominacion",
    "organo_tipo_cod",
    "tipo_contrato_cod",
    "subtipo_contrato_cod",
    "procedimiento_cod",
    "cpv_cod",
    "estado_cod",
    "resultado_cod",
    "presupuesto_sin_iva",
    "presupuesto_con_iva",
    "valor_estimado",
    "importe_adjudicacion",
    "num_ofertas",
    "adjudicatario_id",
    "adjudicatario_id_esquema",
    "adjudicatario_nombre",
    "adjudicatario_es_pyme",
    "fecha_adjudicacion",
    "fecha_formalizacion",
    "fecha_actualizacion",
]


def _text(node: etree._Element | None, path: str) -> str | None:
    if node is None:
        return None
    el = node.find(path, _NS)
    if el is None or el.text is None:
        return None
    txt = el.text.strip()
    return txt or None


def _attr(node: etree._Element | None, path: str, attr: str) -> str | None:
    if node is None:
        return None
    el = node.find(path, _NS)
    return None if el is None else el.get(attr)


def _amount(node: etree._Element | None, path: str) -> float | None:
    """Importe CODICE → float; ausencia → None (nunca 0)."""
    txt = _text(node, path)
    if txt is None:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _date(node: etree._Element | None, path: str) -> date | None:
    return _date_from_text(_text(node, path))


def _date_from_text(txt: str | None) -> date | None:
    if txt is None:
        return None
    # CODICE da fechas ISO (YYYY-MM-DD) y a veces datetime con zona; nos quedamos
    # con la parte de fecha. Ausencia/!formato → None (no rompemos el lote).
    try:
        return date.fromisoformat(txt[:10])
    except ValueError:
        return None


def _bool(node: etree._Element | None, path: str) -> bool | None:
    txt = _text(node, path)
    if txt is None:
        return None
    return txt.strip().lower() == "true"


def _periodo(fecha_ref: date | None) -> str | None:
    return None if fecha_ref is None else f"{fecha_ref.year:04d}-{fecha_ref.month:02d}"


def _licitacion_id(entry_id: str | None, organo_id: str | None, expediente_id: str | None) -> str:
    """Identificador único de la licitación en la plataforma.

    El ``atom:id`` (``…/licitacionesPerfilContratante/<n>``) identifica la
    licitación; el ``ContractFolderID`` NO basta (es un código interno del
    órgano: "12/2026" aparece repetido entre órganos distintos en el feed real).
    Si faltara el id, se compone órgano+expediente como subrogado escopado.
    """
    if entry_id:
        return entry_id.rstrip("/").rsplit("/", 1)[-1]
    return f"{organo_id or 'SIN_ORGANO'}::{expediente_id or 'SIN_EXPEDIENTE'}"


def _winning_party(tr: etree._Element) -> tuple[str | None, str | None, str | None]:
    """(id, esquema, nombre) del adjudicatario de un TenderResult, o (None,None,None)."""
    wp = tr.find("cac:WinningParty", _NS)
    if wp is None:
        return None, None, None
    return (
        _text(wp, "cac:PartyIdentification/cbc:ID"),
        _attr(wp, "cac:PartyIdentification/cbc:ID", "schemeName"),
        _text(wp, "cac:PartyName/cbc:Name"),
    )


def _parse_entry(entry: etree._Element, *, fecha_captura: date | None) -> list[dict[str, object]]:
    entry_id = _text(entry, "a:id")
    fecha_actualizacion = _date(entry, "a:updated")

    # Lápida de sindicación: el expediente se da de baja del feed.
    deleted = entry.find("at:deleted-entry", _NS)
    if deleted is not None or entry.tag == f"{{{_NS['at']}}}deleted-entry":
        ref = deleted if deleted is not None else entry
        exp = ref.get("ref") or entry_id
        cuando = _date_from_text(ref.get("when")) or fecha_actualizacion or fecha_captura
        base: dict[str, object] = dict.fromkeys(PLACSP_COLUMNS)
        base.update(
            fuente=FUENTE,
            fecha_captura=fecha_captura,
            licitacion_id=_licitacion_id(entry_id or exp, None, exp),
            expediente_id=exp,
            entry_id=entry_id or exp,
            es_cabecera_expediente=True,
            lote_id="0",
            estado_cod="BAJA",
            fecha_actualizacion=cuando,
            periodo=_periodo(cuando),
        )
        return [base]

    status = entry.find(".//cacx:LocatedContractingParty", _NS)
    party = status.find("cac:Party", _NS) if status is not None else None
    organo_id = _text(party, "cac:PartyIdentification/cbc:ID")
    organo_esquema = _attr(party, "cac:PartyIdentification/cbc:ID", "schemeName")
    organo_dir3 = organo_id if organo_esquema == "DIR3" else None

    project = entry.find(".//cac:ProcurementProject", _NS)
    budget = project.find("cac:BudgetAmount", _NS) if project is not None else None

    expediente_id = _text(entry, ".//cbc:ContractFolderID")
    # Expediente-level (se repiten en cabecera; en filas-lote van a nulo salvo
    # los identificadores y la organica).
    exp_attrs: dict[str, object] = {
        "fuente": FUENTE,
        "fecha_captura": fecha_captura,
        "licitacion_id": _licitacion_id(entry_id, organo_id, expediente_id),
        "expediente_id": expediente_id,
        "entry_id": entry_id,
        "organo_id": organo_id,
        "organo_id_esquema": organo_esquema,
        "organo_dir3_cod": organo_dir3,
        "organo_denominacion": _text(party, "cac:PartyName/cbc:Name"),
        "organo_tipo_cod": _text(status, "cbc:ContractingPartyTypeCode"),
        "tipo_contrato_cod": _text(project, "cbc:TypeCode"),
        "subtipo_contrato_cod": _text(project, "cbc:SubTypeCode"),
        "procedimiento_cod": _text(entry, ".//cac:TenderingProcess/cbc:ProcedureCode"),
        # CPV principal: el primero de la clasificación (división = 2 primeros díg.).
        "cpv_cod": _text(project, "cac:RequiredCommodityClassification/cbc:ItemClassificationCode"),
        "estado_cod": _text(entry, ".//cbcx:ContractFolderStatusCode"),
        "fecha_formalizacion": _date(entry, ".//cac:Contract/cbc:IssueDate"),
        "fecha_actualizacion": fecha_actualizacion,
    }
    presupuesto = {
        "presupuesto_sin_iva": _amount(budget, "cbc:TaxExclusiveAmount"),
        "presupuesto_con_iva": _amount(budget, "cbc:TotalAmount"),
        "valor_estimado": _amount(budget, "cbc:EstimatedOverallContractAmount"),
    }

    resultados = entry.findall(".//cac:TenderResult", _NS)
    # Periodo del hecho: la última fecha de adjudicación si la hay (es el momento
    # del compromiso jurídico); si no, la última actualización en plataforma.
    fechas_adj = [d for d in (_date(tr, "cbc:AwardDate") for tr in resultados) if d is not None]
    fecha_ref = max(fechas_adj) if fechas_adj else (fecha_actualizacion or fecha_captura)
    periodo = _periodo(fecha_ref)

    def fila(**extra: object) -> dict[str, object]:
        row = dict.fromkeys(PLACSP_COLUMNS)
        row.update(exp_attrs)
        row.update(periodo=periodo, **extra)
        return row

    if not resultados:
        # Sin adjudicación todavía (en plazo, evaluación, anuncio previo): UNA
        # fila cabecera que conserva el presupuesto licitado.
        return [fila(es_cabecera_expediente=True, lote_id="0", **presupuesto)]

    filas: list[dict[str, object]] = []
    vistos: set[str] = set()
    for i, tr in enumerate(resultados):
        adj_id, adj_esq, adj_nombre = _winning_party(tr)
        # ID oficial del lote adjudicado (VERIFICADO: vive bajo
        # AwardedTenderedProject). "0" = expediente sin lotes; si la fuente lo
        # omite en multi-lote, numeración sintética posicional.
        lote = _text(tr, "cac:AwardedTenderedProject/cbc:ProcurementProjectLotID")
        if lote is None:
            lote = "0" if len(resultados) == 1 else f"s{i + 1}"
        while lote in vistos:  # garantiza unicidad de la clave natural
            lote = f"{lote}.{i + 1}"
        vistos.add(lote)
        es_cabecera = i == 0
        filas.append(
            fila(
                es_cabecera_expediente=es_cabecera,
                lote_id=lote,
                resultado_cod=_text(tr, "cbc:ResultCode"),
                importe_adjudicacion=_amount(
                    tr, "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount"
                ),
                num_ofertas=_text(tr, "cbc:ReceivedTenderQuantity"),
                adjudicatario_id=adj_id,
                adjudicatario_id_esquema=adj_esq,
                adjudicatario_nombre=adj_nombre,
                adjudicatario_es_pyme=_bool(tr, "cbc:SMEAwardedIndicator"),
                fecha_adjudicacion=_date(tr, "cbc:AwardDate"),
                # Presupuesto solo en la cabecera (global): evita doble conteo.
                **(presupuesto if es_cabecera else {}),
            )
        )
    return filas


def parse_feed(
    root: etree._Element, *, fecha_captura: date | None = None
) -> list[dict[str, object]]:
    """Parsea un feed Atom/CODICE completo a filas canónicas (todas las entradas)."""
    entradas = root.findall("a:entry", _NS)
    # Las lápidas pueden ir como <at:deleted-entry> al nivel del feed.
    entradas += root.findall("at:deleted-entry", _NS)
    filas: list[dict[str, object]] = []
    for entry in entradas:
        filas.extend(_parse_entry(entry, fecha_captura=fecha_captura))
    return filas
