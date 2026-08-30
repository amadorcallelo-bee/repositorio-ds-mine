"""Pruebas del monitor de deriva: el PSI exacto, sus bordes y la persistencia."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime

import numpy as np
import pytest
from pyspark.sql import SparkSession

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.deriva import CalculadorPsi, MonitorDeriva, VentanasDeriva
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.limpieza import LimpiadorSilver
from umlc_lakehouse.tests.conftest import fila, marco_bronze, reloj_fijo

MOMENTO = datetime(2025, 11, 4, 8, 0, tzinfo=UTC)


def test_las_ventanas_son_7_dias_de_evaluacion_y_30_previos_de_referencia() -> None:
    v = VentanasDeriva.desde_fecha(date(2025, 10, 28))
    assert (v.evaluacion_desde, v.evaluacion_hasta) == (date(2025, 10, 22), date(2025, 10, 28))
    assert (v.referencia_desde, v.referencia_hasta) == (date(2025, 9, 22), date(2025, 10, 21))
    with pytest.raises(ParametroInvalidoError):
        VentanasDeriva.desde_fecha(date(2025, 10, 28), dias_evaluacion=0)


def test_distribuciones_identicas_dan_psi_cero() -> None:
    valores = np.arange(1000, dtype=float)
    resultado = CalculadorPsi().calcular(valores, valores.copy(), "ley_au_gpT")
    assert resultado.psi == pytest.approx(0.0, abs=1e-9)
    assert resultado.veredicto == "estable"
    assert not resultado.critico
    assert len(resultado.proporciones) == 10


def test_el_psi_de_dos_bins_reproduce_la_formula_a_mano() -> None:
    referencia = np.array([1.0] * 50 + [2.0] * 50)
    actual = np.array([1.0] * 90 + [2.0] * 10)
    resultado = CalculadorPsi(bins=2).calcular(referencia, actual, "x")
    esperado = (0.9 - 0.5) * math.log(0.9 / 0.5) + (0.1 - 0.5) * math.log(0.1 / 0.5)
    assert resultado.psi == pytest.approx(esperado, rel=1e-9)
    assert resultado.veredicto == "critico"
    # Con umbrales mas holgados, el mismo indice es solo moderado.
    holgado = CalculadorPsi(bins=2, umbral_moderado=0.5, umbral_critico=1.0)
    assert holgado.calcular(referencia, actual, "x").veredicto == "moderado"


def test_distribuciones_disyuntas_gritan_y_los_bordes_fallan_con_claridad() -> None:
    calculador = CalculadorPsi()
    disyunto = calculador.calcular(
        np.linspace(0, 1, 200), np.linspace(10, 11, 200), "x")
    assert disyunto.psi > 2.0
    assert disyunto.critico
    with pytest.raises(ParametroInvalidoError, match="ventana vacia"):
        calculador.calcular(np.array([]), np.array([1.0]), "x")
    with pytest.raises(ParametroInvalidoError, match="no tiene variacion"):
        calculador.calcular(np.array([3.0] * 50), np.array([4.0] * 50), "x")
    with pytest.raises(ParametroInvalidoError):
        CalculadorPsi(bins=1)
    with pytest.raises(ParametroInvalidoError):
        CalculadorPsi(umbral_moderado=0.3, umbral_critico=0.2)


def _silver_deriva(spark: SparkSession) -> object:
    """Silver sintetica: referencia estable en septiembre-octubre y deriva al final."""
    filas = []
    # La vibracion alterna 4 y 6 en las dos ventanas: con distribucion identica, su PSI
    # debe dar estable; una constante no define bins y el calculador la rechaza.
    for dia in range(1, 31):  # referencia: octubre 1..30, ley alterna 7 y 9
        filas.append(fila(f"2025-10-{dia:02d} 15:00:00", ley_au_gpT=7.0, vibracion_rms_ms2=4.0))
        filas.append(fila(f"2025-10-{dia:02d} 16:00:00", ley_au_gpT=9.0, vibracion_rms_ms2=6.0))
    for dia in range(1, 8):  # evaluacion: noviembre 1..7, ley desplazada y un centinela
        filas.append(fila(f"2025-11-{dia:02d} 15:00:00", ley_au_gpT=15.0, vibracion_rms_ms2=4.0))
        filas.append(fila(f"2025-11-{dia:02d} 16:00:00", ley_au_gpT=-1.0, vibracion_rms_ms2=6.0))
    limpiador = LimpiadorSilver()
    return limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas))).validas


def test_el_monitor_detecta_la_deriva_de_ley_y_excluye_el_centinela(
        spark: SparkSession, catalogo: Catalogo) -> None:
    silver = _silver_deriva(spark)
    ventanas = VentanasDeriva.desde_fecha(date(2025, 11, 7))
    monitor = MonitorDeriva(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    resultados = monitor.evaluar(silver, ventanas)  # type: ignore[arg-type]
    por_clave = {(r.variable, r.ambito): r for r in resultados}
    ley = por_clave[(dominio.COLUMNA_LEY, "global")]
    assert ley.critico
    assert ley.n_actual == 7  # los 7 centinelas quedaron fuera
    vibracion = por_clave[(dominio.COLUMNA_VIBRACION, "global")]
    assert vibracion.veredicto == "estable"
    assert vibracion.n_actual == 14
    assert (dominio.COLUMNA_LEY, "Veta-Sur") in por_clave


def test_el_monitor_persiste_el_reporte_con_el_detalle_de_bins(
        spark: SparkSession, catalogo: Catalogo) -> None:
    silver = _silver_deriva(spark)
    ventanas = VentanasDeriva.desde_fecha(date(2025, 11, 7))
    monitor = MonitorDeriva(spark, catalogo, reloj=reloj_fijo(MOMENTO))
    resultados = monitor.evaluar(silver, ventanas)  # type: ignore[arg-type]
    assert monitor.escribir(resultados, ventanas) == len(resultados)
    tabla = spark.table(catalogo.tabla(dominio.ESQUEMA_DQ, dominio.TABLA_MONITOR_DERIVA))
    assert tabla.count() == len(resultados)
    primera = tabla.filter(tabla.ambito == "global").first()
    assert primera is not None
    assert primera["referencia_desde"] == date(2025, 10, 2)
    detalle = json.loads(primera["detalle_bins"])
    assert len(detalle) >= 2 and len(detalle[0]) == 2


def test_sin_ventanas_las_deduce_de_la_fecha_maxima(
        spark: SparkSession, catalogo: Catalogo) -> None:
    silver = _silver_deriva(spark)
    monitor = MonitorDeriva(spark, catalogo)
    resultados = monitor.evaluar(silver)  # type: ignore[arg-type]
    assert any(r.critico for r in resultados)
