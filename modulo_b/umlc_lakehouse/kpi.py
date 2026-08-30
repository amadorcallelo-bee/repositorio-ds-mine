"""Los KPI por turno de la capa gold.

El grano es `(frente_id, fecha_local, turno_cod)`, el mismo que usa el modelado del A-2, y
las cuatro metricas del enunciado se definen aqui con la decision que cada una encarna:

- **Ley ponderada por tonelaje.** `sum(ley * ton) / sum(ton)` sobre las filas con ley
  valida. El peso es el tonelaje del evento y no el maximo del turno, porque el EDA mostro
  que `ton_rom_acum` no es acumulativo dentro del turno (monotono en el 4% de los grupos).
  El centinela queda fuera del numerador y del denominador: una ley de -1 con 300 t de peso
  hundiria el promedio sin dejar rastro.
- **Eficiencia de avance.** `avg(avance_mmin) / 3.5`, fraccion del tope del rango normal
  del sensor LVDT que publica el manual del equipo. Se descarto el percentil 95 historico
  del frente por no tener fuente externa, y el promedio a secas por no ser una eficiencia.
- **Tasa de fallas.** Eventos con `falla_cod` sobre eventos del turno. Es la misma base
  que la alerta del 5% que pide el B-2.
- **Horas efectivas.** Horas entre el primer y el ultimo evento del turno, acotadas a la
  duracion del turno, menos el tiempo de los eventos con falla o en mantenimiento
  preventivo. El tiempo de un evento es el que transcurre hasta el siguiente del mismo
  turno; el ultimo no aporta duracion, asi que la medida subestima en una cadencia.

Ademas recalcula la produccion en onzas con la formula de OPUS y el tipo de mineral
vigente: tras una reclasificacion del laboratorio, `prod_estimada_oz` queda con el factor
del tipo viejo y solo el recalculo refleja la correccion.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.ingesta import ahora_utc


@dataclass(frozen=True)
class ParametrosKpi:
    """Las constantes que entran a las formulas, con su origen en `dominio`."""

    avance_maximo_mmin: float = dominio.AVANCE_MAXIMO_MMIN
    duracion_turno_horas: float = float(dominio.DURACION_TURNO_HORAS)
    factores_recuperacion: dict[str, float] = field(
        default_factory=lambda: dict(dominio.FACTOR_RECUPERACION)
    )
    oz_troy_en_gramos: float = dominio.OZ_TROY_EN_GRAMOS

    def __post_init__(self) -> None:
        """Valida las precondiciones al construir, no al usar."""
        if self.avance_maximo_mmin <= 0:
            raise ParametroInvalidoError("avance_maximo_mmin debe ser positivo")
        if self.duracion_turno_horas <= 0:
            raise ParametroInvalidoError("duracion_turno_horas debe ser positiva")
        if not self.factores_recuperacion:
            raise ParametroInvalidoError("Faltan los factores de recuperacion")


class ConstructorKpiTurno:
    """Agrega silver al grano de gold."""

    COLUMNAS_GOLD: Final[tuple[str, ...]] = (
        *dominio.CLAVE_TURNO, dominio.COLUMNA_SECTOR,
        "ley_ponderada_gpt", "eficiencia_avance", "tasa_fallas", "horas_efectivas",
        "n_eventos", "n_eventos_ley_valida", "ton_total", "n_fallas",
        "n_eventos_mantenimiento", "horas_parada", "avance_medio_mmin",
        "prod_estimada_oz_total", "prod_oz_recalculada", "equipos_distintos",
        "n_reclasificados", "n_alertas_presion", "n_alertas_rpm", "n_alertas_vibracion",
        "n_alertas_temperatura", "ts_primer_evento", "ts_ultimo_evento", "ts_calculo",
    )

    def __init__(
        self,
        parametros: ParametrosKpi | None = None,
        reloj: Callable[[], datetime] = ahora_utc,
    ) -> None:
        self.parametros = parametros if parametros is not None else ParametrosKpi()
        self.reloj = reloj

    def construir(self, silver: DataFrame) -> DataFrame:
        """Una fila por frente, fecha local y turno, con las columnas de `COLUMNAS_GOLD`."""
        p = self.parametros
        ts = F.col(dominio.COLUMNA_TS_LOCAL)
        ventana = Window.partitionBy(*dominio.CLAVE_TURNO).orderBy(ts)
        siguiente = F.lead(ts).over(ventana)
        duracion_h = F.when(siguiente.isNull(), F.lit(0.0)).otherwise(
            (F.unix_timestamp(siguiente) - F.unix_timestamp(ts)) / 3600.0
        )
        inactivo = F.col(dominio.COLUMNA_FALLA).isNotNull() | F.col(dominio.COLUMNA_MANTENIMIENTO)
        factor = F.create_map(*[
            F.lit(v) for k, f in p.factores_recuperacion.items() for v in (k, f)
        ])[F.col(dominio.COLUMNA_TIPO_MINERAL)]
        ley = F.col(dominio.COLUMNA_LEY)
        ton = F.col(dominio.COLUMNA_TONELAJE)
        valida = F.col(dominio.COLUMNA_LEY_VALIDA)
        eventos = (
            silver.withColumn("_horas_parada", F.when(inactivo, duracion_h).otherwise(0.0))
            .withColumn("_oz", F.when(valida, ley * ton / p.oz_troy_en_gramos * factor))
        )
        alertas = [
            F.sum(F.col(bandera).cast("long")).alias(f"n_alertas_{bandera.removeprefix('alerta_')}")
            for bandera in dominio.ALERTAS.values()
        ]
        agregado = eventos.groupBy(*dominio.CLAVE_TURNO).agg(
            F.max(dominio.COLUMNA_SECTOR).alias(dominio.COLUMNA_SECTOR),
            F.count(F.lit(1)).alias("n_eventos"),
            F.sum(valida.cast("long")).alias("n_eventos_ley_valida"),
            F.sum(ton).alias("ton_total"),
            F.sum(F.when(valida, ley * ton)).alias("_num"),
            F.sum(F.when(valida, ton)).alias("_den"),
            F.avg(F.col(dominio.COLUMNA_AVANCE)).alias("avance_medio_mmin"),
            F.sum(F.col(dominio.COLUMNA_FALLA).isNotNull().cast("long")).alias("n_fallas"),
            F.sum(F.col(dominio.COLUMNA_MANTENIMIENTO).cast("long")).alias(
                "n_eventos_mantenimiento"),
            F.sum("_horas_parada").alias("horas_parada"),
            F.min(ts).alias("ts_primer_evento"),
            F.max(ts).alias("ts_ultimo_evento"),
            F.sum(F.col(dominio.COLUMNA_PRODUCCION)).alias("prod_estimada_oz_total"),
            F.sum("_oz").alias("prod_oz_recalculada"),
            F.countDistinct(dominio.COLUMNA_EQUIPO).alias("equipos_distintos"),
            F.sum((F.col(dominio.COLUMNA_FUENTE_TIPO) == dominio.FUENTE_LAB).cast("long"))
            .alias("n_reclasificados"),
            *alertas,
        )
        span_h = (
            F.unix_timestamp(F.col("ts_ultimo_evento"))
            - F.unix_timestamp(F.col("ts_primer_evento"))
        ) / 3600.0
        resultado = (
            agregado.withColumn(
                "ley_ponderada_gpt",
                F.when(F.col("_den") > 0, F.col("_num") / F.col("_den")),
            )
            .withColumn("eficiencia_avance", F.col("avance_medio_mmin") / p.avance_maximo_mmin)
            .withColumn("tasa_fallas", F.col("n_fallas") / F.col("n_eventos"))
            .withColumn(
                "horas_efectivas",
                F.greatest(
                    F.lit(0.0),
                    F.least(span_h, F.lit(p.duracion_turno_horas)) - F.col("horas_parada"),
                ),
            )
            .withColumn("ts_calculo", F.lit(self.reloj()))
        )
        return resultado.select(*self.COLUMNAS_GOLD)
