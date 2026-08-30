"""Codificacion por objetivo de las categoricas de alta cardinalidad.

`frente_id` es, segun el EDA, la variable que mas separa la ley: entre el frente mas pobre
y el mas rico hay cinco veces de diferencia en la media. Codificarla por el promedio del
objetivo aprovecha esa senal sin inflar la matriz con trece columnas indicadoras, a cambio
de un riesgo concreto: si la media de un frente incluye la propia fila que se esta
codificando, el modelo recibe una pista de su propia respuesta.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.transformers.base import AurumTransformer

logger = logging.getLogger(__name__)


class AurumShiftEncoder(AurumTransformer):
    """Target encoding de `frente_id` y `equipo_id` con leave-one-out y suavizado.

    Cada categoria se reemplaza por la media del objetivo en esa categoria, calculada **sin
    la fila que se esta codificando**:

        codificado_i = (suma_categoria - y_i + m * media_global) / (n_categoria - 1 + m)

    donde `m` es el suavizado. Con `m = 0` es leave-one-out puro; al crecer, las categorias
    con pocos registros se acercan a la media global en lugar de confiar en un promedio de
    dos observaciones.

    **`fit_transform` y `transform` no hacen lo mismo, y esa es la pieza que evita la fuga.**
    Sobre los datos de entrenamiento, donde el objetivo es conocido, se aplica leave-one-out.
    Sobre datos nuevos no hay objetivo que dejar fuera, asi que se aplica la media suavizada
    aprendida en el ajuste. Una implementacion que usara la misma formula en ambos casos
    mostraria en validacion un ajuste que en produccion no se sostiene.

    Las categorias no vistas en el ajuste reciben la media global, que es la mejor estimacion
    disponible sin informacion propia.

    El objetivo se toma de `y` si se entrega, y si no, de la columna de ley del propio marco.
    Los registros con ley faltante quedan fuera de las estadisticas: un centinela no es un
    valor del que se pueda promediar.

    `equipo_id` se codifica porque el enunciado lo pide. El EDA mostro que su ley media es
    plana entre equipos, de modo que su codificacion tendera a la media global.
    """

    def __init__(
        self,
        columnas: tuple[str, ...] = (domain.COLUMNA_FRENTE, domain.COLUMNA_EQUIPO),
        smoothing: float = 10.0,
        columna_objetivo: str = domain.COLUMNA_LEY,
        sufijo: str = "_target_enc",
    ) -> None:
        super().__init__()
        if smoothing < 0:
            raise InvalidParameterError(f"smoothing no puede ser negativo, se recibio {smoothing}")
        if not columnas:
            raise InvalidParameterError("hay que indicar al menos una columna a codificar")
        self.columnas = columnas
        self.smoothing = smoothing
        self.columna_objetivo = columna_objetivo
        self.sufijo = sufijo
        self.columnas_requeridas = columnas
        self.prior_: float | None = None
        self.estadisticas_: dict[str, pd.DataFrame] = {}

    # -- ajuste -------------------------------------------------------------------------

    def _fit(self, X: pd.DataFrame, y: pd.Series | None) -> None:
        """Guarda suma y conteo del objetivo por categoria, mas la media global."""
        objetivo = self._objetivo(X, y)
        utilizables = objetivo.notna()
        if not utilizables.any():
            raise InvalidParameterError(
                "no hay valores de objetivo utilizables para ajustar el codificador")
        self.prior_ = float(objetivo[utilizables].mean())
        self.estadisticas_ = {
            columna: (pd.DataFrame({"categoria": X.loc[utilizables, columna],
                                    "objetivo": objetivo[utilizables]})
                      .groupby("categoria", observed=True)["objetivo"]
                      .agg(["sum", "count"]))
            for columna in self.columnas
        }
        for columna, estadistica in self.estadisticas_.items():
            logger.info("%s: %s codificada con %d categorias, media global %.4f",
                        type(self).__name__, columna, len(estadistica), self.prior_)

    # -- transformacion -----------------------------------------------------------------

    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Aplica la media suavizada de cada categoria, sin dejar fuera ninguna fila.

        Es el camino para datos nuevos. El leave-one-out solo tiene sentido cuando el
        objetivo de la fila participo del ajuste, y de eso se ocupa `fit_transform`.
        """
        for columna in self.columnas:
            X[f"{columna}{self.sufijo}"] = self._codificar(X, columna, dejar_fuera=None)
        return X

    def fit_transform(self, X: pd.DataFrame, y: pd.Series | None = None) -> pd.DataFrame:
        """Ajusta y codifica dejando fuera de su propia media a cada fila."""
        self.fit(X, y)
        self._registrar_frentes(X, "codificacion con leave-one-out")
        transformado = X.copy()
        objetivo = self._objetivo(X, y)
        for columna in self.columnas:
            transformado[f"{columna}{self.sufijo}"] = self._codificar(
                X, columna, dejar_fuera=objetivo)
        return transformado

    # -- interno ------------------------------------------------------------------------

    def _objetivo(self, X: pd.DataFrame, y: pd.Series | None) -> pd.Series:
        """Serie objetivo alineada con `X`, tomada de `y` o de la columna de ley."""
        if y is not None:
            return pd.Series(np.asarray(y, dtype=float), index=X.index)
        if self.columna_objetivo not in X.columns:
            raise InvalidParameterError(
                f"sin `y`, el marco debe traer la columna objetivo {self.columna_objetivo}")
        return X[self.columna_objetivo].astype(float)

    def _codificar(self, X: pd.DataFrame, columna: str,
                   dejar_fuera: pd.Series | None) -> pd.Series:
        """Codifica una columna; `dejar_fuera` activa el leave-one-out fila a fila."""
        assert self.prior_ is not None
        estadistica = self.estadisticas_[columna]
        suma = X[columna].map(estadistica["sum"]).astype(float)
        conteo = X[columna].map(estadistica["count"]).astype(float)
        # Categoria no vista en el ajuste: sin suma ni conteo propios, queda en la media global.
        suma = suma.fillna(0.0)
        conteo = conteo.fillna(0.0)
        if dejar_fuera is not None:
            propio = dejar_fuera.fillna(0.0)
            aporta = dejar_fuera.notna().astype(float)
            suma = suma - propio
            conteo = conteo - aporta
        numerador = suma + self.smoothing * self.prior_
        denominador = conteo + self.smoothing
        codificado = np.where(denominador > 0, numerador / denominador, self.prior_)
        return pd.Series(codificado, index=X.index, name=f"{columna}{self.sufijo}")
