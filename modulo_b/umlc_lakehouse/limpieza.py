"""Capa silver: el extracto validado contra el diccionario, en hora local y con turno real.

Silver hace tres cosas y se abstiene de una cuarta. Convierte `ts_opus_utc` a hora local
con la zona IANA de la operacion y deriva de ahi la fecha local y el mes de particion.
Recalcula `turno_cod` desde la hora local en lugar de copiar el que trae OPUS: el EDA
mostro que la hora determina el turno sin excepcion, asi que la discrepancia, si aparece,
es un error del origen y no una variante. Separa lo invalido de lo alarmante: lo que no
puede existir va a cuarentena con su motivo, lo que esta fuera de rango operacional se
marca y se conserva. Lo que no hace es imputar la ley: el centinela pasa a nulo con
`ley_valida=false`, porque reconstruir un valor es una decision de modelado (Modulo A) y no
de limpieza, y una ley imputada en silver contaminaria el KPI ponderado de gold.

La particion es `anio_mes`, y la justificacion esta en `docs/lakehouse.md`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.calidad import CAPA_SILVER, ReglaCalidad, reglas_silver
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import metricas_desde, version_actual

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultadoLimpieza:
    """Las dos salidas de silver, ya con la forma de sus tablas."""

    validas: DataFrame
    cuarentena: DataFrame


class LimpiadorSilver:
    """Enriquece un lote de bronze y lo separa en filas validas y cuarentena.

    `enriquecer` agrega todas las columnas derivadas y los motivos de rechazo sin quitar
    ninguna fila; sobre ese marco se evalua el reporte de calidad, y `separar` lo parte en
    dos. Que el reporte y la separacion vean el mismo marco es lo que garantiza que las
    cifras del reporte coincidan con lo que quedo en cada tabla.
    """

    COLUMNAS_SILVER: Final[tuple[str, ...]] = (
        *dominio.COLUMNAS_EXTRACTO,
        dominio.COLUMNA_TURNO_OPUS, dominio.COLUMNA_TURNO_DISCREPANTE,
        dominio.COLUMNA_TS_LOCAL, dominio.COLUMNA_FECHA_LOCAL, dominio.COLUMNA_ANIO_MES,
        dominio.COLUMNA_LEY_VALIDA, *dominio.ALERTAS.values(),
        dominio.COLUMNA_FUENTE_TIPO, dominio.COLUMNA_FECHA_CORRECCION,
        dominio.COLUMNA_LOTE_CORRECCION,
        dominio.COLUMNA_LOTE, dominio.COLUMNA_ARCHIVO_FUENTE, dominio.COLUMNA_TS_INGESTA,
    )

    def __init__(
        self,
        zona_horaria: str = dominio.ZONA_HORARIA,
        reglas: tuple[ReglaCalidad, ...] | None = None,
    ) -> None:
        self.zona_horaria = zona_horaria
        self.reglas = reglas if reglas is not None else reglas_silver()

    @staticmethod
    def turno_por_hora(hora: Column) -> Column:
        """El turno que corresponde a una hora local, segun los bloques del dominio."""
        expresion: Column | None = None
        for turno, inicio in dominio.HORA_INICIO_TURNO.items():
            fin = inicio + dominio.DURACION_TURNO_HORAS
            condicion = (hora >= F.lit(inicio)) & (hora < F.lit(fin))
            expresion = (
                F.when(condicion, F.lit(turno)) if expresion is None
                else expresion.when(condicion, F.lit(turno))
            )
        assert expresion is not None
        return expresion

    def enriquecer(self, bronze: DataFrame) -> DataFrame:
        """Agrega hora local, turno recalculado, banderas y motivos de rechazo."""
        EsquemaOpus.verificar(bronze, EsquemaOpus.bronze(), "silver: lote de bronze")
        ts_local = F.from_utc_timestamp(F.col(dominio.COLUMNA_TIEMPO), self.zona_horaria)
        ventana = Window.partitionBy(*dominio.CLAVE_EVENTO).orderBy(
            F.col(dominio.COLUMNA_TS_INGESTA).desc(), F.col(dominio.COLUMNA_ARCHIVO_FUENTE).desc()
        )
        marco = (
            bronze.withColumn(dominio.COLUMNA_ES_DUPLICADO, F.row_number().over(ventana) > 1)
            .withColumn(dominio.COLUMNA_TS_LOCAL, ts_local)
            .withColumn(dominio.COLUMNA_FECHA_LOCAL, F.to_date(ts_local))
            .withColumn(dominio.COLUMNA_ANIO_MES, F.date_format(ts_local, "yyyy-MM"))
            .withColumn(dominio.COLUMNA_TURNO_OPUS, F.col(dominio.COLUMNA_TURNO))
            .withColumn(dominio.COLUMNA_TURNO, self.turno_por_hora(F.hour(ts_local)))
            .withColumn(
                dominio.COLUMNA_TURNO_DISCREPANTE,
                ~F.coalesce(
                    F.col(dominio.COLUMNA_TURNO_OPUS) == F.col(dominio.COLUMNA_TURNO),
                    F.lit(False),
                ),
            )
            .withColumn(
                dominio.COLUMNA_LEY_VALIDA,
                F.col(dominio.COLUMNA_LEY).isNotNull()
                & (F.col(dominio.COLUMNA_LEY) != F.lit(dominio.CENTINELA_LEY))
                & (F.col(dominio.COLUMNA_LEY) >= F.lit(0.0)),
            )
            .withColumn(
                dominio.COLUMNA_LEY,
                F.when(F.col(dominio.COLUMNA_LEY_VALIDA), F.col(dominio.COLUMNA_LEY)),
            )
            .withColumn(
                dominio.COLUMNA_MANTENIMIENTO,
                F.coalesce(F.col(dominio.COLUMNA_MANTENIMIENTO) == F.lit(1), F.lit(False)),
            )
            .withColumn(dominio.COLUMNA_FUENTE_TIPO, F.lit(dominio.FUENTE_OPUS))
            .withColumn(dominio.COLUMNA_FECHA_CORRECCION, F.lit(None).cast("date"))
            .withColumn(dominio.COLUMNA_LOTE_CORRECCION, F.lit(None).cast("string"))
        )
        for columna, bandera in dominio.ALERTAS.items():
            minimo, maximo = dominio.RANGOS_OPERACIONALES[columna]
            fuera = F.lit(False)
            if minimo is not None:
                fuera = fuera | (F.col(columna) < F.lit(minimo))
            if maximo is not None:
                fuera = fuera | (F.col(columna) > F.lit(maximo))
            marco = marco.withColumn(bandera, F.coalesce(fuera, F.lit(False)))
        motivos = F.array_compact(F.array(*[
            F.when(regla.falla(), F.lit(regla.nombre))
            for regla in self.reglas if regla.severidad == "rechaza"
        ]))
        return marco.withColumn(dominio.COLUMNA_MOTIVOS_RECHAZO, motivos)

    def separar(self, enriquecido: DataFrame) -> ResultadoLimpieza:
        """Parte el marco enriquecido en las dos tablas de silver.

        Los duplicados dentro del lote no van a ninguna: son reenvios de la misma clave y
        se conserva la copia mas reciente. Quedan contados en el reporte.
        """
        sin_duplicados = enriquecido.filter(~F.col(dominio.COLUMNA_ES_DUPLICADO))
        rechazada = F.size(F.col(dominio.COLUMNA_MOTIVOS_RECHAZO)) > 0
        validas = sin_duplicados.filter(~rechazada).select(*self.COLUMNAS_SILVER)
        cuarentena = sin_duplicados.filter(rechazada).select(
            *self.COLUMNAS_SILVER, dominio.COLUMNA_RESCATE, dominio.COLUMNA_MOTIVOS_RECHAZO
        )
        return ResultadoLimpieza(validas=validas, cuarentena=cuarentena)


@dataclass(frozen=True)
class ResumenSilver:
    """Lo que un lote dejo en silver."""

    filas_validas: int
    filas_insertadas: int
    filas_cuarentena: int
    version_silver: int


class TablaSilver:
    """Escritura idempotente en `opus_clean` y `opus_cuarentena`.

    La insercion es un `MERGE` con solo `WHEN NOT MATCHED`: reingerir un archivo no
    duplica eventos, que es lo que un `append` no puede garantizar. Las correcciones del
    laboratorio usan el otro lado del `MERGE` y viven en `cdc.py`.
    """

    def __init__(self, spark: SparkSession, catalogo: Catalogo) -> None:
        self.spark = spark
        self.catalogo = catalogo

    def crear_tablas(self) -> None:
        """Crea silver con particion por mes y Change Data Feed, y la cuarentena."""
        muestra = self.spark.createDataFrame([], EsquemaOpus.bronze())
        enriquecido = LimpiadorSilver().enriquecer(muestra)
        resultado = LimpiadorSilver().separar(enriquecido)
        self.spark.sql(
            f"CREATE TABLE IF NOT EXISTS {self.catalogo.opus_clean} "
            f"({EsquemaOpus.ddl(resultado.validas.schema)}) USING DELTA "
            f"PARTITIONED BY ({dominio.COLUMNA_ANIO_MES}) "
            "TBLPROPERTIES (delta.enableChangeDataFeed = true)"
        )
        self.spark.sql(
            f"CREATE TABLE IF NOT EXISTS {self.catalogo.opus_cuarentena} "
            f"({EsquemaOpus.ddl(resultado.cuarentena.schema)}) USING DELTA"
        )

    def lotes_pendientes(self) -> list[str]:
        """Lotes de bronze sin reporte de calidad de silver: los que faltan por procesar.

        El reporte de calidad hace de libro de control: un lote esta procesado cuando tiene
        sus filas de reporte en la capa silver. No se usa "tiene filas en silver" porque un
        lote rechazado o duplicado por completo no las tendria y se reprocesaria por siempre.
        """
        bronze = self.spark.table(self.catalogo.opus_raw).select(dominio.COLUMNA_LOTE).distinct()
        if self.spark.catalog.tableExists(self.catalogo.reporte_calidad):
            procesados = (
                self.spark.table(self.catalogo.reporte_calidad)
                .filter(F.col("capa") == CAPA_SILVER)
                .select(dominio.COLUMNA_LOTE).distinct()
            )
            bronze = bronze.join(procesados, dominio.COLUMNA_LOTE, "left_anti")
        return sorted(str(r[0]) for r in bronze.collect())

    def escribir(self, resultado: ResultadoLimpieza) -> ResumenSilver:
        """Inserta las validas que no existan y anexa la cuarentena."""
        self.crear_tablas()
        validas = resultado.validas.select(*LimpiadorSilver.COLUMNAS_SILVER)
        condicion = " AND ".join(f"t.{c} = s.{c}" for c in dominio.CLAVE_EVENTO)
        version_previa = version_actual(self.spark, self.catalogo.opus_clean)
        (
            DeltaTable.forName(self.spark, self.catalogo.opus_clean).alias("t")
            .merge(validas.alias("s"), condicion)
            .whenNotMatchedInsertAll()
            .execute()
        )
        version = version_actual(self.spark, self.catalogo.opus_clean)
        metricas = metricas_desde(self.spark, self.catalogo.opus_clean, version_previa)
        insertadas = metricas.get("numTargetRowsInserted", 0)
        cuarentena = resultado.cuarentena
        cuarentena.write.format("delta").mode("append").saveAsTable(
            self.catalogo.opus_cuarentena
        )
        resumen = ResumenSilver(
            filas_validas=validas.count(),
            filas_insertadas=insertadas,
            filas_cuarentena=cuarentena.count(),
            version_silver=version,
        )
        logger.info("silver validas=%d insertadas=%d cuarentena=%d version=%d",
                    resumen.filas_validas, insertadas, resumen.filas_cuarentena, version)
        return resumen
