"""Tests de resiliencia operativa (Fase 7, Prompt 17).

Cubren:
- Centinela de formato: detecta hojas renombradas, namespaces cambiados, campos
  ausentes; pasa cuando el formato es el esperado.
- Notificaciones: informe de incidencia se genera correctamente.
- Monitor de URLs: respuestas mockeadas generan informes correctos.
- Detección de revisión silenciosa: dos capturas del mismo periodo con hash
  distinto generan nota.
- Fallo parcial: un asset falla sin bloquear los independientes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Centinela de formato
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_sentinel_igae_ok() -> None:
    """El centinela pasa con el fixture real del Anexo I."""
    from gasto_estado.parsers.format_sentinel import verificar_igae

    d = verificar_igae(FIXTURE_DIR / "igae_anexo_i_muestra.xlsx")
    assert d.valido, d.mensaje
    assert d.detalles.get("vintage") == "2021_plus"


def test_sentinel_igae_hoja_renombrada(tmp_path: Path) -> None:
    """Detecta una hoja renombrada en un IGAE simulado."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Sec05"
    wb.create_sheet("Sec01")
    ruta = tmp_path / "falso.xlsx"
    wb.save(ruta)

    from gasto_estado.parsers.format_sentinel import verificar_igae

    d = verificar_igae(ruta)
    assert not d.valido
    assert "S5" in d.mensaje or "Sec" in d.mensaje


def test_sentinel_igae_contenedor_desconocido(tmp_path: Path) -> None:
    """Contenedor no reconocido (ni xlsx ni xls)."""
    ruta = tmp_path / "falso.pdf"
    ruta.write_bytes(b"%PDF-1.4 fake content")

    from gasto_estado.parsers.format_sentinel import verificar_igae

    d = verificar_igae(ruta)
    assert not d.valido
    assert "Contenedor no reconocido" in d.mensaje


def test_sentinel_placsp_ok() -> None:
    """El centinela pasa con el fixture real de PLACSP."""
    from gasto_estado.parsers.format_sentinel import verificar_placsp

    d = verificar_placsp(FIXTURE_DIR / "placsp_643_page1.atom")
    assert d.valido, d.mensaje


def test_sentinel_placsp_namespace_cambiado(tmp_path: Path) -> None:
    """Detecta un namespace CODICE cambiado."""
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-3">
  <entry><id>1</id></entry>
</feed>"""
    ruta = tmp_path / "feed.atom"
    ruta.write_bytes(xml)

    from gasto_estado.parsers.format_sentinel import verificar_placsp

    d = verificar_placsp(ruta)
    assert not d.valido
    assert "CODICE 2.x" in d.mensaje or "CODICE 3" in d.mensaje


def test_sentinel_placsp_html_error(tmp_path: Path) -> None:
    """Detecta una página HTML de error (soft-200)."""
    ruta = tmp_path / "error.atom"
    ruta.write_bytes(b"<!DOCTYPE html><html><body>Error</body></html>")

    from gasto_estado.parsers.format_sentinel import verificar_placsp

    d = verificar_placsp(ruta)
    assert not d.valido
    assert "<?xml" in d.mensaje or "magic" in d.mensaje.lower()


def test_sentinel_bdns_ok() -> None:
    """El centinela pasa con el fixture real de BDNS."""
    from gasto_estado.parsers.format_sentinel import verificar_bdns

    d = verificar_bdns(FIXTURE_DIR / "bdns_concesiones_page1.json")
    assert d.valido, d.mensaje


def test_sentinel_bdns_campo_ausente(tmp_path: Path) -> None:
    """Detecta un campo ausente en JSON de BDNS."""
    datos = {"content": [{"id": 1, "beneficiario": "test"}]}
    ruta = tmp_path / "page.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    from gasto_estado.parsers.format_sentinel import verificar_bdns

    d = verificar_bdns(ruta)
    assert not d.valido
    assert "ausentes" in d.mensaje
    assert "fechaConcesion" in d.mensaje or "importe" in d.mensaje


def test_sentinel_bdns_sin_content(tmp_path: Path) -> None:
    """Detecta respuesta sin clave 'content'."""
    datos = {"data": [], "totalElements": 0}
    ruta = tmp_path / "page.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    from gasto_estado.parsers.format_sentinel import verificar_bdns

    d = verificar_bdns(ruta)
    assert not d.valido
    assert "content" in d.mensaje


def test_sentinel_boe_ok() -> None:
    """El centinela pasa con el fixture real del BOE (sumario)."""
    from gasto_estado.parsers.format_sentinel import verificar_boe

    d = verificar_boe(FIXTURE_DIR / "boe_sumario_muestra.xml")
    assert d.valido, d.mensaje


def test_sentinel_boe_estructura_cambiada(tmp_path: Path) -> None:
    """Detecta XML sin estructura de sumario ni disposición."""
    xml = b"""<?xml version="1.0"?>
