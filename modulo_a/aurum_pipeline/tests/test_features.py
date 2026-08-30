"""Pruebas del constructor de features.

El riesgo de esta clase no es equivocarse en una cuenta sino mirar hacia adelante: toda
feature de ventana, rezago o antiguedad se calcula sobre el pasado estricto, y varias pruebas
existen solo para fijar eso.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.tests.conftest import INICIO
from aurum_pipeline.transformers.features import AurumFeatureBuilder

SENSORES_NEUTROS = {
    domain.COLUMNA_TEMPERATURA: 70.0,
    domain.COLUMNA_VIBRACION: 3.0,
    domain.COLUMNA_PRESION: 200.0,
    domain.COLUMNA_RPM: 1000.0,
    domain.COLUMNA_AVANCE: 2.0,
}


def marco_features(filas: list[dict[str, float | str]]) -> pd.DataFrame:
    """Marco minimo con sensores en valores neutros salvo los que cada prueba cambie."""
    completas: list[dict[str, object]] = []
    for fila in filas:
        dias = float(fila.pop("dias"))
        registro: dict[str, object] = {
            domain.COLUMNA_TIEMPO: INICIO + pd.Timedelta(days=dias),
            domain.COLUMNA_FRENTE: fila.pop("frente", "FR-A"),
            domain.COLUMNA_LEY: fila.pop("ley", 5.0),
            **SENSORES_NEUTROS,
        }
        registro.update(fila)
        completas.append(registro)
    return pd.DataFrame(completas)


def test_agrega_las_nueve_features_sin_tocar_las_originales() -> None:
    datos = marco_features([{"dias": 0.0}, {"dias": 1.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert list(resultado.columns) == [*datos.columns, *AurumFeatureBuilder.FEATURES]
    pd.testing.assert_frame_equal(resultado[datos.columns], datos)


def test_la_ventana_no_incluye_la_propia_fila() -> None:
    """Con una fila extrema al final, su ventana promedia solo las anteriores."""
    datos = marco_features([{"dias": 0.0, "ley": 2.0}, {"dias": 1.0, "ley": 2.0},
                            {"dias": 2.0, "ley": 100.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["ley_ventana"].iloc[-1] == pytest.approx(2.0)
    assert resultado["ley_n_ventana"].iloc[-1] == 2


def test_la_ventana_no_mira_al_futuro() -> None:
    datos = marco_features([{"dias": 0.0, "ley": 1.0}, {"dias": 1.0, "ley": 1.0},
                            {"dias": 2.0, "ley": 99.0}, {"dias": 3.0, "ley": 99.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["ley_ventana"].iloc[1] == pytest.approx(1.0)


def test_la_primera_fila_de_un_frente_no_tiene_pasado() -> None:
    datos = marco_features([{"dias": 0.0}, {"dias": 1.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["ley_n_ventana"].iloc[0] == 0
    assert pd.isna(resultado["ley_ventana"].iloc[0])
    assert pd.isna(resultado["ley_lag_1"].iloc[0])
    assert pd.isna(resultado["dias_desde_evento_previo"].iloc[0])


def test_cada_frente_tiene_su_propia_historia() -> None:
    datos = marco_features([
        {"dias": 0.0, "frente": "FR-A", "ley": 1.0},
        {"dias": 1.0, "frente": "FR-B", "ley": 50.0},
        {"dias": 2.0, "frente": "FR-A", "ley": 1.0},
    ])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["ley_ventana"].iloc[2] == pytest.approx(1.0)
    assert resultado["ley_lag_1"].iloc[2] == pytest.approx(1.0)


def test_el_rezago_salta_las_lecturas_faltantes() -> None:
    """Tras el imputador, una fila marcada queda con la ley en `NaN` y no puede ser el rezago."""
    datos = marco_features([{"dias": 0.0, "ley": 4.0}, {"dias": 1.0, "ley": np.nan},
                            {"dias": 2.0, "ley": 9.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["ley_lag_1"].iloc[2] == pytest.approx(4.0)


def test_la_antiguedad_se_mide_en_dias() -> None:
    datos = marco_features([{"dias": 0.0}, {"dias": 0.5}, {"dias": 10.5}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["dias_desde_evento_previo"].to_list()[1:] == pytest.approx([0.5, 10.0])


def test_la_ventana_es_configurable() -> None:
    datos = marco_features([{"dias": 0.0, "ley": 3.0}, {"dias": 6.0, "ley": 3.0},
                            {"dias": 12.0, "ley": 8.0}])
    corta = AurumFeatureBuilder(ventana="3D").fit_transform(datos)
    larga = AurumFeatureBuilder(ventana="30D").fit_transform(datos)
    assert corta["ley_n_ventana"].iloc[-1] == 0
    assert larga["ley_n_ventana"].iloc[-1] == 2


def test_el_estadistico_de_la_ventana_es_configurable() -> None:
    """Con un valor extremo, media y mediana se separan: es la unica forma de distinguirlas."""
    datos = marco_features([{"dias": 0.0, "ley": 1.0}, {"dias": 1.0, "ley": 1.0},
                            {"dias": 2.0, "ley": 100.0}, {"dias": 3.0, "ley": 5.0}])
    media = AurumFeatureBuilder().fit_transform(datos)
    mediana = AurumFeatureBuilder(estadistico="mediana").fit_transform(datos)
    assert media["ley_ventana"].iloc[-1] == pytest.approx(34.0)
    assert mediana["ley_ventana"].iloc[-1] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("columna", "bandera", "por_debajo", "por_encima"),
    [
        (domain.COLUMNA_TEMPERATURA, "flag_temp_riesgo", 88.0, 88.1),
        (domain.COLUMNA_TEMPERATURA, "flag_temp_apagado", 95.0, 95.1),
        (domain.COLUMNA_VIBRACION, "flag_vib_alerta", 12.0, 12.1),
    ],
)
def test_las_banderas_se_activan_pasado_el_umbral(
        columna: str, bandera: str, por_debajo: float, por_encima: float) -> None:
    """El umbral no se activa en el valor exacto: el diccionario habla de superarlo."""
    datos = marco_features([{"dias": 0.0, columna: por_debajo},
                            {"dias": 1.0, columna: por_encima}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado[bandera].to_list() == [False, True]


def test_el_umbral_de_riesgo_termico_es_configurable() -> None:
    datos = marco_features([{"dias": 0.0, domain.COLUMNA_TEMPERATURA: 80.0}])
    assert not AurumFeatureBuilder().fit_transform(datos)["flag_temp_riesgo"].iloc[0]
    ajustado = AurumFeatureBuilder(umbral_temp_riesgo=75.0).fit_transform(datos)
    assert bool(ajustado["flag_temp_riesgo"].iloc[0]) is True


def test_los_ratios_operacionales_se_calculan() -> None:
    datos = marco_features([{"dias": 0.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["energia_especifica_proxy"].iloc[0] == pytest.approx(200.0 * 1000.0 / 2.0)
    assert resultado["sobretemperatura_por_rpm"].iloc[0] == pytest.approx(
        (70.0 - domain.TEMPERATURA_REFERENCIA_C) / 1000.0)


def test_la_sobretemperatura_se_mide_sobre_un_cero_real() -> None:
    """Un motor en la temperatura de referencia no tiene sobrecalentamiento que reportar.

    Es la razon de ser de la feature: el cociente sobre grados absolutos no tiene cero fisico
    y cambia de orden al medirlo en kelvin, de modo que deja de ser una magnitud comparable.
    """
    datos = marco_features([
        {"dias": 0.0, domain.COLUMNA_TEMPERATURA: domain.TEMPERATURA_REFERENCIA_C},
        {"dias": 1.0, domain.COLUMNA_TEMPERATURA: domain.TEMPERATURA_REFERENCIA_C + 10.0},
    ])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert resultado["sobretemperatura_por_rpm"].iloc[0] == pytest.approx(0.0)
    assert resultado["sobretemperatura_por_rpm"].iloc[1] == pytest.approx(10.0 / 1000.0)


def test_la_temperatura_de_referencia_es_configurable() -> None:
    datos = marco_features([{"dias": 0.0, domain.COLUMNA_TEMPERATURA: 60.0}])
    resultado = AurumFeatureBuilder(temperatura_referencia=50.0).fit_transform(datos)
    assert resultado["sobretemperatura_por_rpm"].iloc[0] == pytest.approx(10.0 / 1000.0)


def test_un_avance_nulo_no_produce_infinito() -> None:
    """Una division por cero silenciosa envenena el modelo; aqui queda como faltante."""
    datos = marco_features([{"dias": 0.0, domain.COLUMNA_AVANCE: 0.0}])
    resultado = AurumFeatureBuilder().fit_transform(datos)
    assert pd.isna(resultado["energia_especifica_proxy"].iloc[0])


def test_transformar_datos_nuevos_usa_la_historia_del_ajuste() -> None:
    historia = marco_features([{"dias": 0.0, "ley": 6.0}, {"dias": 1.0, "ley": 6.0}])
    constructor = AurumFeatureBuilder().fit(historia)
    nueva = marco_features([{"dias": 2.0, "ley": np.nan}])
    resultado = constructor.transform(nueva)
    assert resultado["ley_ventana"].iloc[0] == pytest.approx(6.0)
    assert resultado["ley_n_ventana"].iloc[0] == 2
    assert resultado["ley_lag_1"].iloc[0] == pytest.approx(6.0)


def test_transformar_el_mismo_marco_no_duplica_la_historia() -> None:
    """Ajustar y transformar lo mismo no puede contar cada evento dos veces.

    Sin deduplicar, la ventana veria la copia historica del propio registro, el rezago
    devolveria el valor de la fila y la antiguedad daria cero. Es la fuga mas silenciosa del
    pipeline y esta prueba la fija.
    """
    datos = marco_features([{"dias": 0.0, "ley": 2.0}, {"dias": 1.0, "ley": 4.0}])
    constructor = AurumFeatureBuilder().fit(datos)
    resultado = constructor.transform(datos)
    assert resultado["ley_n_ventana"].iloc[-1] == 1
    assert resultado["ley_lag_1"].iloc[-1] == pytest.approx(2.0)
    assert resultado["dias_desde_evento_previo"].iloc[-1] == pytest.approx(1.0)


def test_no_muta_el_marco_de_entrada() -> None:
    datos = marco_features([{"dias": 0.0}, {"dias": 1.0}])
    original = datos.copy(deep=True)
    AurumFeatureBuilder().fit_transform(datos)
    pd.testing.assert_frame_equal(datos, original)


def test_parametros_invalidos_fallan_al_construir() -> None:
    with pytest.raises(InvalidParameterError, match="estadistico"):
        AurumFeatureBuilder(estadistico="moda")  # type: ignore[arg-type]
    with pytest.raises(InvalidParameterError, match="ventana"):
        AurumFeatureBuilder(ventana="siete dias")
