# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver: limpieza por diccionario, hora local, turno real y reporte de calidad
# MAGIC
# MAGIC Dos etapas en un mismo notebook, elegidas con el parametro `etapa`:
# MAGIC
# MAGIC - **limpieza**: toma de `bronze.opus_raw` los lotes que todavia no tienen reporte de
# MAGIC   calidad, los enriquece con `LimpiadorSilver`, evalua el reporte **por lote** y escribe
# MAGIC   validas en `silver.opus_clean` (particion `anio_mes`, Change Data Feed activo) y
# MAGIC   rechazadas en `silver.opus_cuarentena`.
# MAGIC - **correcciones**: lee los lotes de reclasificacion del laboratorio que esperan en
# MAGIC   `landing/reclasificacion` y los aplica a silver con `MERGE` (CDC), uno por uno.

# COMMAND ----------

"""Notebook de silver: orquesta `umlc_lakehouse.limpieza`, `calidad` y `cdc`."""

import json

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.calidad import CAPA_SILVER, ReporteCalidad, reglas_silver
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.cdc import AplicadorReclasificacion, ResumenReclasificacion
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import IngestorBronze, version_actual
from umlc_lakehouse.limpieza import LimpiadorSilver, ResumenSilver, TablaSilver

# COMMAND ----------

dbutils.widgets.text("catalogo", "lakehouse_umlc")
dbutils.widgets.dropdown("etapa", "limpieza", ["limpieza", "correcciones"])
spark.conf.set("spark.sql.session.timeZone", "UTC")

