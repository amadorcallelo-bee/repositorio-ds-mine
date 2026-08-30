"""Carga de los modelos desde el Model Registry y prediccion, sin HTTP de por medio.

Esta clase no conoce a FastAPI y esa es toda la razon por la que existe separada de `app.py`:
la logica de prediccion tiene que poder probarse sin levantar un servidor, y el servidor tiene
que poder cambiar sin tocar la prediccion.

**Se resuelve por alias del registry y no por ruta de archivo.** Una URI de la forma
`models:/<modelo>@produccion`
es lo que permite promover una version nueva sin volver a desplegar el servicio: quien
promueve mueve el alias y el proximo arranque toma el modelo nuevo. Una ruta a un `.pkl`
obligaria a reconstruir la imagen para cambiar de modelo.

**Los modelos se cargan una sola vez, al arrancar.** Cargar por peticion agrega cientos de
milisegundos y una dependencia dura del registry en el camino critico: si MLflow se cae, un
servicio que ya cargo sigue respondiendo y uno que carga por peticion se cae con el.

**El servicio arranca aunque falte un modelo.** Un despliegue donde todavia no se entreno el
clasificador debe poder estimar la ley igual, y `/health` lo dice con `estado='sin_modelo'`.
Reventar al arrancar convertiria un servicio a medias en un servicio caido.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import mlflow
import pandas as pd

from aurum_pipeline import domain
from aurum_pipeline.errors import AurumError
from aurum_pipeline.modeling.tracking import resolver_uri
from aurum_pipeline.serving.schemas import CondicionesTurno, PrediccionTurno

logger = logging.getLogger(__name__)

#: Variables de entorno con que se apunta a otro modelo sin tocar el codigo.
VARIABLE_MODELO_LEY: str = "AURUM_MODEL_LEY"
VARIABLE_MODELO_FALLA: str = "AURUM_MODEL_FALLA"


def uri_modelo(nombre: str, alias: str = domain.ALIAS_PRODUCCION) -> str:
    """URI del registry para un modelo y un alias."""
    return f"models:/{nombre}@{alias}"


class ModeloNoDisponibleError(AurumError):
    """Se pidio una prediccion que necesita un modelo que no se pudo cargar."""

    def __init__(self, uri: str) -> None:
        super().__init__(
            f"No hay modelo disponible en {uri}: entrena y registra el modelo, "
            "o apunta el servicio a otro con la variable de entorno correspondiente.")


class PredictorAurum:
    """Estima la ley del proximo turno y la probabilidad de falla de un frente.

    Se construye con las URI de los dos modelos y las carga en `cargar()`, que es una llamada
    explicita y no trabajo escondido en el constructor: quien la invoca decide cuando pagar el
    costo, y en el servicio eso ocurre en el arranque.
    """

    def __init__(
        self,
        uri_ley: str | None = None,
        uri_falla: str | None = None,
        uri_seguimiento: str | None = None,
    ) -> None:
        self.uri_ley = uri_ley or os.environ.get(
            VARIABLE_MODELO_LEY, uri_modelo(domain.MODELO_LEY_REGISTRADO))
        self.uri_falla = uri_falla or os.environ.get(
            VARIABLE_MODELO_FALLA, uri_modelo(domain.MODELO_FALLA_REGISTRADO))
        self.uri_seguimiento = uri_seguimiento or resolver_uri()
        self.modelo_ley: Any | None = None
        self.modelo_falla: Any | None = None

    # -- ciclo de vida ------------------------------------------------------------------

    def cargar(self) -> None:
        """Carga los dos modelos del registry, tolerando que alguno no exista todavia."""
        mlflow.set_tracking_uri(self.uri_seguimiento)
        mlflow.set_registry_uri(self.uri_seguimiento)
        self.modelo_ley = self._cargar_uno(self.uri_ley)
        self.modelo_falla = self._cargar_uno(self.uri_falla)

    @property
    def listo(self) -> bool:
        """El servicio puede responder `/predict` si al menos tiene el modelo de ley."""
        return self.modelo_ley is not None

    # -- prediccion ---------------------------------------------------------------------

    def predecir(self, condiciones: CondicionesTurno) -> PrediccionTurno:
        """Estima la ley del proximo turno y, si hay clasificador, la probabilidad de falla.

        Las alertas del diccionario se calculan siempre, tenga o no modelo el servicio: son
        una regla del dominio y no una salida aprendida.
        """
        if self.modelo_ley is None:
            raise ModeloNoDisponibleError(self.uri_ley)

        marco = condiciones.como_marco()
        ley = float(self.modelo_ley.predict(marco)[0])
        probabilidad = self._probabilidad_de_falla(marco)
        return PrediccionTurno(
            frente_id=condiciones.frente_id,
            ley_estimada=ley,
            prob_falla_4h=probabilidad,
            alertas=condiciones.alertas(),
            modelo_ley=self.uri_ley,
            modelo_falla=self.uri_falla if probabilidad is not None else None,
        )

    # -- interno ------------------------------------------------------------------------

    def _probabilidad_de_falla(self, marco: pd.DataFrame) -> float | None:
        """Probabilidad de la clase positiva, o `None` si no hay clasificador cargado.

        El modelo llega envuelto por MLflow como `pyfunc`, cuyo `predict` de un clasificador
        de scikit-learn devuelve la clase y no la probabilidad. Se desenvuelve al estimador
        original para pedirle `predict_proba`, que es lo que operaciones necesita: una clase
        no se puede ordenar por urgencia y una probabilidad si.
        """
        if self.modelo_falla is None:
            return None
        estimador = getattr(self.modelo_falla, "_model_impl", None)
        interno = getattr(estimador, "sklearn_model", None)
        if interno is not None and hasattr(interno, "predict_proba"):
            return float(interno.predict_proba(marco)[:, 1][0])
        return float(self.modelo_falla.predict(marco)[0])

    @staticmethod
    def _cargar_uno(uri: str) -> Any | None:
        """Carga un modelo del registry, devolviendo `None` si no esta publicado."""
        try:
            modelo = mlflow.pyfunc.load_model(uri)
        except Exception as error:
            logger.warning("No se pudo cargar el modelo %s: %s", uri, error)
            return None
        logger.info("Modelo cargado desde %s", uri)
        return modelo
