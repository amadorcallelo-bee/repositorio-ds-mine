"""Los dos baselines contra los que se mide todo modelo de ley.

El enunciado pide "un baseline naive". Se entregan dos, y la razon es de honestidad de la
comparacion: la persistencia es el naive literal y es facil de ganar, mientras que el nivel
del frente es el rival de verdad. Sobre el extracto la persistencia da 0.5491 g/t de error
medio y el nivel del frente 0.3975; presentar solo el primero haria ver bien a cualquier
modelo que apenas aprenda que cada frente tiene su propia ley.

Los cinco -dos de regresion y tres de clasificacion- implementan el contrato de
scikit-learn para que pasen por el mismo codigo de evaluacion, las mismas particiones y el
mismo registro en MLflow que LightGBM y XGBoost. Un baseline evaluado por un camino distinto
del de los modelos no es comparable con ellos.

Los de clasificacion siguen la misma idea: `BaselinePrevalencia` es el azar,
`BaselineTasaFrente` responde si basta con saber en que frente se esta, y `BaselineActividad`
es el rival de verdad: responde si basta con saber cuanto llevaba el frente sin registrar al
cierre del turno, que es lo que la etiqueta de falla a cuatro horas mide en este extracto.
"""

from __future__ import annotations

import logging
from itertools import pairwise
from typing import Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError, MissingColumnsError, NotFittedError

logger = logging.getLogger(__name__)

Predicciones = npt.NDArray[np.float64]


class BaselinePersistencia(BaseEstimator, RegressorMixin):
    """Predice que el turno siguiente repite la ley del turno actual.

    Es el naive del enunciado y no aprende nada: `fit` solo existe para cumplir el contrato.
    Sirve de piso porque cualquier modelo que no le gane no esta aportando ni memoria de un
    turno.
    """

    def __init__(self, columna_ley: str = domain.COLUMNA_LEY_TURNO) -> None:
        self.columna_ley = columna_ley

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """No hay nada que aprender; se valida la columna para fallar temprano."""
        self._validar(X)
        self._ajustado_ = True
        return self

    def predict(self, X: pd.DataFrame) -> Predicciones:
        """Devuelve la ley del turno actual como prediccion del siguiente."""
        if not hasattr(self, "_ajustado_"):
            raise NotFittedError(type(self).__name__)
        self._validar(X)
        return X[self.columna_ley].to_numpy(dtype=float)

    def _validar(self, X: pd.DataFrame) -> None:
        if self.columna_ley not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_ley])


class BaselineNivelFrente(BaseEstimator, RegressorMixin):
    """Predice la media historica de la ley del frente, aprendida solo con entrenamiento.

    Es el baseline fuerte y el que fija el techo practico del problema: la ley es el nivel
    del frente mas ruido blanco, de modo que la media del frente calculada con todo el
    historico -un oraculo que ningun modelo puede usar- explica el 97.57% de la varianza y
    esta version causal llega al 97.53%. Lo que queda entre esas dos cifras es todo el
    espacio que cualquier modelo tiene para mejorar.

    Un frente no visto en entrenamiento recibe la media global, por la misma razon que en
    `CodificadorNivelFrente`: sin historia del frente no hay nada mejor que decir.
    """

    def __init__(self, columna_frente: str = domain.COLUMNA_FRENTE) -> None:
        self.columna_frente = columna_frente

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """Aprende la media del objetivo por frente sobre las filas recibidas."""
        if y is None:
            raise MissingColumnsError(type(self).__name__, ["objetivo"])
        self._validar(X)
        objetivo = pd.Series(np.asarray(y, dtype=float),
                             index=X[self.columna_frente].to_numpy())
        self.niveles_: pd.Series = objetivo.groupby(level=0).mean()
        self.prior_: float = float(objetivo.mean())
        logger.debug("%s: nivel de %d frentes, prior %.4f",
                     type(self).__name__, len(self.niveles_), self.prior_)
        return self

    def predict(self, X: pd.DataFrame) -> Predicciones:
        """Devuelve el nivel del frente de cada fila, o la media global si no se conoce."""
        if not hasattr(self, "niveles_"):
            raise NotFittedError(type(self).__name__)
        self._validar(X)
        nivel = X[self.columna_frente].map(self.niveles_).fillna(self.prior_)
        return nivel.to_numpy(dtype=float)

    def _validar(self, X: pd.DataFrame) -> None:
        if self.columna_frente not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_frente])


class BaselinePrevalencia(BaseEstimator, ClassifierMixin):
    """Predice para todo turno la tasa historica de falla, sin mirar nada mas.

    Es el naive de la clasificacion y define el piso exacto: su precision media es igual a la
    tasa base, que es lo que da el azar. Un clasificador que no lo supere no esta anticipando
    fallas, esta repitiendo la frecuencia con que ocurren.
    """

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """Aprende la prevalencia de la clase positiva en las filas recibidas."""
        if y is None:
            raise MissingColumnsError(type(self).__name__, ["etiqueta"])
        etiqueta = np.asarray(y, dtype=float)
        self.classes_ = np.array([0, 1])
        self.prevalencia_: float = float((etiqueta > 0).mean())
        return self

    def predict_proba(self, X: pd.DataFrame) -> Predicciones:
        """Probabilidad constante e igual a la prevalencia aprendida."""
        if not hasattr(self, "prevalencia_"):
            raise NotFittedError(type(self).__name__)
        positiva = np.full(len(X), self.prevalencia_, dtype=float)
        return np.column_stack([1.0 - positiva, positiva])

    def predict(self, X: pd.DataFrame) -> Predicciones:
        """Clase mas probable segun la prevalencia; constante por construccion."""
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(float)


