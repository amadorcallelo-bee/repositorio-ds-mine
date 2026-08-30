"""Esquema explicito del extracto y de las correcciones de laboratorio.

El enunciado exige esquema explicito y no inferencia, y aqui eso se hace cumplir por
maquina: `verificar` compara nombre y tipo de cada columna contra lo declarado y falla con
el detalle de la diferencia. Inferir tipos sobre un CSV de telemetria es una apuesta que se
pierde tarde: un archivo con `rpm_corona` vacio en todas sus filas se inferiria como
`string` y rompería la tabla Delta al escribir.

Los tipos siguen el diccionario de variables: `rpm_corona` es entero y `flag_mant_prev`
llega como 0/1 y se convierte a booleano en silver, no aqui, porque bronze conserva el
dato tal como vino.
"""

from __future__ import annotations

from typing import Final

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DataType,
    DateType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import EsquemaInvalidoError


class EsquemaOpus:
    """Los esquemas del lakehouse y la lectura de CSV que los respeta."""

    FORMATO_TIMESTAMP: Final[str] = "yyyy-MM-dd HH:mm:ss"

    #: Las 18 columnas del extracto, en el orden del archivo y con el tipo del diccionario.
    EXTRACTO: Final[StructType] = StructType([
        StructField(dominio.COLUMNA_TIEMPO, TimestampType(), nullable=True),
        StructField(dominio.COLUMNA_FRENTE, StringType(), nullable=True),
        StructField(dominio.COLUMNA_TURNO, StringType(), nullable=True),
        StructField(dominio.COLUMNA_LEY, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_TONELAJE, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_PRESION, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_RPM, IntegerType(), nullable=True),
        StructField(dominio.COLUMNA_AVANCE, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_AGUA, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_VIBRACION, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_TEMPERATURA, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_OPERADOR, StringType(), nullable=True),
        StructField(dominio.COLUMNA_EQUIPO, StringType(), nullable=True),
        StructField(dominio.COLUMNA_FALLA, StringType(), nullable=True),
        StructField(dominio.COLUMNA_PRODUCCION, DoubleType(), nullable=True),
        StructField(dominio.COLUMNA_TIPO_MINERAL, StringType(), nullable=True),
        StructField(dominio.COLUMNA_SECTOR, StringType(), nullable=True),
        StructField(dominio.COLUMNA_MANTENIMIENTO, IntegerType(), nullable=True),
    ])

    #: Un lote de reclasificacion del laboratorio: la clave del evento y el tipo nuevo.
    RECLASIFICACION: Final[StructType] = StructType([
        StructField(dominio.COLUMNA_TIEMPO, TimestampType(), nullable=True),
        StructField(dominio.COLUMNA_FRENTE, StringType(), nullable=True),
        StructField(dominio.COLUMNA_TIPO_LAB, StringType(), nullable=True),
        StructField(dominio.COLUMNA_FECHA_ANALISIS, DateType(), nullable=True),
        StructField(dominio.COLUMNA_LABORATORIO, StringType(), nullable=True),
        StructField(dominio.COLUMNA_MUESTRA, StringType(), nullable=True),
    ])

    #: Metadata de ingesta que bronze agrega a cada fila.
    METADATA_BRONZE: Final[StructType] = StructType([
        StructField(dominio.COLUMNA_RESCATE, StringType(), nullable=True),
        StructField(dominio.COLUMNA_ARCHIVO_FUENTE, StringType(), nullable=True),
        StructField(dominio.COLUMNA_TS_INGESTA, TimestampType(), nullable=True),
        StructField(dominio.COLUMNA_FECHA_INGESTA, DateType(), nullable=True),
        StructField(dominio.COLUMNA_LOTE, StringType(), nullable=True),
    ])

    @classmethod
    def bronze(cls) -> StructType:
        """Esquema de `bronze.opus_raw`: el extracto mas la metadata de ingesta."""
        return StructType([*cls.EXTRACTO.fields, *cls.METADATA_BRONZE.fields])

    @classmethod
    def con_rescate(cls, base: StructType) -> StructType:
        """Un esquema base mas la columna de rescate, que el lector de CSV exige declarar."""
        return StructType(
            [*base.fields, StructField(dominio.COLUMNA_RESCATE, StringType(), True)]
        )

    @staticmethod
    def ddl(esquema: StructType) -> str:
        """Lista de columnas en DDL, para `CREATE TABLE` con esquema explicito."""
        return ", ".join(f"`{f.name}` {f.dataType.simpleString()}" for f in esquema.fields)

    @staticmethod
    def verificar(df: DataFrame, esperado: StructType, contexto: str) -> None:
        """Falla si el marco no tiene exactamente las columnas y tipos esperados.

        Se ignora la anulabilidad, que Spark reporta de forma distinta segun el origen del
        marco, y se exige el resto: ni columnas de mas, ni de menos, ni tipos cambiados.
        """
        reales: dict[str, DataType] = {f.name: f.dataType for f in df.schema.fields}
        esperados: dict[str, DataType] = {f.name: f.dataType for f in esperado.fields}
        diferencias: list[str] = []
        for nombre in esperados.keys() - reales.keys():
            diferencias.append(f"falta la columna {nombre}")
        for nombre in reales.keys() - esperados.keys():
            diferencias.append(f"sobra la columna {nombre}")
        for nombre in esperados.keys() & reales.keys():
            if esperados[nombre] != reales[nombre]:
                diferencias.append(
                    f"{nombre} es {reales[nombre].simpleString()} "
                    f"y se esperaba {esperados[nombre].simpleString()}"
                )
        if diferencias:
            raise EsquemaInvalidoError(contexto, sorted(diferencias))

    @classmethod
    def leer_csv(cls, spark: SparkSession, ruta: str, esquema: StructType) -> DataFrame:
        """Lee CSV con esquema explicito y deja lo que no encaja en la columna de rescate.

        Es el equivalente local de Auto Loader en modo `rescue`: una fila cuyo valor no se
        puede convertir al tipo declarado no se descarta ni se infiere, queda con nulos y con
        el registro original en `_rescued_data`. El archivo de origen se conserva desde la
        metadata del lector, no desde el nombre que el caller crea conocer.
        """
        marco = (
            spark.read.format("csv")
            .schema(cls.con_rescate(esquema))
            .option("header", "true")
            .option("timestampFormat", cls.FORMATO_TIMESTAMP)
            .option("mode", "PERMISSIVE")
            .option("columnNameOfCorruptRecord", dominio.COLUMNA_RESCATE)
            .load(ruta)
        )
        return marco.select(
            "*", F.col("_metadata.file_path").alias(dominio.COLUMNA_ARCHIVO_FUENTE)
        )
