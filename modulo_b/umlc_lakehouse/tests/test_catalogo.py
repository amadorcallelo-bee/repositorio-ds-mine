"""Pruebas de la resolucion de nombres del lakehouse."""

from __future__ import annotations

import pytest
from pyspark.sql import SparkSession

from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import ParametroInvalidoError


def test_los_nombres_siguen_el_arbol_del_enunciado() -> None:
    cat = Catalogo()
    assert cat.opus_raw == "lakehouse_umlc.bronze.opus_raw"
    assert cat.opus_clean == "lakehouse_umlc.silver.opus_clean"
    assert cat.aurum_kpi_turno == "lakehouse_umlc.gold.aurum_kpi_turno"
    assert cat.reporte_calidad == "lakehouse_umlc.dq_reports.reporte_calidad"
    assert cat.ruta_landing == "/Volumes/lakehouse_umlc/bronze/landing"


def test_el_catalogo_local_tiene_dos_niveles_y_prefijo() -> None:
    cat = Catalogo.local(prefijo_esquema="p_")
    assert cat.opus_raw == "p_bronze.opus_raw"
    assert cat.esquemas() == ("p_bronze", "p_silver", "p_gold", "p_dq_reports")
    with pytest.raises(ParametroInvalidoError):
        _ = cat.ruta_landing


def test_crear_esquemas_es_idempotente(spark: SparkSession, catalogo: Catalogo) -> None:
    catalogo.crear_esquemas(spark)
    existentes = {r.namespace for r in spark.sql("SHOW SCHEMAS").collect()}
    assert set(catalogo.esquemas()) <= existentes
