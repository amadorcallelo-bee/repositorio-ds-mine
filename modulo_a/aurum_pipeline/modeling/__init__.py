"""Modelado del Ejercicio A-2: regresion de ley y clasificacion de falla.

El paquete se separa de `transformers` porque su contrato es distinto: los transformadores
producen columnas y este paquete produce estimaciones y metricas. La separacion tambien
mantiene la frontera de dependencias, que es la que permite correr las pruebas del A-1 sin
tener instalados LightGBM, XGBoost ni MLflow.

Modulos previstos, en el orden en que se ejecutan:

- `dataset.py`   arma la matriz supervisada sobre la salida del pipeline del A-1: objetivo
                 de regresion (ley del turno siguiente del mismo frente) y etiqueta de
                 clasificacion (falla del equipo en las proximas cuatro horas).
- `splitter.py`  particion temporal. Nunca aleatoria: el objetivo mira al futuro y una
                 particion barajada entrena con informacion posterior a la que predice.
- `baselines.py` los dos baselines contra los que se mide todo lo demas.
- `models.py`    contrato comun sobre LightGBM y XGBoost, para que la comparacion sea entre
                 modelos y no entre dos formas distintas de llamarlos.
- `metrics.py`   metricas de ambos objetivos, con su lectura operacional.
- `tracking.py`  envoltura de MLflow con nombres que un operador de mina pueda leer.
- `explain.py`   valores SHAP del modelo de regresion.
"""
