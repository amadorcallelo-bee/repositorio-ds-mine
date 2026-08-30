"""API de inferencia del Ejercicio A-2.

Dos endpoints y una regla de diseno: `app.py` no conoce a LightGBM y `predictor.py` no conoce
a FastAPI. La frontera esta en `PredictorAurum`, y es lo que permite probar la prediccion sin
levantar un servidor y cambiar el servidor sin tocar la prediccion.

Los modelos se cargan en el `lifespan`, una sola vez al arrancar. Cargar por peticion agrega
cientos de milisegundos y mete al registry en el camino critico de cada llamada.

El servicio arranca aunque no haya modelos publicados: `/health` responde `sin_modelo` y
`/predict` devuelve 503, que es lo que corresponde a un servicio vivo pero incapaz de servir,
frente a un 500 que anunciaria un defecto.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status

from aurum_pipeline.serving.predictor import (
    ModeloNoDisponibleError,
    PredictorAurum,
)
from aurum_pipeline.serving.schemas import (
    CondicionesTurno,
    EstadoServicio,
    PrediccionTurno,
)

logger = logging.getLogger(__name__)

#: Clave con que el predictor viaja en el estado de la aplicacion. No es una variable de
#: modulo para que las pruebas puedan levantar dos aplicaciones con modelos distintos sin que
#: una pise a la otra.
CLAVE_PREDICTOR: str = "predictor"


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    """Carga los modelos al arrancar y los suelta al apagar."""
    predictor = getattr(app.state, CLAVE_PREDICTOR, None) or PredictorAurum()
    predictor.cargar()
    setattr(app.state, CLAVE_PREDICTOR, predictor)
    logger.info("Servicio listo: %s", "con modelo de ley" if predictor.listo
                else "sin modelo de ley")
    yield
    setattr(app.state, CLAVE_PREDICTOR, None)


def crear_aplicacion(predictor: PredictorAurum | None = None) -> FastAPI:
    """Construye la aplicacion, opcionalmente con un predictor ya provisto.

    El parametro existe para las pruebas y para un despliegue que quiera apuntar a otro
    registry sin variables de entorno; en produccion se llama sin argumentos.
    """
    app = FastAPI(
        title="AURUM - inferencia operacional UMLC",
        summary="Estima la ley del proximo turno y la probabilidad de falla a 4 horas",
        version="1.0.0",
        lifespan=_ciclo_de_vida,
    )
    if predictor is not None:
        setattr(app.state, CLAVE_PREDICTOR, predictor)

    @app.get("/health", response_model=EstadoServicio, tags=["operacion"])
    def salud(request: Request) -> EstadoServicio:
        """Estado del servicio y modelos cargados."""
        actual: PredictorAurum = getattr(request.app.state, CLAVE_PREDICTOR)
        return EstadoServicio(
            estado="listo" if actual.listo else "sin_modelo",
            modelo_ley=actual.uri_ley if actual.modelo_ley is not None else None,
            modelo_falla=actual.uri_falla if actual.modelo_falla is not None else None,
            uri_seguimiento=actual.uri_seguimiento,
        )

    @app.post("/predict", response_model=PrediccionTurno, tags=["operacion"])
    def predecir(condiciones: CondicionesTurno, request: Request) -> PrediccionTurno:
        """Estima la ley del proximo turno y la probabilidad de falla del frente.

        Los valores fuera del rango operacional del diccionario no se rechazan: se aceptan y
        vuelven marcados en `alertas`. Solo lo fisicamente imposible produce un 422, y lo
        resuelve Pydantic antes de llegar aqui.
        """
        actual: PredictorAurum = getattr(request.app.state, CLAVE_PREDICTOR)
        try:
            return actual.predecir(condiciones)
        except ModeloNoDisponibleError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error

    return app


#: Aplicacion por defecto, la que levanta `uvicorn aurum_pipeline.serving.app:app`.
app = crear_aplicacion()
