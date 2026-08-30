"""Imputacion del valor especial de `ley_au_gpT`.

El extracto codifica "sin lectura valida de la sonda XRF" como `-1.0` dentro del dominio
numerico: no es un nulo declarado y ninguna cuenta de `NaN` lo detecta. El EDA midio 2810
casos (5.6% del extracto) y mostro que no se reparten al azar, sino que se concentran en el
turno N2. Ese faltante hay que tratarlo antes de cualquier estadistica, porque un `-1` que
entra a una media la arrastra hacia abajo sin dejar rastro.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.transformers.base import AurumTransformer

logger = logging.getLogger(__name__)


class AurumImputer(AurumTransformer):
    """Reemplaza el centinela de ley por la mediana de sus vecinas recientes.

    La vecindad es la que pide el enunciado: mismo `frente_id` y mismo `tipo_mineral`, en
    los ultimos siete dias. Cuando esa ventana tiene menos de cinco lecturas validas, la
    fila no se imputa y se marca con `flag_imputed=True`.

    Dos decisiones que el enunciado deja abiertas y aqui se cierran de forma explicita:

    **La ventana es estrictamente pasada.** "Los ultimos siete dias" se interpreta como el
    intervalo `[t - 7 dias, t)`: excluye la propia fila y excluye todo lo posterior. La
    alternativa —una ventana centrada, o que incluya el futuro— produce una mediana que en
    validacion se ve mejor y en produccion no existe, porque el objetivo del modulo es
    predecir el turno siguiente. Es la misma razon por la que el codificador usa
    leave-one-out.

    **El centinela se detecta como valor no positivo.** El extracto solo contiene `-1.0`,
    pero comparar por `<= 0` cubre igual cualquier otro centinela negativo o un cero
    imposible, y deja registro en el log cuando aparece uno distinto del esperado. Detectar
    por igualdad exacta habria significado no ver nunca ese caso.

    La marca `flag_imputed` sigue la letra del enunciado: es `True` en las filas que
    **no** se pudieron imputar por falta de registros, y esas filas quedan con la ley en
    `NaN`. No se agrega ninguna otra columna: el faltante ya esta representado por el `NaN`.

    Que filas si se reconstruyeron queda en `filas_imputadas_`, como estado del transformador
    y no como columna del marco. Es informacion que el codificador necesita —una ley
    reconstruida no es una medicion y no deberia entrar a las estadisticas de su categoria—
    y que de otro modo solo se podria recuperar comparando contra el archivo original.
    """

    def __init__(
        self,
        ventana_dias: int = domain.VENTANA_IMPUTACION_DIAS,
        minimo_registros: int = domain.MINIMO_REGISTROS_IMPUTACION,
        columnas_grupo: tuple[str, ...] = (domain.COLUMNA_FRENTE, domain.COLUMNA_TIPO_MINERAL),
        columna_objetivo: str = domain.COLUMNA_LEY,
        columna_tiempo: str = domain.COLUMNA_TIEMPO,
        columna_bandera: str = "flag_imputed",
        centinela: float = domain.CENTINELA_LEY,
    ) -> None:
        super().__init__()
        if ventana_dias <= 0:
            raise InvalidParameterError(
                f"ventana_dias debe ser positivo, se recibio {ventana_dias}")
        if minimo_registros < 1:
            raise InvalidParameterError(
                f"minimo_registros debe ser al menos 1, se recibio {minimo_registros}")
        self.ventana_dias = ventana_dias
        self.minimo_registros = minimo_registros
        self.columnas_grupo = columnas_grupo
        self.columna_objetivo = columna_objetivo
        self.columna_tiempo = columna_tiempo
        self.columna_bandera = columna_bandera
        self.centinela = centinela
        self.columnas_requeridas = (columna_tiempo, columna_objetivo, *columnas_grupo)
        self.historia_: pd.DataFrame | None = None
        self.filas_imputadas_: pd.Index = pd.Index([])

    # -- ajuste -------------------------------------------------------------------------

    def _fit(self, X: pd.DataFrame, y: pd.Series | None) -> None:
        """Guarda las lecturas validas que serviran de referencia al transformar.

        Se guarda el historico completo y no un resumen por grupo porque la mediana depende
        del instante de cada fila: dos filas del mismo frente y tipo, separadas por un mes,
        no comparten ventana.
        """
        self.historia_ = self._lecturas_validas(X)
        logger.info("%s: historia de %d lecturas validas en %d grupos",
                    type(self).__name__, len(self.historia_),
                    self.historia_.groupby(list(self.columnas_grupo), observed=True).ngroups
                    if len(self.historia_) else 0)

    # -- transformacion -----------------------------------------------------------------

    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Convierte el centinela en `NaN`, imputa lo que se puede y marca lo que no."""
        assert self.historia_ is not None  # garantizado por AurumTransformer.transform
        objetivo = X[self.columna_objetivo]
        es_centinela = self._detectar_centinela(objetivo)
        X[self.columna_objetivo] = objetivo.mask(es_centinela, np.nan)
        X[self.columna_bandera] = False

        historia = self._historia_para(X)
        pendientes = X.index[es_centinela]
        reconstruidas = []
        for indice in pendientes:
            fila = X.loc[indice]
            vecinas = self._vecinas(historia, fila)
            if len(vecinas) >= self.minimo_registros:
                X.loc[indice, self.columna_objetivo] = float(vecinas.median())
                reconstruidas.append(indice)
            else:
                X.loc[indice, self.columna_bandera] = True
        self.filas_imputadas_ = pd.Index(reconstruidas)

        logger.info("%s: %d centinelas, %d imputados con la mediana de la ventana, "
                    "%d marcados con %s por ventana con menos de %d lecturas",
                    type(self).__name__, len(pendientes), len(self.filas_imputadas_),
                    len(pendientes) - len(self.filas_imputadas_), self.columna_bandera,
                    self.minimo_registros)
        return X

    def objetivo_medido(self, X: pd.DataFrame) -> pd.Series:
        """Devuelve la ley dejando en faltante las filas que este imputador reconstruyo.

        Es el objetivo que corresponde pasarle al codificador: una mediana de vecinas no es una
        medicion, y usarla para estimar la media de su propia categoria realimenta esa media
        consigo misma. El efecto medido en el extracto es pequeno —milesimas de gramo por
        tonelada—, pero la circularidad es real y aqui cuesta una linea evitarla.
        """
        return X[self.columna_objetivo].mask(X.index.isin(self.filas_imputadas_))

    # -- interno ------------------------------------------------------------------------

    def _detectar_centinela(self, serie: pd.Series) -> pd.Series:
        """Marca las lecturas invalidas y avisa si aparece un centinela inesperado."""
        invalidas = serie.le(0) & serie.notna()
        inesperados = sorted(set(serie[invalidas].unique()) - {self.centinela})
        if inesperados:
            logger.warning("%s: valores no positivos distintos del centinela %.1f: %s",
                           type(self).__name__, self.centinela, inesperados)
        return invalidas

    def _lecturas_validas(self, X: pd.DataFrame) -> pd.DataFrame:
        """Subconjunto de lecturas utilizables como vecinas, ordenado por tiempo."""
        columnas = [self.columna_tiempo, self.columna_objetivo, *self.columnas_grupo]
        validas = X.loc[~self._detectar_centinela(X[self.columna_objetivo]), columnas]
        validas = validas.dropna(subset=[self.columna_objetivo])
        return validas.sort_values(self.columna_tiempo).reset_index(drop=True)

    def _historia_para(self, X: pd.DataFrame) -> pd.DataFrame:
        """Une la historia del ajuste con las lecturas validas del propio marco.

        Se deduplica por instante porque el caso habitual —transformar el mismo marco con
        que se ajusto— traeria cada lectura dos veces, y eso duplicaria el conteo del que
        depende la regla de los cinco registros. El extracto no tiene timestamps repetidos,
        de modo que el instante identifica la lectura sin ambiguedad.
        """
        assert self.historia_ is not None
        completa = pd.concat([self.historia_, self._lecturas_validas(X)], ignore_index=True)
        completa = completa.drop_duplicates(subset=[self.columna_tiempo, *self.columnas_grupo])
        return completa.sort_values(self.columna_tiempo).reset_index(drop=True)

    def _vecinas(self, historia: pd.DataFrame, fila: pd.Series) -> pd.Series:
        """Lecturas validas del mismo grupo en `[t - ventana, t)`."""
        momento = fila[self.columna_tiempo]
        desde = momento - pd.Timedelta(days=self.ventana_dias)
        mismo_grupo = np.ones(len(historia), dtype=bool)
        for columna in self.columnas_grupo:
            mismo_grupo &= (historia[columna] == fila[columna]).to_numpy()
        en_ventana = ((historia[self.columna_tiempo] >= desde)
                      & (historia[self.columna_tiempo] < momento)).to_numpy()
        vecinas: pd.Series = historia.loc[mismo_grupo & en_ventana, self.columna_objetivo]
        return vecinas
