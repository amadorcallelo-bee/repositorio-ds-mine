"""Trigger de reentrenamiento, promocion y rollback sobre MLflow (Ejercicio B-3).

Tres objetos con una responsabilidad cada uno:

- `DecisorReentrenamiento` aplica la regla del enunciado: PSI > 0.2 en cualquier variable
  critica, o el error medio actual mas de un 15% por encima del baseline que el modelo en
  produccion dejo en MLflow al entrenarse. Devuelve las razones, no solo el veredicto,
  porque el evento se registra con ellas.
- `RegistroMlops` es la unica frontera con MLflow: seguimiento, registry y aliases. Recibe
  las URIs por parametro para que las pruebas corran contra un SQLite temporal y el
  notebook contra el workspace (`databricks` / `databricks-uc`).
- `PromotorModelos` resuelve staging contra produccion sobre la misma ventana: si staging
  es peor **o igual**, el alias de produccion no se mueve y el evento queda como rollback
  con la razon y las dos metricas; el "o igual" evita mover el alias por ruido en ventanas
  cortas. Solo un staging estrictamente mejor se promueve.

El alias es el mecanismo de despliegue, igual que en el A-2: promover o revertir es mover
`@produccion`, nunca borrar versiones. El historial completo queda en el registry.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import mlflow
from mlflow.entities.model_registry import ModelVersion

from umlc_lakehouse import dominio
from umlc_lakehouse.deriva import ResultadoPsi
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.modelo import ModeloEntrenado

logger = logging.getLogger(__name__)

Resolucion = Literal["promocion", "rollback"]

ETIQUETA_EVENTO: Final[str] = "evento"
ETIQUETA_RAZON: Final[str] = "razon"


@dataclass(frozen=True)
class DecisionReentrenamiento:
    """El veredicto del trigger con las razones que lo sostienen."""

    reentrenar: bool
    razones: tuple[str, ...]


class DecisorReentrenamiento:
    """La regla del enunciado, con los umbrales del dominio como parametros."""

    def __init__(
        self,
        umbral_psi: float = dominio.PSI_CRITICO,
        degradacion_maxima: float = dominio.DEGRADACION_MAE_MAXIMA,
    ) -> None:
        if umbral_psi <= 0 or degradacion_maxima <= 0:
            raise ParametroInvalidoError("Los umbrales del trigger deben ser positivos")
        self.umbral_psi = umbral_psi
        self.degradacion_maxima = degradacion_maxima

    def decidir(
        self,
        resultados_psi: Sequence[ResultadoPsi],
        error_actual: float | None,
        error_baseline: float | None,
    ) -> DecisionReentrenamiento:
        """PSI global critico o degradacion del error: cualquiera de los dos dispara.

        El desglose por sector no dispara: es informativo, porque un sector que entra o
        sale de campana mueve su PSI sin que el proceso haya cambiado.
        """
        razones: list[str] = [
            f"PSI de {r.variable} = {r.psi:.4f} supera el umbral {self.umbral_psi}"
            for r in resultados_psi
            if r.ambito == "global" and r.psi > self.umbral_psi
        ]
        if error_actual is not None and error_baseline is not None:
            tope = error_baseline * (1.0 + self.degradacion_maxima)
            if error_actual > tope:
                razones.append(
                    f"error actual {error_actual:.4f} g/t supera en mas de "
                    f"{self.degradacion_maxima:.0%} al baseline {error_baseline:.4f}")
        return DecisionReentrenamiento(reentrenar=bool(razones), razones=tuple(razones))


class RegistroMlops:
    """Seguimiento, registry y aliases de MLflow para el ciclo del B-3."""

    def __init__(
        self,
        uri_seguimiento: str,
        uri_registro: str,
        nombre_modelo: str,
        experimento: str = dominio.EXPERIMENTO_MLOPS,
    ) -> None:
        mlflow.set_tracking_uri(uri_seguimiento)
        mlflow.set_registry_uri(uri_registro)
        mlflow.set_experiment(experimento)
        self.nombre_modelo = nombre_modelo
        self.experimento = experimento

    def version_por_alias(self, alias: str) -> ModelVersion | None:
        """La version que porta un alias, o `None` si el alias todavia no existe."""
        cliente = mlflow.MlflowClient()
        try:
            return cliente.get_model_version_by_alias(self.nombre_modelo, alias)
        except mlflow.exceptions.MlflowException:
            return None

    def error_registrado(self, version: ModelVersion) -> float | None:
        """El error de validacion que el run de entrenamiento de esa version registro."""
        if not version.run_id:
            return None
        corrida = mlflow.get_run(version.run_id)
        valor = corrida.data.metrics.get(dominio.METRICA_ERROR)
        return float(valor) if valor is not None else None

    def registrar_entrenamiento(
        self,
        modelo: ModeloEntrenado,
        alias: str,
        nombre_corrida: str,
        etiquetas: dict[str, str] | None = None,
    ) -> ModelVersion:
        """Registra el run con las metricas del A-2, versiona el modelo y fija el alias."""
        with mlflow.start_run(run_name=nombre_corrida) as corrida:
            mlflow.set_tags({
                "conjunto_variables": modelo.conjunto,
                "corte_evaluacion": modelo.corte_evaluacion.isoformat(),
                **(etiquetas or {}),
            })
            mlflow.log_metrics(modelo.metricas)
            mlflow.log_params({
                "turnos_entrenamiento": modelo.turnos_entrenamiento,
                "turnos_evaluacion": modelo.turnos_evaluacion,
            })
            # cloudpickle y no skops, como en el A-2: el pipeline lleva transformadores
            # propios y el formato por defecto de MLflow 3.15 los rechaza.
            mlflow.sklearn.log_model(
                modelo.pipeline,
                name="modelo",
                input_example=modelo.ejemplo,
                serialization_format="cloudpickle",
            )
            uri = f"runs:/{corrida.info.run_id}/modelo"
        version = mlflow.register_model(uri, self.nombre_modelo)
        cliente = mlflow.MlflowClient()
        cliente.set_registered_model_alias(self.nombre_modelo, alias, version.version)
        logger.info("registrado %s v%s con alias %s", self.nombre_modelo, version.version, alias)
        return version

    def cargar(self, alias: str) -> Any:
        """El pipeline que porta un alias, listo para predecir."""
        return mlflow.sklearn.load_model(f"models:/{self.nombre_modelo}@{alias}")

    def mover_alias(self, alias: str, version: str) -> None:
        """Apunta un alias a una version; es la promocion o el rollback en si."""
        mlflow.MlflowClient().set_registered_model_alias(self.nombre_modelo, alias, version)

    def registrar_evento(
        self, evento: str, razones: Sequence[str], metricas: dict[str, float],
    ) -> str:
        """Deja el evento como run del experimento, con la razon como etiqueta."""
        with mlflow.start_run(run_name=f"evento_{evento}") as corrida:
            mlflow.set_tags({
                ETIQUETA_EVENTO: evento,
                ETIQUETA_RAZON: " | ".join(razones) if razones else "sin razones",
            })
            mlflow.log_metrics(metricas)
        return str(corrida.info.run_id)


class PromotorModelos:
    """Resuelve staging contra produccion y deja el evento en MLflow."""

    def __init__(self, registro: RegistroMlops) -> None:
        self.registro = registro

    def resolver(
        self,
        version_staging: ModelVersion,
        error_staging: float,
        error_produccion: float,
        razones_trigger: Sequence[str] = (),
    ) -> Resolucion:
        """Promueve solo si staging es estrictamente mejor; si no, rollback registrado."""
        metricas = {
            "error_staging_g_por_tonelada": error_staging,
            "error_produccion_g_por_tonelada": error_produccion,
        }
        if error_staging < error_produccion:
            self.registro.mover_alias(dominio.ALIAS_PRODUCCION, version_staging.version)
            razon = (f"staging v{version_staging.version} mejora a produccion: "
                     f"{error_staging:.4f} < {error_produccion:.4f} g/t")
            self.registro.registrar_evento("promocion", [razon, *razones_trigger], metricas)
            logger.info("promocion: %s", razon)
            return "promocion"
        razon = (f"staging v{version_staging.version} no mejora a produccion: "
                 f"{error_staging:.4f} >= {error_produccion:.4f} g/t; el alias no se mueve")
        self.registro.registrar_evento("rollback", [razon, *razones_trigger], metricas)
        logger.info("rollback: %s", razon)
        return "rollback"
