# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · MLOps: deriva por PSI, trigger de reentrenamiento y rollback
# MAGIC
# MAGIC Tres piezas del Ejercicio B-3, sobre el modelo **real del A-2** (LightGBM con el conjunto
# MAGIC `MINIMO`, importado de `aurum_pipeline`, sin reimplementar nada):
# MAGIC
# MAGIC 1. **Monitor de deriva**: PSI de `ley_au_gpT` y `vibracion_rms_ms2` sobre silver, con los
# MAGIC    últimos 7 días evaluados contra los 30 anteriores como referencia; persiste en
# MAGIC    `dq_reports.monitor_deriva`.
# MAGIC 2. **Trigger**: PSI > 0.2 en cualquier variable crítica, o error medio actual > baseline
# MAGIC    de MLflow x 1.15. El baseline es `error_medio_g_por_tonelada` del run que entrenó al
# MAGIC    modelo en `@produccion`.
# MAGIC 3. **Promoción con rollback**: staging se compara contra producción sobre la misma
# MAGIC    ventana; si es peor **o igual**, el alias no se mueve y el evento queda en MLflow con
# MAGIC    la razón. Como el extracto real no deriva, las dos ramas se demuestran con un
# MAGIC    escenario sintético **en memoria** sobre un modelo `_demo`: silver y gold no reciben
# MAGIC    datos falsos y el modelo real no se toca.

# COMMAND ----------

# MAGIC %pip install --quiet lightgbm==4.7.0 xgboost==3.4.1

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

"""Notebook de MLOps: orquesta `umlc_lakehouse.deriva`, `modelo` y `promocion`."""

import json
import os
import sys

for _candidato in (
    os.path.abspath(os.path.join(os.getcwd(), "..", "modulo_a")),
    os.path.abspath(os.path.join(os.getcwd(), "modulo_a")),
):
    if os.path.isdir(os.path.join(_candidato, "aurum_pipeline")):
        sys.path.insert(0, _candidato)
        break

import pandas as pd
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.deriva import CalculadorPsi, MonitorDeriva, VentanasDeriva
from umlc_lakehouse.modelo import EntrenadorLey
from umlc_lakehouse.promocion import DecisorReentrenamiento, PromotorModelos, RegistroMlops

# COMMAND ----------

dbutils.widgets.text("catalogo", "lakehouse_umlc")
spark.conf.set("spark.sql.session.timeZone", "UTC")

