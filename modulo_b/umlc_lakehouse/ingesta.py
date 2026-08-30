"""Capa bronze: el extracto tal como llego, con la metadata de su ingesta.

Bronze no limpia, no deduplica y no corrige: conserva la fidelidad del origen para poder
reprocesar y auditar. Lo unico que agrega es lo que el enunciado pide registrar —archivo
fuente, timestamp y conteo de filas— y el identificador del lote, que es lo que permite
que silver produzca un reporte de calidad por lote.

La tabla se particiona por `fecha_ingesta` porque lo prescribe el enunciado y porque es la
unidad operativa de esta capa: reprocesar un dia es borrar una particion, la retencion se
expresa en dias y una ingesta cada 30 minutos nunca reescribe una particion pasada. No es
una decision de rendimiento de lectura: a la escala de este lakehouse (unos 10 MB a cuatro
anios) Databricks recomienda no particionar, y la documentacion lo dice con esas palabras.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import LoteVacioError
from umlc_lakehouse.esquema import EsquemaOpus

logger = logging.getLogger(__name__)


def ahora_utc() -> datetime:
    """Reloj por defecto; las pruebas inyectan uno fijo."""
    return datetime.now(UTC)


def version_actual(spark: SparkSession, tabla: str) -> int:
    """Ultima version Delta de una tabla."""
    fila = DeltaTable.forName(spark, tabla).history(1).select("version").first()
    if fila is None:
        raise RuntimeError(f"{tabla} no tiene historia Delta")
    return int(fila["version"])


def metricas_desde(spark: SparkSession, tabla: str, version_previa: int) -> dict[str, int]:
    """Las metricas de la ultima operacion, o vacio si no hubo commit nuevo.

    Un `MERGE` que no cambia filas no escribe una version nueva, y `history(1)` seguiria
    devolviendo la operacion anterior con sus conteos: leer las metricas sin comparar la
    version reportaria como insertado lo que ya estaba.
    """
    if version_actual(spark, tabla) <= version_previa:
        return {}
    fila = DeltaTable.forName(spark, tabla).history(1).first()
    if fila is None:
        return {}
    return {clave: int(valor) for clave, valor in dict(fila["operationMetrics"]).items()}


@dataclass(frozen=True)
class ResumenArchivo:
    """Filas aportadas por un archivo dentro de un lote."""

    archivo_fuente: str
    filas: int


@dataclass(frozen=True)
class ResumenLote:
    """Lo que bronze registra de un lote: es la misma fila de `ingesta_log`."""

    lote_id: str
    ts_ingesta: datetime
    filas: int
    archivos: tuple[ResumenArchivo, ...]
    version_bronze: int


class IngestorBronze:
    """Agrega la metadata de ingesta, escribe en bronze y deja constancia en el log.

    Recibe un marco ya leido con esquema explicito —por Auto Loader en Databricks o por
    `EsquemaOpus.leer_csv` en local— y no un path, para que la escritura sea la misma en
    ambos entornos y se pueda probar sin `cloudFiles`.
    """

    def __init__(
        self,
        spark: SparkSession,
        catalogo: Catalogo,
        reloj: Callable[[], datetime] = ahora_utc,
    ) -> None:
        self.spark = spark
        self.catalogo = catalogo
        self.reloj = reloj

    def crear_tablas(self) -> None:
        """Crea `opus_raw` particionada por fecha de ingesta e `ingesta_log`; idempotente."""
        columnas = EsquemaOpus.ddl(EsquemaOpus.bronze())
        self.spark.sql(
            f"CREATE TABLE IF NOT EXISTS {self.catalogo.opus_raw} ({columnas}) "
            f"USING DELTA PARTITIONED BY ({dominio.COLUMNA_FECHA_INGESTA})"
        )
        self.spark.sql(
            f"CREATE TABLE IF NOT EXISTS {self.catalogo.ingesta_log} ("
            f"{dominio.COLUMNA_LOTE} string, {dominio.COLUMNA_ARCHIVO_FUENTE} string, "
            f"{dominio.COLUMNA_TS_INGESTA} timestamp, filas bigint, version_bronze bigint"
            ") USING DELTA"
        )

    @staticmethod
    def lote_desde_archivo(archivo: Column) -> Column:
        """El identificador de lote de un archivo: su nombre sin ruta ni extension.

        En produccion cada archivo de OPUS es un lote, y su nombre es lo unico que sobrevive
        de forma identica en Auto Loader, en `dbutils.fs.ls` y en el log de ingesta.
        """
        return F.regexp_extract(archivo, r"(?i)([^/]+)\.csv$", 1)

    @staticmethod
    def nombre_de(ruta: str) -> str:
        """El mismo identificador que `lote_desde_archivo`, calculado en Python."""
        nombre = ruta.rsplit("/", 1)[-1]
        return nombre[:-4] if nombre.lower().endswith(".csv") else nombre

    def enriquecer(self, df: DataFrame, lote_id: Column, ts_ingesta: Column) -> DataFrame:
        """Verifica el esquema del extracto y agrega la metadata de ingesta.

        Recibe columnas y no valores para servir igual a un `DataFrame` de streaming, donde
        el lote y el instante se calculan fila a fila, y a uno de batch, donde son literales.
        """
        if dominio.COLUMNA_RESCATE not in df.columns:
            df = df.withColumn(dominio.COLUMNA_RESCATE, F.lit(None).cast("string"))
        esperado = EsquemaOpus.con_rescate(EsquemaOpus.EXTRACTO)
        EsquemaOpus.verificar(df.drop(dominio.COLUMNA_ARCHIVO_FUENTE), esperado, "bronze")
        if dominio.COLUMNA_ARCHIVO_FUENTE not in df.columns:
            df = df.withColumn(dominio.COLUMNA_ARCHIVO_FUENTE, F.lit(None).cast("string"))
        enriquecido = (
            df.withColumn(dominio.COLUMNA_TS_INGESTA, ts_ingesta)
            .withColumn(dominio.COLUMNA_FECHA_INGESTA, F.to_date(ts_ingesta))
            .withColumn(dominio.COLUMNA_LOTE, lote_id)
        )
        return enriquecido.select(*[f.name for f in EsquemaOpus.bronze().fields])

    def preparar(self, df: DataFrame, lote_id: str, ts_ingesta: datetime) -> DataFrame:
        """`enriquecer` para un lote de batch, que ademas no puede venir vacio."""
        if not lote_id:
            raise LoteVacioError(lote_id)
        preparado = self.enriquecer(df, F.lit(lote_id), F.lit(ts_ingesta))
        if preparado.isEmpty():
            raise LoteVacioError(lote_id)
        return preparado

    def registrar_pendientes(self) -> tuple[ResumenLote, ...]:
        """Lleva a `ingesta_log` los pares (lote, archivo) que bronze tiene y el log no.

        Es el paso que sigue a Auto Loader: el stream escribe en bronze con su metadata y
        este metodo, en batch, deja constancia por archivo con su conteo. La version que
        registra es la vigente al cerrar el stream; la historia Delta conserva ademas un
        commit por microlote.
        """
        self.crear_tablas()
        version = version_actual(self.spark, self.catalogo.opus_raw)
        clave = [dominio.COLUMNA_LOTE, dominio.COLUMNA_ARCHIVO_FUENTE]
        en_bronze = self.spark.table(self.catalogo.opus_raw).groupBy(*clave).agg(
            F.max(dominio.COLUMNA_TS_INGESTA).alias(dominio.COLUMNA_TS_INGESTA),
            F.count(F.lit(1)).alias("filas"),
        )
        en_log = self.spark.table(self.catalogo.ingesta_log).select(*clave)
        pendientes = (
            en_bronze.join(en_log, clave, "left_anti")
            .withColumn("version_bronze", F.lit(version).cast("bigint"))
            .select(*clave, dominio.COLUMNA_TS_INGESTA, F.col("filas").cast("bigint"),
                    "version_bronze")
        )
        # Se materializa antes de escribir: el plan es perezoso y hace un anti-join contra el
        # mismo log que se va a llenar, asi que evaluarlo despues devolveria vacio.
        filas = pendientes.orderBy(*clave).collect()
        self.spark.createDataFrame(filas, pendientes.schema).write.format("delta").mode(
            "append").saveAsTable(self.catalogo.ingesta_log)
        por_lote: dict[str, list[ResumenArchivo]] = {}
        momentos: dict[str, datetime] = {}
        for f in filas:
            lote = str(f[dominio.COLUMNA_LOTE])
            por_lote.setdefault(lote, []).append(
                ResumenArchivo(str(f[dominio.COLUMNA_ARCHIVO_FUENTE]), int(f["filas"])))
            momentos[lote] = f[dominio.COLUMNA_TS_INGESTA]
        return tuple(
            ResumenLote(lote_id=lote, ts_ingesta=momentos[lote],
                        filas=sum(a.filas for a in archivos), archivos=tuple(archivos),
                        version_bronze=version)
            for lote, archivos in por_lote.items()
        )

    def archivos_pendientes(self, rutas: Sequence[str]) -> list[str]:
        """De una lista de rutas, las que todavia no tienen fila en `ingesta_log`.

        Compara por nombre de archivo y no por ruta completa, porque `dbutils.fs.ls` y la
        metadata del lector no siempre escriben el mismo prefijo (`dbfs:/` contra `/`).
        """
        self.crear_tablas()
        registrados = {
            self.nombre_de(str(r[0]))
            for r in self.spark.table(self.catalogo.ingesta_log)
            .select(dominio.COLUMNA_ARCHIVO_FUENTE).distinct().collect()
            if r[0] is not None
        }
        return [ruta for ruta in rutas if self.nombre_de(ruta) not in registrados]

    def escribir(self, preparado: DataFrame) -> ResumenLote:
        """Anexa el lote a bronze y registra un renglon por archivo en `ingesta_log`."""
        self.crear_tablas()
        preparado.write.format("delta").mode("append").saveAsTable(self.catalogo.opus_raw)
        version = version_actual(self.spark, self.catalogo.opus_raw)
        conteos = (
            preparado.groupBy(
                dominio.COLUMNA_LOTE, dominio.COLUMNA_ARCHIVO_FUENTE, dominio.COLUMNA_TS_INGESTA
            )
            .agg(F.count(F.lit(1)).alias("filas"))
            .withColumn("version_bronze", F.lit(version).cast("bigint"))
        )
        conteos.write.format("delta").mode("append").saveAsTable(self.catalogo.ingesta_log)
        filas = conteos.orderBy(dominio.COLUMNA_ARCHIVO_FUENTE).collect()
        archivos = tuple(
            ResumenArchivo(str(f[dominio.COLUMNA_ARCHIVO_FUENTE]), int(f["filas"]))
            for f in filas
        )
        resumen = ResumenLote(
            lote_id=str(filas[0][dominio.COLUMNA_LOTE]),
            ts_ingesta=filas[0][dominio.COLUMNA_TS_INGESTA],
            filas=sum(a.filas for a in archivos),
            archivos=archivos,
            version_bronze=version,
        )
        logger.info(
            "bronze lote=%s filas=%d archivos=%d version=%d",
            resumen.lote_id, resumen.filas, len(archivos), version,
        )
        return resumen

    def registrar_archivos(self, df: DataFrame, lote_id: str) -> int:
        """Deja en `ingesta_log` un renglon por archivo de un lote que no pasa por `opus_raw`.

        Lo usan las correcciones del laboratorio, que se aplican sobre silver y no tienen
        fila en bronze: sin este registro, el log de ingesta no sabria que llegaron.
        """
        if not lote_id:
            raise LoteVacioError(lote_id)
        if dominio.COLUMNA_ARCHIVO_FUENTE not in df.columns:
            df = df.withColumn(dominio.COLUMNA_ARCHIVO_FUENTE, F.lit(None).cast("string"))
        self.crear_tablas()
        conteos = (
            df.groupBy(dominio.COLUMNA_ARCHIVO_FUENTE)
            .agg(F.count(F.lit(1)).alias("filas"))
            .select(
                F.lit(lote_id).alias(dominio.COLUMNA_LOTE),
                F.col(dominio.COLUMNA_ARCHIVO_FUENTE),
                F.lit(self.reloj()).alias(dominio.COLUMNA_TS_INGESTA),
                F.col("filas").cast("bigint"),
                F.lit(None).cast("bigint").alias("version_bronze"),
            )
        )
        conteos.write.format("delta").mode("append").saveAsTable(self.catalogo.ingesta_log)
        return conteos.count()

    def procesar_lote(self, df: DataFrame, lote_id: str) -> ResumenLote:
        """Preparar y escribir en un paso: es lo que llama `foreachBatch`."""
        return self.escribir(self.preparar(df, lote_id, self.reloj()))
