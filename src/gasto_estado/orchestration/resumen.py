"""Resumen uniforme para ejecuciones de GitHub Actions.

Se limita a leer el ledger operativo: nunca modifica datos ni disimula un fallo.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from gasto_estado.orchestration import frescura

_FUENTES_POR_GRUPO = {
    "mensual": ("igae_anexo_i",),
    "alta_frecuencia": ("placsp", "bdns", "boe_sumario", "consejo_ministros"),
    "health_check": ("todas las fuentes configuradas",),
}


def generar_resumen(
    *, grupo: str,
    particion: str,
    resultado: str,
    commit: str | None,
    warehouse_path: Path = Path("data/warehouse.duckdb"),
) -> str:
    """Crea un bloque Markdown con los mínimos operativos exigidos en CI."""
    ledger = frescura.leer(warehouse_path)
    fuentes = _FUENTES_POR_GRUPO[grupo]
    entradas = [ledger[fuente] for fuente in fuentes if fuente in ledger]
    filas = sum(int(entrada.get("filas", 0)) for entrada in entradas)
    capturas = [entrada.get("ultima_captura_disponible") for entrada in entradas]
    captura = max((c for c in capturas if c), default="no registrada")
    checks = "correctos" if resultado == "success" else "fallidos; revisar diagnóstico anterior"
    return "\n".join(
        [
            "## Resumen operativo",
            "",
            f"- **Fuente(s)**: {', '.join(fuentes)}",
            f"- **Partición o ventana**: {particion}",
            f"- **Filas procesadas**: {filas}",
            f"- **Fecha de captura**: {captura}",
            f"- **Commit producido**: {commit or 'sin cambios publicados'}",
            f"- **Resultado de checks**: {checks}",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Escribe el resumen operativo de una ejecución.")
    parser.add_argument("--grupo", choices=tuple(_FUENTES_POR_GRUPO), required=True)
    parser.add_argument("--particion", required=True)
    parser.add_argument("--resultado", choices=("success", "failure"), required=True)
    parser.add_argument("--commit", default=None)
    args = parser.parse_args()
    contenido = generar_resumen(
        grupo=args.grupo,
        particion=args.particion,
        resultado=args.resultado,
        commit=args.commit,
    )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(contenido)
    else:
        print(contenido)


if __name__ == "__main__":
    main()
