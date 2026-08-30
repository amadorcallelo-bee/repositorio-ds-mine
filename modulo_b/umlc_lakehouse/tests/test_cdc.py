"""Pruebas del CDC de reclasificaciones: MERGE, idempotencia, rechazos y Change Data Feed."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.cdc import AplicadorReclasificacion
from umlc_lakehouse.errores import EsquemaInvalidoError, LoteVacioError, TablaInexistenteError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.limpieza import LimpiadorSilver, TablaSilver
from umlc_lakehouse.tests.conftest import FECHA_ANALISIS, fila, marco_bronze, reloj_fijo

MOMENTO = datetime(2025, 11, 3, 10, 0, tzinfo=UTC)
T1, T2, T3 = "2025-08-10 15:00:00", "2025-08-10 15:30:00", "2025-08-10 16:00:00"


def _ts(texto: str) -> datetime:
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")


def poblar_silver(spark: SparkSession, catalogo: Catalogo) -> None:
    filas = [
        fila(T1, tipo_mineral="SUL", prod_estimada_oz=10.0),
        fila(T2, tipo_mineral="SUL"),
        fila(T3, tipo_mineral="MIX"),
    ]
    limpiador = LimpiadorSilver()
    TablaSilver(spark, catalogo).escribir(
        limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas))))


def correcciones(spark: SparkSession, filas: list[tuple[Any, ...]]) -> DataFrame:
    return spark.createDataFrame(filas, EsquemaOpus.RECLASIFICACION)


def lote_mixto(spark: SparkSession) -> DataFrame:
    return correcciones(spark, [
        (_ts(T1), "FR-S2-03", "OX", FECHA_ANALISIS, "ALS", "M1"),
        (_ts(T2), "FR-S2-03", "SUL", FECHA_ANALISIS, "ALS", "M2"),
        (_ts("2025-08-10 15:00:30"), "FR-S2-03", "OX", FECHA_ANALISIS, "ALS", "M3"),
        (_ts(T3), "FR-S2-03", "XX", FECHA_ANALISIS, "ALS", "M4"),
    ])


def test_el_merge_actualiza_solo_lo_que_cambia_y_reporta_el_resto(
        spark: SparkSession, catalogo: Catalogo) -> None:
    poblar_silver(spark, catalogo)
    aplicador = AplicadorReclasificacion(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    resumen = aplicador.aplicar(lote_mixto(spark), "R1")
    assert (resumen.recibidas, resumen.invalidas, resumen.no_encontradas) == (4, 1, 1)
    assert (resumen.actualizadas, resumen.sin_cambio) == (1, 1)
    assert resumen.claves_no_encontradas == ("2025-08-10 15:00:30|FR-S2-03",)
    corregida = spark.table(catalogo.opus_clean).filter(
        F.col(dominio.COLUMNA_TIEMPO) == F.lit(_ts(T1))).first()
    assert corregida is not None
    assert corregida[dominio.COLUMNA_TIPO_MINERAL] == "OX"
    assert corregida[dominio.COLUMNA_FUENTE_TIPO] == dominio.FUENTE_LAB
    assert corregida[dominio.COLUMNA_FECHA_CORRECCION] == date(2025, 9, 28)
    assert corregida[dominio.COLUMNA_LOTE_CORRECCION] == "R1"
    assert corregida[dominio.COLUMNA_PRODUCCION] == 10.0
    intacta = spark.table(catalogo.opus_clean).filter(
        F.col(dominio.COLUMNA_TIEMPO) == F.lit(_ts(T2))).first()
    assert intacta is not None
    assert intacta[dominio.COLUMNA_FUENTE_TIPO] == dominio.FUENTE_OPUS


def test_reenviar_el_mismo_lote_no_escribe_nada(spark: SparkSession, catalogo: Catalogo) -> None:
    poblar_silver(spark, catalogo)
    aplicador = AplicadorReclasificacion(spark, catalogo)
    primero = aplicador.aplicar(lote_mixto(spark), "R1")
    segundo = aplicador.aplicar(lote_mixto(spark), "R1-bis")
    assert primero.actualizadas == 1
    assert (segundo.actualizadas, segundo.sin_cambio) == (0, 2)


def test_con_claves_repetidas_gana_el_analisis_mas_reciente(
        spark: SparkSession, catalogo: Catalogo) -> None:
    poblar_silver(spark, catalogo)
    lote = correcciones(spark, [
        (_ts(T1), "FR-S2-03", "OX", date(2025, 9, 1), "ALS", "M1"),
        (_ts(T1), "FR-S2-03", "EST", date(2025, 9, 20), "ALS", "M2"),
    ])
    resumen = AplicadorReclasificacion(spark, catalogo).aplicar(lote, "R2")
    assert resumen.actualizadas == 1
    fila_ = spark.table(catalogo.opus_clean).filter(
        F.col(dominio.COLUMNA_TIEMPO) == F.lit(_ts(T1))).first()
    assert fila_ is not None
    assert fila_[dominio.COLUMNA_TIPO_MINERAL] == "EST"


def test_el_reporte_lleva_las_cuatro_cuentas_y_las_claves_sin_evento(
        spark: SparkSession, catalogo: Catalogo) -> None:
    poblar_silver(spark, catalogo)
    aplicador = AplicadorReclasificacion(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    reporte = aplicador.reporte(aplicador.aplicar(lote_mixto(spark), "R1"))
    filas = {r["regla"]: r for r in reporte.collect()}
    assert filas["reclasificacion_sin_evento"]["filas_falla"] == 1
    assert filas["reclasificacion_sin_evento"]["detalle"] == "2025-08-10 15:00:30|FR-S2-03"
    assert filas["reclasificacion_aplicada"]["filas_falla"] == 1
    assert filas["reclasificacion_invalida"]["pct_falla"] == 25.0
    assert all(r["filas_evaluadas"] == 4 for r in filas.values())


def test_el_change_data_feed_registra_la_correccion(
        spark: SparkSession, catalogo: Catalogo) -> None:
    poblar_silver(spark, catalogo)
    resumen = AplicadorReclasificacion(spark, catalogo).aplicar(lote_mixto(spark), "R1")
    cambios = (
        spark.read.format("delta").option("readChangeFeed", "true")
        .option("startingVersion", resumen.version_silver).table(catalogo.opus_clean)
    )
    tipos = {r["_change_type"]: r[dominio.COLUMNA_TIPO_MINERAL] for r in cambios.collect()}
    assert tipos == {"update_preimage": "SUL", "update_postimage": "OX"}


def test_precondiciones_del_aplicador(spark: SparkSession, catalogo: Catalogo) -> None:
    aplicador = AplicadorReclasificacion(spark, catalogo)
    with pytest.raises(TablaInexistenteError):
        aplicador.aplicar(lote_mixto(spark), "R1")
    poblar_silver(spark, catalogo)
    with pytest.raises(LoteVacioError):
        aplicador.aplicar(lote_mixto(spark).filter(F.lit(False)), "R1")
    with pytest.raises(LoteVacioError):
        aplicador.aplicar(lote_mixto(spark), "")
    with pytest.raises(EsquemaInvalidoError):
        aplicador.aplicar(lote_mixto(spark).drop(dominio.COLUMNA_MUESTRA), "R1")