catalogo = Catalogo(nombre=dbutils.widgets.get("catalogo"))
etapa = dbutils.widgets.get("etapa")
tabla_silver = TablaSilver(spark, catalogo)
tabla_silver.crear_tablas()
reporte_calidad = ReporteCalidad(reglas_silver())
ingestor = IngestorBronze(spark, catalogo)
print(f"etapa: {etapa}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Etapa `limpieza`: de bronze a silver, con reporte por lote
# MAGIC
# MAGIC Un lote de bronze esta procesado cuando tiene sus filas en `dq_reports.reporte_calidad`
# MAGIC con capa `silver`; los que no las tienen son los pendientes. El reporte y la separacion en
# MAGIC validas y cuarentena se calculan sobre el mismo marco enriquecido, para que las cifras del
# MAGIC reporte coincidan exactamente con lo que quedo en cada tabla.

# COMMAND ----------

resumenes_silver: list[ResumenSilver] = []
reportes: list[dict[str, object]] = []
limpiador = LimpiadorSilver()


def limpiar(lote: DataFrame) -> None:
    """Enriquecer, medir, separar y escribir."""
    enriquecido = limpiador.enriquecer(lote)
    reporte = reporte_calidad.evaluar(enriquecido, CAPA_SILVER)
    resultado = limpiador.separar(enriquecido)
    resumenes_silver.append(tabla_silver.escribir(resultado))
    reporte_calidad.escribir(reporte, catalogo)
    reportes.extend(reporte_calidad.resumen(reporte))


lotes_pendientes: list[str] = []
if etapa == "limpieza":
    lotes_pendientes = tabla_silver.lotes_pendientes()
    print(f"lotes pendientes: {lotes_pendientes}")
    if lotes_pendientes:
        limpiar(spark.table(catalogo.opus_raw).filter(
            F.col(dominio.COLUMNA_LOTE).isin(lotes_pendientes)))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Etapa `correcciones`: CDC del laboratorio con `MERGE`
# MAGIC
# MAGIC Cada archivo de `landing/reclasificacion` es un lote, y `ingesta_log` es el libro que dice
# MAGIC cuales ya se aplicaron. `AplicadorReclasificacion` actualiza solo las filas cuyo
# MAGIC `tipo_mineral` cambia, cuenta las que ya estaban asi, y manda al reporte de calidad las
# MAGIC claves que no existen y los tipos fuera de dominio. Bronze no se toca; la fila de silver
# MAGIC queda con `fuente_tipo_mineral = LAB`, la fecha del analisis y el lote que la corrigio.

# COMMAND ----------

resumenes_cdc: list[ResumenReclasificacion] = []
muestras: list[dict[str, object]] = []
aplicador = AplicadorReclasificacion(spark, catalogo)


def corregir(lote: DataFrame, lote_id: str) -> None:
    """Un archivo de reclasificacion es un lote de CDC; se guarda una muestra antes/despues."""
    version_previa = version_actual(spark, catalogo.opus_clean)
    resumen = aplicador.aplicar(lote, lote_id)
    reporte_calidad.escribir(aplicador.reporte(resumen), catalogo)
    # El registro va al final: si algo falla antes, el archivo sigue pendiente y el reintento
    # vuelve a pasar por un MERGE que no reescribe lo ya aplicado.
    ingestor.registrar_archivos(lote, lote_id)
    resumenes_cdc.append(resumen)
    clave = lote.select(*dominio.CLAVE_EVENTO).orderBy(*dominio.CLAVE_EVENTO).first()
    if clave is not None and resumen.actualizadas > 0:
        condicion = (F.col(dominio.COLUMNA_TIEMPO) == F.lit(clave[dominio.COLUMNA_TIEMPO])) & (
            F.col(dominio.COLUMNA_FRENTE) == F.lit(clave[dominio.COLUMNA_FRENTE]))
        antes = (spark.read.format("delta").option("versionAsOf", version_previa)
                 .table(catalogo.opus_clean).filter(condicion).first())
        despues = spark.table(catalogo.opus_clean).filter(condicion).first()
        muestras.append({
            "lote_id": lote_id,
            "clave": f"{clave[dominio.COLUMNA_TIEMPO]}|{clave[dominio.COLUMNA_FRENTE]}",
            "version_antes": version_previa, "version_despues": resumen.version_silver,
            "tipo_antes": antes[dominio.COLUMNA_TIPO_MINERAL] if antes else None,
            "tipo_despues": despues[dominio.COLUMNA_TIPO_MINERAL] if despues else None,
            "fuente_despues": despues[dominio.COLUMNA_FUENTE_TIPO] if despues else None,
        })


archivos_pendientes: list[str] = []
if etapa == "correcciones":
    ruta = f"{catalogo.ruta_landing}/reclasificacion"
    archivos = sorted(f.path for f in dbutils.fs.ls(ruta) if f.path.endswith(".csv"))
    archivos_pendientes = ingestor.archivos_pendientes(archivos)
    print(f"archivos pendientes: {archivos_pendientes}")
    for ruta_archivo in archivos_pendientes:
        lote = EsquemaOpus.leer_csv(spark, ruta_archivo, EsquemaOpus.RECLASIFICACION)
        corregir(lote, IngestorBronze.nombre_de(ruta_archivo))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Lo que quedo en silver

# COMMAND ----------

detalle = spark.sql(f"DESCRIBE DETAIL {catalogo.opus_clean}").first()
historia = spark.sql(f"DESCRIBE HISTORY {catalogo.opus_clean}").select(
    "version", "operation", "operationMetrics").orderBy(F.col("version").desc()).limit(8)
display(historia)
display(spark.table(catalogo.reporte_calidad).orderBy(F.col("ts_evaluacion").desc(), "regla")
        .limit(40))

resumen = {
    "notebook": "02_silver", "etapa": etapa,
    "lotes_pendientes": lotes_pendientes,
    "archivos_pendientes": [a.rsplit("/", 1)[-1] for a in archivos_pendientes],
    "filas_silver": spark.table(catalogo.opus_clean).count(),
    "filas_cuarentena": spark.table(catalogo.opus_cuarentena).count(),
    "version_silver": version_actual(spark, catalogo.opus_clean),
    "particion": list(detalle["partitionColumns"]) if detalle else None,
    "archivos_delta": int(detalle["numFiles"]) if detalle else None,
    "bytes_delta": int(detalle["sizeInBytes"]) if detalle else None,
    "cdf_activo": detalle["properties"].get("delta.enableChangeDataFeed") if detalle else None,
    "lotes_limpieza": [r.__dict__ for r in resumenes_silver],
    "reporte_calidad": [r for r in reportes if r["filas_falla"]],
    "lotes_correcciones": [r.__dict__ for r in resumenes_cdc],
    "muestras_cdc": muestras,
    "historia": [r.asDict() for r in historia.collect()],
}
print(json.dumps(resumen, indent=2, ensure_ascii=False, default=str))
dbutils.notebook.exit(json.dumps(resumen, ensure_ascii=False, default=str))
