"""Matriz supervisada del Ejercicio A-2: un turno por fila y el turno siguiente por objetivo.

El enunciado pide predecir `ley_au_gpT` del siguiente turno. Eso fija la unidad de modelado
en la celda `(frente_id, fecha_local, turno_cod)` y no en el evento del extracto, que es lo
que trae el CSV. Las tres decisiones que esta clase cierra, con la alternativa que se
descarto en cada una:

**Se agrega a turno y no se modela a nivel de evento.** El extracto tiene una mediana de 14
eventos por celda; modelar por evento repetiria el mismo objetivo catorce veces y produciria
una validacion optimista por correlacion dentro del turno. La contra es que quedan 4019
celdas en vez de 50000 filas, que para trece frentes y un objetivo cuya senal es el nivel del
frente resulta de sobra.

**"El siguiente turno" es el siguiente turno de ese frente en orden cronologico, no el
siguiente del calendario.** Los frentes se apagan por semanas: exigir contiguidad de
calendario descartaria cerca de la mitad de los pares. El salto no se esconde, entra al
modelo como `dias_desde_turno_previo`.

**La ley del turno se promedia solo sobre lecturas medidas.** Las que el imputador
reconstruyo se excluyen del promedio si se le pasan sus indices, por la misma razon por la
que `AurumImputer.objetivo_medido` existe: un objetivo construido sobre imputaciones entrena
al modelo a predecir a su propio imputador. En el extracto solo 11 celdas de 4019 se quedan
sin ninguna lectura medida, asi que el costo de la decision es despreciable.

**El turno cierra con el reloj, no con su primer evento.** El cierre del bloque horario viaja
en la matriz como `cierre_turno_local` porque dos consumidores lo necesitan y no pueden
calcularlo cada uno a su manera: la etiqueta de falla cuenta su ventana desde ahi, y los
minutos de inactividad al cierre se miden hasta ahi. En el extracto el primer evento llega mas
de una hora tarde en el 13.6% de los turnos, de modo que "primer evento mas seis horas" no es
el cierre del turno.

**Los sensores se resumen tambien por umbral, no solo por media.** El EDA midio que la
relacion de la temperatura con la falla es un escalon en 88 C, y la media de catorce lecturas
lo diluye: un turno con una lectura de 97 C promedia 73. El maximo y el conteo de lecturas
sobre el umbral conservan el escalon, y dejan que el experimento -y no un parrafo- responda si
la agregacion por media escondia una senal.

Esta clase no hereda de `AurumTransformer` a proposito. El contrato de los transformadores
es marco de eventos adentro, marco de eventos afuera; aqui cambia la granularidad, y forzar
la herencia obligaria a inventar un `_fit` sin estado que aprender para reutilizar una firma
que no describe lo que el objeto hace.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import numpy as np
import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import (
    InvalidParameterError,
    MissingColumnsError,
    SentinelNotImputedError,
)

logger = logging.getLogger(__name__)

#: Sensores y magnitudes continuas del evento que se resumen por turno con la media.
#: `ton_rom_acum` entra aqui y no como suma porque el EDA mostro que, pese al nombre, no es
#: un acumulado del turno sino una lectura por evento.
SENSORES_PROMEDIADOS: Final[tuple[str, ...]] = (
    domain.COLUMNA_TONELAJE,
    domain.COLUMNA_PRESION,
    domain.COLUMNA_RPM,
    domain.COLUMNA_AVANCE,
    domain.COLUMNA_AGUA,
    domain.COLUMNA_VIBRACION,
    domain.COLUMNA_TEMPERATURA,
)

#: Claves que identifican una celda de la matriz.
CLAVES_CELDA: Final[tuple[str, ...]] = (
    domain.COLUMNA_FRENTE,
    domain.COLUMNA_FECHA_LOCAL,
    domain.COLUMNA_TURNO,
)

_LEY_MEDIDA: Final[str] = "_ley_medida"
_TEMP_RIESGO: Final[str] = "_temp_riesgo"
_VIB_ALERTA: Final[str] = "_vib_alerta"
_ULTIMO_EVENTO: Final[str] = "_ultimo_evento_local"


def _moda(serie: pd.Series) -> Any:
    """Categoria mas frecuente del turno, o faltante si no hay ninguna.

    `Series.mode()` devuelve un marco vacio cuando todo es nulo, y `.iat[0]` sobre eso
    revienta con `IndexError` a treinta lineas de distancia del turno que lo causo.
    """
    modas = serie.mode()
    return modas.iat[0] if len(modas) else pd.NA


class ConstructorMatrizTurno:
    """Agrega el extracto por turno y le construye el objetivo del turno siguiente.

    Recibe eventos ya pasados por `AurumImputer` —lo verifica y falla si no— y devuelve una
    fila por celda `(frente_id, fecha_local, turno_cod)` con:

    - las claves de la celda, `inicio_turno_local` -el primer instante local del turno- y
      `cierre_turno_local`, el fin del bloque horario segun el reloj;
    - `ley_turno`, promedio de las lecturas medidas, y `lecturas_ley_turno`, cuantas fueron;
    - la media por turno de los siete sensores continuos;
    - `temp_max_turno`, `eventos_temp_riesgo`, `vib_max_turno` y `eventos_vib_alerta`, el
      resumen por umbral que la media no conserva;
    - `minutos_inactivo_al_cierre`, cuanto llevaba el frente sin registrar al cerrar el turno;
    - `tipo_mineral` y `equipo_id` por moda, `sector_geol` por primera aparicion;
    - `eventos_turno`, `fallas_turno` y `mantenimiento_turno` como resumen del turno;
    - la historia causal del frente: rezagos, medias y desviaciones moviles, dias desde el
      turno previo y cuantos turnos del frente lo preceden;
    - `ley_turno_siguiente` como objetivo y `inicio_turno_siguiente` como el instante en que
      ese objetivo ocurre.

    `inicio_turno_siguiente` no es informacion para el modelo: es lo que el particionador
    necesita para purgar la frontera entre pliegues. Sin esa columna no hay forma de saber si
    una fila de entrenamiento predice algo que cae dentro del bloque de validacion.

    Toda la historia se calcula con desplazamiento o con ventanas que terminan en el turno
    actual, nunca sobre el objetivo: al predecir el turno `t+1` se conoce todo hasta `t`
    inclusive.
    """

    def __init__(
        self,
        desfase_local_horas: int = domain.DESFASE_LOCAL_HORAS,
        rezagos: tuple[int, ...] = domain.REZAGOS_TURNO,
        ventanas_moviles: tuple[int, ...] = domain.VENTANAS_MOVILES_TURNO,
        columna_ley: str = domain.COLUMNA_LEY,
        columna_tiempo: str = domain.COLUMNA_TIEMPO,
    ) -> None:
        if any(rezago < 1 for rezago in rezagos):
            raise InvalidParameterError(
                f"los rezagos se cuentan en turnos y deben ser positivos, se recibio {rezagos}")
        if any(ventana < 2 for ventana in ventanas_moviles):
            raise InvalidParameterError(
                "una ventana movil de menos de dos turnos repite el turno actual, "
                f"se recibio {ventanas_moviles}")
        self.desfase_local_horas = desfase_local_horas
        self.rezagos = rezagos
        self.ventanas_moviles = ventanas_moviles
        self.columna_ley = columna_ley
        self.columna_tiempo = columna_tiempo
        self.columnas_requeridas: tuple[str, ...] = (
            columna_tiempo, columna_ley, domain.COLUMNA_FRENTE, domain.COLUMNA_TURNO,
            domain.COLUMNA_TIPO_MINERAL, domain.COLUMNA_EQUIPO, domain.COLUMNA_SECTOR,
            domain.COLUMNA_FALLA, domain.COLUMNA_MANTENIMIENTO, *SENSORES_PROMEDIADOS,
        )

    # -- contrato publico ---------------------------------------------------------------

    def construir(
        self,
        X: pd.DataFrame,
        indices_imputados: pd.Index | None = None,
    ) -> pd.DataFrame:
        """Devuelve la matriz supervisada, con una fila por par (turno, turno siguiente).

        `indices_imputados` es `AurumImputer.filas_imputadas_`: las filas cuya ley fue
        reconstruida y que por eso no entran al promedio del turno. Si no se pasa, se
        promedia todo lo que no sea faltante.

        Las celdas sin turno siguiente conocido —la ultima de cada frente, y las que van
        seguidas de un turno sin ninguna lectura medida— no forman par y se descartan: son
        filas sin objetivo, no filas con objetivo faltante.
        """
        self._validar(X)
        eventos = self._preparar_eventos(X, indices_imputados)
        celdas = self._agregar(eventos)
        celdas = self._agregar_cierre(celdas)
        celdas = self._agregar_historia(celdas)
        celdas = self._agregar_objetivo(celdas)
        return self._descartar_sin_objetivo(celdas)

    def columnas_generadas(self) -> tuple[str, ...]:
        """Nombres de las columnas de historia que construye, en el orden en que se agregan."""
        rezagos = tuple(f"ley_rezago_{k}" for k in self.rezagos)
        moviles = tuple(
            nombre
            for ventana in self.ventanas_moviles
            for nombre in (f"ley_media_{ventana}", f"ley_desv_{ventana}")
        )
        return (*rezagos, *moviles, "dias_desde_turno_previo", "turnos_previos_frente")

    # -- interno ------------------------------------------------------------------------

    def _validar(self, X: pd.DataFrame) -> None:
        """Comprueba columnas y que el centinela de la sonda ya no este presente."""
        faltantes = set(self.columnas_requeridas) - set(X.columns)
        if faltantes:
            raise MissingColumnsError(type(self).__name__, faltantes)
        ley = X[self.columna_ley]
        centinelas = int((ley.le(0) & ley.notna()).sum())
        if centinelas:
            raise SentinelNotImputedError(type(self).__name__, self.columna_ley, centinelas)
        # Un nulo en una clave de la celda no puede pasar en silencio: agrupar con
        # `dropna=False` lo convertiria en un frente inventado que se empareja consigo mismo,
        # y agrupar con `dropna=True` descartaria filas sin decirlo.
        nulas = [clave for clave in (domain.COLUMNA_FRENTE, domain.COLUMNA_TURNO)
                 if X[clave].isna().any()]
        if nulas:
            raise InvalidParameterError(
                "las claves de la celda no admiten nulos y los traen: " + ", ".join(nulas))
        # Un codigo de turno fuera del dominio no tiene bloque horario, y sin bloque no hay
        # cierre: fallar aqui evita un cierre nulo que la etiqueta de falla leeria como
        # "sin ventana" en silencio.
        desconocidos = set(X[domain.COLUMNA_TURNO].unique()) - set(domain.ORDEN_TURNOS)
        if desconocidos:
            raise InvalidParameterError(
                "codigos de turno sin bloque horario en el dominio: "
                + ", ".join(sorted(str(codigo) for codigo in desconocidos)))

    def _preparar_eventos(
        self,
        X: pd.DataFrame,
        indices_imputados: pd.Index | None,
    ) -> pd.DataFrame:
        """Pasa a hora local, deriva la fecha de operacion y aisla la ley medida."""
        eventos = X.copy()
        eventos[domain.COLUMNA_INICIO_TURNO] = (
            eventos[self.columna_tiempo] - pd.Timedelta(hours=self.desfase_local_horas))
        # Cada turno cae entero dentro de un mismo dia local -N2 va de 00:00 a 05:59-, de modo
        # que la fecha normalizada identifica la jornada sin partir ningun turno en dos.
        eventos[domain.COLUMNA_FECHA_LOCAL] = eventos[domain.COLUMNA_INICIO_TURNO].dt.normalize()
        medida = eventos[self.columna_ley]
        if indices_imputados is not None and len(indices_imputados):
            medida = medida.mask(eventos.index.isin(indices_imputados))
        eventos[_LEY_MEDIDA] = medida
        # Las banderas por umbral se marcan por evento para que el resumen del turno las
        # cuente con una suma; un faltante del sensor no supera ningun umbral.
        eventos[_TEMP_RIESGO] = (
            eventos[domain.COLUMNA_TEMPERATURA] > domain.UMBRAL_TEMP_RIESGO).astype(int)
        eventos[_VIB_ALERTA] = (
            eventos[domain.COLUMNA_VIBRACION]
            > domain.RANGOS_SENSORES[domain.COLUMNA_VIBRACION][1]).astype(int)
        return eventos

    def _agregar(self, eventos: pd.DataFrame) -> pd.DataFrame:
        """Resume los eventos de cada celda con una regla explicita por columna."""
        agregaciones: dict[str, tuple[str, Any]] = {
            domain.COLUMNA_INICIO_TURNO: (domain.COLUMNA_INICIO_TURNO, "min"),
            domain.COLUMNA_LEY_TURNO: (_LEY_MEDIDA, "mean"),
            "lecturas_ley_turno": (_LEY_MEDIDA, "count"),
            "eventos_turno": (self.columna_tiempo, "size"),
            domain.COLUMNA_TIPO_MINERAL: (domain.COLUMNA_TIPO_MINERAL, _moda),
            domain.COLUMNA_EQUIPO: (domain.COLUMNA_EQUIPO, _moda),
            domain.COLUMNA_SECTOR: (domain.COLUMNA_SECTOR, "first"),
            "fallas_turno": (domain.COLUMNA_FALLA, "count"),
            "mantenimiento_turno": (domain.COLUMNA_MANTENIMIENTO, "mean"),
            _ULTIMO_EVENTO: (domain.COLUMNA_INICIO_TURNO, "max"),
            domain.COLUMNA_TEMP_MAX: (domain.COLUMNA_TEMPERATURA, "max"),
            domain.COLUMNA_EVENTOS_TEMP_RIESGO: (_TEMP_RIESGO, "sum"),
            domain.COLUMNA_VIB_MAX: (domain.COLUMNA_VIBRACION, "max"),
            domain.COLUMNA_EVENTOS_VIB_ALERTA: (_VIB_ALERTA, "sum"),
        }
        agregaciones.update({sensor: (sensor, "mean") for sensor in SENSORES_PROMEDIADOS})

        celdas = (
            eventos.groupby(list(CLAVES_CELDA), observed=True, dropna=False)
            .agg(**agregaciones)
            .reset_index()
            .sort_values([domain.COLUMNA_INICIO_TURNO, domain.COLUMNA_FRENTE])
            .reset_index(drop=True)
        )
        logger.info("%s: %d eventos agregados en %d turnos de %d frentes",
                    type(self).__name__, len(eventos), len(celdas),
                    celdas[domain.COLUMNA_FRENTE].nunique())
        return celdas

    def _agregar_cierre(self, celdas: pd.DataFrame) -> pd.DataFrame:
        """Cierre del bloque horario del turno y minutos que el frente llevaba sin registrar.

        El cierre sale del reloj -inicio del bloque del turno mas su duracion- y no del primer
        evento mas seis horas, porque el primer evento llega tarde en uno de cada siete turnos
        y anclarlo ahi correria la ventana de prediccion hasta seis horas. Los minutos de
        inactividad se miden desde el ultimo evento hasta ese cierre: es lo unico que se sabe
        al predecir sobre si el frente sigue en campana, y se sabe con certeza.
        """
        horas_de_cierre = (
            celdas[domain.COLUMNA_TURNO].map(domain.HORA_INICIO_TURNO).to_numpy(dtype="int64")
            + domain.DURACION_TURNO_HORAS)
        cierre = (celdas[domain.COLUMNA_FECHA_LOCAL].to_numpy(dtype="datetime64[ns]")
                  + horas_de_cierre.astype("timedelta64[h]"))
        ultimo = celdas[_ULTIMO_EVENTO].to_numpy(dtype="datetime64[ns]")
        celdas[domain.COLUMNA_CIERRE_TURNO] = cierre
        celdas[domain.COLUMNA_MINUTOS_INACTIVO] = (cierre - ultimo) / np.timedelta64(1, "m")
        return celdas.drop(columns=[_ULTIMO_EVENTO])

    def _agregar_historia(self, celdas: pd.DataFrame) -> pd.DataFrame:
        """Rezagos, medias y desviaciones moviles del frente, todo causal.

        Las ventanas moviles incluyen el turno actual y eso no es fuga: el objetivo es el
        turno siguiente, de modo que al momento de predecir el turno actual ya ocurrio.
        """
        por_frente = celdas.groupby(domain.COLUMNA_FRENTE, sort=False)[domain.COLUMNA_LEY_TURNO]
        for rezago in self.rezagos:
            celdas[f"ley_rezago_{rezago}"] = por_frente.shift(rezago)
        for ventana in self.ventanas_moviles:
            celdas[f"ley_media_{ventana}"] = por_frente.transform(
                lambda serie, v=ventana: serie.rolling(v, min_periods=1).mean())
            celdas[f"ley_desv_{ventana}"] = por_frente.transform(
                lambda serie, v=ventana: serie.rolling(v, min_periods=2).std())

        inicios = celdas.groupby(domain.COLUMNA_FRENTE, sort=False)[domain.COLUMNA_INICIO_TURNO]
        celdas["dias_desde_turno_previo"] = inicios.diff().dt.total_seconds() / 86400.0
        celdas["turnos_previos_frente"] = celdas.groupby(
            domain.COLUMNA_FRENTE, sort=False).cumcount()
        return celdas

    def _agregar_objetivo(self, celdas: pd.DataFrame) -> pd.DataFrame:
        """Adjunta la ley del turno siguiente del frente y el instante en que ocurre."""
        por_frente = celdas.groupby(domain.COLUMNA_FRENTE, sort=False)
        celdas[domain.COLUMNA_OBJETIVO] = por_frente[domain.COLUMNA_LEY_TURNO].shift(-1)
        celdas[domain.COLUMNA_INICIO_OBJETIVO] = por_frente[domain.COLUMNA_INICIO_TURNO].shift(-1)
        return celdas

    def _descartar_sin_objetivo(self, celdas: pd.DataFrame) -> pd.DataFrame:
        """Deja solo los pares completos y avisa cuantos turnos se perdieron y por que."""
        completos = celdas.dropna(
            subset=[domain.COLUMNA_OBJETIVO, domain.COLUMNA_INICIO_OBJETIVO,
                    domain.COLUMNA_LEY_TURNO]
        ).reset_index(drop=True)
        logger.info("%s: %d pares (turno, turno siguiente) sobre %d turnos; "
                    "%d descartados por no tener objetivo o ley medida",
                    type(self).__name__, len(completos), len(celdas),
                    len(celdas) - len(completos))
        if completos.empty:
            return completos
        assert bool(
            (completos[domain.COLUMNA_INICIO_OBJETIVO]
             > completos[domain.COLUMNA_INICIO_TURNO]).all()
        ), "el objetivo debe ocurrir estrictamente despues del turno que lo predice"
        return completos


def matriz_a_numpy(matriz: pd.DataFrame, columnas: tuple[str, ...]) -> np.ndarray:
    """Extrae las columnas pedidas como arreglo denso de flotantes.

    Existe para que el paso a los modelos sea explicito y falle aqui si una columna no esta,
    en lugar de propagarse como un `NaN` silencioso dentro de LightGBM.
    """
    faltantes = set(columnas) - set(matriz.columns)
    if faltantes:
        raise MissingColumnsError("matriz_a_numpy", faltantes)
    return matriz.loc[:, list(columnas)].to_numpy(dtype=float)
