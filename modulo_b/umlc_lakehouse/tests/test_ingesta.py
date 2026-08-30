"""Pruebas de bronze: metadata de ingesta, particion y fidelidad."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import EsquemaInvalidoError, LoteVacioError
from umlc_lakehouse.ingesta import IngestorBronze
from umlc_lakehouse.tests.conftest import fila, marco_extracto, reloj_fijo

MOMENTO = datetime(2025, 11, 2, 15, 30, tzinfo=UTC)


def test_el_lote_queda_con_archivo_timestamp_y_conteo(
        spark: SparkSession, catalogo: Catalogo) -> None:
    ingestor = IngestorBronze(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    filas = [
        fila("2025-01-01 10:00:00", archivo_fuente="a.csv"),
        fila("2025-01-01 10:30:00", archivo_fuente="a.csv"),
        fila("2025-01-01 11:00:00", archivo_fuente="b.csv"),
    ]
    resumen = ingestor.procesar_lote(marco_extracto(spark, filas), "L1")
    assert resumen.filas == 3
    assert resumen.version_bronze == 1
    assert resumen.ts_ingesta == MOMENTO.replace(tzinfo=None) or resumen.ts_ingesta == MOMENTO
    assert [(a.archivo_fuente, a.filas) for a in resumen.archivos] == [("a.csv", 2), ("b.csv", 1)]
    bronze = spark.table(catalogo.opus_raw)
    assert bronze.count() == 3
    fechas = {r[0] for r in bronze.select(dominio.COLUMNA_FECHA_INGESTA).distinct().collect()}
    assert fechas == {MOMENTO.date()}
    log = spark.table(catalogo.ingesta_log).orderBy(dominio.COLUMNA_ARCHIVO_FUENTE).collect()
    assert [(r[dominio.COLUMNA_ARCHIVO_FUENTE], r["filas"], r["version_bronze"]) for r in log] == [
        ("a.csv", 2, 1), ("b.csv", 1, 1),
    ]


def test_bronze_se_particiona_por_fecha_de_ingesta(
        spark: SparkSession, catalogo: Catalogo) -> None:
    IngestorBronze(spark, catalogo).crear_tablas()
    detalle = spark.sql(f"DESCRIBE DETAIL {catalogo.opus_raw}").first()
    assert detalle is not None
    assert list(detalle["partitionColumns"]) == [dominio.COLUMNA_FECHA_INGESTA]


def test_bronze_conserva_el_dato_aunque_se_reenvie(
        spark: SparkSession, catalogo: Catalogo) -> None:
    """Bronze no deduplica: la fidelidad al origen es su razon de ser. Dedup es de silver."""
    ingestor = IngestorBronze(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    marco = marco_extracto(spark, [fila("2025-01-01 10:00:00")])
    primero = ingestor.procesar_lote(marco, "L1")
    segundo = ingestor.procesar_lote(marco, "L2")
    assert (primero.version_bronze, segundo.version_bronze) == (1, 2)
    assert spark.table(catalogo.opus_raw).count() == 2
    lotes = {r[0] for r in spark.table(catalogo.opus_raw).select(dominio.COLUMNA_LOTE).collect()}
    assert lotes == {"L1", "L2"}


def test_un_lote_vacio_o_sin_identificador_falla(spark: SparkSession, catalogo: Catalogo) -> None:
    ingestor = IngestorBronze(spark, catalogo)
    vacio = marco_extracto(spark, [fila("2025-01-01 10:00:00")]).filter(F.lit(False))
    with pytest.raises(LoteVacioError):
        ingestor.procesar_lote(vacio, "L1")
    with pytest.raises(LoteVacioError):
        ingestor.procesar_lote(marco_extracto(spark, [fila("2025-01-01 10:00:00")]), "")


def test_un_esquema_distinto_al_declarado_se_rechaza(
        spark: SparkSession, catalogo: Catalogo) -> None:
    ingestor = IngestorBronze(spark, catalogo)
    marco = marco_extracto(spark, [fila("2025-01-01 10:00:00")]).withColumn("nueva", F.lit(1))
    with pytest.raises(EsquemaInvalidoError, match="sobra la columna nueva"):
        ingestor.procesar_lote(marco, "L1")


def test_preparar_tolera_un_marco_sin_columna_de_rescate(
        spark: SparkSession, catalogo: Catalogo) -> None:
    """Auto Loader solo agrega `_rescued_data` si la activa; la tabla la tiene siempre."""
    ingestor = IngestorBronze(spark, catalogo)
    marco = marco_extracto(spark, [fila("2025-01-01 10:00:00")]).drop(dominio.COLUMNA_RESCATE)
    preparado = ingestor.preparar(marco, "L1", MOMENTO)
    assert dominio.COLUMNA_RESCATE in preparado.columns
    assert preparado.first() is not None


def test_registrar_archivos_deja_el_lote_en_el_log_sin_tocar_bronze(
        spark: SparkSession, catalogo: Catalogo) -> None:
    ingestor = IngestorBronze(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    marco = marco_extracto(spark, [
        fila("2025-01-01 10:00:00", archivo_fuente="r1.csv"),
        fila("2025-01-01 10:30:00", archivo_fuente="r1.csv"),
    ])
    assert ingestor.registrar_archivos(marco, "R1") == 1
    [r] = spark.table(catalogo.ingesta_log).collect()
    assert (r[dominio.COLUMNA_LOTE], r[dominio.COLUMNA_ARCHIVO_FUENTE], r["filas"]) == (
        "R1", "r1.csv", 2)
    assert r["version_bronze"] is None
    assert spark.table(catalogo.opus_raw).count() == 0
    with pytest.raises(LoteVacioError):
        ingestor.registrar_archivos(marco, "")


def test_registrar_pendientes_completa_el_log_una_sola_vez(
        spark: SparkSession, catalogo: Catalogo) -> None:
    """Es el paso posterior a Auto Loader: bronze ya tiene filas y el log todavia no."""
    ingestor = IngestorBronze(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    ingestor.crear_tablas()
    marco = marco_extracto(spark, [
        fila("2025-01-01 10:00:00", archivo_fuente="dbfs:/landing/opus/01_2025-08.csv"),
        fila("2025-01-01 10:30:00", archivo_fuente="dbfs:/landing/opus/01_2025-08.csv"),
        fila("2025-01-01 11:00:00", archivo_fuente="dbfs:/landing/opus/02_2025-09.csv"),
    ])
    enriquecido = ingestor.enriquecer(
        marco, IngestorBronze.lote_desde_archivo(F.col(dominio.COLUMNA_ARCHIVO_FUENTE)),
        F.lit(MOMENTO))
    enriquecido.write.format("delta").mode("append").saveAsTable(catalogo.opus_raw)
    resumenes = ingestor.registrar_pendientes()
    assert [(r.lote_id, r.filas, len(r.archivos)) for r in resumenes] == [
        ("01_2025-08", 2, 1), ("02_2025-09", 1, 1)]
    assert all(r.version_bronze == 1 for r in resumenes)
    assert ingestor.registrar_pendientes() == ()
    assert spark.table(catalogo.ingesta_log).count() == 2


def test_archivos_pendientes_compara_por_nombre(spark: SparkSession, catalogo: Catalogo) -> None:
    ingestor = IngestorBronze(spark, catalogo)
    marco = marco_extracto(spark, [
        fila("2025-01-01 10:00:00", archivo_fuente="/Volumes/x/landing/r1.csv")])
    ingestor.registrar_archivos(marco, "r1")
    pendientes = ingestor.archivos_pendientes(
        ["dbfs:/Volumes/x/landing/r1.csv", "dbfs:/Volumes/x/landing/r2.csv"])
    assert pendientes == ["dbfs:/Volumes/x/landing/r2.csv"]
    assert IngestorBronze.nombre_de("dbfs:/a/b/03_x.csv") == "03_x"
    assert IngestorBronze.nombre_de("dbfs:/a/b/04_X.CSV") == "04_X"
    assert IngestorBronze.nombre_de("sin_extension") == "sin_extension"
    [r] = spark.createDataFrame([("s3://l/opus/05_2025-11.CSV",)], ["a"]).select(
        IngestorBronze.lote_desde_archivo(F.col("a")).alias("lote")).collect()
    assert r["lote"] == "05_2025-11"
