"""Reglas de calidad y reporte por lote.

Una regla es un objeto con nombre, severidad y condicion de falla, y el reporte es una fila
por regla, capa y lote. Se modela asi, y no como una funcion que imprime porcentajes, por
tres razones: la severidad decide lo que silver hace con la fila (rechazar o solo marcar),
el reporte tiene que persistir en una tabla que el B-2 pueda consultar desde Fabric, y las
mismas condiciones tienen que servir para separar filas y para contarlas, o los dos
numeros se desincronizan.

Las condiciones se declaran como funciones que devuelven una `Column` y no como columnas
ya construidas, porque PySpark necesita una sesion activa para construirlas y el modulo
tiene que poder importarse sin ella.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from umlc_lakehouse import dominio
from umlc_lakehouse.catalogo import Catalogo
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.esquema import EsquemaOpus
from umlc_lakehouse.ingesta import ahora_utc

Severidad = Literal["rechaza", "marca", "informa"]

CAPA_SILVER: Final[str] = "silver"
CAPA_SILVER_CDC: Final[str] = "silver_cdc"


@dataclass(frozen=True)
class ReglaCalidad:
    """Una regla: `condicion()` es verdadera en las filas que la incumplen."""

    nombre: str
    descripcion: str
    severidad: Severidad
    condicion: Callable[[], Column]

    def falla(self) -> Column:
        """La condicion como booleano sin nulos, para poder sumarla."""
        return F.coalesce(self.condicion().cast("boolean"), F.lit(False))


def _fuera_de(columna: str, minimo: float | None, maximo: float | None) -> Callable[[], Column]:
    def condicion() -> Column:
        c = F.col(columna)
        partes: list[Column] = []
        if minimo is not None:
            partes.append(c < F.lit(minimo))
        if maximo is not None:
            partes.append(c > F.lit(maximo))
        resultado = partes[0]
        for parte in partes[1:]:
            resultado = resultado | parte
        return resultado
    return condicion


def _fuera_de_dominio(columna: str, valores: Sequence[str]) -> Callable[[], Column]:
    return lambda: ~F.col(columna).isin(list(valores))


def _bandera(nombre: str) -> Callable[[], Column]:
    return lambda: F.col(nombre)


def _limite_fisico() -> Column:
    partes = [
        _fuera_de(columna, minimo, maximo)()
        for columna, (minimo, maximo) in dominio.LIMITES_FISICOS.items()
    ]
    resultado = F.coalesce(partes[0], F.lit(False))
    for parte in partes[1:]:
        resultado = resultado | F.coalesce(parte, F.lit(False))
    return resultado


def reglas_silver() -> tuple[ReglaCalidad, ...]:
    """Las reglas que silver aplica sobre el marco ya enriquecido.

    `rechaza` manda la fila a cuarentena; `marca` deja una bandera en silver; `informa`
    solo cuenta. La distincion entre rango operacional (marca) y limite fisico (rechaza)
    es la misma que usa el servicio de inferencia del A-2: una vibracion de 14 m/s2 es una
    alerta que operaciones quiere ver, una presion negativa es un registro corrupto.
    """
    reglas: list[ReglaCalidad] = [
        ReglaCalidad(
            "ts_nulo", "ts_opus_utc vacio o no convertible a timestamp",
            "rechaza", lambda: F.col(dominio.COLUMNA_TIEMPO).isNull(),
        ),
        ReglaCalidad(
            "frente_nulo", "frente_id vacio",
            "rechaza", lambda: F.col(dominio.COLUMNA_FRENTE).isNull()
            | (F.trim(F.col(dominio.COLUMNA_FRENTE)) == ""),
        ),
        ReglaCalidad(
            "tipo_mineral_fuera_dominio", "tipo_mineral distinto de OX, SUL, MIX, EST",
            "rechaza", _fuera_de_dominio(dominio.COLUMNA_TIPO_MINERAL, dominio.TIPOS_MINERAL),
        ),
        ReglaCalidad(
            "sector_fuera_dominio", "sector_geol fuera de los cuatro sectores UMLC",
            "rechaza", _fuera_de_dominio(dominio.COLUMNA_SECTOR, dominio.SECTORES),
        ),
        ReglaCalidad(
            "fuera_de_limite_fisico", "algun sensor con un valor fisicamente imposible",
            "rechaza", _limite_fisico,
        ),
        ReglaCalidad(
            "registro_rescatado", "fila que no encajo en el esquema explicito",
            "rechaza", lambda: F.col(dominio.COLUMNA_RESCATE).isNotNull(),
        ),
        ReglaCalidad(
            "duplicado_en_lote", "clave (ts_opus_utc, frente_id) repetida dentro del lote",
            "informa", lambda: F.col(dominio.COLUMNA_ES_DUPLICADO),
        ),
        ReglaCalidad(
            "ley_centinela", "ley_au_gpT en -1: sonda XRF sin comunicacion (E-ELEC-04)",
            "marca", lambda: ~F.col(dominio.COLUMNA_LEY_VALIDA),
        ),
        ReglaCalidad(
            "turno_discrepante", "turno_cod de OPUS distinto del que da la hora local",
            "marca", lambda: F.col(dominio.COLUMNA_TURNO_DISCREPANTE),
        ),
        ReglaCalidad(
            "turno_opus_fuera_dominio", "turno_cod recibido fuera de D1, D2, N1, N2",
            "informa", _fuera_de_dominio(dominio.COLUMNA_TURNO_OPUS, dominio.ORDEN_TURNOS),
        ),
        ReglaCalidad(
            "prod_estimada_nula", "prod_estimada_oz vacio (OPUS no la calcula sin ley)",
            "informa", lambda: F.col(dominio.COLUMNA_PRODUCCION).isNull(),
        ),
    ]
    for columna, bandera in dominio.ALERTAS.items():
        minimo, maximo = dominio.RANGOS_OPERACIONALES[columna]
        rango = f"{minimo if minimo is not None else ''}-{maximo if maximo is not None else ''}"
        reglas.append(ReglaCalidad(
            bandera, f"{columna} fuera del rango operacional {rango}",
            "marca", _bandera(bandera),
        ))
    return tuple(reglas)


class ReporteCalidad:
    """Evalua un conjunto de reglas por lote y persiste el resultado."""

    ESQUEMA: Final[StructType] = StructType([
        StructField(dominio.COLUMNA_LOTE, StringType(), True),
        StructField("capa", StringType(), True),
        StructField("regla", StringType(), True),
        StructField("severidad", StringType(), True),
        StructField("descripcion", StringType(), True),
        StructField("filas_evaluadas", LongType(), True),
        StructField("filas_falla", LongType(), True),
        StructField("pct_falla", DoubleType(), True),
        StructField("detalle", StringType(), True),
        StructField("ts_evaluacion", TimestampType(), True),
    ])

    def __init__(
        self,
        reglas: Sequence[ReglaCalidad],
        reloj: Callable[[], datetime] = ahora_utc,
    ) -> None:
        if not reglas:
            raise ParametroInvalidoError("El reporte necesita al menos una regla")
        nombres = [r.nombre for r in reglas]
        if len(set(nombres)) != len(nombres):
            raise ParametroInvalidoError("Hay reglas con el mismo nombre")
        self.reglas = tuple(reglas)
        self.reloj = reloj

    def evaluar(
        self, df: DataFrame, capa: str, columna_lote: str = dominio.COLUMNA_LOTE
    ) -> DataFrame:
        """Una fila por regla y lote, en una sola pasada sobre el marco."""
        ts = self.reloj()
        agregados = [F.count(F.lit(1)).alias("filas_evaluadas")] + [
            F.sum(regla.falla().cast("long")).alias(f"_r_{i}")
            for i, regla in enumerate(self.reglas)
        ]
        por_lote = df.groupBy(F.col(columna_lote).alias(dominio.COLUMNA_LOTE)).agg(*agregados)
        filas = F.array(*[
            F.struct(
                F.lit(regla.nombre).alias("regla"),
                F.lit(regla.severidad).alias("severidad"),
                F.lit(regla.descripcion).alias("descripcion"),
                F.col(f"_r_{i}").alias("filas_falla"),
            )
            for i, regla in enumerate(self.reglas)
        ])
        explotado = por_lote.select(
            dominio.COLUMNA_LOTE, "filas_evaluadas", F.explode(filas).alias("r")
        )
        return explotado.select(
            F.col(dominio.COLUMNA_LOTE),
            F.lit(capa).alias("capa"),
            F.col("r.regla").alias("regla"),
            F.col("r.severidad").alias("severidad"),
            F.col("r.descripcion").alias("descripcion"),
            F.col("filas_evaluadas").cast("long"),
            F.col("r.filas_falla").cast("long").alias("filas_falla"),
            F.when(F.col("filas_evaluadas") > 0,
                   F.round(F.col("r.filas_falla") * 100.0 / F.col("filas_evaluadas"), 4))
            .otherwise(F.lit(0.0)).alias("pct_falla"),
            F.lit(None).cast("string").alias("detalle"),
            F.lit(ts).alias("ts_evaluacion"),
        )

    @staticmethod
    def crear_tabla(catalogo: Catalogo, spark_df: DataFrame) -> None:
        """Crea la tabla del reporte con esquema explicito; idempotente."""
        spark_df.sparkSession.sql(
            f"CREATE TABLE IF NOT EXISTS {catalogo.reporte_calidad} "
            f"({EsquemaOpus.ddl(ReporteCalidad.ESQUEMA)}) USING DELTA"
        )

    def escribir(self, reporte: DataFrame, catalogo: Catalogo) -> int:
        """Anexa el reporte a `dq_reports.reporte_calidad` y devuelve las filas escritas."""
        EsquemaOpus.verificar(reporte, self.ESQUEMA, "reporte de calidad")
        self.crear_tabla(catalogo, reporte)
        ordenado = reporte.select(*[f.name for f in self.ESQUEMA.fields])
        ordenado.write.format("delta").mode("append").saveAsTable(catalogo.reporte_calidad)
        return ordenado.count()

    @staticmethod
    def resumen(reporte: DataFrame) -> list[dict[str, object]]:
        """El reporte como lista de diccionarios, para el resumen que exporta el notebook."""
        return [
            {
                "lote_id": fila[dominio.COLUMNA_LOTE], "regla": fila["regla"],
                "severidad": fila["severidad"], "filas_evaluadas": int(fila["filas_evaluadas"]),
                "filas_falla": int(fila["filas_falla"]), "pct_falla": float(fila["pct_falla"]),
            }
            for fila in reporte.orderBy(dominio.COLUMNA_LOTE, "regla").collect()
        ]
