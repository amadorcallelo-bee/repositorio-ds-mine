"""Pruebas del imputador del valor especial de la ley.

El caso borde del centinela es obligatorio segun el enunciado y esta cubierto en las dos
direcciones: la fila con ventana suficiente se imputa, la fila con ventana escasa se marca.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.tests.conftest import INICIO, marco
from aurum_pipeline.transformers.imputer import AurumImputer


def test_el_centinela_se_imputa_con_la_mediana_de_la_ventana(
        ventana_completa: pd.DataFrame) -> None:
    resultado = AurumImputer().fit_transform(ventana_completa)
    ultima = resultado.iloc[-1]
    assert ultima[domain.COLUMNA_LEY] == pytest.approx(5.0)
    assert ultima["flag_imputed"] is np.False_ or ultima["flag_imputed"] is False


def test_ventana_escasa_marca_la_fila_y_deja_la_ley_faltante(
        ventana_insuficiente: pd.DataFrame) -> None:
    resultado = AurumImputer().fit_transform(ventana_insuficiente)
    ultima = resultado.iloc[-1]
    assert bool(ultima["flag_imputed"]) is True
    assert pd.isna(ultima[domain.COLUMNA_LEY])


def test_el_limite_de_registros_es_exacto(ventana_completa: pd.DataFrame) -> None:
    """Con cinco vecinas imputa; exigiendo seis, la misma ventana ya no alcanza."""
    con_cinco = AurumImputer(minimo_registros=5).fit_transform(ventana_completa)
    con_seis = AurumImputer(minimo_registros=6).fit_transform(ventana_completa)
    assert not bool(con_cinco.iloc[-1]["flag_imputed"])
    assert bool(con_seis.iloc[-1]["flag_imputed"])


def test_la_ventana_es_estrictamente_pasada() -> None:
    """Las lecturas posteriores al centinela no participan de su mediana."""
    datos = marco([
        (0.0, 1.0, "FR-A", "OX"),
        (1.0, 1.0, "FR-A", "OX"),
        (2.0, 1.0, "FR-A", "OX"),
        (3.0, 1.0, "FR-A", "OX"),
        (4.0, 1.0, "FR-A", "OX"),
        (5.0, domain.CENTINELA_LEY, "FR-A", "OX"),
        (6.0, 99.0, "FR-A", "OX"),
        (6.5, 99.0, "FR-A", "OX"),
    ])
    resultado = AurumImputer().fit_transform(datos)
    assert resultado.iloc[5][domain.COLUMNA_LEY] == pytest.approx(1.0)


def test_el_borde_de_siete_dias_es_exacto() -> None:
    """La ventana es `[t - 7 dias, t)`: lo de hace siete dias justos cuenta, lo anterior no."""
    recientes = [(4.0, 1.0, "FR-A", "OX"), (5.0, 1.0, "FR-A", "OX"),
                 (6.0, 1.0, "FR-A", "OX"), (6.5, 1.0, "FR-A", "OX")]
    centinela = (7.0, domain.CENTINELA_LEY, "FR-A", "OX")

    justo_en_el_borde = marco([(0.0, 9.0, "FR-A", "OX"), *recientes, centinela])
    resultado = AurumImputer().fit_transform(justo_en_el_borde)
    assert not bool(resultado.iloc[-1]["flag_imputed"]), "hace 7 dias justos entra en la ventana"
    assert resultado.iloc[-1][domain.COLUMNA_LEY] == pytest.approx(1.0)

    apenas_afuera = marco([(-0.01, 9.0, "FR-A", "OX"), *recientes, centinela])
    resultado = AurumImputer().fit_transform(apenas_afuera)
    assert bool(resultado.iloc[-1]["flag_imputed"]) is True, "hace mas de 7 dias queda fuera"


def test_otro_grupo_no_aporta_vecinas() -> None:
    """La vecindad es frente y tipo de mineral: otro tipo no sirve aunque sea el mismo frente."""
    datos = marco([
        (0.0, 4.0, "FR-A", "SUL"),
        (1.0, 4.0, "FR-A", "SUL"),
        (2.0, 4.0, "FR-A", "SUL"),
        (3.0, 4.0, "FR-A", "SUL"),
        (4.0, 4.0, "FR-A", "SUL"),
        (5.0, domain.CENTINELA_LEY, "FR-A", "OX"),
    ])
    resultado = AurumImputer().fit_transform(datos)
    assert bool(resultado.iloc[-1]["flag_imputed"]) is True


def test_las_lecturas_validas_no_se_tocan(ventana_completa: pd.DataFrame) -> None:
    resultado = AurumImputer().fit_transform(ventana_completa)
    validas = resultado.iloc[:-1][domain.COLUMNA_LEY]
    pd.testing.assert_series_equal(validas, ventana_completa.iloc[:-1][domain.COLUMNA_LEY])


def test_un_centinela_inesperado_tambien_se_trata(caplog: pytest.LogCaptureFixture) -> None:
    """Un cero es tan imposible como un negativo: se trata igual y queda avisado en el log."""
    datos = marco([
        (0.0, 2.0, "FR-A", "OX"),
        (1.0, 4.0, "FR-A", "OX"),
        (2.0, 6.0, "FR-A", "OX"),
        (3.0, 8.0, "FR-A", "OX"),
        (4.0, 10.0, "FR-A", "OX"),
        (5.0, 0.0, "FR-A", "OX"),
    ])
    with caplog.at_level("WARNING", logger="aurum_pipeline.transformers.imputer"):
        resultado = AurumImputer().fit_transform(datos)
    assert resultado.iloc[-1][domain.COLUMNA_LEY] == pytest.approx(6.0)
    assert "distintos del centinela" in caplog.text


def test_transformar_datos_nuevos_usa_la_historia_del_ajuste(
        ventana_completa: pd.DataFrame) -> None:
    """Una fila nueva sin vecinas propias se imputa con lo aprendido en el ajuste."""
    imputador = AurumImputer().fit(ventana_completa)
    nueva = marco([(5.5, domain.CENTINELA_LEY, "FR-A", "OX")])
    resultado = imputador.transform(nueva)
    assert resultado.iloc[0][domain.COLUMNA_LEY] == pytest.approx(5.0)
    assert not bool(resultado.iloc[0]["flag_imputed"])


def test_transformar_el_mismo_marco_no_duplica_la_historia(
        ventana_insuficiente: pd.DataFrame) -> None:
    """Ajustar y transformar el mismo marco no puede inflar el conteo de la ventana.

    Sin deduplicar, las cuatro vecinas se contarian dos veces, la regla del minimo se
    cumpliria por un artefacto y la fila quedaria imputada en lugar de marcada.
    """
    imputador = AurumImputer().fit(ventana_insuficiente)
    resultado = imputador.transform(ventana_insuficiente)
    assert bool(resultado.iloc[-1]["flag_imputed"]) is True


def test_fit_no_muta_el_marco(ventana_completa: pd.DataFrame) -> None:
    original = ventana_completa.copy(deep=True)
    AurumImputer().fit(ventana_completa)
    pd.testing.assert_frame_equal(ventana_completa, original)


def test_parametros_invalidos_fallan_al_construir() -> None:
    with pytest.raises(InvalidParameterError, match="ventana_dias"):
        AurumImputer(ventana_dias=0)
    with pytest.raises(InvalidParameterError, match="minimo_registros"):
        AurumImputer(minimo_registros=0)


def test_la_ventana_es_configurable() -> None:
    """Con una ventana mas larga, vecinas viejas vuelven a contar."""
    datos = marco([
        (0.0, 2.0, "FR-A", "OX"),
        (1.0, 2.0, "FR-A", "OX"),
        (2.0, 2.0, "FR-A", "OX"),
        (3.0, 2.0, "FR-A", "OX"),
        (4.0, 2.0, "FR-A", "OX"),
        (20.0, domain.CENTINELA_LEY, "FR-A", "OX"),
    ])
    assert bool(AurumImputer().fit_transform(datos).iloc[-1]["flag_imputed"]) is True
    largo = AurumImputer(ventana_dias=30).fit_transform(datos)
    assert largo.iloc[-1][domain.COLUMNA_LEY] == pytest.approx(2.0)


def test_el_marco_conserva_sus_columnas_originales(ventana_completa: pd.DataFrame) -> None:
    """El enunciado prohibe renombrar columnas: solo se agrega la bandera."""
    resultado = AurumImputer().fit_transform(ventana_completa)
    assert list(resultado.columns) == [*ventana_completa.columns, "flag_imputed"]
    assert resultado[domain.COLUMNA_TIEMPO].iloc[0] == INICIO


def test_registra_que_filas_reconstruyo(ventana_completa: pd.DataFrame) -> None:
    """El indice de las filas imputadas queda en el estado, no como columna del marco."""
    imputador = AurumImputer()
    resultado = imputador.fit_transform(ventana_completa)
    assert list(imputador.filas_imputadas_) == [ventana_completa.index[-1]]
    assert "ley_imputada" not in resultado.columns


def test_las_filas_marcadas_no_cuentan_como_reconstruidas(
        ventana_insuficiente: pd.DataFrame) -> None:
    imputador = AurumImputer()
    imputador.fit_transform(ventana_insuficiente)
    assert len(imputador.filas_imputadas_) == 0


def test_el_objetivo_medido_excluye_las_reconstruidas(ventana_completa: pd.DataFrame) -> None:
    """El objetivo que se le pasa al codificador no puede incluir valores inventados."""
    imputador = AurumImputer()
    resultado = imputador.fit_transform(ventana_completa)
    objetivo = imputador.objetivo_medido(resultado)
    assert pd.isna(objetivo.iloc[-1]), "la fila reconstruida debe quedar fuera del objetivo"
    assert objetivo.iloc[:-1].notna().all(), "las lecturas medidas tienen que conservarse"
