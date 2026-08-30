"""Pruebas del codificador por objetivo.

La prueba de fuga es obligatoria segun el enunciado y esta escrita de la forma mas dura
posible: una categoria donde una sola fila concentra todo el valor, de modo que si el
codificado la incluyera, el resultado seria evidentemente distinto de cero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError, NotFittedError
from aurum_pipeline.transformers.encoder import AurumShiftEncoder

COLUMNA_CODIFICADA = f"{domain.COLUMNA_FRENTE}_target_enc"


def test_leave_one_out_no_filtra_el_objetivo_de_la_propia_fila(
        marco_objetivo_por_categoria: pd.DataFrame) -> None:
    """La fila extrema de FR-A se codifica con el promedio de las otras tres, que es cero."""
    codificador = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0)
    resultado = codificador.fit_transform(marco_objetivo_por_categoria)
    fila_extrema = resultado.iloc[3]
    assert fila_extrema[domain.COLUMNA_LEY] == 100.0
    assert fila_extrema[COLUMNA_CODIFICADA] == pytest.approx(0.0)


def test_sin_leave_one_out_la_media_incluiria_la_fila(
        marco_objetivo_por_categoria: pd.DataFrame) -> None:
    """Contraste explicito: la media simple de FR-A es 25, y ese es el valor a evitar."""
    media_simple = marco_objetivo_por_categoria.groupby(domain.COLUMNA_FRENTE)[
        domain.COLUMNA_LEY].mean()["FR-A"]
    assert media_simple == pytest.approx(25.0)
    codificado = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0) \
        .fit_transform(marco_objetivo_por_categoria)
    assert codificado.iloc[3][COLUMNA_CODIFICADA] != pytest.approx(media_simple)


def test_transform_sobre_datos_nuevos_usa_la_media_completa(
        marco_objetivo_por_categoria: pd.DataFrame) -> None:
    """En datos nuevos no hay objetivo que dejar fuera: se aplica la media aprendida."""
    codificador = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0)
    codificador.fit(marco_objetivo_por_categoria)
    nuevos = pd.DataFrame({domain.COLUMNA_FRENTE: ["FR-A", "FR-B"],
                           domain.COLUMNA_LEY: [np.nan, np.nan]})
    resultado = codificador.transform(nuevos)
    assert resultado[COLUMNA_CODIFICADA].to_list() == pytest.approx([25.0, 15.0])


def test_categoria_no_vista_recibe_la_media_global(
        marco_objetivo_por_categoria: pd.DataFrame) -> None:
    codificador = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0)
    codificador.fit(marco_objetivo_por_categoria)
    nuevos = pd.DataFrame({domain.COLUMNA_FRENTE: ["FR-Z"], domain.COLUMNA_LEY: [np.nan]})
    resultado = codificador.transform(nuevos)
    media_global = marco_objetivo_por_categoria[domain.COLUMNA_LEY].mean()
    assert resultado[COLUMNA_CODIFICADA].iloc[0] == pytest.approx(media_global)


def test_el_suavizado_acerca_las_categorias_pequenas_a_la_media_global(
        marco_objetivo_por_categoria: pd.DataFrame) -> None:
    media_global = marco_objetivo_por_categoria[domain.COLUMNA_LEY].mean()
    sin_suavizar = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0) \
        .fit_transform(marco_objetivo_por_categoria)
    muy_suavizado = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=1000.0) \
        .fit_transform(marco_objetivo_por_categoria)
    distancia_sin = abs(sin_suavizar[COLUMNA_CODIFICADA] - media_global).mean()
    distancia_con = abs(muy_suavizado[COLUMNA_CODIFICADA] - media_global).mean()
    assert distancia_con < distancia_sin
    assert muy_suavizado[COLUMNA_CODIFICADA].iloc[0] == pytest.approx(media_global, abs=0.5)


def test_las_filas_sin_objetivo_no_entran_en_las_estadisticas() -> None:
    """Un centinela ya convertido en `NaN` no puede arrastrar la media de su categoria."""
    datos = pd.DataFrame({
        domain.COLUMNA_FRENTE: ["FR-A", "FR-A", "FR-A"],
        domain.COLUMNA_LEY: [10.0, 10.0, np.nan],
    })
    codificador = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0)
    codificador.fit(datos)
    assert codificador.estadisticas_[domain.COLUMNA_FRENTE].loc["FR-A", "count"] == 2
    assert codificador.prior_ == pytest.approx(10.0)


def test_codifica_todas_las_columnas_pedidas(marco_objetivo_por_categoria: pd.DataFrame) -> None:
    resultado = AurumShiftEncoder().fit_transform(marco_objetivo_por_categoria)
    assert f"{domain.COLUMNA_FRENTE}_target_enc" in resultado.columns
    assert f"{domain.COLUMNA_EQUIPO}_target_enc" in resultado.columns


def test_el_objetivo_explicito_manda_sobre_la_columna_de_ley(
        marco_objetivo_por_categoria: pd.DataFrame) -> None:
    objetivo = pd.Series([1.0] * len(marco_objetivo_por_categoria),
                         index=marco_objetivo_por_categoria.index)
    codificador = AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,), smoothing=0.0)
    codificador.fit(marco_objetivo_por_categoria, objetivo)
    assert codificador.prior_ == pytest.approx(1.0)


def test_no_muta_el_marco_de_entrada(marco_objetivo_por_categoria: pd.DataFrame) -> None:
    original = marco_objetivo_por_categoria.copy(deep=True)
    AurumShiftEncoder().fit_transform(marco_objetivo_por_categoria)
    pd.testing.assert_frame_equal(marco_objetivo_por_categoria, original)


def test_transform_sin_fit_falla(marco_objetivo_por_categoria: pd.DataFrame) -> None:
    with pytest.raises(NotFittedError):
        AurumShiftEncoder().transform(marco_objetivo_por_categoria)


def test_parametros_invalidos_fallan_al_construir() -> None:
    with pytest.raises(InvalidParameterError, match="smoothing"):
        AurumShiftEncoder(smoothing=-1.0)
    with pytest.raises(InvalidParameterError, match="al menos una columna"):
        AurumShiftEncoder(columnas=())


def test_sin_objetivo_utilizable_falla_con_mensaje_propio() -> None:
    datos = pd.DataFrame({domain.COLUMNA_FRENTE: ["FR-A"], domain.COLUMNA_LEY: [np.nan]})
    with pytest.raises(InvalidParameterError, match="objetivo utilizables"):
        AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,)).fit(datos)


def test_sin_y_ni_columna_objetivo_falla() -> None:
    datos = pd.DataFrame({domain.COLUMNA_FRENTE: ["FR-A", "FR-B"]})
    with pytest.raises(InvalidParameterError, match="columna objetivo"):
        AurumShiftEncoder(columnas=(domain.COLUMNA_FRENTE,)).fit(datos)
