"""Sesion de Spark local con Delta y constructores de datos sinteticos.

Las pruebas no dependen del extracto: cada caso construye las filas que necesita con
`fila()` y las convierte a un marco con el esquema explicito de bronze. La sesion es una
por ejecucion, porque arrancar la JVM cuesta segundos, y cada prueba trabaja en esquemas
con prefijo propio para que las tablas Delta no se pisen.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from delta import configure_spark_with_delta_pip
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.limpieza import LimpiadorSilver

TS_INGESTA = datetime(2025, 11, 1, 12, 0, tzinfo=UTC)

_CANDIDATOS_JAVA = (
    "/opt/homebrew/opt/openjdk@21",
    "/opt/homebrew/opt/openjdk",
    "/usr/lib/jvm/java-21-openjdk-amd64",
    "/usr/lib/jvm/default-java",
)


def _asegurar_java() -> None:
    """Spark necesita una JVM; si no hay `java` en el PATH se busca el JDK de Homebrew."""
    if os.environ.get("JAVA_HOME") or shutil.which("java"):
        return
    for candidato in _CANDIDATOS_JAVA:
        if Path(candidato, "bin", "java").is_file():
            os.environ["JAVA_HOME"] = candidato
            os.environ["PATH"] = f"{candidato}/bin:{os.environ.get('PATH', '')}"
            return
    raise RuntimeError(
        "No se encontro un JDK. Instala uno (brew install openjdk@21) o define JAVA_HOME."
    )


def _fijar_utc() -> None:
    """El driver de PySpark convierte `datetime` con la zona de la maquina, no de la sesion.

    Un `datetime` naive que entra a `createDataFrame` se interpreta en la zona local del
    proceso Python, y un timestamp que vuelve por `collect()` se renderiza en esa misma
    zona. Con la maquina en UTC-5 y la sesion en UTC, las horas se corren cinco horas en
    cada frontera. Fijar `TZ=UTC` en el proceso deja las dos conversiones alineadas con la
    sesion, que es lo que ocurre en Databricks, donde el driver corre en UTC.
    """
    os.environ["TZ"] = "UTC"
    time.tzset()


@pytest.fixture(scope="session")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    _asegurar_java()
    _fijar_utc()
    almacen = tmp_path_factory.mktemp("warehouse")
    constructor = (
        SparkSession.builder.master("local[2]").appName("umlc-lakehouse-tests")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.warehouse.dir", str(almacen))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.extraJavaOptions", "-Dlog4j2.level=error")
    )
    sesion = configure_spark_with_delta_pip(constructor).getOrCreate()
    sesion.sparkContext.setLogLevel("ERROR")
    yield sesion
    sesion.stop()


@pytest.fixture
def catalogo(spark: SparkSession) -> Catalogo:
    """Un catalogo local con esquemas propios para la prueba."""
    cat = Catalogo.local(prefijo_esquema=f"t{uuid.uuid4().hex[:8]}_")
    cat.crear_esquemas(spark)
    return cat


def fila(ts: str, **cambios: Any) -> dict[str, Any]:
    """Una fila del extracto con valores normales; `cambios` sobreescribe lo que haga falta."""
    base: dict[str, Any] = {
        dominio.COLUMNA_TIEMPO: datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
        dominio.COLUMNA_FRENTE: "FR-S2-03",
        dominio.COLUMNA_TURNO: "D1",
        dominio.COLUMNA_LEY: 8.0,
        dominio.COLUMNA_TONELAJE: 100.0,
        dominio.COLUMNA_PRESION: 210.0,
        dominio.COLUMNA_RPM: 1100,
        dominio.COLUMNA_AVANCE: 1.75,
        dominio.COLUMNA_AGUA: 45.0,
        dominio.COLUMNA_VIBRACION: 5.0,
        dominio.COLUMNA_TEMPERATURA: 75.0,
        dominio.COLUMNA_OPERADOR: "OP-0001",
        dominio.COLUMNA_EQUIPO: "EQ-ATLAS-01",
        dominio.COLUMNA_FALLA: None,
        dominio.COLUMNA_PRODUCCION: 23.4,
        dominio.COLUMNA_TIPO_MINERAL: "SUL",
        dominio.COLUMNA_SECTOR: "Veta-Sur",
        dominio.COLUMNA_MANTENIMIENTO: 0,
        dominio.COLUMNA_RESCATE: None,
        dominio.COLUMNA_ARCHIVO_FUENTE: "lote_a.csv",
        dominio.COLUMNA_TS_INGESTA: TS_INGESTA,
        dominio.COLUMNA_FECHA_INGESTA: TS_INGESTA.date(),
        dominio.COLUMNA_LOTE: "L1",
    }
    base.update(cambios)
    return base


def marco_bronze(spark: SparkSession, filas: list[dict[str, Any]]) -> DataFrame:
    """Un marco con el esquema exacto de bronze."""
    esquema = EsquemaOpus.bronze()
    orden = [f.name for f in esquema.fields]
    return spark.createDataFrame([tuple(f[c] for c in orden) for f in filas], esquema)


def marco_extracto(spark: SparkSession, filas: list[dict[str, Any]]) -> DataFrame:
    """Un marco como el que entrega el lector de CSV: extracto, rescate y archivo."""
    esquema = EsquemaOpus.con_rescate(EsquemaOpus.EXTRACTO)
    orden = [f.name for f in esquema.fields] + [dominio.COLUMNA_ARCHIVO_FUENTE]
    marco = spark.createDataFrame([tuple(f[c] for c in orden[:-1]) for f in filas], esquema)
    archivos = {f[dominio.COLUMNA_TIEMPO]: f[dominio.COLUMNA_ARCHIVO_FUENTE] for f in filas}
    expresion = F.lit(None).cast("string")
    for ts, archivo in archivos.items():
        expresion = F.when(F.col(dominio.COLUMNA_TIEMPO) == F.lit(ts), F.lit(archivo)).otherwise(
            expresion
        )
    return marco.withColumn(dominio.COLUMNA_ARCHIVO_FUENTE, expresion)


def silver_de(spark: SparkSession, filas: list[dict[str, Any]]) -> DataFrame:
    """Las filas validas de silver que produce un lote de bronze."""
    limpiador = LimpiadorSilver()
    return limpiador.separar(limpiador.enriquecer(marco_bronze(spark, filas))).validas


def reloj_fijo(momento: datetime) -> Any:
    """Un reloj que siempre devuelve `momento`."""
    return lambda: momento


FECHA_ANALISIS = date(2025, 9, 28)


def eventos_sinteticos(
    dias: int = 21,
    leyes: dict[str, float] | None = None,
    ley_eval: dict[str, float] | None = None,
    dias_evaluacion: int = 7,
    inicio: str = "2025-09-01",
) -> pd.DataFrame:
    """Eventos a nivel del extracto para el B-3, con un evento por turno y frente.

    Cada frente tiene una ley base; `ley_eval` permite desplazarla en los ultimos
    `dias_evaluacion` dias, que es como se fabrica una degradacion o una deriva sin tocar
    el generador. Las horas UTC 05, 11, 17 y 23 caen en los turnos N2, D1, D2 y N1 de Lima.
    """
    leyes = leyes if leyes is not None else {"FR-A-01": 5.0, "FR-B-02": 10.0}
    ley_eval = ley_eval or {}
    base = pd.Timestamp(inicio)
    filas: list[dict[str, object]] = []
    for dia in range(dias):
        fecha = base + pd.Timedelta(days=dia)
        en_evaluacion = dia >= dias - dias_evaluacion
        for hora, turno in ((5, "N2"), (11, "D1"), (17, "D2"), (23, "N1")):
            for frente, ley in leyes.items():
                valor = ley_eval.get(frente, ley) if en_evaluacion else ley
                filas.append({
                    dominio.COLUMNA_TIEMPO: fecha + pd.Timedelta(hours=hora),
                    dominio.COLUMNA_FRENTE: frente,
                    dominio.COLUMNA_TURNO: turno,
                    dominio.COLUMNA_LEY: valor,
                    dominio.COLUMNA_TONELAJE: 100.0,
                    dominio.COLUMNA_PRESION: 210.0,
                    dominio.COLUMNA_RPM: 1100,
                    dominio.COLUMNA_AVANCE: 1.75,
                    dominio.COLUMNA_AGUA: 45.0,
                    dominio.COLUMNA_VIBRACION: 5.0,
                    dominio.COLUMNA_TEMPERATURA: 75.0,
                    dominio.COLUMNA_OPERADOR: "OP-0001",
                    dominio.COLUMNA_EQUIPO: "EQ-ATLAS-01",
                    dominio.COLUMNA_FALLA: None,
                    dominio.COLUMNA_PRODUCCION: 20.0,
                    dominio.COLUMNA_TIPO_MINERAL: "SUL",
                    dominio.COLUMNA_SECTOR: "Veta-Sur",
                    dominio.COLUMNA_MANTENIMIENTO: 0,
                })
    return pd.DataFrame(filas)
