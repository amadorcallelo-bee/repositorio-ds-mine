"""Clasificadores de falla a cuatro horas, y como se trata el desbalance.

**El desbalance de este problema es moderado, no extremo, y se trata midiendolo.** A nivel de
evento la tasa de falla es 3.3%, pero la unidad de decision no es el evento sino el turno: la
pregunta operacional es si conviene intervenir un frente antes del proximo relevo. A nivel de
celda, la tasa de falla en las cuatro horas siguientes al cierre del turno es 21.8%. Con ese
balance no se remuestrea: SMOTE o el submuestreo del negativo introducen mas varianza de la
que corrigen y distorsionan las probabilidades. El peso de clase reequilibra la perdida sin
inventar ni descartar turnos, pero distorsiona las probabilidades igual que el remuestreo:
con el peso, el clasificador registrado daba un error de Brier de 0.213 sobre la prueba,
peor que el 0.172 de una constante. Y la metrica principal es insensible al umbral, de modo
que el peso no compra ordenamiento. Por eso el valor por defecto es sin peso, y la fase A del
experimento corre cada combinacion con y sin el, para que la decision quede medida y no
supuesta. El mecanismo sigue disponible como parametro para el caso severo -a nivel de
evento, con 3.3%- donde si haria falta.

**La metrica principal es la precision media (area bajo la curva de precision y exhaustividad).**
El area bajo la curva ROC se descarta porque con 78% de negativos se ve bien sin serlo: basta
ordenar bien los negativos entre si. La precision media mira solo la clase positiva, que es la
que cuesta dinero.

**Por que esa metrica en operacion minera.** Los dos errores no cuestan lo mismo. Un falso
negativo es una perforadora que se detiene sin plan, con el frente parado y una cuadrilla
esperando; un falso positivo es una inspeccion preventiva que no hacia falta. El costo
asimetrico empuja a privilegiar la exhaustividad, pero no sin limite: una alarma que se
equivoca la mayoria de las veces deja de mirarse a la semana, y entonces la exhaustividad real
cae a cero. Por eso se reporta ademas la exhaustividad al 50% de precision, que responde la
pregunta que un jefe de mantenimiento hace de verdad: si acepto que una de cada dos alarmas
sea en vano, cuantas fallas alcanzo a anticipar.
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
from aurum_pipeline.modeling.models import PASO_MODELO


class ModeloFalla(ABC):
    """Contrato comun de los clasificadores de falla, espejo del de la regresion.

    Comparte la estructura de `ModeloLey` a proposito -mismo pipeline, mismos conjuntos de
    variables, misma particion- para que la unica diferencia entre los dos problemas sea el
    objetivo. Lo que no comparte es la jerarquia: heredar de `ModeloLey` obligaria a que un
    clasificador fuera un regresor, y eso no es cierto.
    """

    def __init__(
        self,
        conjunto: ConjuntoVariables = COMPLETO,
        semilla: int = domain.SEMILLA,
        peso_positivo: float = 1.0,
    ) -> None:
        self.conjunto = conjunto
        self.semilla = semilla
        self.peso_positivo = peso_positivo

    @property
    @abstractmethod
    def nombre(self) -> str:
        """Etiqueta del modelo, tal como queda registrada en MLflow."""

    @abstractmethod
    def _clasificador(self) -> BaseEstimator:
        """Clasificador concreto, con la semilla y el peso de clase ya aplicados."""

    @abstractmethod
    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Distribuciones que muestrea la busqueda aleatoria, prefijadas por el paso."""

    def pipeline(self) -> Pipeline:
        """Codificacion del frente, seleccion de variables y clasificador, en ese orden.

        El codificador aprende el nivel de ley del frente aunque el objetivo aqui sea la
        falla: `CodificadorNivelFrente` codifica con el objetivo que reciba, de modo que en
        este pipeline la codificacion del frente es su tasa historica de falla y no su ley.
        Es la misma idea aplicada al otro problema, y por eso tiene que reajustarse dentro
        del pipeline igual que alli.
        """
        return Pipeline([
            ("nivel", CodificadorNivelFrente()),
            ("variables", SelectorVariables(conjunto=self.conjunto)),
            (PASO_MODELO, self._clasificador()),
        ])


