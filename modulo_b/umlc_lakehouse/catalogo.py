"""Nombres del lakehouse y su creacion.

Traduce el arbol del enunciado (`lakehouse_umlc/bronze/opus_raw`, ...) a objetos de Unity
Catalog: un catalogo, cuatro esquemas y tablas gestionadas Delta. Existe como objeto y no
como cadenas sueltas por dos razones: en Databricks los nombres tienen tres niveles y en
Spark local solo dos, y las pruebas necesitan esquemas con prefijo propio para no pisarse
entre si. Un unico lugar resuelve las dos cosas.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import SparkSession

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError


@dataclass(frozen=True)
class Catalogo:
    """Resuelve nombres calificados de esquemas, tablas y volumenes.

    `nombre` es el catalogo de Unity Catalog; `None` significa Spark local, donde solo
    existen esquema y tabla. `prefijo_esquema` lo usan las pruebas para aislar cada caso.
    """

    nombre: str | None = dominio.CATALOGO
    prefijo_esquema: str = ""

    @classmethod
    def local(cls, prefijo_esquema: str = "") -> Catalogo:
        """Catalogo para Spark local: sin catalogo de tres niveles."""
        return cls(nombre=None, prefijo_esquema=prefijo_esquema)

    def esquema(self, base: str) -> str:
        """Nombre calificado de un esquema (`catalogo.esquema` o `esquema`)."""
        nombre = f"{self.prefijo_esquema}{base}"
        return f"{self.nombre}.{nombre}" if self.nombre else nombre

    def tabla(self, esquema_base: str, tabla: str) -> str:
        """Nombre calificado de una tabla."""
        return f"{self.esquema(esquema_base)}.{tabla}"

    @property
    def opus_raw(self) -> str:
        """Bronze: el extracto tal como llego, con metadata de ingesta."""
        return self.tabla(dominio.ESQUEMA_BRONZE, dominio.TABLA_OPUS_RAW)

    @property
    def ingesta_log(self) -> str:
        """Bronze: un registro por archivo ingerido."""
        return self.tabla(dominio.ESQUEMA_BRONZE, dominio.TABLA_INGESTA_LOG)

    @property
    def opus_clean(self) -> str:
        """Silver: eventos validados, en hora local y con turno recalculado."""
        return self.tabla(dominio.ESQUEMA_SILVER, dominio.TABLA_OPUS_CLEAN)

    @property
    def opus_cuarentena(self) -> str:
        """Silver: filas rechazadas con el motivo."""
        return self.tabla(dominio.ESQUEMA_SILVER, dominio.TABLA_CUARENTENA)

    @property
    def reporte_calidad(self) -> str:
        """Reporte de calidad: una fila por regla, capa y lote."""
        return self.tabla(dominio.ESQUEMA_DQ, dominio.TABLA_REPORTE_CALIDAD)

    @property
    def aurum_kpi_turno(self) -> str:
        """Gold: KPI por frente, fecha local y turno."""
        return self.tabla(dominio.ESQUEMA_GOLD, dominio.TABLA_KPI_TURNO)

    @property
    def ruta_landing(self) -> str:
        """Ruta del volumen donde llegan los archivos. Solo existe en Unity Catalog."""
        if self.nombre is None:
            raise ParametroInvalidoError("El volumen de landing requiere un catalogo")
        esquema = f"{self.prefijo_esquema}{dominio.ESQUEMA_BRONZE}"
        return f"/Volumes/{self.nombre}/{esquema}/{dominio.VOLUMEN_LANDING}"

    def esquemas(self) -> tuple[str, ...]:
        """Los cuatro esquemas del arbol del enunciado, calificados."""
        return tuple(
            self.esquema(base)
            for base in (
                dominio.ESQUEMA_BRONZE, dominio.ESQUEMA_SILVER,
                dominio.ESQUEMA_GOLD, dominio.ESQUEMA_DQ,
            )
        )

    def crear_esquemas(self, spark: SparkSession) -> None:
        """Crea el catalogo (si aplica) y los esquemas; es idempotente."""
        if self.nombre is not None:
            spark.sql(f"CREATE CATALOG IF NOT EXISTS {self.nombre}")
        for esquema in self.esquemas():
            spark.sql(f"CREATE SCHEMA IF NOT EXISTS {esquema}")
