"""Ingenieria de features del pipeline AURUM.

Las features no se eligieron por catalogo sino por los dos objetivos del modulo: predecir la
ley del turno siguiente y anticipar la falla mecanica. El analisis exploratorio decidio cuales
sobreviven, y tres mediciones explican por que la lista es corta:

1. **La ley es el nivel del frente mas ruido blanco.** La correlacion de una lectura con la
   anterior del mismo frente es 0.83, pero al quitar la media del frente cae a -0.001. La
   memoria del proceso no existe: lo unico que hay para predecir es el nivel del frente, y por
   eso sobrevive una ventana movil que lo estima y un lag que aporta el ultimo dato conocido,
   no una bateria de rezagos.

2. **Los sensores no tienen persistencia.** La correlacion de `temp_motor_c` con su propio
   valor anterior en el mismo equipo es 0.004; la de vibracion, -0.011. Cualquier rolling de
   sensor seria ruido promediado con ruido.

3. **La relacion de la temperatura con la falla es un escalon, no una pendiente.** Por debajo
   de 88 C la tasa ronda el 2%; por encima se estabiliza en 22% y ya no crece. Eso descarta
   codificar la magnitud del exceso y pide banderas.
"""

from __future__ import annotations

import logging
from typing import Literal

import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.transformers.base import AurumTransformer

logger = logging.getLogger(__name__)

Estadistico = Literal["media", "mediana"]