catalogo = Catalogo(nombre=dbutils.widgets.get("catalogo"))
esquema_modelos = catalogo.esquema(dominio.ESQUEMA_MODELOS)
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {esquema_modelos}")
usuario = spark.sql("SELECT current_user()").first()[0]
experimento = f"/Users/{usuario}/{dominio.EXPERIMENTO_MLOPS}"
nombre_modelo = f"{esquema_modelos}.{dominio.MODELO_LEY_REGISTRADO}"
registro = RegistroMlops("databricks", "databricks-uc", nombre_modelo, experimento)
print(f"modelo: {nombre_modelo}\nexperimento: {experimento}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Monitor de deriva sobre los datos reales

# COMMAND ----------

silver = spark.table(catalogo.opus_clean)
fila_max = silver.agg(F.max(dominio.COLUMNA_FECHA_LOCAL)).first()
ventanas = VentanasDeriva.desde_fecha(fila_max[0])
monitor = MonitorDeriva(spark, catalogo)
resultados_psi = monitor.evaluar(silver, ventanas)
monitor.escribir(resultados_psi, ventanas)
globales = [r for r in resultados_psi if r.ambito == "global"]
for r in resultados_psi:
    print(f"{r.variable:20s} {r.ambito:15s} PSI={r.psi:.4f} {r.veredicto}"
          f" (ref {r.n_referencia}, actual {r.n_actual})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. El modelo real: bootstrap si no existe, y evaluación en la ventana

# COMMAND ----------

columnas_extracto = list(dominio.COLUMNAS_EXTRACTO)
eventos = silver.select(*columnas_extracto).toPandas()
entrenador = EntrenadorLey()

version_produccion = registro.version_por_alias(dominio.ALIAS_PRODUCCION)
bootstrap = version_produccion is None
if bootstrap:
    modelo_inicial = entrenador.entrenar(eventos)
    version_produccion = registro.registrar_entrenamiento(
        modelo_inicial, dominio.ALIAS_PRODUCCION, "bootstrap_produccion",
        etiquetas={"origen": "A-2", "modelo": "lightgbm_MINIMO"})
error_baseline = registro.error_registrado(version_produccion)
pipeline_produccion = registro.cargar(dominio.ALIAS_PRODUCCION)
error_actual = entrenador.evaluar_en_ventana(pipeline_produccion, eventos)
print(f"produccion v{version_produccion.version}: baseline={error_baseline:.4f} "
      f"actual={error_actual:.4f} g/t (bootstrap={bootstrap})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. El trigger sobre los datos reales

# COMMAND ----------

decisor = DecisorReentrenamiento()
decision = decisor.decidir(globales, error_actual, error_baseline)
registro.registrar_evento(
    "monitoreo",
    decision.razones or ["sin disparo: PSI y error dentro de umbral"],
    {
        **{f"psi_{r.variable}": r.psi for r in globales},
        "error_actual_g_por_tonelada": error_actual,
        "error_baseline_g_por_tonelada": error_baseline or float("nan"),
    },
)
print(f"reentrenar: {decision.reentrenar}  razones: {list(decision.razones)}")

resolucion_real = None
if decision.reentrenar:
    candidato = entrenador.entrenar(eventos)
    version_staging = registro.registrar_entrenamiento(
        candidato, dominio.ALIAS_STAGING, "candidato_por_trigger")
    error_staging = candidato.metricas[dominio.METRICA_ERROR]
    resolucion_real = PromotorModelos(registro).resolver(
        version_staging, error_staging, error_actual, decision.razones)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Demo determinista de las dos ramas, en memoria y sobre un modelo `_demo`
# MAGIC
# MAGIC La deriva se fabrica multiplicando la vibración de la ventana evaluada por 1.4 (PSI
# MAGIC crítico) y la degradación desplazando la ley del histórico con que se entrena cada
# MAGIC candidato. Producción demo se entrena con historia contaminada (+3 g/t), el primer
# MAGIC candidato con una peor (+6, **rollback**) y el segundo con la historia limpia
# MAGIC (**promoción**). Todos se miden sobre la misma ventana limpia.

# COMMAND ----------

registro_demo = RegistroMlops(
    "databricks", "databricks-uc", f"{nombre_modelo}_demo", experimento)
promotor_demo = PromotorModelos(registro_demo)

corte = entrenador.particion(entrenador.matriz(eventos))[2]
es_historia = eventos[dominio.COLUMNA_TIEMPO].dt.date < corte


def _con_historia_desplazada(desplazamiento: float) -> pd.DataFrame:
    desplazado = eventos.copy()
    ley = desplazado[dominio.COLUMNA_LEY]
    desplazado.loc[es_historia & ley.notna(), dominio.COLUMNA_LEY] = (
        ley[es_historia & ley.notna()] + desplazamiento)
    return desplazado


# Deriva sintetica de vibracion: la ventana evaluada se multiplica por 1.4.
vib = eventos.loc[eventos[dominio.COLUMNA_VIBRACION].notna(),
                  [dominio.COLUMNA_TIEMPO, dominio.COLUMNA_VIBRACION]]
vib_ref = vib.loc[vib[dominio.COLUMNA_TIEMPO].dt.date < corte, dominio.COLUMNA_VIBRACION]
vib_eval = vib.loc[vib[dominio.COLUMNA_TIEMPO].dt.date >= corte, dominio.COLUMNA_VIBRACION]
psi_demo = CalculadorPsi().calcular(
    vib_ref.to_numpy(), vib_eval.to_numpy() * 1.4, dominio.COLUMNA_VIBRACION)
decision_demo = DecisorReentrenamiento().decidir([psi_demo], None, None)
print(f"PSI demo vibracion: {psi_demo.psi:.4f} ({psi_demo.veredicto}) -> "
      f"reentrenar={decision_demo.reentrenar}")

produccion_demo = registro_demo.registrar_entrenamiento(
    entrenador.entrenar(_con_historia_desplazada(3.0)), dominio.ALIAS_PRODUCCION,
    "demo_produccion_contaminada", etiquetas={"escenario": "demo"})
error_produccion_demo = entrenador.evaluar_en_ventana(
    registro_demo.cargar(dominio.ALIAS_PRODUCCION), eventos)

candidato_malo = entrenador.entrenar(_con_historia_desplazada(6.0))
version_malo = registro_demo.registrar_entrenamiento(
    candidato_malo, dominio.ALIAS_STAGING, "demo_candidato_peor",
    etiquetas={"escenario": "demo"})
error_malo = entrenador.evaluar_en_ventana(candidato_malo.pipeline, eventos)
resolucion_rollback = promotor_demo.resolver(
    version_malo, error_malo, error_produccion_demo, decision_demo.razones)

candidato_bueno = entrenador.entrenar(eventos)
version_bueno = registro_demo.registrar_entrenamiento(
    candidato_bueno, dominio.ALIAS_STAGING, "demo_candidato_limpio",
    etiquetas={"escenario": "demo"})
error_bueno = entrenador.evaluar_en_ventana(candidato_bueno.pipeline, eventos)
resolucion_promocion = promotor_demo.resolver(
    version_bueno, error_bueno, error_produccion_demo, decision_demo.razones)

vigente_demo = registro_demo.version_por_alias(dominio.ALIAS_PRODUCCION)
print(f"rollback: {resolucion_rollback} (staging {error_malo:.4f} vs "
      f"produccion {error_produccion_demo:.4f})")
print(f"promocion: {resolucion_promocion} -> produccion demo v{vigente_demo.version} "
      f"(staging {error_bueno:.4f})")
assert resolucion_rollback == "rollback" and resolucion_promocion == "promocion"

# COMMAND ----------

resumen = {
    "notebook": "04_mlops",
    "ventanas": {
        "referencia": [str(ventanas.referencia_desde), str(ventanas.referencia_hasta)],
        "evaluacion": [str(ventanas.evaluacion_desde), str(ventanas.evaluacion_hasta)],
    },
    "psi": [
        {"variable": r.variable, "ambito": r.ambito, "psi": round(r.psi, 4),
         "veredicto": r.veredicto, "n_referencia": r.n_referencia, "n_actual": r.n_actual}
        for r in resultados_psi
    ],
    "modelo": {
        "nombre": nombre_modelo, "version_produccion": version_produccion.version,
        "bootstrap": bootstrap, "error_baseline": error_baseline,
        "error_actual": error_actual,
    },
    "decision": {"reentrenar": decision.reentrenar, "razones": list(decision.razones),
                 "resolucion": resolucion_real},
    "demo": {
        "psi_vibracion": round(psi_demo.psi, 4),
        "razones": list(decision_demo.razones),
        "error_produccion_contaminada": error_produccion_demo,
        "rollback": {"resolucion": resolucion_rollback, "error_staging": error_malo},
        "promocion": {"resolucion": resolucion_promocion, "error_staging": error_bueno,
                      "version_final": vigente_demo.version},
    },
    "filas_monitor_deriva": spark.table(
        catalogo.tabla(dominio.ESQUEMA_DQ, dominio.TABLA_MONITOR_DERIVA)).count(),
}
print(json.dumps(resumen, indent=2, ensure_ascii=False, default=str))
dbutils.notebook.exit(json.dumps(resumen, ensure_ascii=False, default=str))
