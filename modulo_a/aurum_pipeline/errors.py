"""Excepciones del pipeline AURUM.

Existen para que un uso incorrecto falle donde se comete y con un mensaje que nombre la
causa, en lugar de propagarse hasta un `KeyError` de pandas treinta lineas mas adelante.
Todas descienden de `AurumError`, de modo que quien integre el pipeline pueda capturar sus
fallos sin capturar de paso los del resto del programa.
"""

from __future__ import annotations

from collections.abc import Iterable


class AurumError(Exception):
    """Raiz de los errores propios del pipeline."""


class NotFittedError(AurumError):
    """Se llamo `transform` sobre un transformador que todavia no fue ajustado."""

    def __init__(self, nombre_clase: str) -> None:
        super().__init__(
            f"{nombre_clase} no esta ajustado: llama a fit() o fit_transform() "
            "antes de transform()."
        )


class MissingColumnsError(AurumError):
    """Al marco de entrada le faltan columnas que el transformador necesita."""

    def __init__(self, nombre_clase: str, faltantes: Iterable[str]) -> None:
        columnas = ", ".join(sorted(faltantes))
        super().__init__(f"{nombre_clase} requiere columnas ausentes en el marco: {columnas}")


class InvalidParameterError(AurumError):
    """Un parametro de construccion esta fuera de su rango admisible."""
