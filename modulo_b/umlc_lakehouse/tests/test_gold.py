"""Pruebas del ciclo de gold: carga completa, Z-ORDER, e incremental via Change Data Feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.cdc import AplicadorReclasificacion
from umlc_lakehouse.errores import TablaInexistenteError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.gold import ActualizadorGold, celdas_de
from umlc_lakehouse.kpi import ConstructorKpiTurno
from umlc_lakehouse.limpieza import LimpiadorSilver, TablaSilver
from umlc_lakehouse.tests.conftest import FECHA_ANALISIS, fila, marco_bronze

T0 = datetime(2025, 11, 3, 10, 0, tzinfo=UTC)
CELDA_A = ("2025-08-10 15:00:00", "2025-08-10 15:30:00")
CELDA_B = ("2025-08-11 15:00:00",)


class Reloj:
    """Un reloj que avanza una hora por lectura, para distinguir corridas."""

    def __init__(self) -> None:
        self.lecturas = 0

    def __call__(self) -> datetime:
        """Una hora mas que la lectura anterior."""
        self.lecturas += 1
        return T0 + timedelta(hours=self.lecturas)


def _escribir_silver(spark: SparkSession, catalogo: Catalogo, tiempos: tuple[str, ...],
                     **cambios: object) -> None:
    limpiador = LimpiadorSilver()
    filas = [fila(t, **cambios) for t in tiempos]
    TablaSilver(spark, catalogo).escribir(
        limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas))))


def _actualizador(spark: SparkSession, catalogo: Catalogo, reloj: Reloj) -> ActualizadorGold:
    return ActualizadorGold(spark, catalogo, ConstructorKpiTurno(reloj=reloj))


def test_la_carga_completa_ordena_por_zorder_y_fija_la_version_de_silver(
        spark: SparkSession, catalogo: Catalogo) -> None:
    _escribir_silver(spark, catalogo, CELDA_A + CELDA_B)
    actualizador = _actualizador(spark, catalogo, Reloj())
    resumen = actualizador.actualizar()
    assert resumen.modo == "completo"
    assert (resumen.filas_gold, resumen.celdas_afectadas) == (2, 2)
    assert actualizador.version_procesada() == resumen.version_silver_hasta
    detalle = actualizador.detalle()
    assert detalle["partitionColumns"] == []
    assert detalle["filas"] == 2
    operaciones = [r["operation"] for r in spark.sql(
        f"DESCRIBE HISTORY {catalogo.aurum_kpi_turno}").collect()]
    assert "OPTIMIZE" in operaciones
    zorder = [r["operationParameters"] for r in spark.sql(
        f"DESCRIBE HISTORY {catalogo.aurum_kpi_turno}").collect() if r["operation"] == "OPTIMIZE"]
    assert "frente_id" in zorder[0]["zOrderBy"] and "fecha_local" in zorder[0]["zOrderBy"]


def test_sin_cambios_en_silver_gold_no_se_toca(spark: SparkSession, catalogo: Catalogo) -> None:
    _escribir_silver(spark, catalogo, CELDA_A)
    actualizador = _actualizador(spark, catalogo, Reloj())
    actualizador.actualizar()
    version_gold = spark.sql(f"DESCRIBE HISTORY {catalogo.aurum_kpi_turno}").count()
    resumen = actualizador.actualizar()
    assert resumen.modo == "sin_cambios"
    assert spark.sql(f"DESCRIBE HISTORY {catalogo.aurum_kpi_turno}").count() == version_gold


def test_una_reclasificacion_recalcula_solo_su_celda(
        spark: SparkSession, catalogo: Catalogo) -> None:
    _escribir_silver(spark, catalogo, CELDA_A + CELDA_B, ley_au_gpT=10.0, ton_rom_acum=100.0)
    reloj = Reloj()
    actualizador = _actualizador(spark, catalogo, reloj)
    actualizador.actualizar()
    antes = {r[dominio.COLUMNA_FECHA_LOCAL]: r.asDict()
             for r in spark.table(catalogo.aurum_kpi_turno).collect()}
    lote = spark.createDataFrame(
        [(datetime.strptime(CELDA_A[0], "%Y-%m-%d %H:%M:%S"), "FR-S2-03", "EST",
          FECHA_ANALISIS, "ALS", "M1")], EsquemaOpus.RECLASIFICACION)
    AplicadorReclasificacion(spark, catalogo).aplicar(lote, "R1")
    resumen = actualizador.actualizar()
    assert resumen.modo == "incremental"
    assert (resumen.celdas_afectadas, resumen.filas_actualizadas, resumen.filas_insertadas,
            resumen.filas_borradas) == (1, 1, 0, 0)
    despues = {r[dominio.COLUMNA_FECHA_LOCAL]: r.asDict()
               for r in spark.table(catalogo.aurum_kpi_turno).collect()}
    fecha_a, fecha_b = sorted(despues)
    assert despues[fecha_a]["n_reclasificados"] == 1
    assert despues[fecha_a]["prod_oz_recalculada"] < antes[fecha_a]["prod_oz_recalculada"]
    assert despues[fecha_a]["ts_calculo"] > antes[fecha_a]["ts_calculo"]
    assert despues[fecha_b] == antes[fecha_b]


def test_los_eventos_nuevos_insertan_celdas_y_los_borrados_las_quitan(
        spark: SparkSession, catalogo: Catalogo) -> None:
    _escribir_silver(spark, catalogo, CELDA_A)
    actualizador = _actualizador(spark, catalogo, Reloj())
    actualizador.actualizar()
    _escribir_silver(spark, catalogo, CELDA_B)
    insercion = actualizador.actualizar()
    assert (insercion.filas_insertadas, insercion.filas_actualizadas) == (1, 0)
    spark.sql(f"DELETE FROM {catalogo.opus_clean} WHERE {dominio.COLUMNA_FECHA_LOCAL} = "
              f"DATE'2025-08-11'")
    borrado = actualizador.actualizar()
    assert (borrado.filas_borradas, borrado.filas_gold) == (1, 1)
    celdas = celdas_de(spark.table(catalogo.opus_clean)).collect()
    assert len(celdas) == 1


def test_precondiciones_de_gold(spark: SparkSession, catalogo: Catalogo) -> None:
    actualizador = _actualizador(spark, catalogo, Reloj())
    assert actualizador.version_procesada() is None
    with pytest.raises(TablaInexistenteError):
        actualizador.construir_completo()
    with pytest.raises(TablaInexistenteError):
        actualizador.actualizar_incremental()
    _escribir_silver(spark, catalogo, CELDA_A)
    actualizador.actualizar()
    assert spark.table(catalogo.aurum_kpi_turno).filter(F.col("n_eventos") == 2).count() == 1
