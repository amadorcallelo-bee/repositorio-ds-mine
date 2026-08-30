"""Ciclo de vida de `gold.aurum_kpi_turno`: construccion completa y actualizacion incremental.

La primera carga agrega toda la silver; las siguientes leen el Change Data Feed de silver
desde la ultima version incorporada, identifican las celdas `(frente, fecha, turno)` que
esas filas tocan, las recalculan desde la silver vigente y las funden en gold con un
`MERGE`. Es lo que hace incremental al CDC: una reclasificacion de 40 eventos reescribe
las celdas de esos eventos, no la tabla.

Gold no se particiona: son unas cuatro mil filas por anio y una particion las convertiria
en archivos de kilobytes. Se ordena con `OPTIMIZE ... ZORDER BY (frente_id, fecha_local)`
porque las consultas del B-2 filtran por las dos dimensiones a la vez. A esta escala el
beneficio es nulo y se declara asi; el argumento es para el volumen de produccion.

La version de silver ya incorporada se guarda como propiedad de la tabla gold, para no
tener una tabla de control aparte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import TablaInexistenteError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import metricas_desde, version_actual
from umlc_lakehouse.kpi import ConstructorKpiTurno

logger = logging.getLogger(__name__)

Modo = Literal["completo", "incremental", "sin_cambios"]


@dataclass(frozen=True)
class ResumenGold:
    """Lo que una corrida dejo en gold."""

    modo: Modo
    version_silver_desde: int | None
    version_silver_hasta: int
    celdas_afectadas: int
    filas_insertadas: int
    filas_actualizadas: int
    filas_borradas: int
    filas_gold: int


class ActualizadorGold:
    """Construye o actualiza gold desde silver, segun exista o no."""

    def __init__(
        self, spark: SparkSession, catalogo: Catalogo, constructor: ConstructorKpiTurno
    ) -> None:
        self.spark = spark
        self.catalogo = catalogo
        self.constructor = constructor

    def existe(self) -> bool:
        """Si gold ya fue construida alguna vez."""
        return bool(self.spark.catalog.tableExists(self.catalogo.aurum_kpi_turno))

    def version_procesada(self) -> int | None:
        """La ultima version de silver incorporada, o `None` si gold no existe."""
        if not self.existe():
            return None
        filas = self.spark.sql(
            f"SHOW TBLPROPERTIES {self.catalogo.aurum_kpi_turno}"
            f" ('{dominio.PROPIEDAD_VERSION_SILVER}')"
        ).collect()
        valor = str(filas[0]["value"]) if filas else ""
        return int(valor) if valor.isdigit() else None

    def _silver_en(self, version: int) -> DataFrame:
        return (
            self.spark.read.format("delta").option("versionAsOf", version)
            .table(self.catalogo.opus_clean)
        )

    def _cerrar(self, version: int) -> None:
        self.spark.sql(
            f"ALTER TABLE {self.catalogo.aurum_kpi_turno} SET TBLPROPERTIES "
            f"('{dominio.PROPIEDAD_VERSION_SILVER}' = '{version}')"
        )
        columnas = ", ".join(dominio.COLUMNAS_ZORDER_GOLD)
        self.spark.sql(f"OPTIMIZE {self.catalogo.aurum_kpi_turno} ZORDER BY ({columnas})")

    def construir_completo(self) -> ResumenGold:
        """Agrega toda la silver en una version fija y la escribe como gold."""
        if not self.spark.catalog.tableExists(self.catalogo.opus_clean):
            raise TablaInexistenteError(self.catalogo.opus_clean)
        version = version_actual(self.spark, self.catalogo.opus_clean)
        kpi = self.constructor.construir(self._silver_en(version))
        self.spark.sql(
            f"CREATE TABLE IF NOT EXISTS {self.catalogo.aurum_kpi_turno} "
            f"({EsquemaOpus.ddl(kpi.schema)}) USING DELTA"
        )
        kpi.write.format("delta").mode("overwrite").saveAsTable(self.catalogo.aurum_kpi_turno)
        filas = self.spark.table(self.catalogo.aurum_kpi_turno).count()
        self._cerrar(version)
        logger.info("gold completo version_silver=%d filas=%d", version, filas)
        return ResumenGold(
            modo="completo", version_silver_desde=None, version_silver_hasta=version,
            celdas_afectadas=filas, filas_insertadas=filas, filas_actualizadas=0,
            filas_borradas=0, filas_gold=filas,
        )

    def celdas_afectadas(self, desde: int, hasta: int) -> DataFrame:
        """Las celdas de gold tocadas por los cambios de silver en `(desde, hasta]`."""
        cambios = (
            self.spark.read.format("delta").option("readChangeFeed", "true")
            .option("startingVersion", desde + 1).option("endingVersion", hasta)
            .table(self.catalogo.opus_clean)
        )
        return cambios.select(*dominio.CLAVE_TURNO).distinct()

    def actualizar_incremental(self) -> ResumenGold:
        """Recalcula solo las celdas afectadas desde la ultima version incorporada."""
        desde = self.version_procesada()
        if desde is None:
            raise TablaInexistenteError(self.catalogo.aurum_kpi_turno)
        hasta = version_actual(self.spark, self.catalogo.opus_clean)
        filas_gold = self.spark.table(self.catalogo.aurum_kpi_turno).count()
        if hasta <= desde:
            return ResumenGold(
                modo="sin_cambios", version_silver_desde=desde, version_silver_hasta=hasta,
                celdas_afectadas=0, filas_insertadas=0, filas_actualizadas=0,
                filas_borradas=0, filas_gold=filas_gold,
            )
        celdas = self.celdas_afectadas(desde, hasta)
        eventos = self._silver_en(hasta).join(celdas, list(dominio.CLAVE_TURNO), "inner")
        recalculado = self.constructor.construir(eventos)
        fuente = celdas.join(recalculado, list(dominio.CLAVE_TURNO), "left")
        condicion = " AND ".join(f"t.{c} = s.{c}" for c in dominio.CLAVE_TURNO)
        version_previa = version_actual(self.spark, self.catalogo.aurum_kpi_turno)
        (
            DeltaTable.forName(self.spark, self.catalogo.aurum_kpi_turno).alias("t")
            .merge(fuente.alias("s"), condicion)
            .whenMatchedDelete(condition="s.n_eventos IS NULL")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll(condition="s.n_eventos IS NOT NULL")
            .execute()
        )
        metricas = metricas_desde(self.spark, self.catalogo.aurum_kpi_turno, version_previa)
        self._cerrar(hasta)
        resumen = ResumenGold(
            modo="incremental", version_silver_desde=desde, version_silver_hasta=hasta,
            celdas_afectadas=celdas.count(),
            filas_insertadas=metricas.get("numTargetRowsInserted", 0),
            filas_actualizadas=metricas.get("numTargetRowsUpdated", 0),
            filas_borradas=metricas.get("numTargetRowsDeleted", 0),
            filas_gold=self.spark.table(self.catalogo.aurum_kpi_turno).count(),
        )
        logger.info("gold incremental %s", resumen)
        return resumen

    def actualizar(self) -> ResumenGold:
        """Construccion completa la primera vez, incremental despues."""
        if self.version_procesada() is None:
            return self.construir_completo()
        return self.actualizar_incremental()

    def detalle(self) -> dict[str, object]:
        """`DESCRIBE DETAIL` de gold, para documentar particion y archivos con cifras reales."""
        fila = self.spark.sql(f"DESCRIBE DETAIL {self.catalogo.aurum_kpi_turno}").first()
        if fila is None:
            raise TablaInexistenteError(self.catalogo.aurum_kpi_turno)
        return {
            "partitionColumns": list(fila["partitionColumns"]),
            "numFiles": int(fila["numFiles"]),
            "sizeInBytes": int(fila["sizeInBytes"]),
            "filas": self.spark.table(self.catalogo.aurum_kpi_turno).count(),
        }


def celdas_de(df: DataFrame) -> DataFrame:
    """Las celdas de gold presentes en un marco de silver; util para las pruebas."""
    return df.select(*dominio.CLAVE_TURNO).distinct().orderBy(*dominio.CLAVE_TURNO)

