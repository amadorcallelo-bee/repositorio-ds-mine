# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze: ingesta incremental del extracto OPUS
# MAGIC
# MAGIC Los archivos CSV llegan al volumen `landing/opus` como llegarian de OPUS-MINE cada 30
# MAGIC minutos. Auto Loader los descubre, los lee con el **esquema explicito** de
# MAGIC `EsquemaOpus.EXTRACTO` (sin inferencia), les agrega la metadata de ingesta y los escribe
# MAGIC en `bronze.opus_raw`, particionada por `fecha_ingesta`. El checkpoint garantiza que un
# MAGIC archivo ya procesado no vuelve a entrar aunque el job se relance. Al cerrar el stream,
# MAGIC `IngestorBronze.registrar_pendientes` deja en `ingesta_log` un renglon por archivo con su
# MAGIC conteo de filas, su instante y la version Delta.

# COMMAND ----------

"""Notebook de bronze: orquesta Auto Loader sobre `umlc_lakehouse.ingesta`."""

import json

from pyspark.sql import functions as F

from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import IngestorBronze

# COMMAND ----------

dbutils.widgets.text("catalogo", "lakehouse_umlc")
spark.conf.set("spark.sql.session.timeZone", "UTC")

catalogo = Catalogo(nombre=dbutils.widgets.get("catalogo"))
catalogo.crear_esquemas(spark)
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalogo.esquema('bronze')}.landing")
ingestor = IngestorBronze(spark, catalogo)
ingestor.crear_tablas()

ruta_opus = f"{catalogo.ruta_landing}/opus"
ruta_checkpoint = f"{catalogo.ruta_landing}/_checkpoints/bronze_opus_raw"
ruta_esquema = f"{catalogo.ruta_landing}/_schemas/opus"
print(f"landing: {ruta_opus}\ncheckpoint: {ruta_checkpoint}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Auto Loader con esquema explicito
# MAGIC
# MAGIC `maxFilesPerTrigger = 1` hace que cada archivo sea un microlote y un commit Delta propio:
# MAGIC asi la historia de bronze muestra la llegada archivo por archivo. `schemaEvolutionMode =
# MAGIC rescue` no infiere ni amplia el esquema: lo que no encaja va a `_rescued_data` y silver lo
# MAGIC manda a cuarentena. El `lote_id` es el nombre del archivo, que es lo que OPUS controla.

# COMMAND ----------

flujo = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "csv")
    .option("cloudFiles.schemaLocation", ruta_esquema)
    .option("cloudFiles.schemaEvolutionMode", "rescue")
    .option("cloudFiles.maxFilesPerTrigger", "1")
    .option("rescuedDataColumn", "_rescued_data")
    .option("header", "true")
    .option("timestampFormat", EsquemaOpus.FORMATO_TIMESTAMP)
    .schema(EsquemaOpus.EXTRACTO)
    .load(ruta_opus)
    .withColumn("archivo_fuente", F.col("_metadata.file_path"))
)
enriquecido = ingestor.enriquecer(
    flujo,
    lote_id=IngestorBronze.lote_desde_archivo(F.col("archivo_fuente")),
    ts_ingesta=F.current_timestamp(),
)
consulta = (
    enriquecido.writeStream
    .option("checkpointLocation", ruta_checkpoint)
    .trigger(availableNow=True)
    .toTable(catalogo.opus_raw)
)
consulta.awaitTermination()
resumenes = ingestor.registrar_pendientes()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Lo que quedo en bronze

# COMMAND ----------

detalle = spark.sql(f"DESCRIBE DETAIL {catalogo.opus_raw}").first()
log = spark.table(catalogo.ingesta_log).orderBy("ts_ingesta", "archivo_fuente")
historia = spark.sql(f"DESCRIBE HISTORY {catalogo.opus_raw}").select(
    "version", "operation", "operationMetrics").orderBy(F.col("version").desc()).limit(8)
display(log)
display(historia)

resumen = {
    "notebook": "01_bronze",
    "lotes_nuevos": [
        {
            "lote_id": r.lote_id, "filas": r.filas, "version_bronze": r.version_bronze,
            "ts_ingesta": r.ts_ingesta,
            "archivos": [{"archivo": a.archivo_fuente.rsplit("/", 1)[-1], "filas": a.filas}
                         for a in r.archivos],
        }
        for r in resumenes
    ],
    "filas_lotes_nuevos": sum(r.filas for r in resumenes),
    "filas_bronze": spark.table(catalogo.opus_raw).count(),
    "particion": list(detalle["partitionColumns"]) if detalle else None,
    "archivos_delta": int(detalle["numFiles"]) if detalle else None,
    "bytes_delta": int(detalle["sizeInBytes"]) if detalle else None,
    "filas_ingesta_log": log.count(),
    "historia": [r.asDict() for r in historia.collect()],
}
print(json.dumps(resumen, indent=2, ensure_ascii=False, default=str))
dbutils.notebook.exit(json.dumps(resumen, ensure_ascii=False, default=str))
