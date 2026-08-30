"""Pruebas del contrato comun de los transformadores."""

from __future__ import annotations

import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import MissingColumnsError, NotFittedError
from aurum_pipeline.transformers.base import AurumTransformer


class TransformadorDePrueba(AurumTransformer):
    """Implementacion minima para ejercitar la clase base sin logica de dominio."""

    columnas_requeridas: tuple[str, ...] = (domain.COLUMNA_FRENTE,)

    def _fit(self, X: pd.DataFrame, y: pd.Series | None) -> None:
        self.filas_vistas_ = len(X)

    def _transform(self, X: pd.DataFrame) -> pd.DataFrame:
        X["marca"] = 1
        return X


def test_no_se_puede_instanciar_la_clase_abstracta() -> None:
    with pytest.raises(TypeError):
        AurumTransformer()  # type: ignore[abstract]


def test_transform_sin_fit_falla_con_mensaje_propio(ventana_completa: pd.DataFrame) -> None:
    with pytest.raises(NotFittedError, match="no esta ajustado"):
        TransformadorDePrueba().transform(ventana_completa)


def test_columna_faltante_falla_nombrandola() -> None:
    sin_frente = pd.DataFrame({"otra": [1, 2]})
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FRENTE):
        TransformadorDePrueba().fit(sin_frente)


def test_fit_devuelve_el_propio_transformador(ventana_completa: pd.DataFrame) -> None:
    transformador = TransformadorDePrueba()
    assert transformador.fit(ventana_completa) is transformador


def test_transform_no_muta_el_marco_de_entrada(ventana_completa: pd.DataFrame) -> None:
    original = ventana_completa.copy(deep=True)
    TransformadorDePrueba().fit_transform(ventana_completa)
    pd.testing.assert_frame_equal(ventana_completa, original)


def test_fit_transform_equivale_a_fit_mas_transform(ventana_completa: pd.DataFrame) -> None:
    encadenado = TransformadorDePrueba().fit(ventana_completa).transform(ventana_completa)
    de_una = TransformadorDePrueba().fit_transform(ventana_completa)
    pd.testing.assert_frame_equal(encadenado, de_una)


def test_el_log_nombra_los_frentes_procesados(
        ventana_completa: pd.DataFrame, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG", logger="aurum_pipeline.transformers.base"):
        TransformadorDePrueba().fit(ventana_completa)
    assert "frente_id=FR-A" in caplog.text



def test_el_log_tolera_un_marco_sin_columna_de_frente(caplog: pytest.LogCaptureFixture) -> None:
    """Un marco sin `frente_id` no rompe el registro: se anota el total y se sigue."""

    class SinRequisitos(TransformadorDePrueba):
        columnas_requeridas: tuple[str, ...] = ()

    datos = pd.DataFrame({"otra": [1, 2, 3]})
    with caplog.at_level("INFO", logger="aurum_pipeline.transformers.base"):
        SinRequisitos().fit(datos)
    assert "sin columna de frente" in caplog.text
