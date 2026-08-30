"""Pruebas de los KPI de gold, formula por formula."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pyspark.sql import SparkSession

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.kpi import ConstructorKpiTurno, ParametrosKpi
from umlc_lakehouse.tests.conftest import fila, reloj_fijo, silver_de

MOMENTO = datetime(2025, 11, 3, 9, 0, tzinfo=UTC)
# 17:00 UTC es 12:00 en Lima: turno D2 del mismo dia.
BASE = "2025-03-10 17:{m:02d}:00"


def _kpi(spark: SparkSession, filas: list[dict[str, Any]],
         parametros: ParametrosKpi | None = None) -> list[dict[str, Any]]:
    constructor = ConstructorKpiTurno(parametros, reloj=reloj_fijo(MOMENTO))
    return [r.asDict() for r in constructor.construir(silver_de(spark, filas))
            .orderBy(*dominio.CLAVE_TURNO).collect()]


def test_la_ley_se_pondera_por_tonelaje_y_excluye_el_centinela(spark: SparkSession) -> None:
    filas = [
        fila(BASE.format(m=0), ley_au_gpT=10.0, ton_rom_acum=100.0),
        fila(BASE.format(m=30), ley_au_gpT=20.0, ton_rom_acum=300.0),
        fila(BASE.format(m=59), ley_au_gpT=-1.0, ton_rom_acum=500.0),
    ]
    [r] = _kpi(spark, filas)
    assert r["ley_ponderada_gpt"] == pytest.approx(17.5)
    assert (r["n_eventos"], r["n_eventos_ley_valida"], r["ton_total"]) == (3, 2, 900.0)
    assert r[dominio.COLUMNA_TURNO] == "D2"
    assert r[dominio.COLUMNA_SECTOR] == "Veta-Sur"


def test_sin_ley_valida_o_sin_tonelaje_la_ley_ponderada_es_nula(spark: SparkSession) -> None:
    [solo_centinela] = _kpi(spark, [fila(BASE.format(m=0), ley_au_gpT=-1.0)])
    assert solo_centinela["ley_ponderada_gpt"] is None
    [sin_tonelaje] = _kpi(spark, [fila(BASE.format(m=0), ton_rom_acum=0.0)])
    assert sin_tonelaje["ley_ponderada_gpt"] is None


def test_la_eficiencia_de_avance_es_la_fraccion_del_maximo_del_manual(
        spark: SparkSession) -> None:
    [r] = _kpi(spark, [fila(BASE.format(m=0), avance_mmin=1.75)])
    assert r["eficiencia_avance"] == pytest.approx(0.5)
    assert r["avance_medio_mmin"] == pytest.approx(1.75)


def test_la_tasa_de_fallas_es_por_evento(spark: SparkSession) -> None:
    filas = [fila(BASE.format(m=m)) for m in (0, 15, 30)] + [
        fila(BASE.format(m=45), falla_cod="H-HIDRA-02")]
    [r] = _kpi(spark, filas)
    assert r["tasa_fallas"] == pytest.approx(0.25)
    assert r["n_fallas"] == 1


def test_las_horas_efectivas_descuentan_falla_y_mantenimiento(spark: SparkSession) -> None:
    filas = [
        fila(BASE.format(m=0)),
        fila(BASE.format(m=30), falla_cod="H-HIDRA-02"),
        fila("2025-03-10 18:00:00", flag_mant_prev=1),
        fila("2025-03-10 18:30:00"),
    ]
    [r] = _kpi(spark, filas)
    assert r["horas_parada"] == pytest.approx(1.0)
    assert r["horas_efectivas"] == pytest.approx(0.5)
    assert r["n_eventos_mantenimiento"] == 1


def test_un_solo_evento_no_tiene_horas_y_el_tope_es_la_duracion_del_turno(
        spark: SparkSession) -> None:
    [uno] = _kpi(spark, [fila(BASE.format(m=0))])
    assert uno["horas_efectivas"] == 0.0
    filas = [fila(BASE.format(m=0)), fila("2025-03-10 19:00:00")]
    [acotado] = _kpi(spark, filas, ParametrosKpi(duracion_turno_horas=1.0))
    assert acotado["horas_efectivas"] == pytest.approx(1.0)


def test_la_produccion_se_recalcula_con_el_factor_del_tipo_vigente(spark: SparkSession) -> None:
    filas = [fila(BASE.format(m=0), ley_au_gpT=10.0, ton_rom_acum=100.0, tipo_mineral="SUL",
                  prod_estimada_oz=5.0)]
    [r] = _kpi(spark, filas)
    assert r["prod_oz_recalculada"] == pytest.approx(10.0 * 100.0 / 31.1035 * 0.91)
    assert r["prod_estimada_oz_total"] == pytest.approx(5.0)


def test_el_grano_es_frente_fecha_local_y_turno(spark: SparkSession) -> None:
    filas = [
        fila(BASE.format(m=0), frente_id="FR-S2-03"),
        fila(BASE.format(m=30), frente_id="FR-C1-05", sector_geol="Cuerpo-Central"),
        fila("2025-03-10 23:30:00", frente_id="FR-S2-03"),
    ]
    resultado = _kpi(spark, filas)
    assert [(r[dominio.COLUMNA_FRENTE], r[dominio.COLUMNA_TURNO]) for r in resultado] == [
        ("FR-C1-05", "D2"), ("FR-S2-03", "D2"), ("FR-S2-03", "N1"),
    ]
    assert all(r["ts_calculo"] == MOMENTO.replace(tzinfo=None) for r in resultado)


def test_las_alertas_y_los_reclasificados_se_cuentan(spark: SparkSession) -> None:
    filas = [fila(BASE.format(m=0), temp_motor_c=97.0), fila(BASE.format(m=30))]
    [r] = _kpi(spark, filas)
    assert (r["n_alertas_temperatura"], r["n_alertas_presion"], r["n_reclasificados"]) == (1, 0, 0)


def test_los_parametros_validan_sus_precondiciones() -> None:
    with pytest.raises(ParametroInvalidoError):
        ParametrosKpi(avance_maximo_mmin=0.0)
    with pytest.raises(ParametroInvalidoError):
        ParametrosKpi(duracion_turno_horas=-1.0)
    with pytest.raises(ParametroInvalidoError):
        ParametrosKpi(factores_recuperacion={})
