"""Particion temporal del Ejercicio A-2: entrenamiento, validacion y prueba.

Tres conjuntos con tres papeles que no se mezclan. **Entrenamiento** ajusta los parametros
del modelo. **Validacion** elige hiperparametros, conjunto de variables y estrategia de
ventana. **Prueba** se reporta una vez y no participa de ninguna decision.

El corte de prueba es por fecha y no por numero de filas. Con frentes que se apagan por
semanas, cortar por filas dejaria las mismas fechas a los dos lados de la particion, y una
metrica de prueba que comparte calendario con el entrenamiento no mide lo que dice medir.

Dentro del desarrollo, la validacion es walk-forward: el periodo se divide en tramos de
igual duracion, el primero solo entrena y cada uno de los siguientes es un bloque de
validacion. Un turno de un tramo intermedio valida en su pliegue y entrena en los
posteriores; eso no es fuga porque la direccion es siempre pasado hacia futuro, pero
significa que entrenamiento y validacion son papeles que se mueven y no bloques fijos. La
alternativa —tres bloques disjuntos, sin walk-forward— deja una sola estimacion de
validacion, sin dispersion medible, e inutiliza el bloque intermedio para el ajuste final.

**La purga es la pieza que hay que entender.** El objetivo de una celda ocurre en el futuro
de esa celda. Si una fila de entrenamiento predice un turno que cae dentro del bloque de
validacion, el modelo esta viendo el bloque que lo evalua. No produce error: produce una
metrica sospechosamente buena. Por eso una fila entrena solo si su `inicio_turno_siguiente`
es anterior al comienzo del bloque. Sobre el extracto real la purga saca 12 o 13 celdas por
pliegue, una por frente, que son exactamente las que tienen el turno abierto sobre la
frontera.

Las dos estrategias de ventana comparten esta clase base para que la comparacion entre
ellas signifique algo: los bloques de validacion son identicos y lo unico que cambia es
donde empieza el entrenamiento.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import (
    EmptyPartitionError,
    InvalidParameterError,
    MisalignedIndexError,
    MissingColumnsError,
)

logger = logging.getLogger(__name__)

Indices = npt.NDArray[np.intp]


class ParticionTemporal:
    """Separa el desarrollo del conjunto de prueba por una fecha de corte del calendario."""

    def __init__(
        self,
        proporcion_prueba: float = domain.PROPORCION_PRUEBA,
        columna_inicio: str = domain.COLUMNA_INICIO_TURNO,
    ) -> None:
        if not 0.0 < proporcion_prueba < 1.0:
            raise InvalidParameterError(
                "proporcion_prueba debe estar entre 0 y 1 sin incluirlos, "
                f"se recibio {proporcion_prueba}")
        self.proporcion_prueba = proporcion_prueba
        self.columna_inicio = columna_inicio
        self.fecha_corte_: pd.Timestamp | None = None

    def dividir(self, matriz: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Devuelve (desarrollo, prueba). La prueba es la cola mas reciente del calendario."""
        if self.columna_inicio not in matriz.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_inicio])
        if matriz.empty:
            raise EmptyPartitionError("la matriz recibida no tiene filas")

        inicio = matriz[self.columna_inicio]
        # `quantile` sobre instantes devuelve un Timestamp, pero su tipo declarado es
        # flotante; la conversion explicita deja el contrato del atributo sin ambiguedad.
        corte = pd.Timestamp(inicio.quantile(1.0 - self.proporcion_prueba))
        self.fecha_corte_ = corte
        desarrollo = matriz.loc[inicio <= corte].reset_index(drop=True)
        prueba = matriz.loc[inicio > corte].reset_index(drop=True)
        if desarrollo.empty or prueba.empty:
            raise EmptyPartitionError(
                f"el corte en {corte} deja desarrollo con {len(desarrollo)} filas y "
                f"prueba con {len(prueba)}")

        logger.info("%s: corte en %s; desarrollo %d turnos, prueba %d turnos",
                    type(self).__name__, corte, len(desarrollo), len(prueba))
        return desarrollo, prueba


