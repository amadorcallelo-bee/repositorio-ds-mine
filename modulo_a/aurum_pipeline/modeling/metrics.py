"""Metricas de la regresion de ley, con nombres que un operador de mina pueda leer.

La metrica principal es el error absoluto medio en gramos por tonelada. No es una eleccion
estetica: g/t es la unidad con la que la mina decide mezcla y ley de corte, de modo que un
error de 0.40 g/t se traduce directo a una decision de planta. El error cuadratico se reporta
al lado porque castiga los turnos raros, y la varianza explicada porque es lo que permite
comparar contra el techo del problema, pero ninguna de las dos se lee en unidades del negocio.

Se reporta ademas el error por frente. Un promedio global esconde que un frente concreto este
mal predicho, y en operacion la pregunta no es "cuanto se equivoca el modelo" sino "en cual de
mis trece frentes no puedo confiar".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)

from aurum_pipeline.errors import InvalidParameterError

Vector = npt.NDArray[np.float64]


@dataclass(frozen=True)
class MetricasRegresion:
    """Resultado de evaluar una prediccion de ley contra su objetivo."""

    error_medio_g_por_tonelada: float
    error_cuadratico_g_por_tonelada: float
    error_relativo_pct: float
    varianza_explicada: float
    turnos: int

    #: El error medio es la metrica principal y aqui menos es mejor. Lo declara la clase para
    #: que el codigo de comparacion no tenga que suponerlo.
    mejor_es_mayor: ClassVar[bool] = False

    @property
    def valor_principal(self) -> float:
        """Error absoluto medio en gramos por tonelada."""
        return self.error_medio_g_por_tonelada

    def como_diccionario(self) -> dict[str, float]:
        """Metricas listas para registrar en MLflow, con los nombres del negocio."""
        return {
            "error_medio_g_por_tonelada": self.error_medio_g_por_tonelada,
            "error_cuadratico_g_por_tonelada": self.error_cuadratico_g_por_tonelada,
            "error_relativo_pct": self.error_relativo_pct,
            "varianza_explicada": self.varianza_explicada,
            "turnos": float(self.turnos),
        }


def evaluar(objetivo: Vector, prediccion: Vector) -> MetricasRegresion:
    """Calcula las cuatro metricas de una prediccion.

    La varianza explicada se calcula contra la media del propio conjunto evaluado, que es la
    definicion habitual de R2 y la que hace comparable un pliegue con otro.
    """
    y = np.asarray(objetivo, dtype=float)
    p = np.asarray(prediccion, dtype=float)
    if y.shape != p.shape:
        raise InvalidParameterError(
            f"objetivo y prediccion no coinciden: {y.shape} contra {p.shape}")
    if y.size == 0:
        raise InvalidParameterError("no hay turnos que evaluar")
    if not np.isfinite(p).all():
        raise InvalidParameterError("la prediccion trae valores no finitos")

    residuo = y - p
    mae = float(np.abs(residuo).mean())
    rmse = float(np.sqrt((residuo**2).mean()))
    media = float(y.mean())
    varianza = float(((y - media) ** 2).sum())
    # Un conjunto donde el objetivo es constante no tiene varianza que explicar; devolver 0
    # es preferible a una division por cero o a un infinito que despues promedia mal.
    r2 = 1.0 - float((residuo**2).sum()) / varianza if varianza > 0 else 0.0
    relativo = 100.0 * mae / abs(media) if media != 0 else float("nan")
    return MetricasRegresion(
        error_medio_g_por_tonelada=mae,
        error_cuadratico_g_por_tonelada=rmse,
        error_relativo_pct=relativo,
        varianza_explicada=r2,
        turnos=int(y.size),
    )


def error_por_frente(
    frentes: pd.Series,
    objetivo: Vector,
    prediccion: Vector,
) -> pd.DataFrame:
    """Error absoluto medio de cada frente, de peor a mejor.

    Se ordena por error descendente porque quien lo lee busca donde no confiar, no donde si.
    """
    detalle = pd.DataFrame({
        "frente_id": np.asarray(frentes),
        "error_absoluto": np.abs(np.asarray(objetivo, float) - np.asarray(prediccion, float)),
    })
    resumen = (
        detalle.groupby("frente_id")["error_absoluto"]
        .agg(error_medio_g_por_tonelada="mean", turnos="size")
        .reset_index()
        .sort_values("error_medio_g_por_tonelada", ascending=False)
        .reset_index(drop=True)
    )
    return resumen


def mejora_vs_baseline_pct(error_modelo: float, error_baseline: float) -> float:
    """Cuanto reduce el modelo el error del baseline, en porcentaje.

    Positivo significa que el modelo mejora. Es la cifra que decide si vale la pena poner un
    gradiente en produccion en lugar de una media por frente.
    """
    if error_baseline <= 0:
        raise InvalidParameterError(
            f"el error del baseline debe ser positivo, se recibio {error_baseline}")
    return 100.0 * (error_baseline - error_modelo) / error_baseline


@dataclass(frozen=True)
class MetricasClasificacion:
    """Resultado de evaluar una probabilidad de falla contra su etiqueta.

    Se guarda la tasa base al lado de las metricas porque sin ella ninguna es interpretable:
    una precision media de 0.22 es exactamente el azar cuando el 22% de los turnos falla, y
    seria un resultado notable si fallara el 3%.

    La precision media **con actividad** se calcula solo sobre las ventanas en que el frente
    registro eventos, y es el detector de senal mecanica: la etiqueta es cero por construccion
    cuando el frente se apago, de modo que un modelo que solo anticipe la continuidad
    operativa se luce en la metrica global y vuelve a la tasa base en esta. Lleva su propia
    tasa base al lado, por la misma razon que la global.
    """

    precision_media: float
    exhaustividad_al_50_pct: float
    area_bajo_roc: float
    error_brier: float
    tasa_base: float
    precision_media_con_actividad: float
    tasa_base_con_actividad: float
    turnos: int

    #: La precision media es la metrica principal y aqui mas es mejor, al reves que en la
    #: regresion. Lo declara la clase para que el codigo de comparacion no lo suponga.
    mejor_es_mayor: ClassVar[bool] = True

    @property
    def valor_principal(self) -> float:
        """Precision media, que es el area bajo la curva de precision y exhaustividad."""
        return self.precision_media

    @property
    def levante_sobre_azar(self) -> float:
        """Cuantas veces mejor que el azar. Uno significa que el modelo no aporta nada."""
        return self.precision_media / self.tasa_base if self.tasa_base > 0 else float("nan")

    def como_diccionario(self) -> dict[str, float]:
        """Metricas listas para registrar en MLflow, con los nombres del negocio."""
        return {
            "precision_media": self.precision_media,
            "exhaustividad_al_50_pct_precision": self.exhaustividad_al_50_pct,
            "area_bajo_roc": self.area_bajo_roc,
            "error_brier": self.error_brier,
            "tasa_base_falla": self.tasa_base,
            "levante_sobre_azar": self.levante_sobre_azar,
            "precision_media_con_actividad": self.precision_media_con_actividad,
            "tasa_base_con_actividad": self.tasa_base_con_actividad,
            "turnos": float(self.turnos),
        }


def _precision_media(etiqueta: Vector, probabilidad: Vector) -> tuple[float, float]:
    """Precision media y tasa base de un subconjunto, con los casos degenerados resueltos.

    Un bloque sin ningun positivo -o sin ningun negativo- no tiene precision media definida;
    se devuelve la tasa base, que es el valor que le corresponde al azar, en lugar de un `NaN`
    que despues contamina el promedio de los pliegues. Un bloque vacio devuelve cero en ambas.
    """
    if etiqueta.size == 0:
        return 0.0, 0.0
    tasa_base = float(etiqueta.mean())
    if tasa_base in (0.0, 1.0):
        return tasa_base, tasa_base
    return float(average_precision_score(etiqueta, probabilidad)), tasa_base


def evaluar_falla(
    etiqueta: Vector,
    probabilidad: Vector,
    con_actividad: Vector | None = None,
) -> MetricasClasificacion:
    """Calcula las metricas de una probabilidad de falla.

    `con_actividad` marca, por turno, si la ventana de cuatro horas tuvo registros del frente.
    Sobre esas ventanas se calcula la precision media con actividad. Sin la marca se asume que
    todas las ventanas tuvieron registros, y la metrica condicional coincide con la global.
    """
    y = np.asarray(etiqueta, dtype=float)
    p = np.asarray(probabilidad, dtype=float)
    if y.shape != p.shape:
        raise InvalidParameterError(
            f"etiqueta y probabilidad no coinciden: {y.shape} contra {p.shape}")
    if y.size == 0:
        raise InvalidParameterError("no hay turnos que evaluar")
    if not np.isfinite(p).all():
        raise InvalidParameterError("la probabilidad trae valores no finitos")
    if con_actividad is None:
        activas = np.ones(y.size, dtype=bool)
    else:
        marca = np.asarray(con_actividad, dtype=float)
        if marca.shape != y.shape:
            raise InvalidParameterError(
                f"etiqueta y marca de actividad no coinciden: {y.shape} contra {marca.shape}")
        activas = marca > 0

    tasa_base = float(y.mean())
    brier = float(((p - y) ** 2).mean())
    precision_activa, tasa_activa = _precision_media(y[activas], p[activas])
    if tasa_base in (0.0, 1.0):
        return MetricasClasificacion(
            precision_media=tasa_base, exhaustividad_al_50_pct=0.0, area_bajo_roc=0.5,
            error_brier=brier, tasa_base=tasa_base,
            precision_media_con_actividad=precision_activa,
            tasa_base_con_actividad=tasa_activa, turnos=int(y.size))

    precision, exhaustividad, _ = precision_recall_curve(y, p)
    utiles = precision >= 0.5
    return MetricasClasificacion(
        precision_media=float(average_precision_score(y, p)),
        exhaustividad_al_50_pct=float(exhaustividad[utiles].max()) if utiles.any() else 0.0,
        area_bajo_roc=float(roc_auc_score(y, p)),
        error_brier=brier,
        tasa_base=tasa_base,
        precision_media_con_actividad=precision_activa,
        tasa_base_con_actividad=tasa_activa,
        turnos=int(y.size),
    )
