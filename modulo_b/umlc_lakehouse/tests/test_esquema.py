"""Pruebas del esquema explicito: el enunciado prohibe la inferencia y aqui se comprueba."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, StringType, TimestampType

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import EsquemaInvalidoError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.tests.conftest import fila, marco_bronze

ENCABEZADO = ",".join(dominio.COLUMNAS_EXTRACTO)


def test_el_extracto_tiene_las_18_columnas_en_orden_y_con_tipo() -> None:
    nombres = [f.name for f in EsquemaOpus.EXTRACTO.fields]
    assert tuple(nombres) == dominio.COLUMNAS_EXTRACTO
    tipos = {f.name: f.dataType for f in EsquemaOpus.EXTRACTO.fields}
    assert tipos[dominio.COLUMNA_TIEMPO] == TimestampType()
    assert tipos[dominio.COLUMNA_RPM] == IntegerType()
    assert tipos[dominio.COLUMNA_MANTENIMIENTO] == IntegerType()
    assert tipos[dominio.COLUMNA_LEY] == DoubleType()
    assert tipos[dominio.COLUMNA_FALLA] == StringType()


def test_bronze_agrega_la_metadata_al_final() -> None:
    nombres = [f.name for f in EsquemaOpus.bronze().fields]
    assert nombres[:18] == list(dominio.COLUMNAS_EXTRACTO)
    assert nombres[18:] == [
        dominio.COLUMNA_RESCATE, dominio.COLUMNA_ARCHIVO_FUENTE, dominio.COLUMNA_TS_INGESTA,
        dominio.COLUMNA_FECHA_INGESTA, dominio.COLUMNA_LOTE,
    ]


def test_verificar_acepta_el_esquema_exacto(spark: SparkSession) -> None:
    EsquemaOpus.verificar(marco_bronze(spark, [fila("2025-01-01 10:00:00")]),
                          EsquemaOpus.bronze(), "prueba")


def test_verificar_reporta_faltantes_sobrantes_y_tipos(spark: SparkSession) -> None:
    marco = marco_bronze(spark, [fila("2025-01-01 10:00:00")])
    con_extra = marco.withColumn("extra", F.lit(1))
    with pytest.raises(EsquemaInvalidoError, match="sobra la columna extra"):
        EsquemaOpus.verificar(con_extra, EsquemaOpus.bronze(), "prueba")
    sin_ley = marco.drop(dominio.COLUMNA_LEY)
    with pytest.raises(EsquemaInvalidoError, match="falta la columna ley_au_gpT"):
        EsquemaOpus.verificar(sin_ley, EsquemaOpus.bronze(), "prueba")
    otro_tipo = marco.withColumn(dominio.COLUMNA_RPM, F.col(dominio.COLUMNA_RPM).cast("string"))
    with pytest.raises(EsquemaInvalidoError, match="rpm_corona es string y se esperaba int"):
        EsquemaOpus.verificar(otro_tipo, EsquemaOpus.bronze(), "prueba")


def test_el_ddl_declara_cada_columna_con_su_tipo() -> None:
    ddl = EsquemaOpus.ddl(EsquemaOpus.EXTRACTO)
    assert "`ts_opus_utc` timestamp" in ddl
    assert "`rpm_corona` int" in ddl
    assert ddl.count(",") == 17


def test_leer_csv_no_infiere_y_rescata_lo_que_no_encaja(
        spark: SparkSession, tmp_path: Path) -> None:
    resto = "1.8,45,5,75,OP-1,EQ-1,,23.4,SUL,Veta-Sur,0"
    buena = f"2025-01-01 10:00:00,FR-S2-03,D1,8.1,100,210,1100,{resto}"
    mala = f"2025-01-01 10:30:00,FR-S2-03,D1,8.1,100,210,abc,{resto}"
    archivo = tmp_path / "lote.csv"
    archivo.write_text("\n".join([ENCABEZADO, buena, mala]) + "\n")
    marco = EsquemaOpus.leer_csv(spark, str(archivo), EsquemaOpus.EXTRACTO)
    filas = {r[dominio.COLUMNA_TIEMPO].minute: r for r in marco.collect()}
    assert filas[0][dominio.COLUMNA_RPM] == 1100
    assert filas[0][dominio.COLUMNA_RESCATE] is None
    assert filas[30][dominio.COLUMNA_RPM] is None
    assert filas[30][dominio.COLUMNA_RESCATE] == mala
    assert all(r[dominio.COLUMNA_ARCHIVO_FUENTE].endswith("lote.csv") for r in filas.values())
    assert filas[0][dominio.COLUMNA_FALLA] is None
