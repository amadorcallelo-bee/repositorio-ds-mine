"""Contrato comun sobre LightGBM y XGBoost para la regresion de ley.

El enunciado pide comparar los dos. Sin una abstraccion encima, esa comparacion termina
siendo entre dos formas distintas de llamarlos -uno con `verbose=-1`, el otro con
`verbosity=0`; uno con `min_child_samples`, el otro con `min_child_weight`- y las diferencias
de resultado se confunden con diferencias de configuracion. Aqui cada modelo declara su
regresor y su espacio de busqueda, y todo lo demas -la codificacion del frente, la seleccion
de variables, la particion, las metricas y el registro- es identico.

Cada modelo se entrega como un `Pipeline` de scikit-learn y no como un regresor suelto, y esa
es la decision que impide la fuga: el codificador del nivel del frente es el primer paso del
pipeline, de modo que `RandomizedSearchCV` lo reajusta con las filas de entrenamiento de cada
pliegue. Codificar antes de partir habria dado una metrica mejor y falsa.

Los espacios de busqueda son deliberadamente conservadores en complejidad -pocas hojas,
muchas observaciones minimas por hoja- porque con unos 1500 turnos de entrenamiento por
pliegue y trece frentes, el riesgo real no es quedarse corto sino memorizar el identificador
del frente.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import lightgbm as lgb
import xgboost as xgb
from scipy.stats import loguniform, randint, uniform
from sklearn.base import BaseEstimator
from sklearn.pipeline import Pipeline

from aurum_pipeline import domain
from aurum_pipeline.modeling.features import (
    COMPLETO,
    CodificadorNivelFrente,
    ConjuntoVariables,
    SelectorVariables,
)

#: Nombre del paso final del pipeline. Los espacios de busqueda lo prefijan.
PASO_MODELO: str = "modelo"


class ModeloLey(ABC):
    """Fabrica del pipeline de un modelo de ley y de su espacio de hiperparametros.

    No es un estimador de scikit-learn sino lo que construye uno: separar la fabrica del
    objeto ajustable permite pedir un pipeline nuevo por cada combinacion de conjunto de
    variables y ventana temporal sin arrastrar estado de la corrida anterior.
    """

    def __init__(
        self,
        conjunto: ConjuntoVariables = COMPLETO,
        semilla: int = domain.SEMILLA,
    ) -> None:
        self.conjunto = conjunto
        self.semilla = semilla

    @property
    @abstractmethod
    def nombre(self) -> str:
        """Etiqueta del modelo, tal como queda registrada en MLflow."""

    @abstractmethod
    def _regresor(self) -> BaseEstimator:
        """Regresor concreto, ya configurado con la semilla y sin verbosidad."""

    @abstractmethod
    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Distribuciones que muestrea la busqueda aleatoria, prefijadas por el paso."""

    def pipeline(self) -> Pipeline:
        """Codificacion del frente, seleccion de variables y regresor, en ese orden."""
        return Pipeline([
            ("nivel", CodificadorNivelFrente()),
            ("variables", SelectorVariables(conjunto=self.conjunto)),
            (PASO_MODELO, self._regresor()),
        ])


class ModeloLightGBM(ModeloLey):
    """LightGBM sobre arboles por hojas, que es su modo natural.

    `min_child_samples` alto y `num_leaves` bajo son la defensa contra el sobreajuste al
    frente: con trece categorias y pocos miles de filas, un arbol profundo aprende el
    identificador y no la relacion.
    """

    @property
    def nombre(self) -> str:
        """Etiqueta del modelo."""
        return "lightgbm"

    def _regresor(self) -> BaseEstimator:
        """Regresor con la semilla fijada y el log apagado."""
        return lgb.LGBMRegressor(random_state=self.semilla, verbose=-1, n_jobs=-1)

    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Espacio de siete hiperparametros, muestreado por la busqueda aleatoria."""
        return {
            f"{PASO_MODELO}__num_leaves": randint(7, 64),
            f"{PASO_MODELO}__min_child_samples": randint(10, 101),
            f"{PASO_MODELO}__learning_rate": loguniform(0.01, 0.2),
            f"{PASO_MODELO}__n_estimators": randint(100, 801),
            f"{PASO_MODELO}__subsample": uniform(0.6, 0.4),
            f"{PASO_MODELO}__subsample_freq": randint(1, 6),
            f"{PASO_MODELO}__colsample_bytree": uniform(0.6, 0.4),
            f"{PASO_MODELO}__reg_lambda": loguniform(0.001, 10.0),
        }


class ModeloXGBoost(ModeloLey):
    """XGBoost sobre arboles por profundidad, con el equivalente de cada hiperparametro.

    El espacio no es una traduccion literal del de LightGBM porque los dos no parametrizan lo
    mismo: aqui la complejidad se acota con `max_depth` y `min_child_weight`, que es como esta
    libreria expresa la misma idea.
    """

    @property
    def nombre(self) -> str:
        """Etiqueta del modelo."""
        return "xgboost"

    def _regresor(self) -> BaseEstimator:
        """Regresor con la semilla fijada y el log apagado."""
        return xgb.XGBRegressor(random_state=self.semilla, verbosity=0, n_jobs=-1)

    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Espacio de siete hiperparametros, muestreado por la busqueda aleatoria."""
        return {
            f"{PASO_MODELO}__max_depth": randint(2, 9),
            f"{PASO_MODELO}__min_child_weight": randint(1, 21),
            f"{PASO_MODELO}__learning_rate": loguniform(0.01, 0.2),
            f"{PASO_MODELO}__n_estimators": randint(100, 801),
            f"{PASO_MODELO}__subsample": uniform(0.6, 0.4),
            f"{PASO_MODELO}__colsample_bytree": uniform(0.6, 0.4),
            f"{PASO_MODELO}__reg_lambda": loguniform(0.001, 10.0),
        }


#: Los dos modelos que el enunciado pide comparar, en el orden en que se reportan.
MODELOS: tuple[type[ModeloLey], ...] = (ModeloLightGBM, ModeloXGBoost)
