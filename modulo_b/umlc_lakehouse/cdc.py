"""CDC de las reclasificaciones del laboratorio sobre silver.

El laboratorio reclasifica `tipo_mineral` de eventos pasados y el cambio se aplica con un
`MERGE` sobre `silver.opus_clean` por la clave natural del evento. Las decisiones:

- **Solo se actualiza lo que cambia.** `WHEN MATCHED AND t.tipo_mineral <> s.tipo_mineral_lab`:
  reenviar un lote ya aplicado no produce escrituras, y el Change Data Feed no arrastra
  cambios vacios a gold.
- **Una correccion sin evento no se inserta.** Corregir lo que no existe es un error del
  laboratorio o de la clave, y se cuenta y se detalla en el reporte de calidad; un
  `WHEN NOT MATCHED INSERT` fabricaria un evento sin sensores.
- **Bronze no se toca.** Bronze conserva lo que OPUS dijo; la correccion queda en silver
  con su fuente, fecha y lote, de modo que la fila sigue diciendo de donde salio su tipo.
- **`prod_estimada_oz` no se reescribe.** Es un calculo de OPUS con el factor del tipo
  viejo; gold la recalcula con el nuevo (`prod_oz_recalculada`) y conserva la original.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.calidad import CAPA_SILVER_CDC, ReporteCalidad
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import LoteVacioError, TablaInexistenteError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import ahora_utc, metricas_desde, version_actual

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumenReclasificacion:
    """Lo que un lote de correcciones hizo, y lo que no pudo hacer."""

    lote_id: str
    recibidas: int
    invalidas: int
    no_encontradas: int
    actualizadas: int
    sin_cambio: int
    version_silver: int
    claves_no_encontradas: tuple[str, ...]


class AplicadorReclasificacion:
    """Aplica un lote de reclasificaciones a silver y produce su reporte."""

    MAXIMO_CLAVES_DETALLE: Final[int] = 10

    def __init__(
        self,
        spark: SparkSession,
        catalogo: Catalogo,
        reloj: Callable[[], datetime] = ahora_utc,
    ) -> None:
        self.spark = spark
        self.catalogo = catalogo
        self.reloj = reloj

    def aplicar(self, correcciones: DataFrame, lote_id: str) -> ResumenReclasificacion:
        """Valida, deduplica y funde el lote en silver."""
        if not lote_id:
            raise LoteVacioError(lote_id)
        if not self.spark.catalog.tableExists(self.catalogo.opus_clean):
            raise TablaInexistenteError(self.catalogo.opus_clean)
        sin_rescate = correcciones.drop(dominio.COLUMNA_RESCATE, dominio.COLUMNA_ARCHIVO_FUENTE)
        EsquemaOpus.verificar(
            sin_rescate, EsquemaOpus.RECLASIFICACION, f"reclasificacion, lote {lote_id}"
        )
        recibidas = sin_rescate.count()
        if recibidas == 0:
            raise LoteVacioError(lote_id)
        es_valida = (
            F.col(dominio.COLUMNA_TIPO_LAB).isin(list(dominio.TIPOS_MINERAL))
            & F.col(dominio.COLUMNA_TIEMPO).isNotNull()
            & F.col(dominio.COLUMNA_FRENTE).isNotNull()
        )
        validas = sin_rescate.filter(es_valida)
        invalidas = recibidas - validas.count()
        ventana = Window.partitionBy(*dominio.CLAVE_EVENTO).orderBy(
            F.col(dominio.COLUMNA_FECHA_ANALISIS).desc_nulls_last(),
            F.col(dominio.COLUMNA_MUESTRA).desc_nulls_last(),
        )
        ultimas = (
            validas.withColumn("_n", F.row_number().over(ventana))
            .filter(F.col("_n") == 1).drop("_n")
        )
        claves_silver = self.spark.table(self.catalogo.opus_clean).select(*dominio.CLAVE_EVENTO)
        no_encontradas = ultimas.join(claves_silver, list(dominio.CLAVE_EVENTO), "left_anti")
        claves = tuple(
            f"{f[dominio.COLUMNA_TIEMPO]:%Y-%m-%d %H:%M:%S}|{f[dominio.COLUMNA_FRENTE]}"
            for f in no_encontradas.orderBy(*dominio.CLAVE_EVENTO)
            .limit(self.MAXIMO_CLAVES_DETALLE).collect()
        )
        n_no_encontradas = no_encontradas.count()
        encontradas = ultimas.join(claves_silver, list(dominio.CLAVE_EVENTO), "left_semi")
        n_encontradas = encontradas.count()
        condicion = " AND ".join(f"t.{c} = s.{c}" for c in dominio.CLAVE_EVENTO)
        version_previa = version_actual(self.spark, self.catalogo.opus_clean)
        (
            DeltaTable.forName(self.spark, self.catalogo.opus_clean).alias("t")
            .merge(encontradas.alias("s"), condicion)
            .whenMatchedUpdate(
                condition=f"t.{dominio.COLUMNA_TIPO_MINERAL} <> s.{dominio.COLUMNA_TIPO_LAB}",
                set={
                    dominio.COLUMNA_TIPO_MINERAL: f"s.{dominio.COLUMNA_TIPO_LAB}",
                    dominio.COLUMNA_FUENTE_TIPO: F.lit(dominio.FUENTE_LAB),
                    dominio.COLUMNA_FECHA_CORRECCION: f"s.{dominio.COLUMNA_FECHA_ANALISIS}",
                    dominio.COLUMNA_LOTE_CORRECCION: F.lit(lote_id),
                },
            )
            .execute()
        )
        metricas = metricas_desde(self.spark, self.catalogo.opus_clean, version_previa)
        actualizadas = metricas.get("numTargetRowsUpdated", 0)
        resumen = ResumenReclasificacion(
            lote_id=lote_id, recibidas=recibidas, invalidas=invalidas,
            no_encontradas=n_no_encontradas, actualizadas=actualizadas,
            sin_cambio=n_encontradas - actualizadas,
            version_silver=version_actual(self.spark, self.catalogo.opus_clean),
            claves_no_encontradas=claves,
        )
        logger.info("cdc %s", resumen)
        return resumen

    def reporte(self, resumen: ResumenReclasificacion) -> DataFrame:
        """El resumen como filas del reporte de calidad, con las claves no encontradas."""
        ts = self.reloj()
        detalle = ", ".join(resumen.claves_no_encontradas) or None
        filas = [
            ("reclasificacion_invalida", "rechaza",
             "tipo_mineral_lab fuera de dominio o clave incompleta", resumen.invalidas, None),
            ("reclasificacion_sin_evento", "rechaza",
             "clave (ts_opus_utc, frente_id) que no existe en silver",
             resumen.no_encontradas, detalle),
            ("reclasificacion_sin_cambio", "informa",
             "el tipo recibido ya era el vigente", resumen.sin_cambio, None),
            ("reclasificacion_aplicada", "informa",
             "tipo_mineral actualizado con fuente LAB", resumen.actualizadas, None),
        ]
        datos = [
            (resumen.lote_id, CAPA_SILVER_CDC, nombre, severidad, descripcion,
             resumen.recibidas, cantidad,
             round(cantidad * 100.0 / resumen.recibidas, 4) if resumen.recibidas else 0.0,
             det, ts)
            for nombre, severidad, descripcion, cantidad, det in filas
        ]
        return self.spark.createDataFrame(datos, ReporteCalidad.ESQUEMA)