class BaselineTasaFrente(BaseEstimator, ClassifierMixin):
    """Predice la tasa historica de falla del frente, aprendida solo con entrenamiento.

    Es el equivalente en clasificacion del baseline del nivel del frente: responde si la
    identidad del frente, por si sola, anticipa la falla. Si le gana a los modelos, la
    conclusion es que la telemetria no aporta nada sobre saber en que frente se esta.
    """

    def __init__(self, columna_frente: str = domain.COLUMNA_FRENTE) -> None:
        self.columna_frente = columna_frente

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """Aprende la tasa de falla de cada frente y la prevalencia global de respaldo."""
        if y is None:
            raise MissingColumnsError(type(self).__name__, ["etiqueta"])
        if self.columna_frente not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_frente])
        etiqueta = pd.Series(np.asarray(y, dtype=float),
                             index=X[self.columna_frente].to_numpy())
        self.classes_ = np.array([0, 1])
        self.tasas_: pd.Series = etiqueta.groupby(level=0).mean()
        self.prior_: float = float(etiqueta.mean())
        return self

    def predict_proba(self, X: pd.DataFrame) -> Predicciones:
        """Tasa del frente de cada fila, o la prevalencia global si no se conoce."""
        if not hasattr(self, "tasas_"):
            raise NotFittedError(type(self).__name__)
        if self.columna_frente not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_frente])
        positiva = X[self.columna_frente].map(self.tasas_).fillna(self.prior_).to_numpy(float)
        return np.column_stack([1.0 - positiva, positiva])

    def predict(self, X: pd.DataFrame) -> Predicciones:
        """Clase mas probable segun la tasa del frente."""
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(float)


class BaselineActividad(BaseEstimator, ClassifierMixin):
    """Predice la tasa de falla segun cuantos minutos llevaba el frente sin registrar al cierre.

    Es el rival honesto de la clasificacion, como lo es el nivel del frente en la regresion.
    La etiqueta de falla a cuatro horas es cero por construccion cuando el frente se apago, y
    con eventos independientes a 3.3% cada uno la probabilidad de falla de una ventana es una
    funcion del numero de eventos que tendra: anticipar la falla es, en este extracto,
    anticipar si el frente sigue operando. La senal causal mas directa de eso es cuanto hace
    que dejo de registrar: un frente que emitio su ultimo evento a veinte minutos del cierre
    sigue en campana; uno que lleva cuatro horas callado ya se fue.

    Aprende una tasa por tramo de minutos -tramos cerrados por la derecha, como los de
    `pandas.cut`- y nada mas: cinco numeros contra las veintitantas variables del
    modelo. Si el modelo no le gana con claridad, lo que aprendio es esto. Los
    tramos vienen del dominio y no se ajustan aqui, porque un baseline que optimiza sus cortes
    deja de ser un baseline. Un turno sin la medida -o en un tramo que no aparecio en
    entrenamiento- recibe la prevalencia global, por la misma razon que un frente no visto
    recibe la media global en `BaselineTasaFrente`.
    """

    def __init__(
        self,
        columna_minutos: str = domain.COLUMNA_MINUTOS_INACTIVO,
        tramos: tuple[float, ...] = domain.TRAMOS_INACTIVIDAD_MINUTOS,
    ) -> None:
        self.columna_minutos = columna_minutos
        self.tramos = tramos

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """Aprende la tasa de falla de cada tramo y la prevalencia global de respaldo."""
        if y is None:
            raise MissingColumnsError(type(self).__name__, ["etiqueta"])
        self._validar(X)
        etiqueta = np.asarray(y, dtype=float)
        tramo = self._tramo(X)
        self.classes_ = np.array([0, 1])
        self.prior_: float = float(etiqueta.mean())
        self.tasas_: Predicciones = np.full(len(self.tramos) + 1, self.prior_, dtype=float)
        conocidos = tramo >= 0
        for indice in np.unique(tramo[conocidos]):
            del_tramo = etiqueta[conocidos][tramo[conocidos] == indice]
            self.tasas_[int(indice)] = float(del_tramo.mean())
        logger.debug("%s: tasas por tramo %s, prior %.4f",
                     type(self).__name__, np.round(self.tasas_, 4).tolist(), self.prior_)
        return self

    def predict_proba(self, X: pd.DataFrame) -> Predicciones:
        """Tasa del tramo de cada fila, o la prevalencia global si no se conoce."""
        if not hasattr(self, "tasas_"):
            raise NotFittedError(type(self).__name__)
        self._validar(X)
        tramo = self._tramo(X)
        positiva = np.where(tramo >= 0, self.tasas_[np.clip(tramo, 0, None)], self.prior_)
        return np.column_stack([1.0 - positiva, positiva])

    def predict(self, X: pd.DataFrame) -> Predicciones:
        """Clase mas probable segun la tasa del tramo."""
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(float)

    def _tramo(self, X: pd.DataFrame) -> npt.NDArray[np.intp]:
        """Devuelve el indice del tramo de cada fila, o -1 cuando la medida falta."""
        minutos = X[self.columna_minutos].to_numpy(dtype=float)
        tramo = np.searchsorted(np.asarray(self.tramos, dtype=float), minutos, side="left")
        return np.where(np.isnan(minutos), -1, tramo)

    def _validar(self, X: pd.DataFrame) -> None:
        if self.columna_minutos not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_minutos])
        cortes = tuple(float(corte) for corte in self.tramos)
        if not cortes or cortes[0] <= 0 or any(b <= a for a, b in pairwise(cortes)):
            raise InvalidParameterError(
                "los tramos de inactividad deben ser positivos y crecientes, "
                f"se recibio {self.tramos}")
