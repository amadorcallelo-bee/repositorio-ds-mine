"""Pruebas de silver: hora local, turno recalculado, banderas, cuarentena e idempotencia."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.calidad import CAPA_SILVER, ReporteCalidad, reglas_silver
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import EsquemaInvalidoError
from umlc_lakehouse.ingesta import IngestorBronze
from umlc_lakehouse.limpieza import LimpiadorSilver, TablaSilver
from umlc_lakehouse.tests.conftest import TS_INGESTA, fila, marco_bronze, marco_extracto


def _validas(spark: SparkSession, filas: list[dict[str, object]]) -> list[dict[str, object]]:
    limpiador = LimpiadorSilver()
    resultado = limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas)))
    return [r.asDict() for r in resultado.validas.orderBy(dominio.COLUMNA_TIEMPO).collect()]


def test_la_hora_local_cruza_la_medianoche_y_cambia_fecha_mes_y_turno(
        spark: SparkSession) -> None:
    """03:00 UTC del 1 de enero es 22:00 del 31 de diciembre en Lima: turno N1 del dia anterior."""
    [r] = _validas(spark, [fila("2025-01-01 03:00:00", turno_cod="N2")])
    assert r[dominio.COLUMNA_TS_LOCAL] == datetime(2024, 12, 31, 22, 0)
    assert r[dominio.COLUMNA_FECHA_LOCAL] == date(2024, 12, 31)
    assert r[dominio.COLUMNA_ANIO_MES] == "2024-12"
    assert r[dominio.COLUMNA_TURNO] == "N1"
    assert r[dominio.COLUMNA_TURNO_OPUS] == "N2"
    assert r[dominio.COLUMNA_TURNO_DISCREPANTE] is True


@pytest.mark.parametrize(("hora_utc", "turno"), [
    ("05:00:00", "N2"), ("10:59:00", "N2"),
    ("11:00:00", "D1"), ("16:59:00", "D1"),
    ("17:00:00", "D2"), ("22:59:00", "D2"),
    ("23:00:00", "N1"), ("04:59:00", "N1"),
])
def test_los_limites_exactos_de_cada_turno(spark: SparkSession, hora_utc: str, turno: str) -> None:
    [r] = _validas(spark, [fila(f"2025-03-10 {hora_utc}", turno_cod=turno)])
    assert r[dominio.COLUMNA_TURNO] == turno
    assert r[dominio.COLUMNA_TURNO_DISCREPANTE] is False


def test_el_centinela_pasa_a_nulo_y_se_marca_sin_rechazar(spark: SparkSession) -> None:
    filas = [
        fila("2025-03-10 12:00:00", ley_au_gpT=-1.0),
        fila("2025-03-10 12:30:00", ley_au_gpT=-5.0),
        fila("2025-03-10 13:00:00", ley_au_gpT=0.0),
        fila("2025-03-10 13:30:00", ley_au_gpT=None),
        fila("2025-03-10 14:00:00", ley_au_gpT=7.5),
    ]
    validas = _validas(spark, filas)
    assert [r[dominio.COLUMNA_LEY_VALIDA] for r in validas] == [False, False, True, False, True]
    assert [r[dominio.COLUMNA_LEY] for r in validas] == [None, None, 0.0, None, 7.5]


def test_flag_mant_prev_se_convierte_a_booleano(spark: SparkSession) -> None:
    filas = [
        fila("2025-03-10 12:00:00", flag_mant_prev=1),
        fila("2025-03-10 12:30:00", flag_mant_prev=0),
        fila("2025-03-10 13:00:00", flag_mant_prev=None),
    ]
    assert [r[dominio.COLUMNA_MANTENIMIENTO] for r in _validas(spark, filas)] == [
        True, False, False]


@pytest.mark.parametrize(("columna", "valor", "bandera", "alerta"), [
    ("pres_hidraul_bar", 180.0, "alerta_presion", False),
    ("pres_hidraul_bar", 179.9, "alerta_presion", True),
    ("pres_hidraul_bar", 240.0, "alerta_presion", False),
    ("pres_hidraul_bar", 240.1, "alerta_presion", True),
    ("rpm_corona", 800, "alerta_rpm", False),
    ("rpm_corona", 799, "alerta_rpm", True),
    ("rpm_corona", 1401, "alerta_rpm", True),
    ("vibracion_rms_ms2", 12.0, "alerta_vibracion", False),
    ("vibracion_rms_ms2", 12.1, "alerta_vibracion", True),
    ("temp_motor_c", 95.0, "alerta_temperatura", False),
    ("temp_motor_c", 95.1, "alerta_temperatura", True),
    ("temp_motor_c", None, "alerta_temperatura", False),
])
def test_las_alertas_respetan_los_limites_del_diccionario(
        spark: SparkSession, columna: str, valor: float | None, bandera: str, alerta: bool
) -> None:
    [r] = _validas(spark, [fila("2025-03-10 12:00:00", **{columna: valor})])
    assert r[bandera] is alerta


def test_lo_imposible_va_a_cuarentena_con_su_motivo(spark: SparkSession) -> None:
    filas = [
        fila("2025-03-10 12:00:00", pres_hidraul_bar=-3.0),
        fila("2025-03-10 12:30:00", tipo_mineral="XX"),
        fila("2025-03-10 13:00:00", sector_geol="Otro"),
        fila("2025-03-10 13:30:00", _rescued_data="linea rota"),
        fila("2025-03-10 14:00:00", frente_id=" "),
        fila("2025-03-10 14:30:00"),
    ]
    limpiador = LimpiadorSilver()
    resultado = limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas)))
    assert resultado.validas.count() == 1
    motivos = {
        r[dominio.COLUMNA_TIEMPO].minute + 100 * r[dominio.COLUMNA_TIEMPO].hour: list(
            r[dominio.COLUMNA_MOTIVOS_RECHAZO])
        for r in resultado.cuarentena.collect()
    }
    assert motivos == {
        1200: ["fuera_de_limite_fisico"], 1230: ["tipo_mineral_fuera_dominio"],
        1300: ["sector_fuera_dominio"], 1330: ["registro_rescatado"], 1400: ["frente_nulo"],
    }


def test_un_timestamp_nulo_se_rechaza(spark: SparkSession) -> None:
    limpiador = LimpiadorSilver()
    marco = marco_bronze(spark, [fila("2025-03-10 12:00:00")]).withColumn(
        dominio.COLUMNA_TIEMPO, F.lit(None).cast("timestamp"))
    resultado = limpiador.separar(limpiador.enriquecer(marco))
    assert resultado.validas.count() == 0
    [r] = resultado.cuarentena.collect()
    assert list(r[dominio.COLUMNA_MOTIVOS_RECHAZO]) == ["ts_nulo"]


def test_los_duplicados_del_lote_conservan_la_copia_mas_reciente(spark: SparkSession) -> None:
    vieja = fila("2025-03-10 12:00:00", ley_au_gpT=1.0, ts_ingesta=TS_INGESTA)
    nueva = fila("2025-03-10 12:00:00", ley_au_gpT=2.0,
                 ts_ingesta=TS_INGESTA.replace(hour=13))
    limpiador = LimpiadorSilver()
    enriquecido = limpiador.enriquecer(marco_bronze(spark, [vieja, nueva]))
    assert enriquecido.filter(F.col(dominio.COLUMNA_ES_DUPLICADO)).count() == 1
    [r] = limpiador.separar(enriquecido).validas.collect()
    assert r[dominio.COLUMNA_LEY] == 2.0


def test_silver_conserva_los_18_nombres_originales(spark: SparkSession) -> None:
    [r] = _validas(spark, [fila("2025-03-10 12:00:00")])
    assert set(dominio.COLUMNAS_EXTRACTO) <= set(r)
    assert r[dominio.COLUMNA_FUENTE_TIPO] == dominio.FUENTE_OPUS
    assert r[dominio.COLUMNA_FECHA_CORRECCION] is None


def test_enriquecer_exige_el_esquema_de_bronze(spark: SparkSession) -> None:
    marco = marco_bronze(spark, [fila("2025-03-10 12:00:00")]).drop(dominio.COLUMNA_LOTE)
    with pytest.raises(EsquemaInvalidoError, match="falta la columna lote_id"):
        LimpiadorSilver().enriquecer(marco)


def test_la_escritura_en_silver_es_idempotente_y_la_cuarentena_se_anexa(
        spark: SparkSession, catalogo: Catalogo) -> None:
    filas = [
        fila("2025-03-10 12:00:00"), fila("2025-03-10 12:30:00"),
        fila("2025-03-10 13:00:00", tipo_mineral="XX"),
    ]
    limpiador = LimpiadorSilver()
    resultado = limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas)))
    tabla = TablaSilver(spark, catalogo)
    primero = tabla.escribir(resultado)
    segundo = tabla.escribir(resultado)
    assert (primero.filas_validas, primero.filas_insertadas, primero.filas_cuarentena) == (2, 2, 1)
    assert (segundo.filas_insertadas, segundo.filas_cuarentena) == (0, 1)
    # Un MERGE sin filas nuevas no escribe version: silver queda exactamente igual.
    assert segundo.version_silver == primero.version_silver
    assert spark.table(catalogo.opus_clean).count() == 2
    assert spark.table(catalogo.opus_cuarentena).count() == 2


def test_silver_se_particiona_por_mes_y_publica_change_data_feed(
        spark: SparkSession, catalogo: Catalogo) -> None:
    TablaSilver(spark, catalogo).crear_tablas()
    detalle = spark.sql(f"DESCRIBE DETAIL {catalogo.opus_clean}").first()
    assert detalle is not None
    assert list(detalle["partitionColumns"]) == [dominio.COLUMNA_ANIO_MES]
    assert detalle["properties"]["delta.enableChangeDataFeed"] == "true"


def test_los_lotes_pendientes_son_los_que_no_tienen_reporte_de_silver(
        spark: SparkSession, catalogo: Catalogo) -> None:
    ingestor = IngestorBronze(spark, catalogo)
    ingestor.procesar_lote(marco_extracto(spark, [fila("2025-03-10 12:00:00")]), "L1")
    ingestor.procesar_lote(marco_extracto(spark, [fila("2025-03-10 12:30:00")]), "L2")
    tabla = TablaSilver(spark, catalogo)
    assert tabla.lotes_pendientes() == ["L1", "L2"]
    lote = spark.table(catalogo.opus_raw).filter(F.col(dominio.COLUMNA_LOTE) == "L1")
    reporte = ReporteCalidad(reglas_silver())
    reporte.escribir(reporte.evaluar(LimpiadorSilver().enriquecer(lote), CAPA_SILVER), catalogo)
    assert tabla.lotes_pendientes() == ["L2"]