class ClasificadorLightGBM(ModeloFalla):
    """LightGBM con peso de clase, sin remuestreo."""

    @property
    def nombre(self) -> str:
        """Etiqueta del modelo."""
        return "lightgbm"

    def _clasificador(self) -> BaseEstimator:
        """Clasificador con `scale_pos_weight` para reequilibrar la perdida."""
        return lgb.LGBMClassifier(
            random_state=self.semilla, verbose=-1, n_jobs=-1,
            scale_pos_weight=self.peso_positivo)

    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Espacio de hiperparametros, muestreado por la busqueda aleatoria."""
        return {
            f"{PASO_MODELO}__num_leaves": randint(7, 64),
            f"{PASO_MODELO}__min_child_samples": randint(10, 101),
            f"{PASO_MODELO}__learning_rate": loguniform(0.01, 0.2),
            f"{PASO_MODELO}__n_estimators": randint(100, 601),
            f"{PASO_MODELO}__subsample": uniform(0.6, 0.4),
            f"{PASO_MODELO}__subsample_freq": randint(1, 6),
            f"{PASO_MODELO}__colsample_bytree": uniform(0.6, 0.4),
            f"{PASO_MODELO}__reg_lambda": loguniform(0.001, 10.0),
        }


class ClasificadorXGBoost(ModeloFalla):
    """XGBoost con peso de clase, sin remuestreo."""

    @property
    def nombre(self) -> str:
        """Etiqueta del modelo."""
        return "xgboost"

    def _clasificador(self) -> BaseEstimator:
        """Clasificador con `scale_pos_weight` para reequilibrar la perdida."""
        return xgb.XGBClassifier(
            random_state=self.semilla, verbosity=0, n_jobs=-1,
            scale_pos_weight=self.peso_positivo, eval_metric="logloss")

    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Espacio de hiperparametros, muestreado por la busqueda aleatoria."""
        return {
            f"{PASO_MODELO}__max_depth": randint(2, 9),
            f"{PASO_MODELO}__min_child_weight": randint(1, 21),
            f"{PASO_MODELO}__learning_rate": loguniform(0.01, 0.2),
            f"{PASO_MODELO}__n_estimators": randint(100, 601),
            f"{PASO_MODELO}__subsample": uniform(0.6, 0.4),
            f"{PASO_MODELO}__colsample_bytree": uniform(0.6, 0.4),
            f"{PASO_MODELO}__reg_lambda": loguniform(0.001, 10.0),
        }


#: Los dos clasificadores que se comparan, en el orden en que se reportan.
CLASIFICADORES: tuple[type[ModeloFalla], ...] = (ClasificadorLightGBM, ClasificadorXGBoost)


def peso_de_clase(objetivo: Any) -> float:
    """Razon entre negativos y positivos, que es lo que espera `scale_pos_weight`.

    Con la tasa de falla del extracto da alrededor de 3.6: la perdida pondera cada turno con
    falla como si fueran casi cuatro. Devuelve 1.0 cuando no hay positivos, para que un bloque
    degenerado no produzca una division por cero en medio de una busqueda.

    **Limitacion declarada.** Cuando la fase A lo compara, el peso se calcula una vez sobre
    todo el desarrollo y no dentro de cada pliegue, de modo que un escalar -la prevalencia
    marginal del periodo de desarrollo- cruza la frontera entre entrenamiento y validacion. Se
    acepta a proposito: la alternativa correcta seria recalcularlo por pliegue, lo que en
    LightGBM se resuelve con `class_weight="balanced"` pero en XGBoost no tiene equivalente
    directo, y usar mecanismos distintos en cada libreria haria que la comparacion entre las
    dos midiera el mecanismo y no el modelo. Lo que se filtra es un solo numero que ademas
    apenas varia entre bloques, y la decision queda escrita aqui en lugar de quedar escondida.
    """
    import numpy as np

    y = np.asarray(objetivo, dtype=float)
    positivos = float((y > 0).sum())
    negativos = float((y <= 0).sum())
    return negativos / positivos if positivos > 0 else 1.0
