"""Monitor de deriva del Ejercicio B-3: PSI sobre la ley y la vibracion.

El PSI (Population Stability Index) compara la distribucion actual de una variable contra
una referencia, bin a bin: `sum((p_actual - p_ref) * ln(p_actual / p_ref))`. Las decisiones
que este modulo cierra:

- **Los bins son los deciles de la referencia**, no cortes fijos: asi cada bin de la
  referencia pesa lo mismo y el indice mide movimiento, no forma. Un bin vacio no revienta
  el logaritmo: las proporciones se acotan por debajo con un epsilon declarado.
- **La ley solo entra con lecturas validas.** El centinela de la sonda ya es nulo en silver
  con `ley_valida = false`; dejarlo entrar haria que un dia con la sonda caida parezca
  deriva geologica.
- **El calculo baja a numpy.** Las ventanas son miles de filas, no millones: colectar al
  driver da un PSI exacto, determinista y probable en local sin Spark distribuido.
- **El desglose por sector es informativo.** El PSI global de la ley confunde deriva
  geologica con un cambio en la mezcla de frentes activos; el desglose por sector permite
  distinguirlos, pero el veredicto que dispara el trigger es el global, que es lo que pide
  el enunciado.

El resultado queda en `dq_reports.monitor_deriva`: el monitoreo de deriva es control de
calidad del dato en el tiempo y vive con los demas reportes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Literal

import numpy as np
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import ahora_utc

logger = logging.getLogger(__name__)

Veredicto = Literal["estable", "moderado", "critico"]

#: Piso de una proporcion antes del logaritmo. Con deciles, un bin vacio contra un decil
#: lleno aporta ~1.5 al indice: suficiente para gritar sin volverse infinito.
EPSILON_PROPORCION: Final[float] = 1e-6

AMBITO_GLOBAL: Final[str] = "global"


@dataclass(frozen=True)
class VentanasDeriva:
    """Las dos ventanas del monitor, cerradas en la fecha del dato mas reciente."""

    referencia_desde: date
    referencia_hasta: date
    evaluacion_desde: date
    evaluacion_hasta: date

    @classmethod
    def desde_fecha(
        cls,
        fecha_max: date,
        dias_referencia: int = dominio.VENTANA_REFERENCIA_DIAS,
        dias_evaluacion: int = dominio.VENTANA_EVALUACION_DIAS,
    ) -> VentanasDeriva:
        """Evaluacion: los ultimos `dias_evaluacion`; referencia: los 30 dias anteriores."""
        if dias_referencia < 1 or dias_evaluacion < 1:
            raise ParametroInvalidoError("Las ventanas deben tener al menos un dia")
        evaluacion_desde = fecha_max - timedelta(days=dias_evaluacion - 1)
        referencia_hasta = evaluacion_desde - timedelta(days=1)
        referencia_desde = referencia_hasta - timedelta(days=dias_referencia - 1)
        return cls(referencia_desde, referencia_hasta, evaluacion_desde, fecha_max)


@dataclass(frozen=True)
class ResultadoPsi:
    """El PSI de una variable en un ambito, con el detalle que sustenta el numero."""

    variable: str
    ambito: str
    psi: float
    veredicto: Veredicto
    n_referencia: int
    n_actual: int
    proporciones: tuple[tuple[float, float], ...]

    @property
    def critico(self) -> bool:
        """Si supera el umbral que dispara el reentrenamiento."""
        return self.veredicto == "critico"


class CalculadorPsi:
    """PSI entre dos muestras, con bins tomados de los deciles de la referencia."""

    def __init__(
        self,
        bins: int = dominio.BINS_PSI,
        umbral_moderado: float = dominio.PSI_MODERADO,
        umbral_critico: float = dominio.PSI_CRITICO,
    ) -> None:
        if bins < 2:
            raise ParametroInvalidoError(f"El PSI necesita al menos 2 bins, se pidieron {bins}")
        if not 0 < umbral_moderado < umbral_critico:
            raise ParametroInvalidoError("Los umbrales deben cumplir 0 < moderado < critico")
        self.bins = bins
        self.umbral_moderado = umbral_moderado
        self.umbral_critico = umbral_critico

    def calcular(
        self, referencia: np.ndarray, actual: np.ndarray, variable: str,
        ambito: str = AMBITO_GLOBAL,
    ) -> ResultadoPsi:
        """PSI exacto de `actual` contra `referencia`, ambas sin faltantes."""
        referencia = np.asarray(referencia, dtype=float)
        actual = np.asarray(actual, dtype=float)
        if referencia.size == 0 or actual.size == 0:
            raise ParametroInvalidoError(
                f"PSI de {variable}: ventana vacia "
                f"(referencia {referencia.size}, actual {actual.size})")
        if float(referencia.min()) == float(referencia.max()):
            raise ParametroInvalidoError(
                f"PSI de {variable}: la referencia no tiene variacion y no define bins")
        cortes = np.quantile(referencia, np.linspace(0, 1, self.bins + 1)[1:-1])
        interiores = np.unique(cortes)
        bordes = np.concatenate(([-np.inf], interiores, [np.inf]))
        conteo_ref, _ = np.histogram(referencia, bordes)
        conteo_act, _ = np.histogram(actual, bordes)
        p_ref = np.clip(conteo_ref / referencia.size, EPSILON_PROPORCION, None)
        p_act = np.clip(conteo_act / actual.size, EPSILON_PROPORCION, None)
        psi = float(np.sum((p_act - p_ref) * np.log(p_act / p_ref)))
        veredicto: Veredicto = (
            "critico" if psi > self.umbral_critico
            else "moderado" if psi > self.umbral_moderado
            else "estable"
        )
        return ResultadoPsi(
            variable=variable, ambito=ambito, psi=psi, veredicto=veredicto,
            n_referencia=int(referencia.size), n_actual=int(actual.size),
            proporciones=tuple(zip(p_ref.tolist(), p_act.tolist(), strict=True)),
        )


class MonitorDeriva:
    """Corre el PSI de las variables criticas sobre silver y persiste el reporte."""

    ESQUEMA: Final[StructType] = StructType([
        StructField("variable", StringType(), True),
        StructField("ambito", StringType(), True),
        StructField("psi", DoubleType(), True),
        StructField("veredicto", StringType(), True),
        StructField("n_referencia", LongType(), True),
        StructField("n_actual", LongType(), True),
        StructField("referencia_desde", DateType(), True),
        StructField("referencia_hasta", DateType(), True),
        StructField("evaluacion_desde", DateType(), True),
        StructField("evaluacion_hasta", DateType(), True),
        StructField("detalle_bins", StringType(), True),
        StructField("ts_evaluacion", TimestampType(), True),
    ])

    def __init__(
        self,
        spark: SparkSession,
        catalogo: Catalogo,
        calculador: CalculadorPsi | None = None,
        reloj: Callable[[], datetime] = ahora_utc,
    ) -> None:
        self.spark = spark
        self.catalogo = catalogo
        self.calculador = calculador if calculador is not None else CalculadorPsi()
        self.reloj = reloj

    def _valores(self, silver: DataFrame, variable: str) -> DataFrame:
        marco = silver.select(variable, dominio.COLUMNA_FECHA_LOCAL, dominio.COLUMNA_SECTOR)
        if variable == dominio.COLUMNA_LEY:
            marco = silver.filter(F.col(dominio.COLUMNA_LEY_VALIDA)).select(
                variable, dominio.COLUMNA_FECHA_LOCAL, dominio.COLUMNA_SECTOR)
        return marco.filter(F.col(variable).isNotNull())

    def evaluar(
        self,
        silver: DataFrame,
        ventanas: VentanasDeriva | None = None,
        variables: tuple[str, ...] = dominio.VARIABLES_DERIVA,
    ) -> list[ResultadoPsi]:
        """PSI global de cada variable, mas el desglose informativo por sector."""
        if ventanas is None:
            fila = silver.agg(F.max(dominio.COLUMNA_FECHA_LOCAL)).first()
            if fila is None or fila[0] is None:
                raise ParametroInvalidoError("Silver no tiene fechas para definir ventanas")
            ventanas = VentanasDeriva.desde_fecha(fila[0])
        resultados: list[ResultadoPsi] = []
        for variable in variables:
            valores = self._valores(silver, variable)
            fecha = F.col(dominio.COLUMNA_FECHA_LOCAL)
            referencia = valores.filter(
                fecha.between(ventanas.referencia_desde, ventanas.referencia_hasta))
            actual = valores.filter(
                fecha.between(ventanas.evaluacion_desde, ventanas.evaluacion_hasta))
            ref_np = np.array([r[0] for r in referencia.select(variable).collect()])
            act_np = np.array([r[0] for r in actual.select(variable).collect()])
            resultados.append(self.calculador.calcular(ref_np, act_np, variable))
            por_sector_ref = {
                s[dominio.COLUMNA_SECTOR]: s for s in referencia.groupBy(
                    dominio.COLUMNA_SECTOR).agg(F.collect_list(variable).alias("v")).collect()
            }
            for fila_act in actual.groupBy(dominio.COLUMNA_SECTOR).agg(
                    F.collect_list(variable).alias("v")).collect():
                sector = fila_act[dominio.COLUMNA_SECTOR]
                if sector in por_sector_ref:
                    resultados.append(self.calculador.calcular(
                        np.array(por_sector_ref[sector]["v"]), np.array(fila_act["v"]),
                        variable, ambito=str(sector)))
        return resultados

    def escribir(self, resultados: list[ResultadoPsi], ventanas: VentanasDeriva) -> int:
        """Anexa una fila por resultado a `dq_reports.monitor_deriva`."""
        ts = self.reloj()
        filas = [
            (r.variable, r.ambito, r.psi, r.veredicto, r.n_referencia, r.n_actual,
             ventanas.referencia_desde, ventanas.referencia_hasta,
             ventanas.evaluacion_desde, ventanas.evaluacion_hasta,
             json.dumps([[round(a, 6), round(b, 6)] for a, b in r.proporciones]), ts)
            for r in resultados
        ]
        marco = self.spark.createDataFrame(filas, self.ESQUEMA)
        tabla = self.catalogo.tabla(dominio.ESQUEMA_DQ, dominio.TABLA_MONITOR_DERIVA)
        self.spark.sql(
            f"CREATE TABLE IF NOT EXISTS {tabla} ({EsquemaOpus.ddl(self.ESQUEMA)}) USING DELTA")
        marco.write.format("delta").mode("append").saveAsTable(tabla)
        logger.info("monitor_deriva: %d filas", len(filas))
        return len(filas)
