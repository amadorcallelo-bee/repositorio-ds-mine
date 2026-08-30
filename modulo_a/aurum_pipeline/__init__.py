"""Pipeline de preprocesamiento del extracto OPUS-MINE (Ejercicio A-1).

Expone los transformadores del pipeline y deja el logging en manos de la aplicacion: una
libreria que configura logging le impone su formato a todo el proceso que la importa, asi
que aqui solo se instala un `NullHandler` y el notebook o el servicio deciden el resto.
"""

from __future__ import annotations

import logging

from aurum_pipeline.transformers.base import AurumTransformer
from aurum_pipeline.transformers.encoder import AurumShiftEncoder
from aurum_pipeline.transformers.features import AurumFeatureBuilder
from aurum_pipeline.transformers.imputer import AurumImputer

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["AurumFeatureBuilder", "AurumImputer", "AurumShiftEncoder", "AurumTransformer"]