class VentanaTemporal(ABC):
    """Generador de pliegues walk-forward con purga, compatible con scikit-learn.

    Se construye con los instantes de la matriz y no los recibe en `split`, porque `split`
    solo ve la matriz de variables y esa, por diseno, no lleva las marcas de tiempo. La
    consecuencia es que el objeto queda atado a una matriz concreta: si se le pasa otra con
    distinto numero de filas, falla con `MisalignedIndexError` en lugar de producir pliegues
    equivocados en silencio.

    Implementa `split` y `get_n_splits` con la firma de scikit-learn para que
    `RandomizedSearchCV` use estos mismos pliegues purgados. Sin eso, la busqueda de
    hiperparametros armaria por dentro una particion aleatoria y echaria a perder toda la
    estructura temporal montada afuera.
    """

    def __init__(
        self,
        inicio: pd.Series,
        inicio_objetivo: pd.Series,
        pliegues: int = domain.PLIEGUES_VALIDACION,
    ) -> None:
        if pliegues < 1:
            raise InvalidParameterError(
                f"pliegues debe ser al menos 1, se recibio {pliegues}")
        if len(inicio) != len(inicio_objetivo):
            raise MisalignedIndexError(len(inicio), len(inicio_objetivo))
        if len(inicio) == 0:
            raise EmptyPartitionError("el indice temporal no tiene filas")

        self.pliegues = pliegues
        self._inicio = pd.to_datetime(pd.Series(inicio).reset_index(drop=True))
        self._inicio_objetivo = pd.to_datetime(
            pd.Series(inicio_objetivo).reset_index(drop=True))
        self._primer_instante: pd.Timestamp = self._inicio.min()
        self._ultimo_instante: pd.Timestamp = self._inicio.max()

    # -- contrato publico ---------------------------------------------------------------

    @property
    @abstractmethod
    def nombre(self) -> str:
        """Etiqueta de la estrategia, tal como queda registrada en MLflow."""

    @property
    @abstractmethod
    def meses(self) -> int | None:
        """Longitud de la ventana en meses, o `None` si es expansiva."""

    def get_n_splits(
        self,
        X: Any = None,
        y: Any = None,
        groups: Any = None,
    ) -> int:
        """Numero de pliegues. Firma impuesta por scikit-learn."""
        return self.pliegues

    def split(
        self,
        X: Any = None,
        y: Any = None,
        groups: Any = None,
    ) -> Iterator[tuple[Indices, Indices]]:
        """Produce (indices de entrenamiento, indices de validacion) por pliegue.

        Los indices son posicionales, como espera scikit-learn, y por eso la matriz que se
        pase tiene que ser la misma con la que se construyo el objeto y en el mismo orden.
        """
        if X is not None and len(X) != len(self._inicio):
            raise MisalignedIndexError(len(self._inicio), len(X))

        inicio = self._inicio.to_numpy()
        objetivo = self._inicio_objetivo.to_numpy()
        for numero, (desde_val, hasta_val, es_ultimo) in enumerate(self.bloques(), start=1):
            en_bloque = (inicio >= np.datetime64(desde_val)) & (
                inicio <= np.datetime64(hasta_val) if es_ultimo
                else inicio < np.datetime64(hasta_val))
            desde_entrenamiento = self._inicio_ventana(desde_val)
            # La purga vive en esta linea: entrena solo lo que predice un turno anterior al
            # comienzo del bloque de validacion.
            entrena = (objetivo < np.datetime64(desde_val)) & (
                inicio >= np.datetime64(desde_entrenamiento))
            if not entrena.any() or not en_bloque.any():
                raise EmptyPartitionError(
                    f"pliegue {numero} de la ventana {self.nombre}: "
                    f"{int(entrena.sum())} filas de entrenamiento y "
                    f"{int(en_bloque.sum())} de validacion desde {desde_val}")

            logger.debug("%s: pliegue %d entrena %d y valida %d desde %s",
                         self.nombre, numero, int(entrena.sum()), int(en_bloque.sum()),
                         desde_val)
            yield np.flatnonzero(entrena), np.flatnonzero(en_bloque)

    def bloques(self) -> tuple[tuple[pd.Timestamp, pd.Timestamp, bool], ...]:
        """Bloques de validacion como (desde, hasta, es_el_ultimo), iguales en toda estrategia.

        El ultimo bloque se cierra por la derecha para que el instante final de la matriz no
        quede fuera de toda validacion; los demas se cierran por la izquierda para que ningun
        turno valide dos veces.
        """
        bordes = pd.date_range(
            self._primer_instante, self._ultimo_instante, periods=self.pliegues + 2)
        return tuple(
            (bordes[k], bordes[k + 1], k == self.pliegues)
            for k in range(1, self.pliegues + 1)
        )

    # -- extension ----------------------------------------------------------------------

    @abstractmethod
    def _inicio_ventana(self, inicio_validacion: pd.Timestamp) -> pd.Timestamp:
        """Instante en que empieza el entrenamiento de un pliegue que valida desde el dado."""


