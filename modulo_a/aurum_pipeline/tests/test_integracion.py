"""Prueba de integracion sobre el extracto real.

Las demas pruebas usan datos sinteticos y por eso corren en cualquier maquina; esta existe
para el riesgo que esas no cubren: que el pipeline pase todas las pruebas y falle contra el
archivo verdadero por un tipo, un orden o una escala inesperados. Se salta sola cuando el
extracto no esta disponible, de modo que nunca rompe una instalacion limpia.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from aurum_pipeline import AurumFeatureBuilder, AurumImputer, AurumShiftEncoder, domain


def localizar_extracto() -> Path | None:
    """Devuelve la ruta del extracto real, o None si no esta en esta maquina."""
    del_entorno = os.environ.get("AURUM_CSV_PATH")
    if del_entorno and Path(del_entorno).exists():
        return Path(del_entorno)
    for padre in Path(__file__).resolve().parents:
        candidato = padre / "data" / "OP_AURUM_extract.csv"
        if candidato.exists():
            return candidato
    return None


@pytest.fixture(scope="module")
def extracto_real() -> pd.DataFrame:
    ruta = localizar_extracto()
    if ruta is None:
        pytest.skip("el extracto no esta disponible; define AURUM_CSV_PATH o copialo en data/")
    return pd.read_csv(ruta, parse_dates=[domain.COLUMNA_TIEMPO])


@pytest.mark.integracion
def test_el_pipeline_completo_corre_sobre_el_extracto_real(extracto_real: pd.DataFrame) -> None:
    """Encadena los tres transformadores y comprueba lo que el EDA dejo medido."""
    datos = extracto_real.sort_values(domain.COLUMNA_TIEMPO)
    imputado = AurumImputer().fit_transform(datos)
    codificado = AurumShiftEncoder().fit_transform(imputado)
    final = AurumFeatureBuilder().fit_transform(codificado)

    centinelas = datos[domain.COLUMNA_LEY].eq(domain.CENTINELA_LEY).sum()
    assert centinelas == 2810, "el extracto cambio: ya no son 2810 centinelas"
    assert not final[domain.COLUMNA_LEY].eq(domain.CENTINELA_LEY).any(), \
        "quedo un centinela sin tratar"
    assert final.loc[final["flag_imputed"], domain.COLUMNA_LEY].isna().all(), \
        "una fila marcada como no imputable quedo con valor de ley"
    assert list(final.columns[:len(datos.columns)]) == list(datos.columns), \
        "se altero el orden o el nombre de las columnas originales"
    for feature in AurumFeatureBuilder.FEATURES:
        assert feature in final.columns


@pytest.mark.integracion
def test_ninguna_feature_mira_su_propia_fila(extracto_real: pd.DataFrame) -> None:
    """La ventana y el rezago tienen que diferir del valor de la fila que describen.

    Si la historia se duplicara, el rezago devolveria la ley de la propia fila y la ventana la
    incluiria: la correlacion con el objetivo seria perfecta y el modelo, una ilusion.
    """
    datos = extracto_real.sort_values(domain.COLUMNA_TIEMPO)
    final = AurumFeatureBuilder().fit_transform(AurumImputer().fit_transform(datos))
    comparables = final.dropna(subset=["ley_lag_1", domain.COLUMNA_LEY])
    correlacion = comparables["ley_lag_1"].corr(comparables[domain.COLUMNA_LEY])
    assert correlacion < 0.95, f"ley_lag_1 replica el objetivo (corr={correlacion:.4f})"
    assert (final["dias_desde_evento_previo"].dropna() > 0).all(), \
        "hay antiguedades en cero: la historia esta duplicada"
