"""Manifiestos reproducibles de capturas, sin almacenar el raw masivo.

El módulo no descarga ni publica datos: convierte una captura ya disponible en
un documento compacto y verificable. La ubicación inmutable se exige de forma
explícita para no afirmar trazabilidad histórica que el repositorio no posee.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


class ManifiestoIncompletoError(ValueError):
    """Falta un dato obligatorio para publicar un manifiesto verificable."""


@dataclass(frozen=True)
class ManifiestoCaptura:
    schema_version: int
    fuente: str
    fecha_extraccion: str
    rango_cubierto: dict[str, str]
    url_origen: str
    sha256: str
    commit_codigo: str
    commit_warehouse: str
    ubicacion_inmutable: str

    def a_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_archivo(ruta: Path) -> str:
    """Calcula el hash completo de un fichero sin cargarlo entero en memoria."""
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def sha256_rutas(rutas: list[Path]) -> str:
    """Hash estable de un conjunto de ficheros, sensible a ruta y contenido."""
    if not rutas:
        raise ManifiestoIncompletoError("no hay archivos para calcular SHA-256")
    digest = hashlib.sha256()
    for ruta in sorted(rutas, key=lambda p: p.as_posix()):
        if not ruta.is_file():
            raise ManifiestoIncompletoError(f"no se puede hashear {ruta}: no es un fichero")
        digest.update(ruta.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_archivo(ruta).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def crear_manifiesto(
    *,
    fuente: str,
    fecha_extraccion: datetime,
    desde: str,
    hasta: str,
    url_origen: str,
    sha256: str,
    commit_codigo: str,
    commit_warehouse: str,
    ubicacion_inmutable: str,
) -> ManifiestoCaptura:
    """Valida y construye el contrato JSON de reproducibilidad versión 1."""
    if fecha_extraccion.tzinfo is None:
        raise ManifiestoIncompletoError("fecha_extraccion debe incluir zona horaria")
    obligatorios = {
        "fuente": fuente,
        "rango desde": desde,
        "rango hasta": hasta,
        "url_origen": url_origen,
        "sha256": sha256,
        "commit_codigo": commit_codigo,
        "commit_warehouse": commit_warehouse,
        "ubicacion_inmutable": ubicacion_inmutable,
    }
    faltan = [nombre for nombre, valor in obligatorios.items() if not valor.strip()]
    if faltan:
        raise ManifiestoIncompletoError(f"faltan campos obligatorios: {', '.join(faltan)}")
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256.lower()):
        raise ManifiestoIncompletoError("sha256 debe ser un hash SHA-256 hexadecimal completo")
    fecha_utc = fecha_extraccion.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return ManifiestoCaptura(
        schema_version=1,
        fuente=fuente,
        fecha_extraccion=fecha_utc,
        rango_cubierto={"desde": desde, "hasta": hasta},
        url_origen=url_origen,
        sha256=sha256,
        commit_codigo=commit_codigo,
        commit_warehouse=commit_warehouse,
        ubicacion_inmutable=ubicacion_inmutable,
    )


def ruta_manifiesto(directorio: Path, manifiesto: ManifiestoCaptura) -> Path:
    """Ruta determinista: la misma captura no crea documentos duplicados."""
    particion = manifiesto.rango_cubierto["desde"].replace("/", "-")
    return directorio / manifiesto.fuente / f"{particion}-{manifiesto.sha256[:16]}.json"


def escribir_manifiesto(directorio: Path, manifiesto: ManifiestoCaptura) -> Path:
    """Escritura idempotente; rechaza colisiones con contenido distinto."""
    ruta = ruta_manifiesto(directorio, manifiesto)
    contenido = manifiesto.a_json()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        try:
            existente = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            mensaje = f"colisión de manifiesto no idempotente: {ruta}"
            raise ManifiestoIncompletoError(mensaje) from exc
        identidad = {
            "fuente": manifiesto.fuente,
            "rango_cubierto": manifiesto.rango_cubierto,
            "sha256": manifiesto.sha256,
        }
        if {clave: existente.get(clave) for clave in identidad} != identidad:
            raise ManifiestoIncompletoError(f"colisión de manifiesto no idempotente: {ruta}")
        return ruta
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def registrar_desde_archivos(
    *,
    directorio: Path,
    fuente: str,
    fecha_extraccion: datetime,
    desde: str,
    hasta: str,
    url_origen: str,
    archivos: list[Path],
    commit_codigo: str,
    commit_warehouse: str,
    ubicacion_inmutable: str,
) -> Path:
    """Calcula el hash y escribe un manifiesto completo de forma atómica lógica."""
    manifiesto = crear_manifiesto(
        fuente=fuente,
        fecha_extraccion=fecha_extraccion,
        desde=desde,
        hasta=hasta,
        url_origen=url_origen,
        sha256=sha256_rutas(archivos),
        commit_codigo=commit_codigo,
        commit_warehouse=commit_warehouse,
        ubicacion_inmutable=ubicacion_inmutable,
    )
    return escribir_manifiesto(directorio, manifiesto)


def main() -> None:
    """Interfaz de CI: falla antes de publicar si falta trazabilidad verificable."""
    parser = argparse.ArgumentParser(description="Registra un manifiesto de captura.")
    parser.add_argument("--fuente", required=True)
    parser.add_argument("--particion", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--archivos", type=Path, required=True)
    parser.add_argument("--commit-codigo", required=True)
    parser.add_argument("--commit-warehouse", required=True)
    parser.add_argument("--ubicacion-inmutable", required=True)
    parser.add_argument("--fecha-extraccion", required=True)
    parser.add_argument("--directorio", type=Path, default=Path("data/manifiestos"))
    args = parser.parse_args()
    try:
        fecha = datetime.fromisoformat(args.fecha_extraccion.replace("Z", "+00:00"))
        archivos = sorted(path for path in args.archivos.rglob("*") if path.is_file())
        ruta = registrar_desde_archivos(
            directorio=args.directorio,
            fuente=args.fuente,
            fecha_extraccion=fecha,
            desde=args.particion,
            hasta=args.particion,
            url_origen=args.url,
            archivos=archivos,
            commit_codigo=args.commit_codigo,
            commit_warehouse=args.commit_warehouse,
            ubicacion_inmutable=args.ubicacion_inmutable,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: manifiesto no publicado: {exc}") from exc
    print(ruta)


if __name__ == "__main__":
    main()