class VentanaExpansiva(VentanaTemporal):
    """Entrena con toda la historia disponible antes del bloque de validacion.

    Es la estrategia por defecto: el nivel de ley de un frente no deriva -su desviacion
    entre semestres es 0.14 g/t contra 3.69 g/t de desviacion entre frentes-, de modo que no
    hay regimen viejo que descartar y recortar historia solo empeora la estimacion del nivel.
    """

    @property
    def nombre(self) -> str:
        """Etiqueta de la estrategia."""
        return "expansiva"

    @property
    def meses(self) -> int | None:
        """La ventana expansiva no tiene longitud fija."""
        return None

    def _inicio_ventana(self, inicio_validacion: pd.Timestamp) -> pd.Timestamp:
        """Toda la historia: la ventana empieza en el primer instante de la matriz."""
        return self._primer_instante


class VentanaDeslizante(VentanaTemporal):
    """Entrena con una ventana de longitud constante que termina en el bloque de validacion.

    Existe para que la eleccion de ventana se decida con cifras del propio experimento y no
    por preferencia: se compara contra la expansiva sobre los mismos bloques y el resultado
    queda registrado en MLflow.
    """

    def __init__(
        self,
        inicio: pd.Series,
        inicio_objetivo: pd.Series,
        meses: int,
        pliegues: int = domain.PLIEGUES_VALIDACION,
    ) -> None:
        if meses < 1:
            raise InvalidParameterError(
                f"la ventana deslizante se mide en meses positivos, se recibio {meses}")
        super().__init__(inicio, inicio_objetivo, pliegues=pliegues)
        self._meses = meses

    @property
    def nombre(self) -> str:
        """Etiqueta de la estrategia, con su longitud."""
        return f"deslizante_{self._meses}m"

    @property
    def meses(self) -> int:
        """Longitud de la ventana en meses."""
        return self._meses

    def _inicio_ventana(self, inicio_validacion: pd.Timestamp) -> pd.Timestamp:
        """Retrocede la longitud de la ventana desde el comienzo del bloque de validacion."""
        return inicio_validacion - pd.DateOffset(months=self._meses)


def ventana_desde_matriz(
    matriz: pd.DataFrame,
    meses: int | None = None,
    pliegues: int = domain.PLIEGUES_VALIDACION,
) -> VentanaTemporal:
    """Construye la estrategia de ventana leyendo los instantes de la matriz.

    Es el unico lugar donde se nombran las dos columnas temporales al construir un
    particionador, de modo que el codigo de experimentacion no las repita en cada corrida.
    """
    faltantes = {domain.COLUMNA_INICIO_TURNO, domain.COLUMNA_INICIO_OBJETIVO} - set(
        matriz.columns)
    if faltantes:
        raise MissingColumnsError("ventana_desde_matriz", faltantes)
    inicio = matriz[domain.COLUMNA_INICIO_TURNO]
    objetivo = matriz[domain.COLUMNA_INICIO_OBJETIVO]
    if meses is None:
        return VentanaExpansiva(inicio, objetivo, pliegues=pliegues)
    return VentanaDeslizante(inicio, objetivo, meses=meses, pliegues=pliegues)
