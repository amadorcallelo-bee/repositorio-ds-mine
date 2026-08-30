"""Contrato comun de los transformadores del pipeline AURUM.

El enunciado pide una clase abstracta con `fit`, `transform` y `fit_transform`. Se
implementa como ABC propia y no heredando de `TransformerMixin` de scikit-learn a
proposito: el contrato pedido es explicito y corto, y una dependencia de framework en la
pieza mas central del paquete obliga a todo el que lea el codigo a conocer las convenciones
de sklearn para entender que hace `fit_transform`. La firma sigue igual la convencion
`fit(X, y=None)`, de modo que estos objetos encajan en una `Pipeline` de sklearn por duck
typing si mas adelante conviene.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Self

import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import MissingColumnsError, NotFittedError

logger = logging.getLogger(__name__)


class AurumTransformer(ABC):
    """Transformador de un marco OPUS, con estado propio y contrato explicito.

    Las subclases declaran que columnas necesitan y implementan `_fit` y `_transform`; la
    clase base se encarga de lo que debe ser identico en todas: validar la entrada, impedir
    que se transforme antes de ajustar, no mutar el marco recibido y registrar en el log que
    frentes se procesaron.

    El registro por `frente_id` que pide el enunciado no es decorativo: el extracto es
    intermitente por frente, y saber cuales entraron en cada ajuste es lo que permite
    explicar despues por que un frente quedo sin imputar o sin codificar.
    """

    #: Columnas que el marco de entrada debe traer para que el transformador funcione.
    columnas_requeridas: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._ajustado: bool = False

    # -- contrato publico ---------------------------------------------------------------

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """Aprende del marco `X` y devuelve el propio transformador.

        No modifica `X`: las subclases trabajan sobre lo que necesiten copiar. Devolver
        `self` permite encadenar `fit(...).transform(...)`.
        """
        self._validar(X)
        self._registrar_frentes(X, "ajuste")
        self._fit(X, y)
        self._ajustado = True
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Devuelve una copia transformada de `X`, sin tocar el marco original."""
        if not self._ajustado:
            raise NotFittedError(type(self).__name__)
        self._validar(X)
        self._registrar_frentes(X, "transformacion")
        return self._transform(X.copy())

    def fit_transform(self, X: pd.DataFrame, y: pd.Series | None = None) -> pd.DataFrame:
        """Ajusta y transforma en un paso.

        Se implementa aqui, y no se hereda de un mixin, porque en `AurumShiftEncoder` la
        diferencia entre `fit_transform` y `transform` es justamente lo que evita la fuga de
        informacion: la primera codifica dejando fuera la propia fila, la segunda no puede.
        """
        return self.fit(X, y).transform(X)

    # -- extension ----------------------------------------------------------------------

    @abstractmethod
    def _fit(self, X: pd.DataFrame, y: pd.Series | None) -> None:
        """Aprende el estado necesario. Lo implementa cada transformador concreto."""

    @abstractmethod
    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Transforma una copia ya validada del marco de entrada."""

    # -- utilidades comunes -------------------------------------------------------------

    def _validar(self, X: pd.DataFrame) -> None:
        """Comprueba que estan las columnas requeridas antes de tocar el marco."""
        faltantes = set(self.columnas_requeridas) - set(X.columns)
        if faltantes:
            raise MissingColumnsError(type(self).__name__, faltantes)

    def _registrar_frentes(self, X: pd.DataFrame, accion: str) -> None:
        """Deja en el log que frentes entraron y con cuantos registros cada uno."""
        if domain.COLUMNA_FRENTE not in X.columns:
            logger.info("%s: %s de %d registros sin columna de frente",
                        type(self).__name__, accion, len(X))
            return
        conteo = X[domain.COLUMNA_FRENTE].value_counts().sort_index()
        logger.info("%s: %s de %d registros en %d frentes: %s",
                    type(self).__name__, accion, len(X), len(conteo),
                    ", ".join(str(frente) for frente in conteo.index))
        for frente, registros in conteo.items():
            logger.debug("%s: frente_id=%s con %d registros",
                         type(self).__name__, frente, registros)
