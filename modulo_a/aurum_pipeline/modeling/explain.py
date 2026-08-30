"""Valores SHAP del modelo de regresion de ley.

El enunciado pregunta que sensor es el predictor mas importante de la ley de oro y si tiene
sentido operacional. La respuesta que da este extracto es que **ninguno**: lo que manda es el
nivel historico del propio frente, y los sensores de perforacion reparten entre si una
contribucion que no se distingue del ruido.

Tiene todo el sentido geologico. La ley es una propiedad de la veta, no de como se perfora:
la presion hidraulica y las revoluciones de la corona describen el esfuerzo sobre la roca, no
su contenido de oro. Y deja una conclusion accionable, que es lo que un area de operaciones
espera de un analisis: para mejorar esta prediccion hace falta geologia -ensayos, mapeo,
sondajes- y no mas telemetria.

**Se usa SHAP y no la importancia por ganancia de los arboles.** La ganancia reparte credito
entre variables correlacionadas segun el orden en que el arbol las eligio, y en una sonda
sobre este extracto mostraba a la presion con 9.7% y a la vibracion con 9.5% de importancia
cuando ninguna de las dos aporta nada medible. SHAP atribuye la contribucion a la prediccion
de cada fila, que es lo que se puede llevar a una conversacion con operaciones.

**El clasificador tambien se explica, y a tres horizontes.** La objecion legitima es que, si
la temperatura anticipa la falla, deberia verse en el SHAP del clasificador. El clasificador
registrado no lleva sensores, asi que explicarlo no puede mostrarla por construccion; por eso
`ExplicadorFalla` explica ademas un clasificador con todas las variables, y
`SondaContemporanea` mide el mismo sensor a nivel de evento contra la falla del mismo evento y
contra la del evento siguiente. Si la senal muere entre esos dos horizontes, no hay ventana de
cuatro horas que la recupere: el rango util del sensor es contemporaneo.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Self

import matplotlib
import numpy as np
import numpy.typing as npt
import pandas as pd
import shap
import xgboost as xgb
from sklearn.pipeline import Pipeline

from aurum_pipeline import domain
from aurum_pipeline.errors import (
    EmptyPartitionError,
    InvalidParameterError,
    MissingColumnsError,
)
from aurum_pipeline.modeling.dataset import SENSORES_PROMEDIADOS
from aurum_pipeline.modeling.metrics import evaluar_falla

logger = logging.getLogger(__name__)


class ExplicadorLey:
    """Calcula la contribucion de cada variable a la prediccion, sobre el conjunto de prueba.

    Toma el pipeline completo y separa por dentro sus dos partes: los transformadores producen
    la matriz numerica que el regresor recibio de verdad, y sobre esa matriz corre el
    explicador de arboles. Explicar sobre las columnas originales daria nombres bonitos y
    atribuciones equivocadas, porque el modelo nunca vio esas columnas.
    """

    #: Unidad de la contribucion media, que da nombre a la columna de la tabla de importancia:
    #: en regresion, gramos por tonelada; el clasificador la redefine.
    unidad: str = "g_por_tonelada"

    def __init__(self, pipeline: Pipeline) -> None:
        if len(pipeline.steps) < 2:
            raise InvalidParameterError(
                "el pipeline debe tener al menos un transformador y un regresor")
        self.pipeline = pipeline
        # Se guardan los transformadores ya ajustados y no un corte `pipeline[:-1]`: el corte
        # devuelve un `Pipeline` nuevo que scikit-learn considera sin ajustar, aunque sus
        # pasos si lo esten, y `transform` sobre el falla con `NotFittedError`.
        self._transformadores = [paso for _, paso in pipeline.steps[:-1]]
        self._regresor = pipeline.steps[-1][1]

    def variables(self, matriz: pd.DataFrame) -> pd.DataFrame:
        """Matriz numerica tal como la recibio el regresor."""
        preparada: pd.DataFrame = matriz
        for transformador in self._transformadores:
            preparada = transformador.transform(preparada)
        return pd.DataFrame(preparada).reset_index(drop=True)

    def valores(self, matriz: pd.DataFrame) -> pd.DataFrame:
        """Valores SHAP por fila y variable, con los nombres de las columnas del modelo."""
        variables = self.variables(matriz)
        explicador = shap.TreeExplainer(self._regresor)
        valores = np.asarray(explicador.shap_values(variables), dtype=float)
        return pd.DataFrame(valores, columns=variables.columns)

    def importancia(self, matriz: pd.DataFrame) -> pd.DataFrame:
        """Contribucion media absoluta de cada variable, de mayor a menor.

        Se acompana del porcentaje sobre el total porque la cifra absoluta en g/t no dice por
        si sola si una variable pesa mucho o poco frente a las demas.
        """
        valores = self.valores(matriz)
        media = valores.abs().mean().sort_values(ascending=False)
        contribucion = np.asarray(media.to_numpy(), dtype=float)
        total = float(contribucion.sum())
        return pd.DataFrame({
            "variable": list(media.index),
            f"contribucion_media_{self.unidad}": contribucion,
            "contribucion_pct": 100.0 * contribucion / total if total > 0 else contribucion,
        }).reset_index(drop=True)

    def figura_resumen(self, matriz: pd.DataFrame, ruta: Path) -> Path:
        """Guarda el resumen grafico de SHAP y devuelve la ruta del archivo.

        Se fija el backend `Agg` porque esto corre tanto en un notebook como en una consola
        sin entorno grafico, y sin el la generacion falla en la segunda.
        """
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        variables = self.variables(matriz)
        valores = self.valores(matriz).to_numpy()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        plt.figure()
        shap.summary_plot(valores, variables, show=False, plot_size=(9, 6))
        plt.tight_layout()
        plt.savefig(ruta, dpi=140)
        plt.close("all")
        logger.info("Figura SHAP guardada en %s", ruta)
        return ruta


def _clase_positiva(crudos: Any) -> npt.NDArray[np.float64]:
    """Atribucion de la clase positiva, sea cual sea la forma en que la libreria la entregue.

    Los explicadores de arboles devuelven, para un clasificador binario, una lista de dos
    arreglos o un tensor de tres ejes segun la libreria y la version. Se normaliza aqui una
    sola vez para que los dos usos -el explicador y la sonda- no repitan la misma lectura.
    """
    if isinstance(crudos, list):
        crudos = crudos[-1]
    valores = np.asarray(crudos, dtype=float)
    return valores[..., -1] if valores.ndim == 3 else valores


class ExplicadorFalla(ExplicadorLey):
    """Atribucion SHAP de un clasificador de falla, sobre la clase positiva.

    Comparte todo con el explicador de ley salvo una cosa: los explicadores de arboles
    devuelven, para un clasificador binario, una atribucion por clase -una lista o un tensor
    de tres ejes segun la libreria- y lo que interesa es la de la falla. Se hereda para
    compartir el contrato y no para reutilizar por conveniencia: la unica diferencia es como
    se leen los valores, y esa diferencia queda en un solo metodo.
    """

    #: La atribucion de un clasificador de arboles esta en el margen del logit, no en g/t.
    unidad: str = "log_odds"

    def valores(self, matriz: pd.DataFrame) -> pd.DataFrame:
        """Valores SHAP de la clase positiva por fila y variable."""
        variables = self.variables(matriz)
        valores = _clase_positiva(shap.TreeExplainer(self._regresor).shap_values(variables))
        return pd.DataFrame(valores, columns=variables.columns)


#: Hiperparametros de la sonda. No se buscan: es una medicion y no un modelo que se despliegue.
#: Arboles rasos como los que la busqueda prefirio para el clasificador de falla, pero sin
#: peso minimo por hoja: con positivos al 3% el hessiano de cada fila es 0.03, y un minimo
#: de 19 como el del clasificador impediria cualquier division sobre pocos miles de eventos.
PARAMETROS_SONDA: Final[dict[str, Any]] = {
    "max_depth": 3, "min_child_weight": 1, "learning_rate": 0.05, "n_estimators": 300,
    "subsample": 0.8, "colsample_bytree": 0.9, "reg_lambda": 2.5,
}

#: Etiquetas de los dos horizontes de la sonda, tal como salen en la tabla de resultados.
HORIZONTE_MISMO_EVENTO: Final[str] = "mismo evento"
HORIZONTE_EVENTO_SIGUIENTE: Final[str] = "evento siguiente"


class SondaContemporanea:
    """Mide cuanto vale el mismo sensor a horizonte cero y a un evento, a nivel de evento.

    Entrena dos clasificadores identicos sobre los sensores del evento: uno contra la falla del
    mismo evento -deteccion, no pronostico- y otro contra la falla del evento siguiente del
    mismo frente, unos 25 minutos despues. Los dos se entrenan antes del corte y se evaluan
    despues, con la misma disciplina temporal que el resto del modelado. La atribucion SHAP se
    calcula sobre el modelo contemporaneo, que es donde la temperatura tiene algo que decir.

    Es una sonda: sus hiperparametros no se buscan y su resultado no se despliega. Existe para
    que la frase "el rango util del sensor es contemporaneo" tenga un numero al lado en lugar
    de apoyarse en una tabla del EDA.
    """

    def __init__(
        self,
        sensores: tuple[str, ...] = SENSORES_PROMEDIADOS,
        columna_tiempo: str = domain.COLUMNA_INICIO_TURNO,
        columna_grupo: str = domain.COLUMNA_FRENTE,
        columna_falla: str = domain.COLUMNA_FALLA,
        semilla: int = domain.SEMILLA,
    ) -> None:
        if not sensores:
            raise InvalidParameterError("la sonda necesita al menos un sensor")
        self.sensores = sensores
        self.columna_tiempo = columna_tiempo
        self.columna_grupo = columna_grupo
        self.columna_falla = columna_falla
        self.semilla = semilla

    def ajustar(self, eventos: pd.DataFrame, corte: pd.Timestamp) -> Self:
        """Entrena los dos modelos antes de `corte` y los evalua sobre los eventos posteriores."""
        faltantes = {*self.sensores, self.columna_tiempo, self.columna_grupo,
                     self.columna_falla} - set(eventos.columns)
        if faltantes:
            raise MissingColumnsError(type(self).__name__, faltantes)

        orden = eventos.sort_values([self.columna_grupo, self.columna_tiempo])
        por_grupo = orden.groupby(self.columna_grupo, sort=False)
        etiquetas = {
            HORIZONTE_MISMO_EVENTO: orden[self.columna_falla].notna().astype(int),
            HORIZONTE_EVENTO_SIGUIENTE: por_grupo[self.columna_falla].shift(-1).notna().astype(int),
        }
        # El ultimo evento de cada frente no tiene siguiente: sale del segundo horizonte.
        validos = {
            HORIZONTE_MISMO_EVENTO: pd.Series(True, index=orden.index),
            HORIZONTE_EVENTO_SIGUIENTE: por_grupo[self.columna_tiempo].shift(-1).notna(),
        }
        antes = orden[self.columna_tiempo] < pd.Timestamp(corte)
        if not antes.any() or antes.all():
            raise EmptyPartitionError(
                f"el corte {corte} deja {int(antes.sum())} eventos para entrenar y "
                f"{int((~antes).sum())} para evaluar")

        filas = []
        for horizonte, etiqueta in etiquetas.items():
            entrena = antes & validos[horizonte]
            evalua = ~antes & validos[horizonte]
            modelo = xgb.XGBClassifier(
                **PARAMETROS_SONDA, random_state=self.semilla, verbosity=0, n_jobs=-1)
            modelo.fit(orden.loc[entrena, list(self.sensores)], etiqueta[entrena])
            probabilidad = modelo.predict_proba(orden.loc[evalua, list(self.sensores)])[:, 1]
            metricas = evaluar_falla(etiqueta[evalua].to_numpy(dtype=float), probabilidad)
            filas.append({
                "horizonte": horizonte,
                "eventos": int(evalua.sum()),
                "precision_media": metricas.precision_media,
                "tasa_base_falla": metricas.tasa_base,
                "levante_sobre_azar": metricas.levante_sobre_azar,
                "area_bajo_roc": metricas.area_bajo_roc,
            })
            if horizonte == HORIZONTE_MISMO_EVENTO:
                self.importancia_ = self._importancia(
                    modelo, orden.loc[evalua, list(self.sensores)])
        self.resultados_: pd.DataFrame = pd.DataFrame(filas)
        logger.info("%s: %s", type(self).__name__, self.resultados_.round(4).to_dict("records"))
        return self

    def _importancia(self, modelo: Any, variables: pd.DataFrame) -> pd.DataFrame:
        """Contribucion media absoluta de cada sensor, de mayor a menor, en porcentaje."""
        valores = _clase_positiva(shap.TreeExplainer(modelo).shap_values(variables))
        media = pd.Series(np.abs(valores).mean(axis=0), index=variables.columns)
        media = media.sort_values(ascending=False)
        total = float(media.sum())
        return pd.DataFrame({
            "variable": list(media.index),
            "contribucion_media_log_odds": media.to_numpy(dtype=float),
            "contribucion_pct": 100.0 * media.to_numpy(dtype=float) / max(total, 1e-12),
        }).reset_index(drop=True)
