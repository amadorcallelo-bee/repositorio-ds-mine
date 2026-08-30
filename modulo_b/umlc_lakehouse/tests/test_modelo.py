"""Pruebas del entrenador portado del A-2: particion temporal, metricas y brecha."""

from __future__ import annotations

from datetime import date

import pytest

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.modelo import EntrenadorLey
from umlc_lakehouse.tests.conftest import eventos_sinteticos


def test_el_entrenador_reproduce_el_nivel_del_frente() -> None:
    """Con leyes constantes por frente, el modelo del A-2 predice sin error."""
    entrenador = EntrenadorLey()
    modelo = entrenador.entrenar(eventos_sinteticos(dias=21))
    assert modelo.conjunto == "MINIMO"
    assert modelo.metricas[dominio.METRICA_ERROR] == pytest.approx(0.0, abs=1e-3)
    assert modelo.metricas[dominio.METRICA_ERROR_ENTRENAMIENTO] == pytest.approx(0.0, abs=1e-3)
    assert modelo.metricas[dominio.METRICA_BRECHA] == pytest.approx(
        modelo.metricas[dominio.METRICA_ERROR]
        - modelo.metricas[dominio.METRICA_ERROR_ENTRENAMIENTO], abs=1e-9)
    assert modelo.turnos_entrenamiento > modelo.turnos_evaluacion > 0
    assert list(modelo.ejemplo.columns) == [dominio.COLUMNA_FRENTE]


def test_la_particion_corta_por_los_ultimos_dias() -> None:
    entrenador = EntrenadorLey(dias_evaluacion=7)
    matriz = entrenador.matriz(eventos_sinteticos(dias=21))
    entrena, evalua, corte = entrenador.particion(matriz)
    assert corte == date(2025, 9, 15)
    assert len(entrena) + len(evalua) == len(matriz)
    assert entrena["inicio_turno_local"].dt.date.max() < corte
    assert evalua["inicio_turno_local"].dt.date.min() >= corte


def test_una_degradacion_en_la_ventana_se_mide() -> None:
    """Si la ley del frente cambia en la evaluacion, el error del modelo la refleja."""
    eventos = eventos_sinteticos(dias=21, ley_eval={"FR-B-02": 14.0})
    modelo = EntrenadorLey().entrenar(eventos)
    # El modelo aprende FR-B en 10 y la ventana lo mide contra 14: el error queda cerca
    # de la mitad del salto (la mitad de los turnos son de FR-A, que no cambio).
    assert modelo.metricas[dominio.METRICA_ERROR] > 1.5
    assert EntrenadorLey().evaluar_en_ventana(modelo.pipeline, eventos) == pytest.approx(
        modelo.metricas[dominio.METRICA_ERROR], rel=1e-9)


def test_precondiciones_del_entrenador() -> None:
    with pytest.raises(ParametroInvalidoError):
        EntrenadorLey(dias_evaluacion=0)
    with pytest.raises(ParametroInvalidoError, match="particion"):
        EntrenadorLey(dias_evaluacion=40).entrenar(eventos_sinteticos(dias=21))
