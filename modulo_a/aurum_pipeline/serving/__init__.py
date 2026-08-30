"""Servicio de inferencia del Ejercicio A-2: API FastAPI con endpoint `/predict`.

Se separa de `modeling` a proposito: la logica de prediccion tiene que poder probarse sin
levantar un servidor HTTP, y el paquete de modelado no debe arrastrar FastAPI como
dependencia para entrenar. La frontera es `predictor.py`, que no conoce a FastAPI, contra
`app.py`, que no conoce a LightGBM.

- `schemas.py`   contratos de entrada y salida en Pydantic, con los rangos del diccionario
                 de variables validados en el servidor y no solo documentados.
- `predictor.py` carga de los modelos registrados y prediccion. Sin HTTP adentro.
- `app.py`       aplicacion FastAPI: `/predict` y `/health`.
"""
