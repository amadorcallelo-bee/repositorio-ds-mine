"""Entrenamiento y evaluacion del modelo de ley para el B-3, portado del A-2.

No se reimplementa nada del modelado: la matriz por turno la construye
`ConstructorMatrizTurno`, el pipeline es `ModeloLightGBM` con el conjunto `MINIMO` -el
ganador del A-2, que empata con el baseline del nivel del frente hasta la cuarta cifra- y
las metricas salen de `aurum_pipeline.modeling.metrics`, con los mismos nombres de
operacion que quedaron en el MLflow local. Lo unico nuevo es la particion: aqui no hay
walk-forward de cinco pliegues -ese protocolo es del A-2 y se cita, no se duplica- sino un
corte temporal simple: se entrena con la historia hasta el inicio de la ventana de
evaluacion del monitor y se valida sobre esa ventana, que es la misma con la que se decide
promover o revertir.

Sin busqueda de hiperparametros: el A-2 midio que en `MINIMO` la configuracion por defecto
reproduce al baseline y no hay nada que buscar (docs/modelado.md, fases A y B).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sklearn.pipeline import Pipeline

from aurum_pipeline import domain as dominio_a2
from aurum_pipeline.modeling import metrics as metricas_a2
from aurum_pipeline.modeling.dataset import ConstructorMatrizTurno
from aurum_pipeline.modeling.features import MINIMO, columnas_de_entrada, tipos_de_servicio
from aurum_pipeline.modeling.models import ModeloLightGBM
from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModeloEntrenado:
    """Un pipeline ajustado con las metricas y el contrato que el registro necesita."""

    pipeline: Pipeline
    conjunto: str
    corte_evaluacion: date
    turnos_entrenamiento: int
    turnos_evaluacion: int
    metricas: dict[str, float]
    ejemplo: pd.DataFrame


class EntrenadorLey:
    """Entrena el modelo del A-2 sobre eventos de silver y lo mide en la ventana del monitor.

    Recibe eventos como pandas -la matriz del A-2 es pandas y son ~50 000 filas- y silver ya
    trae el centinela como nulo, que es exactamente lo que el constructor de la matriz exige.
    """

    def __init__(self, dias_evaluacion: int = dominio.VENTANA_EVALUACION_DIAS) -> None:
        if dias_evaluacion < 1:
            raise ParametroInvalidoError("La ventana de evaluacion necesita al menos un dia")
        self.dias_evaluacion = dias_evaluacion
        self.constructor = ConstructorMatrizTurno()

    def matriz(self, eventos: pd.DataFrame) -> pd.DataFrame:
        """La matriz supervisada del A-2, una fila por par (turno, turno siguiente)."""
        return self.constructor.construir(eventos[list(self.constructor.columnas_requeridas)])

    def particion(self, matriz: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, date]:
        """Corta por fecha: entrena la historia, evalua los ultimos dias del monitor."""
        inicios = matriz[dominio_a2.COLUMNA_INICIO_TURNO]
        corte = inicios.max().date() - timedelta(days=self.dias_evaluacion - 1)
        evalua = matriz[inicios.dt.date >= corte]
        entrena = matriz[inicios.dt.date < corte]
        if entrena.empty or evalua.empty:
            raise ParametroInvalidoError(
                f"La particion en {corte} deja {len(entrena)} turnos de entrenamiento "
                f"y {len(evalua)} de evaluacion")
        return entrena, evalua, corte

    def entrenar(self, eventos: pd.DataFrame) -> ModeloEntrenado:
        """Ajusta el pipeline del A-2 y registra validacion, entrenamiento y brecha."""
        matriz = self.matriz(eventos)
        entrena, evalua, corte = self.particion(matriz)
        pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline()
        objetivo = dominio_a2.COLUMNA_OBJETIVO
        pipeline.fit(entrena, entrena[objetivo])
        error_entrena = metricas_a2.evaluar(
            entrena[objetivo].to_numpy(dtype=float), pipeline.predict(entrena)).valor_principal
        error_evalua = metricas_a2.evaluar(
            evalua[objetivo].to_numpy(dtype=float), pipeline.predict(evalua)).valor_principal
        ejemplo = tipos_de_servicio(
            entrena.loc[entrena.index[:3], list(columnas_de_entrada(MINIMO))])
        resultado = ModeloEntrenado(
            pipeline=pipeline,
            conjunto=MINIMO.nombre,
            corte_evaluacion=corte,
            turnos_entrenamiento=len(entrena),
            turnos_evaluacion=len(evalua),
            metricas={
                dominio.METRICA_ERROR: error_evalua,
                dominio.METRICA_ERROR_ENTRENAMIENTO: error_entrena,
                dominio.METRICA_BRECHA: error_evalua - error_entrena,
                "turnos_entrenamiento": float(len(entrena)),
            },
            ejemplo=ejemplo,
        )
        logger.info("entrenado %s: %s", MINIMO.nombre, resultado.metricas)
        return resultado

    def evaluar_en_ventana(self, pipeline: Pipeline, eventos: pd.DataFrame) -> float:
        """El error del pipeline sobre la ventana de evaluacion, en g/t."""
        matriz = self.matriz(eventos)
        _, evalua, _ = self.particion(matriz)
        objetivo = evalua[dominio_a2.COLUMNA_OBJETIVO].to_numpy(dtype=float)
        return float(metricas_a2.evaluar(objetivo, pipeline.predict(evalua)).valor_principal)
