"""Datos sinteticos para las pruebas del pipeline.

Las pruebas no leen `OP_AURUM_extract.csv`: tienen que correr en una maquina limpia, sin la
variable `AURUM_CSV_PATH` ni el archivo, y tienen que fallar por el motivo que cada prueba
declara y no porque el extracto real cambio. Los marcos de aqui son pequenos, escritos a
mano y deterministas, con la estructura minima que el pipeline necesita.
"""

from __future__ import annotations

import pandas as pd
import pytest

from aurum_pipeline import domain

INICIO = pd.Timestamp("2025-01-10 00:00:00")


def marco(filas: list[tuple[float, float, str, str]]) -> pd.DataFrame:
    """Construye un marco OPUS minimo a partir de (dias, ley, frente, tipo).

    `dias` se cuenta desde una fecha fija, de modo que cada prueba escribe distancias
    temporales legibles en lugar de timestamps completos.
    """
    return pd.DataFrame({
        domain.COLUMNA_TIEMPO: [INICIO + pd.Timedelta(days=d) for d, _, _, _ in filas],
        domain.COLUMNA_LEY: [ley for _, ley, _, _ in filas],
        domain.COLUMNA_FRENTE: [frente for _, _, frente, _ in filas],
        domain.COLUMNA_TIPO_MINERAL: [tipo for _, _, _, tipo in filas],
        domain.COLUMNA_EQUIPO: ["EQ-01" for _ in filas],
    })


@pytest.fixture
def ventana_completa() -> pd.DataFrame:
    """Cinco lecturas validas en los ultimos siete dias y un centinela al final.

    Es el caso nominal del imputador: la ventana alcanza el minimo exigido, de modo que la
    fila se imputa con la mediana de esas cinco lecturas, que es 5.0.
    """
    return marco([
        (0.0, 1.0, "FR-A", "OX"),
        (1.0, 3.0, "FR-A", "OX"),
        (2.0, 5.0, "FR-A", "OX"),
        (3.0, 7.0, "FR-A", "OX"),
        (4.0, 9.0, "FR-A", "OX"),
        (5.0, domain.CENTINELA_LEY, "FR-A", "OX"),
    ])


@pytest.fixture
def ventana_insuficiente() -> pd.DataFrame:
    """Cuatro lecturas validas y un centinela: la ventana no alcanza el minimo de cinco."""
    return marco([
        (0.0, 1.0, "FR-A", "OX"),
        (1.0, 3.0, "FR-A", "OX"),
        (2.0, 5.0, "FR-A", "OX"),
        (3.0, 7.0, "FR-A", "OX"),
        (4.0, domain.CENTINELA_LEY, "FR-A", "OX"),
    ])


@pytest.fixture
def marco_objetivo_por_categoria() -> pd.DataFrame:
    """Una categoria donde una sola fila concentra todo el valor del objetivo.

    Sirve para la prueba de fuga: si el codificado de la fila extrema incluyera su propio
    objetivo, el valor devuelto seria distinto de cero de forma evidente.
    """
    return pd.DataFrame({
        domain.COLUMNA_FRENTE: ["FR-A", "FR-A", "FR-A", "FR-A", "FR-B", "FR-B"],
        domain.COLUMNA_EQUIPO: ["EQ-01"] * 6,
        domain.COLUMNA_LEY: [0.0, 0.0, 0.0, 100.0, 10.0, 20.0],
    })