<respuesta><datos><otro>contenido</otro></datos></respuesta>"""
    ruta = tmp_path / "boe.xml"
    ruta.write_bytes(xml)

    from gasto_estado.parsers.format_sentinel import verificar_boe

    d = verificar_boe(ruta)
    assert not d.valido
    assert "sumario" in d.mensaje.lower() or "disposición" in d.mensaje.lower()


def test_sentinel_consejo_ok() -> None:
    """El centinela pasa con el fixture real del Consejo de Ministros."""
    from gasto_estado.parsers.format_sentinel import verificar_consejo

    d = verificar_consejo(FIXTURE_DIR / "consejo_referencia_2026.html")
    assert d.valido, d.mensaje


def test_sentinel_consejo_sin_sumario(tmp_path: Path) -> None:
    """Detecta HTML sin bloque SUMARIO."""
    html_sin_sumario = "<html><body><h1>Consejo</h1><h2>Otros</h2></body></html>"
    ruta = tmp_path / "referencia.html"
    ruta.write_text(html_sin_sumario, encoding="utf-8")

    from gasto_estado.parsers.format_sentinel import verificar_consejo

    d = verificar_consejo(ruta)
    assert not d.valido
    assert "SUMARIO" in d.mensaje


def test_sentinel_dispatch() -> None:
    """El dispatch verificar() enruta a la función correcta."""
    from gasto_estado.parsers.format_sentinel import verificar

    d = verificar("igae_mensual", FIXTURE_DIR / "igae_anexo_i_muestra.xlsx")
    assert d.valido
    assert d.fuente == "igae_mensual"

    d2 = verificar("fuente_desconocida", FIXTURE_DIR / "igae_anexo_i_muestra.xlsx")
    assert d2.valido  # sin centinela definido → pasa


# ---------------------------------------------------------------------------
# Notificaciones
# ---------------------------------------------------------------------------


def test_notificacion_generar_step_summary() -> None:
    """El informe de incidencia se genera correctamente para cada tipo de fallo."""
    from gasto_estado.orchestration.notifications import Incidencia, generar_step_summary

    tipos = [
        "validacion_contable",
        "formato_no_reconocido",
        "error_descarga",
        "revision_silenciosa",
        "url_caida",
    ]
    incidencias = [
        Incidencia(
            fuente=f"fuente_{i}",
            particion=f"2026-0{i + 1}",
            tipo_fallo=t,
            mensaje_diagnostico=f"Fallo de prueba: {t}",
        )
        for i, t in enumerate(tipos)
    ]
    summary = generar_step_summary(incidencias)
    assert "5 incidencia" in summary
    for t in tipos:
        assert t in summary
    for i in range(5):
        assert f"fuente_{i}" in summary


def test_notificacion_sin_incidencias() -> None:
    from gasto_estado.orchestration.notifications import generar_step_summary

    summary = generar_step_summary([])
    assert "sin incidencias" in summary


def test_notificacion_step_summary_escribe_en_archivo(tmp_path: Path) -> None:
    """Escribe en $GITHUB_STEP_SUMMARY cuando la variable existe."""
    from gasto_estado.orchestration.notifications import Incidencia, escribir_step_summary

    archivo = tmp_path / "summary.md"
    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(archivo)}):
        escribir_step_summary(
            [
                Incidencia(
                    fuente="test",
                    particion=None,
                    tipo_fallo="error_descarga",
                    mensaje_diagnostico="test msg",
                )
            ]
        )
    assert archivo.exists()
    contenido = archivo.read_text(encoding="utf-8")
    assert "test" in contenido
    assert "error_descarga" in contenido


def test_notificacion_step_summary_noop_fuera_ci() -> None:
    """No hace nada si $GITHUB_STEP_SUMMARY no está definida."""
    from gasto_estado.orchestration.notifications import Incidencia, escribir_step_summary

    env = os.environ.copy()
    env.pop("GITHUB_STEP_SUMMARY", None)
    with patch.dict(os.environ, env, clear=True):
        escribir_step_summary(
            [
                Incidencia(
                    fuente="test",
                    particion=None,
                    tipo_fallo="error_descarga",
                    mensaje_diagnostico="test msg",
                )
            ]
        )


def test_notificacion_formatear_issue_body() -> None:
    from gasto_estado.orchestration.notifications import Incidencia, formatear_issue_body

    body = formatear_issue_body(
        Incidencia(
            fuente="igae_mensual",
            particion="2026-04",
            tipo_fallo="validacion_contable",
            mensaje_diagnostico="El check R1 falló: total secciones != total AGE.",
        )
    )
    assert "igae_mensual" in body
    assert "validacion_contable" in body
    assert "R1" in body


def test_notificacion_crear_issue_noop_fuera_ci() -> None:
    """No crea issue fuera de CI."""
    from gasto_estado.orchestration.notifications import Incidencia, crear_issue_si_ci

    env = os.environ.copy()
    env.pop("GITHUB_ACTIONS", None)
    with patch.dict(os.environ, env, clear=True):
        resultado = crear_issue_si_ci(
            Incidencia(
                fuente="test",
                particion=None,
                tipo_fallo="error_descarga",
                mensaje_diagnostico="test",
            )
        )
    assert not resultado


# ---------------------------------------------------------------------------
# Monitor de URLs
# ---------------------------------------------------------------------------


def test_health_check_extraer_urls() -> None:
    from gasto_estado.orchestration.health_check import _extraer_urls

    sources = {
        "igae_mensual": {
            "url_base": "https://example.com/igae",
            "url_index": "https://example.com/igae/index",
        },
        "dir3": {
            "url_base": "https://example.com/dir3",
            "files": [
                {"key": "unidades", "url": "https://example.com/age.xlsx", "requerido": True},
                {"key": "tipos", "url": "https://example.com/tipos.xlsx", "requerido": False},
            ],
        },
    }
    urls = _extraer_urls(sources)
    assert len(urls) >= 4
    # dir3 fichero obligatorio
    req_urls = [(f, u, r) for f, u, r in urls if "age.xlsx" in u]
    assert req_urls[0][2] is True
    # dir3 fichero opcional
    opt_urls = [(f, u, r) for f, u, r in urls if "tipos.xlsx" in u]
    assert opt_urls[0][2] is False


def test_health_check_verificar_url_ok() -> None:
    from gasto_estado.orchestration.health_check import verificar_url

    with patch("gasto_estado.orchestration.health_check.httpx.head") as mock_head:
        mock_head.return_value.status_code = 200
        r = verificar_url("test", "https://example.com", True)
    assert r.error is None
    assert r.status == 200


def test_health_check_verificar_url_404() -> None:
    from gasto_estado.orchestration.health_check import verificar_url

    with patch("gasto_estado.orchestration.health_check.httpx.head") as mock_head:
        mock_head.return_value.status_code = 404
        r = verificar_url("test", "https://example.com", True)
    assert r.error is not None
    assert "404" in r.error


def test_health_check_verificar_url_timeout() -> None:
    import httpx

    from gasto_estado.orchestration.health_check import verificar_url

    with patch("gasto_estado.orchestration.health_check.httpx.head") as mock_head:
        mock_head.side_effect = httpx.TimeoutException("timeout")
        r = verificar_url("test", "https://example.com", True)
    assert r.error is not None
    assert r.status is None


def test_health_check_verificar_url_redirect() -> None:
    from gasto_estado.orchestration.health_check import verificar_url

    with patch("gasto_estado.orchestration.health_check.httpx.head") as mock_head:
        mock_head.return_value.status_code = 302
        r = verificar_url("test", "https://example.com", True)
    assert r.error is None


# ---------------------------------------------------------------------------
# Detección de revisión silenciosa
# ---------------------------------------------------------------------------


def test_revision_silenciosa_detecta_cambio(tmp_path: Path) -> None:
    """Dos capturas del mismo periodo con hash distinto generan revisión."""
    from gasto_estado.orchestration.revision_detector import detectar_revision_igae

    raw_dir = tmp_path / "raw"
    periodo_dir = raw_dir / "igae_mensual" / "2026-04"
    periodo_dir.mkdir(parents=True)

    # Captura anterior
    anterior = periodo_dir / "MENSUAL ABRIL 2026 ANEXO I.xlsx"
    anterior.write_bytes(b"PK\x03\x04contenido_original")

    # Captura nueva (diferente)
    nueva = periodo_dir / "MENSUAL ABRIL 2026 ANEXO I_rev.xlsx"
    nueva.write_bytes(b"PK\x03\x04contenido_REVISADO")

    rev = detectar_revision_igae(raw_dir, "2026-04", nueva)
    assert rev is not None
    assert rev.hash_anterior != rev.hash_nuevo
    assert rev.periodo == "2026-04"


def test_revision_silenciosa_identico_sin_nota(tmp_path: Path) -> None:
    """Si el hash es idéntico, no hay revisión."""
    from gasto_estado.orchestration.revision_detector import detectar_revision_igae

    raw_dir = tmp_path / "raw"
    periodo_dir = raw_dir / "igae_mensual" / "2026-04"
    periodo_dir.mkdir(parents=True)

    contenido = b"PK\x03\x04contenido_identico"
    anterior = periodo_dir / "MENSUAL ABRIL 2026 ANEXO I.xlsx"
    anterior.write_bytes(contenido)
    nueva = periodo_dir / "copia.xlsx"
    nueva.write_bytes(contenido)

    rev = detectar_revision_igae(raw_dir, "2026-04", nueva)
    assert rev is None


def test_revision_silenciosa_sin_captura_previa(tmp_path: Path) -> None:
    """Sin captura previa, no hay revisión."""
    from gasto_estado.orchestration.revision_detector import detectar_revision_igae

    raw_dir = tmp_path / "raw"
    rev = detectar_revision_igae(raw_dir, "2026-04", tmp_path / "nuevo.xlsx")
    assert rev is None


def test_revision_silenciosa_registra_y_genera_incidencia(tmp_path: Path) -> None:
    """registrar_revision genera la incidencia correctamente."""
    from gasto_estado.orchestration.revision_detector import Revision, registrar_revision

    warehouse = tmp_path / "warehouse.duckdb"
    rev = Revision(
        fuente="igae_mensual",
        periodo="2026-04",
        hash_anterior="abcd1234",
        hash_nuevo="efgh5678",
        ruta_anterior=tmp_path / "anterior.xlsx",
        ruta_nueva=tmp_path / "nueva.xlsx",
    )
    inc = registrar_revision(warehouse, rev)
    assert inc.tipo_fallo == "revision_silenciosa"
    assert "2026-04" in inc.mensaje_diagnostico
    assert "abcd1234" in inc.mensaje_diagnostico

    # Verifica que se registró en el ledger
    from gasto_estado.orchestration import frescura

    ledger = frescura.leer(warehouse)
    assert "igae_mensual_revision" in ledger


# ---------------------------------------------------------------------------
# Fallo parcial (assets independientes no se bloquean)
# ---------------------------------------------------------------------------


def test_grupos_alta_frecuencia_assets_independientes() -> None:
    """Los hechos de alta frecuencia no dependen unos de otros."""
    from gasto_estado.orchestration.assets import (
        fact_acuerdos_cdm,
        fact_boe,
        fact_contratos,
        fact_subvenciones,
    )

    def _dep_keys(asset_obj: object) -> set[object]:
        deps: dict = asset_obj.asset_deps  # type: ignore[attr-defined]
        return set().union(*deps.values()) if deps else set()

    # fact_contratos NO depende de fact_subvenciones/fact_boe/fact_acuerdos_cdm
    deps_contratos = _dep_keys(fact_contratos)
    assert fact_subvenciones.key not in deps_contratos
    assert fact_boe.key not in deps_contratos
    assert fact_acuerdos_cdm.key not in deps_contratos

    # fact_subvenciones NO depende de fact_contratos/fact_boe/fact_acuerdos_cdm
    deps_subvenciones = _dep_keys(fact_subvenciones)
    assert fact_contratos.key not in deps_subvenciones
    assert fact_boe.key not in deps_subvenciones

    # fact_boe NO depende de fact_contratos/fact_subvenciones
    deps_boe = _dep_keys(fact_boe)
    assert fact_contratos.key not in deps_boe
    assert fact_subvenciones.key not in deps_boe
