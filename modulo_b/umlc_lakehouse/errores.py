"""Excepciones del lakehouse.

Existen para que un lote mal formado falle en la frontera, con un mensaje que nombre la
causa, y no como un `AnalysisException` de Spark tres transformaciones despues. Todas
descienden de `LakehouseError` para que el notebook pueda distinguir un error de datos de
un error de plataforma.
"""

from __future__ import annotations

from collections.abc import Iterable


class LakehouseError(Exception):
    """Raiz de los errores propios del lakehouse."""


class EsquemaInvalidoError(LakehouseError):
    """Un marco no tiene el esquema explicito que la capa exige."""

    def __init__(self, contexto: str, diferencias: Iterable[str]) -> None:
        detalle = "; ".join(diferencias)
        super().__init__(f"Esquema invalido en {contexto}: {detalle}")


class LoteVacioError(LakehouseError):
    """Un lote llego sin filas: es una senal de la fuente, no algo que se ignore."""

    def __init__(self, lote_id: str) -> None:
        super().__init__(f"El lote {lote_id!r} no contiene filas")


class ParametroInvalidoError(LakehouseError):
    """Un parametro de construccion esta fuera de su rango admisible."""


class TablaInexistenteError(LakehouseError):
    """Se intento leer o actualizar una tabla que todavia no existe."""

    def __init__(self, nombre: str) -> None:
        super().__init__(f"La tabla {nombre} no existe")