class AurumFeatureBuilder(AurumTransformer):
    """Construye las nueve features del pipeline, agrupadas en cuatro familias.

    **Historia de la ley en el frente** (regresion)

    - `ley_ventana`: media movil de la ley del mismo frente en la ventana configurable. Es el
      estimador causal del nivel del frente, que es toda la senal disponible. Se usa la media
      y no la mediana porque dentro de cada frente la ley es simetrica (asimetria +0.03) y sin
      contaminacion —el centinela ya lo trato el imputador—, y ahi la media es el estimador
      eficiente: sobre el objetivo real gana 0.9695 contra 0.9671 de R2. El estadistico queda
      como parametro por si aparece un centinela no declarado.
    - `ley_n_ventana`: cuantas lecturas **disponibles** respaldan a la anterior. Cuenta lo que
      hay en el marco, de modo que si el imputador corrio antes incluye tanto las lecturas
      medidas como las reconstruidas: es una medida de respaldo, no de calidad. Con frentes que
      se apagan por semanas, la misma media vale distinto segun cuantos datos tenga detras.
    - `ley_lag_1`: ultima ley valida observada en el frente. Son las "condiciones actuales" del
      enunciado y la unica informacion disponible cuando la ventana esta vacia.
    - `dias_desde_evento_previo`: cuanto hace que ese frente no registra. El extracto es
      bimodal —o se perfora cada 25 minutos o el frente desaparece por semanas— y esta feature
      le dice al modelo si las tres anteriores estan frescas o rancias.

    **Banderas de anomalia** (clasificacion)

    - `flag_temp_riesgo`: temperatura sobre el punto de quiebre medido en el extracto, 88 C.
    - `flag_temp_apagado`: temperatura sobre el apagado automatico del diccionario, 95 C. Se
      conservan las dos porque dicen cosas distintas: 95 es el umbral declarado y 88 es donde
      el riesgo empieza de verdad. La primera captura el 49% de las fallas y la segunda el 12%.
    - `flag_vib_alerta`: vibracion sobre la alerta operacional del diccionario, 12 m/s2. Solo
      el 19% de esos registros supera tambien el umbral de temperatura, asi que no es
      informacion repetida.

    **Ratios operacionales**

    - `energia_especifica_proxy`: presion por revoluciones sobre avance, el esfuerzo por metro
      perforado. Es la variable de dominio que en una operacion real seguiria a la dureza de la
      roca. En este extracto su correlacion con la ley es del orden de 0.003, y se construye
      igual porque el criterio es de dominio y su valor real se mide, no se supone.
    - `carga_termica_por_rpm`: temperatura por revolucion, para separar el motor que esta
      caliente porque trabaja del que esta caliente sin razon.

    Las columnas originales no se tocan: el enunciado prohibe renombrarlas y las features se
    agregan al lado.
    """

    def __init__(
        self,
        ventana: str = f"{domain.VENTANA_IMPUTACION_DIAS}D",
        estadistico: Estadistico = "media",
        umbral_temp_riesgo: float = domain.UMBRAL_TEMP_RIESGO,
        columna_frente: str = domain.COLUMNA_FRENTE,
        columna_ley: str = domain.COLUMNA_LEY,
        columna_tiempo: str = domain.COLUMNA_TIEMPO,
    ) -> None:
        super().__init__()
        if estadistico not in ("media", "mediana"):
            raise InvalidParameterError(
                f"estadistico debe ser 'media' o 'mediana', se recibio {estadistico!r}")
        try:
            pd.Timedelta(ventana)
        except ValueError as error:
            raise InvalidParameterError(f"ventana no es un periodo valido: {ventana!r}") from error
        self.ventana = ventana
        self.estadistico: Estadistico = estadistico
        self.umbral_temp_riesgo = umbral_temp_riesgo
        self.columna_frente = columna_frente
        self.columna_ley = columna_ley
        self.columna_tiempo = columna_tiempo
        self.columnas_requeridas = (
            columna_tiempo, columna_frente, columna_ley,
            domain.COLUMNA_TEMPERATURA, domain.COLUMNA_VIBRACION,
            domain.COLUMNA_PRESION, domain.COLUMNA_RPM, domain.COLUMNA_AVANCE,
        )
        self.historia_: pd.DataFrame | None = None

    #: Nombres de las features que produce, en el orden en que se agregan.
    FEATURES: tuple[str, ...] = (
        "ley_ventana", "ley_n_ventana", "ley_lag_1", "dias_desde_evento_previo",
        "flag_temp_riesgo", "flag_temp_apagado", "flag_vib_alerta",
        "energia_especifica_proxy", "carga_termica_por_rpm",
    )

    # -- ajuste -------------------------------------------------------------------------

    def _fit(self, X: pd.DataFrame, y: pd.Series | None) -> None:
        """Guarda la historia de ley por frente que necesitan las features temporales.

        Se guardan los eventos y no un resumen porque la ventana depende del instante de cada
        fila: dos filas del mismo frente separadas por un mes no comparten vecinas.
        """
        self.historia_ = X[[self.columna_tiempo, self.columna_frente, self.columna_ley]].copy()
        logger.info("%s: historia de %d eventos para las features de ventana",
                    type(self).__name__, len(self.historia_))

    # -- transformacion -----------------------------------------------------------------

    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Agrega las nueve features sin tocar ninguna columna original."""
        temporales = self._features_temporales(X)
        for nombre in ("ley_ventana", "ley_n_ventana", "ley_lag_1", "dias_desde_evento_previo"):
            X[nombre] = temporales[nombre]

        X["flag_temp_riesgo"] = X[domain.COLUMNA_TEMPERATURA] > self.umbral_temp_riesgo
        X["flag_temp_apagado"] = (X[domain.COLUMNA_TEMPERATURA]
                                  > domain.RANGOS_SENSORES[domain.COLUMNA_TEMPERATURA][1])
        X["flag_vib_alerta"] = (X[domain.COLUMNA_VIBRACION]
                                > domain.RANGOS_SENSORES[domain.COLUMNA_VIBRACION][1])

        avance = X[domain.COLUMNA_AVANCE].where(X[domain.COLUMNA_AVANCE] > 0)
        rpm = X[domain.COLUMNA_RPM].where(X[domain.COLUMNA_RPM] > 0)
        X["energia_especifica_proxy"] = X[domain.COLUMNA_PRESION] * X[domain.COLUMNA_RPM] / avance
        X["carga_termica_por_rpm"] = X[domain.COLUMNA_TEMPERATURA] / rpm

        logger.info("%s: %d features agregadas; %d filas sin ventana suficiente",
                    type(self).__name__, len(self.FEATURES), int(X["ley_ventana"].isna().sum()))
        return X

    # -- interno ------------------------------------------------------------------------

    def _features_temporales(self, X: pd.DataFrame) -> pd.DataFrame:
        """Calcula ventana, conteo, lag y antiguedad usando historia y marco a la vez.

        Todo se calcula con `closed='left'` y con desplazamiento: ninguna feature ve su propia
        fila ni el futuro. Es la misma regla que aplica el imputador y por la misma razon: el
        objetivo es el turno siguiente, y una ventana que incluya el presente produce una
        metrica de validacion que en produccion no se sostiene.
        """
        assert self.historia_ is not None
        historia = self.historia_.assign(_es_objetivo=False, _indice=None)
        objetivo = X[[self.columna_tiempo, self.columna_frente, self.columna_ley]].assign(
            _es_objetivo=True, _indice=X.index)
        # El marco va primero para que, al deduplicar, sobreviva la copia que lleva el indice
        # de destino. La historia y el marco coinciden cuando se transforma lo mismo que se
        # ajusto: sin deduplicar, cada evento aparece dos veces con el mismo instante, el
        # conteo de la ventana se duplica, la antiguedad da cero y el rezago devuelve el
        # propio valor de la fila. Es la fuga mas silenciosa de todo el pipeline.
        todos = pd.concat([objetivo, historia], ignore_index=True)
        todos = todos.drop_duplicates(subset=[self.columna_tiempo, self.columna_frente],
                                      keep="first")
        todos = todos.sort_values([self.columna_frente, self.columna_tiempo])

        indexado = todos.set_index(self.columna_tiempo)
        ventana = indexado.groupby(self.columna_frente)[self.columna_ley].rolling(
            self.ventana, closed="left")
        agregado = ventana.mean() if self.estadistico == "media" else ventana.median()
        todos["ley_ventana"] = agregado.to_numpy()
        # Cuenta lo disponible en el marco, medido o reconstruido por el imputador. Sin
        # lecturas previas el conteo es cero y no un faltante: la ventana existe y esta vacia,
        # que es justo lo que la feature tiene que poder decir.
        todos["ley_n_ventana"] = pd.Series(ventana.count().to_numpy()).fillna(0.0).to_numpy()

        por_frente = todos.groupby(self.columna_frente, sort=False)
        todos["ley_lag_1"] = por_frente[self.columna_ley].transform(
            lambda serie: serie.ffill().shift(1))
        todos["dias_desde_evento_previo"] = (
            por_frente[self.columna_tiempo].diff().dt.total_seconds() / 86_400)

        del por_frente
        resultado = todos.loc[todos["_es_objetivo"]].set_index("_indice")
        return resultado.reindex(X.index)
