"""Contrato de errores uniforme (Prompt 15).

Todo error sale con el mismo cuerpo ``{"error": {"codigo", "mensaje", "detalle"}}``
mapeado a los HTTP que la API ya usa, para que el frontal maneje los errores de
forma homogénea. Códigos estables (no el número HTTP):

- ``no_encontrado``      (404): periodo/ejercicio/fuente no cargado o ruta inexistente.
- ``entrada_invalida``   (422): parámetro mal formado, nivel/velocidad inválidos.
- ``servicio_no_disponible`` (503): el warehouse no está construido.
- ``error_interno``      (500): fallo no previsto.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_CODIGO_POR_HTTP = {
    404: "no_encontrado",
    422: "entrada_invalida",
    503: "servicio_no_disponible",
    500: "error_interno",
}


def _cuerpo(codigo: str, mensaje: str, detalle: Any | None = None) -> dict[str, Any]:
    return {"error": {"codigo": codigo, "mensaje": mensaje, "detalle": detalle}}


def registrar_manejadores(app: FastAPI) -> None:
    """Instala los manejadores que uniforman el cuerpo de error."""

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        codigo = _CODIGO_POR_HTTP.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code, content=_cuerpo(codigo, str(exc.detail))
        )

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_cuerpo(
                "entrada_invalida", "Parámetros de la petición inválidos.", exc.errors()
            ),
        )

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        # Las funciones puras validan su entrada con ValueError (nivel/periodo
        # inválido): 422 uniforme, no un 500 opaco.
        return JSONResponse(
            status_code=422, content=_cuerpo("entrada_invalida", str(exc))
        )
