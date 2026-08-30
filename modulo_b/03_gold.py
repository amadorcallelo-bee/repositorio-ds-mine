# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold: `aurum_kpi_turno`, Z-ORDER y actualizacion incremental
# MAGIC
# MAGIC Una fila por `(frente_id, fecha_local, turno_cod)` con ley ponderada por tonelaje,
# MAGIC eficiencia de avance, tasa de fallas y horas efectivas, mas la produccion recalculada con el
# MAGIC tipo de mineral vigente. La primera corrida construye la tabla completa desde silver; las
# MAGIC siguientes leen el Change Data Feed de silver desde la ultima version incorporada y
# MAGIC recalculan **solo las celdas afectadas**, que se funden con `MERGE`. Al cerrar, la tabla
# MAGIC se ordena con `OPTIMIZE ... ZORDER BY (frente_id, fecha_local)`.

# COMMAND ----------

"""Notebook de gold: orquesta `umlc_lakehouse.gold` y `kpi`."""

import json

from pyspark.sql import functions as F

from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.gold import ActualizadorGold
from umlc_lakehouse.kpi import ConstructorKpiTurno

# COMMAND ----------

dbutils.widgets.text("catalogo", "lakehouse_umlc")
spark.conf.set("spark.sql.session.timeZone", "UTC")

catalogo = Catalogo(nombre=dbutils.widgets.get("catalogo"))
actualizador = ActualizadorGold(spark, catalogo, ConstructorKpiTurno())
version_previa = actualizador.version_procesada()
print(f"gold existe: {actualizador.existe()}  version de silver ya incorporada: {version_previa}")

# COMMAND ----------

resumen_gold = actualizador.actualizar()
print(resumen_gold)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Lo que quedo en gold

# COMMAND ----------

gold = spark.table(catalogo.aurum_kpi_turno)
display(gold.orderBy(F.col("fecha_local").desc(), "frente_id", "turno_cod").limit(20))
historia = spark.sql(f"DESCRIBE HISTORY {catalogo.aurum_kpi_turno}").select(
    "version", "operation", "operationParameters", "operationMetrics"
).orderBy(F.col("version").desc()).limit(6)
display(historia)

reclasificadas = gold.filter(F.col("n_reclasificados") > 0)
resumen = {
    "notebook": "03_gold",
    "resultado": resumen_gold.__dict__,
    "detalle": actualizador.detalle(),
    "zorder": [
        r["operationParameters"].get("zOrderBy") for r in historia.collect()
        if r["operation"] == "OPTIMIZE"
    ][:1],
    "celdas_con_reclasificacion": reclasificadas.count(),
    "muestra_reclasificadas": [
        r.asDict() for r in reclasificadas.select(
            "frente_id", "fecha_local", "turno_cod", "n_eventos", "n_reclasificados",
            "ley_ponderada_gpt", "prod_estimada_oz_total", "prod_oz_recalculada", "ts_calculo",
        ).orderBy("fecha_local", "frente_id", "turno_cod").limit(5).collect()
    ],
    "kpi_globales": gold.agg(
        F.count(F.lit(1)).alias("celdas"),
        F.avg("ley_ponderada_gpt").alias("ley_ponderada_media"),
        F.avg("eficiencia_avance").alias("eficiencia_avance_media"),
        F.avg("tasa_fallas").alias("tasa_fallas_media"),
        F.avg("horas_efectivas").alias("horas_efectivas_media"),
    ).first().asDict(),
    "historia": [r.asDict() for r in historia.collect()],
}
print(json.dumps(resumen, indent=2, ensure_ascii=False, default=str))
dbutils.notebook.exit(json.dumps(resumen, ensure_ascii=False, default=str))
