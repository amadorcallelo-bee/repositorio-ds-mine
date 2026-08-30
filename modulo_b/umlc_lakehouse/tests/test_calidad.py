"""Pruebas del reporte de calidad por lote."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.calidad import CAPA_SILVER, ReglaCalidad, ReporteCalidad, reglas_silver
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import EsquemaInvalidoError, ParametroInvalidoError
from umlc_lakehouse.limpieza import LimpiadorSilver
from umlc_lakehouse.tests.conftest import fila, marco_bronze, reloj_fijo

MOMENTO = datetime(2025, 11, 3, 8, 0, tzinfo=UTC)


def test_las_reglas_de_silver_tienen_nombres_unicos_y_las_tres_severidades() -> None:
    reglas = reglas_silver()
    nombres = [r.nombre for r in reglas]
    assert len(nombres) == len(set(nombres)) == 15
    assert {r.severidad for r in reglas} == {"rechaza", "marca", "informa"}


def test_el_reporte_cuenta_por_lote_y_por_regla(spark: SparkSession) -> None:
    filas = [
        fila("2025-03-10 12:00:00", ley_au_gpT=-1.0, lote_id="L1"),
        fila("2025-03-10 12:30:00", lote_id="L1"),
        fila("2025-03-10 13:00:00", vibracion_rms_ms2=14.0, lote_id="L2"),
        fila("2025-03-10 13:00:00", vibracion_rms_ms2=14.0, lote_id="L2"),
    ]
    enriquecido = LimpiadorSilver().enriquecer(marco_bronze(spark, filas))
    reporte = ReporteCalidad(reglas_silver(), reloj=reloj_fijo(MOMENTO)).evaluar(
        enriquecido, CAPA_SILVER)
    assert reporte.count() == 2 * 15
    por_clave = {
        (r[dominio.COLUMNA_LOTE], r["regla"]): (
            r["filas_evaluadas"], r["filas_falla"], r["pct_falla"])
        for r in reporte.collect()
    }
    assert por_clave[("L1", "ley_centinela")] == (2, 1, 50.0)
    assert por_clave[("L2", "ley_centinela")] == (2, 0, 0.0)
    assert por_clave[("L2", "alerta_vibracion")] == (2, 2, 100.0)
    assert por_clave[("L2", "duplicado_en_lote")] == (2, 1, 50.0)
    assert {r["capa"] for r in reporte.collect()} == {CAPA_SILVER}


def test_un_marco_vacio_no_produce_filas(spark: SparkSession) -> None:
    vacio = LimpiadorSilver().enriquecer(marco_bronze(spark, [fila("2025-03-10 12:00:00")]))
    reporte = ReporteCalidad(reglas_silver()).evaluar(vacio.filter(F.lit(False)), CAPA_SILVER)
    assert reporte.count() == 0


def test_una_regla_con_nulos_no_cuenta_el_nulo_como_falla(spark: SparkSession) -> None:
    regla = ReglaCalidad("nula", "col nula", "informa", lambda: F.col("x") > 1)
    marco = spark.createDataFrame([(None, "L"), (2, "L"), (0, "L")], ["x", "lote_id"])
    [r] = ReporteCalidad([regla]).evaluar(marco, "capa").collect()
    assert (r["filas_evaluadas"], r["filas_falla"]) == (3, 1)


def test_el_reporte_rechaza_reglas_vacias_o_repetidas() -> None:
    with pytest.raises(ParametroInvalidoError):
        ReporteCalidad([])
    regla = ReglaCalidad("a", "a", "informa", lambda: F.lit(True))
    with pytest.raises(ParametroInvalidoError):
        ReporteCalidad([regla, regla])


def test_escribir_persiste_y_resumen_ordena(spark: SparkSession, catalogo: Catalogo) -> None:
    enriquecido = LimpiadorSilver().enriquecer(marco_bronze(spark, [fila("2025-03-10 12:00:00")]))
    reporte_obj = ReporteCalidad(reglas_silver(), reloj=reloj_fijo(MOMENTO))
    reporte = reporte_obj.evaluar(enriquecido, CAPA_SILVER)
    assert reporte_obj.escribir(reporte, catalogo) == 15
    assert reporte_obj.escribir(reporte, catalogo) == 15
    assert spark.table(catalogo.reporte_calidad).count() == 30
    resumen = reporte_obj.resumen(reporte)
    assert [r["regla"] for r in resumen] == sorted(r.nombre for r in reglas_silver())
    with pytest.raises(EsquemaInvalidoError):
        reporte_obj.escribir(reporte.drop("detalle"), catalogo)
