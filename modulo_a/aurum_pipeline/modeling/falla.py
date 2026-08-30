"""Etiqueta de falla mecanica en las proximas cuatro horas.

El enunciado pide predecir si **un equipo** tendra una falla en las proximas 4 horas. Aqui la
etiqueta se construye por defecto sobre el `frente_id` y no sobre el `equipo_id`, y la razon
esta medida en el EDA: el extracto es un flujo estrictamente serial -ningun par de registros
comparte instante y la cadencia global es uniforme entre 15 y 34 minutos-, lo que es
incompatible con diez perforadoras trabajando en paralelo. Bajo ese supuesto, `equipo_id` es
una etiqueta repartida sobre un flujo unico y no admite lectura causal: una falla atribuida al
equipo cuatro no dice nada sobre el estado del equipo cuatro.

La clase acepta la columna de agrupacion como parametro para que la variante por `equipo_id`
-la que pide la letra del enunciado- se pueda construir y reportar al lado, en lugar de
quedar como una afirmacion sin numero.

**La ventana empieza al cierre del bloque horario del turno.** El momento de la prediccion es
el cierre del turno segun el reloj, que es cuando estan disponibles todas sus lecturas. Contar
desde el inicio del turno significaria etiquetar con horas que ya ocurrieron; contar desde el
primer evento mas la duracion del turno -que fue la primera version de esta clase- corre la
ventana respecto del reloj: en el extracto el primer evento llega mas de una hora tarde en el
13.6% de los turnos, hasta seis horas en el extremo, y la etiqueta cambiaba en el 5.5% de las
celdas. El cierre lo calcula `ConstructorMatrizTurno` y viaja en la matriz como
`cierre_turno_local`, de modo que la etiqueta y los minutos de inactividad miran el mismo
instante.

Una ventana sin ningun registro del grupo -el frente se apago- se etiqueta como cero, se marca
en `ventana_con_registros` y deja su conteo en `eventos_en_ventana`. No es lo mismo "no fallo"
que "no habia nadie perforando": con eventos independientes a 3.3% cada uno, la probabilidad
de falla de una ventana es una funcion del numero de eventos que tendra, y ese conteo es el
techo del problema. Ninguna de las dos columnas es una variable del modelo -describen el
futuro-, y `features.py` impide que entren a un conjunto.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError, MissingColumnsError

logger = logging.getLogger(__name__)

#: Horizonte que pide el enunciado, en horas.
HORIZONTE_FALLA_HORAS: Final[int] = 4

#: Nombre de la etiqueta, de la marca de ventana observada y del conteo de eventos.
COLUMNA_FALLA_HORIZONTE: Final[str] = "falla_en_4h"
COLUMNA_VENTANA_OBSERVADA: Final[str] = "ventana_con_registros"
COLUMNA_EVENTOS_VENTANA: Final[str] = "eventos_en_ventana"


class ConstructorEtiquetaFalla:
    """Marca, para cada celda, si hubo falla en las horas siguientes al cierre del turno.

    Trabaja con busqueda binaria sobre los instantes ordenados de cada grupo y no con un
    filtro por celda: con 4019 celdas y 50000 eventos, el filtro anidado tarda minutos y esto
    tarda milisegundos. La diferencia importa porque la etiqueta se reconstruye en cada
    corrida del notebook.
    """

    def __init__(
        self,
        columna_grupo: str = domain.COLUMNA_FRENTE,
        horizonte_horas: int = HORIZONTE_FALLA_HORAS,
    ) -> None:
        if horizonte_horas <= 0:
            raise InvalidParameterError(
                f"el horizonte debe ser positivo, se recibio {horizonte_horas}")
        self.columna_grupo = columna_grupo
        self.horizonte_horas = horizonte_horas

    def agregar(
        self,
        matriz: pd.DataFrame,
        eventos: pd.DataFrame,
        columna_tiempo_evento: str = domain.COLUMNA_INICIO_TURNO,
    ) -> pd.DataFrame:
        """Devuelve la matriz con la etiqueta, el conteo de eventos y la marca de ventana.

        `eventos` es el marco de eventos ya pasado por `ConstructorMatrizTurno`, del que se
        usan el instante local, el grupo y el codigo de falla. La matriz tiene que traer
        `cierre_turno_local`, que es desde donde se cuenta la ventana.
        """
        self._validar(matriz, eventos, columna_tiempo_evento)
        salida = matriz.copy()
        fin_turno = salida[domain.COLUMNA_CIERRE_TURNO]
        limite = fin_turno + pd.Timedelta(hours=self.horizonte_horas)

        etiqueta = np.zeros(len(salida), dtype=int)
        eventos_ventana = np.zeros(len(salida), dtype=int)
        # Se trabaja por posicion y no por etiqueta del indice: `get_indexer` exige un indice
        # unico, y la matriz puede llegar con el indice de otra particion.
        grupos = salida[self.columna_grupo].to_numpy()
        for grupo in pd.unique(grupos):
            indices = np.flatnonzero(grupos == grupo)
            del_grupo = eventos.loc[eventos[self.columna_grupo] == grupo]
            instantes = np.sort(del_grupo[columna_tiempo_evento].to_numpy())
            con_falla = np.sort(
                del_grupo.loc[del_grupo[domain.COLUMNA_FALLA].notna(),
                              columna_tiempo_evento].to_numpy())
            desde = fin_turno.to_numpy()[indices]
            hasta = limite.to_numpy()[indices]
            etiqueta[indices] = (
                np.searchsorted(con_falla, hasta, side="right")
                - np.searchsorted(con_falla, desde, side="right") > 0).astype(int)
            eventos_ventana[indices] = (
                np.searchsorted(instantes, hasta, side="right")
                - np.searchsorted(instantes, desde, side="right"))

        salida[COLUMNA_FALLA_HORIZONTE] = etiqueta
        salida[COLUMNA_EVENTOS_VENTANA] = eventos_ventana
        salida[COLUMNA_VENTANA_OBSERVADA] = (eventos_ventana > 0).astype(int)
        logger.info("%s: %d celdas, tasa de falla a %d h del %.2f%%, "
                    "%.1f%% con ventana observada, agrupando por %s",
                    type(self).__name__, len(salida), self.horizonte_horas,
                    100.0 * float(etiqueta.mean()),
                    100.0 * float((eventos_ventana > 0).mean()), self.columna_grupo)
        return salida

    def _validar(
        self,
        matriz: pd.DataFrame,
        eventos: pd.DataFrame,
        columna_tiempo_evento: str,
    ) -> None:
        faltan_matriz = {self.columna_grupo, domain.COLUMNA_CIERRE_TURNO} - set(matriz.columns)
        if faltan_matriz:
            raise MissingColumnsError(type(self).__name__, faltan_matriz)
        faltan_eventos = {
            self.columna_grupo, columna_tiempo_evento, domain.COLUMNA_FALLA,
        } - set(eventos.columns)
        if faltan_eventos:
            raise MissingColumnsError(type(self).__name__, faltan_eventos)
