"""Evaluacion por pliegues y busqueda de hiperparametros sobre la particion temporal.

Existe como modulo propio y no dentro de `metrics.py` porque son dos responsabilidades
distintas: alli se calcula el error de una prediccion, aqui se decide sobre que datos se
calcula. La separacion es la que permite que baselines, regresores y clasificadores pasen
exactamente por el mismo camino.

**Por que no se usa `cross_val_score`.** Devuelve un numero por pliegue y nada mas. Aqui hace
falta el detalle -cuantos turnos entrenaron, cuantos validaron, la metrica de cada bloque-
para que la comparacion de ventanas temporales muestre no solo cual gana en promedio sino
cual es mas estable, que en este problema es la mitad del argumento.

**Cada pliegue se mide dos veces: sobre lo que valida y sobre lo que entreno.** La metrica de
validacion dice cuanto acierta el modelo; la de entrenamiento, cuanto memorizo. Sin la segunda
la brecha entre ambas no existe en el registro, y el sobreajuste no se puede diagnosticar desde
MLflow: se ve un numero de validacion y no se sabe si viene de un modelo que generaliza o de
uno que aprendio el ruido y perdio por el camino. Cuesta una prediccion mas por pliegue, que
frente al ajuste es despreciable. La brecha se expresa siempre como "cuanto mejor se ve el
modelo sobre sus propios datos", de modo que sea positiva bajo sobreajuste en los dos problemas
aunque en uno la metrica principal se maximice y en el otro se minimice.

**Regresion y clasificacion comparten el recorrido y difieren en un objeto.** Lo unico que
cambia entre los dos problemas es como se obtiene la prediccion -valor o probabilidad- y con
que metricas se juzga; eso viaja en un `Evaluador`, y el resto del codigo es identico. La
alternativa, un parametro booleano que bifurque por dentro, esconde dos comportamientos en
una firma que dice tener uno.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, clone
from sklearn.model_selection import RandomizedSearchCV
from sklearn.pipeline import Pipeline

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.modeling.falla import COLUMNA_VENTANA_OBSERVADA
from aurum_pipeline.modeling.metrics import evaluar, evaluar_falla
from aurum_pipeline.modeling.splitter import VentanaTemporal

logger = logging.getLogger(__name__)

#: Sufijo con que la familia de metricas de entrenamiento se distingue de la de validacion en
#: MLflow: `precision_media_entrenamiento` junto a `precision_media`.
SUFIJO_ENTRENAMIENTO: Final[str] = "_entrenamiento"

#: Nombre de la metrica derivada que un panel puede ordenar y alertar.
BRECHA: Final[str] = "brecha_entrenamiento_validacion"

#: Nombre del conteo de turnos dentro de cada familia de metricas. No lleva sufijo de
#: entrenamiento porque el tamano del entrenamiento ya tiene su propio nombre en el registro.
METRICA_TURNOS: Final[str] = "turnos"


class Metricas(Protocol):
    """Lo que toda familia de metricas tiene que ofrecer para entrar a una comparacion."""

    @property
    def valor_principal(self) -> float:
        """Metrica con la que se ordena la comparacion."""

    def como_diccionario(self) -> dict[str, float]:
        """Metricas con los nombres del negocio, listas para MLflow."""


class Evaluador(Protocol):
    """Como se obtiene una prediccion de un estimador ajustado y con que se la juzga.

    Los dos atributos se declaran de solo lectura porque quienes lo implementan son
    `dataclass` congelados: un protocolo con atributos escribibles no los aceptaria.
    """

    @property
    def nombre_principal(self) -> str:
        """Nombre de la metrica con que se ordena la comparacion."""

    @property
    def mejor_es_mayor(self) -> bool:
        """Si un valor mayor de la metrica principal es mejor."""

    def __call__(
        self,
        estimador: BaseEstimator,
        variables: pd.DataFrame,
        objetivo: pd.Series,
    ) -> Metricas:
        """Predice sobre `variables` y compara contra `objetivo`."""


class FabricaModelo(Protocol):
    """Lo que la busqueda necesita de un modelo: un pipeline, un espacio y un nombre."""

    @property
    def nombre(self) -> str:
        """Etiqueta del modelo."""

    def pipeline(self) -> Pipeline:
        """Pipeline sin ajustar."""

    def espacio_busqueda(self) -> Mapping[str, Any]:
        """Distribuciones de hiperparametros."""


@dataclass(frozen=True)
class _EvaluadorRegresion:
    """Evalua un regresor por su prediccion puntual."""

    nombre_principal: str = "error_medio_g_por_tonelada"
    mejor_es_mayor: bool = False

    def __call__(
        self,
        estimador: BaseEstimator,
        variables: pd.DataFrame,
        objetivo: pd.Series,
    ) -> Metricas:
        """Error de la prediccion contra el objetivo."""
        return evaluar(objetivo.to_numpy(dtype=float), estimador.predict(variables))


@dataclass(frozen=True)
class _EvaluadorFalla:
    """Evalua un clasificador por la probabilidad que asigna a la clase positiva.

    Si el marco trae la marca de ventana observada, la pasa a las metricas para que la
    precision media con actividad se calcule sobre los turnos que siguieron operando. La marca
    no es una variable del modelo: el estimador recibe el marco completo y su selector de
    variables la ignora, igual que ignora el objetivo.
    """

    nombre_principal: str = "precision_media"
    mejor_es_mayor: bool = True

    def __call__(
        self,
        estimador: BaseEstimator,
        variables: pd.DataFrame,
        objetivo: pd.Series,
    ) -> Metricas:
        """Metricas de la probabilidad de falla contra la etiqueta."""
        probabilidad = estimador.predict_proba(variables)[:, 1]
        con_actividad = (
            variables[COLUMNA_VENTANA_OBSERVADA].to_numpy(dtype=float)
            if COLUMNA_VENTANA_OBSERVADA in variables.columns else None)
        return evaluar_falla(objetivo.to_numpy(dtype=float), probabilidad, con_actividad)


#: Los dos evaluadores del modulo, uno por problema.
EVALUADOR_REGRESION: Evaluador = _EvaluadorRegresion()
EVALUADOR_FALLA: Evaluador = _EvaluadorFalla()

#: Metrica con que `RandomizedSearchCV` ordena cada problema. Son las mismas con que despues
#: se reporta: buscar con una y reportar con otra elige el modelo equivocado.
PUNTAJE_REGRESION: str = "neg_mean_absolute_error"
PUNTAJE_FALLA: str = "average_precision"


@dataclass(frozen=True)
class ResultadoPliegue:
    """Lo que dejo un bloque de validacion: sus metricas, las de entrenamiento y los tamanos."""

    numero: int
    turnos_entrenamiento: int
    turnos_validacion: int
    frentes_entrenamiento: int
    metricas: Metricas
    metricas_entrenamiento: Metricas
    mejor_es_mayor: bool

    @property
    def brecha_entrenamiento_validacion(self) -> float:
        """Cuanto mejor se ve el modelo sobre lo que entreno que sobre lo que valida.

        Positiva bajo sobreajuste en los dos problemas: en clasificacion es la precision media
        de entrenamiento menos la de validacion; en regresion, el error de validacion menos el
        de entrenamiento.
        """
        entrenamiento = self.metricas_entrenamiento.valor_principal
        validacion = self.metricas.valor_principal
        return entrenamiento - validacion if self.mejor_es_mayor else validacion - entrenamiento

    def como_diccionario(self) -> dict[str, float]:
        """Validacion, entrenamiento con sufijo y brecha, con los nombres del negocio."""
        registro = dict(self.metricas.como_diccionario())
        registro.update({
            f"{nombre}{SUFIJO_ENTRENAMIENTO}": valor
            for nombre, valor in self.metricas_entrenamiento.como_diccionario().items()
            if nombre != METRICA_TURNOS
        })
        registro[BRECHA] = self.brecha_entrenamiento_validacion
        return registro


@dataclass(frozen=True)
class ResultadoEvaluacion:
    """Resumen de una combinacion evaluada sobre todos los pliegues."""

    nombre: str
    pliegues: tuple[ResultadoPliegue, ...]
    nombre_principal: str
    mejor_es_mayor: bool

    @property
    def valor_principal(self) -> float:
        """Promedio simple de la metrica principal: todos los pliegues pesan igual."""
        return float(np.mean([p.metricas.valor_principal for p in self.pliegues]))

    @property
    def valor_principal_entrenamiento(self) -> float:
        """Promedio de la metrica principal sobre las filas con que entreno cada pliegue."""
        return float(np.mean([p.metricas_entrenamiento.valor_principal for p in self.pliegues]))

    @property
    def brecha_entrenamiento_validacion(self) -> float:
        """Promedio de la brecha de cada pliegue."""
        return float(np.mean([p.brecha_entrenamiento_validacion for p in self.pliegues]))

    @property
    def desviacion_entre_pliegues(self) -> float:
        """Cuanto varia la metrica de un bloque a otro. Es la mitad del argumento."""
        valores = [p.metricas.valor_principal for p in self.pliegues]
        return float(np.std(valores, ddof=1)) if len(valores) > 1 else 0.0

    @property
    def turnos_entrenamiento_medio(self) -> float:
        """Tamano medio del entrenamiento, que es lo que distingue una ventana de otra."""
        return float(np.mean([p.turnos_entrenamiento for p in self.pliegues]))

    def promedio(self, metrica: str) -> float:
        """Promedio de cualquier metrica registrada, entre los pliegues."""
        return float(np.mean([p.como_diccionario()[metrica] for p in self.pliegues]))

    def como_diccionario(self) -> dict[str, float]:
        """Metricas agregadas listas para MLflow, con los nombres del negocio."""
        agregadas = {
            nombre: self.promedio(nombre)
            for nombre in self.pliegues[0].como_diccionario()
        }
        agregadas["desviacion_entre_pliegues"] = self.desviacion_entre_pliegues
        agregadas["turnos_entrenamiento"] = self.turnos_entrenamiento_medio
        return agregadas


def evaluar_por_pliegues(
    estimador: BaseEstimator,
    matriz: pd.DataFrame,
    ventana: VentanaTemporal,
    nombre: str,
    columna_objetivo: str = domain.COLUMNA_OBJETIVO,
    evaluador: Evaluador = EVALUADOR_REGRESION,
) -> ResultadoEvaluacion:
    """Ajusta y evalua el estimador en cada pliegue, devolviendo el detalle y el agregado.

    El estimador se clona en cada pliegue: reutilizar el mismo objeto lo dejaria ajustado con
    el pliegue anterior y la evaluacion mediria un modelo que en produccion no existe. El
    modelo ajustado se mide contra el bloque de validacion y contra sus propias filas de
    entrenamiento, para que la brecha entre ambas quede registrada.
    """
    if columna_objetivo not in matriz.columns:
        raise InvalidParameterError(
            f"la matriz no trae la columna de objetivo {columna_objetivo!r}")

    objetivo = matriz[columna_objetivo]
    resultados: list[ResultadoPliegue] = []
    for numero, (entrena, valida) in enumerate(ventana.split(matriz), start=1):
        modelo = clone(estimador)
        modelo.fit(matriz.iloc[entrena], objetivo.iloc[entrena])
        resultados.append(ResultadoPliegue(
            numero=numero,
            turnos_entrenamiento=len(entrena),
            turnos_validacion=len(valida),
            frentes_entrenamiento=int(
                matriz.iloc[entrena][domain.COLUMNA_FRENTE].nunique()),
            metricas=evaluador(modelo, matriz.iloc[valida], objetivo.iloc[valida]),
            metricas_entrenamiento=evaluador(
                modelo, matriz.iloc[entrena], objetivo.iloc[entrena]),
            mejor_es_mayor=evaluador.mejor_es_mayor,
        ))

    resultado = ResultadoEvaluacion(
        nombre=nombre, pliegues=tuple(resultados),
        nombre_principal=evaluador.nombre_principal,
        mejor_es_mayor=evaluador.mejor_es_mayor)
    logger.info("%s: %s %.4f, desviacion %.4f entre %d pliegues, brecha %.4f",
                nombre, resultado.nombre_principal, resultado.valor_principal,
                resultado.desviacion_entre_pliegues, len(resultados),
                resultado.brecha_entrenamiento_validacion)
    return resultado


def buscar_hiperparametros(
    modelo: FabricaModelo,
    matriz: pd.DataFrame,
    ventana: VentanaTemporal,
    iteraciones: int = domain.ITERACIONES_BUSQUEDA,
    semilla: int = domain.SEMILLA,
    columna_objetivo: str = domain.COLUMNA_OBJETIVO,
    puntaje: str = PUNTAJE_REGRESION,
) -> RandomizedSearchCV:
    """Busca hiperparametros con muestreo aleatorio sobre los mismos pliegues purgados.

    La busqueda se anida dentro de cada estrategia de ventana y no se hace una vez con la
    expansiva: fijar los hiperparametros con una estrategia y despues comparar estrategias
    sesgaria la comparacion a favor de la que los eligio. Asi cada ventana compite en su mejor
    configuracion.

    Se pide el puntaje de entrenamiento de cada configuracion porque sale casi gratis de la
    busqueda que ya se corre, y con el la tabla de configuraciones muestra la curva entre
    capacidad y brecha sin un experimento aparte.

    Se descarto la rejilla exhaustiva porque con siete hiperparametros y unos 1500 turnos de
    entrenamiento es gastar computo en explorar ruido, y se descarto la optimizacion bayesiana
    porque agrega una dependencia para una ganancia que aqui no existe: el techo del problema
    esta a cinco diezmilesimas del baseline.
    """
    if iteraciones < 1:
        raise InvalidParameterError(
            f"la busqueda necesita al menos una iteracion, se recibio {iteraciones}")

    busqueda = RandomizedSearchCV(
        estimator=modelo.pipeline(),
        param_distributions=dict(modelo.espacio_busqueda()),
        n_iter=iteraciones,
        cv=ventana,
        scoring=puntaje,
        random_state=semilla,
        refit=True,
        return_train_score=True,
        error_score="raise",
    )
    busqueda.fit(matriz, matriz[columna_objetivo])
    logger.info("%s con ventana %s: mejor puntaje de validacion %.4f",
                modelo.nombre, ventana.nombre, float(busqueda.best_score_))
    return busqueda


def configuraciones_muestreadas(busqueda: RandomizedSearchCV) -> pd.DataFrame:
    """Tabla de todas las configuraciones probadas, de mejor a peor.

    Es el artefacto que hace reproducible una busqueda aleatoria: sin el, la semilla obliga a
    reejecutar para saber que se probo. Trae el puntaje de entrenamiento y la brecha de cada
    configuracion; los puntajes de scikit-learn se maximizan siempre, de modo que la resta
    tiene el mismo signo en los dos problemas.
    """
    tabla = pd.DataFrame(busqueda.cv_results_["params"])
    tabla.columns = [columna.split("__")[-1] for columna in tabla.columns]
    tabla["puntaje_validacion"] = np.asarray(
        busqueda.cv_results_["mean_test_score"], dtype=float)
    tabla["puntaje_entrenamiento"] = np.asarray(
        busqueda.cv_results_["mean_train_score"], dtype=float)
    tabla[BRECHA] = tabla["puntaje_entrenamiento"] - tabla["puntaje_validacion"]
    tabla["desviacion_entre_pliegues"] = np.asarray(
        busqueda.cv_results_["std_test_score"], dtype=float)
    return tabla.sort_values("puntaje_validacion", ascending=False).reset_index(drop=True)
