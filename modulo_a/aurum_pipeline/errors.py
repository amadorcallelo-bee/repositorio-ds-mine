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


class EmptyPartitionError(AurumError):
    """Una particion temporal quedo sin filas y el resultado no seria interpretable."""

    def __init__(self, descripcion: str) -> None:
        super().__init__(f"La particion quedo vacia: {descripcion}")


class MisalignedIndexError(AurumError):
    """El marco recibido no tiene el mismo numero de filas que el indice temporal guardado.

    Es el fallo que se quiere hacer ruidoso: el particionador trabaja por posicion, porque es
    la interfaz que espera scikit-learn, y una matriz reordenada o filtrada despues de
    construirlo produciria pliegues silenciosamente equivocados.
    """

    def __init__(self, esperado: int, recibido: int) -> None:
        super().__init__(
            f"El indice temporal se construyo con {esperado} filas y se recibieron "
            f"{recibido}: la matriz debe ser la misma, en el mismo orden."
        )


class SentinelNotImputedError(AurumError):
    """La columna de ley todavia trae el valor especial de la sonda XRF.

    Agregar por turno sin haber tratado el centinela arrastraria la media hacia abajo sin
    dejar rastro, que es exactamente lo que el imputador existe para evitar.
    """

    def __init__(self, nombre_clase: str, columna: str, cuantos: int) -> None:
        super().__init__(
            f"{nombre_clase} recibio {cuantos} valores no positivos en {columna}: "
            "ejecuta AurumImputer antes de construir la matriz por turno."
        )
