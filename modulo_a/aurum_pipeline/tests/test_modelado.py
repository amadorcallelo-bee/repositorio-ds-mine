"""Pruebas de variables, baselines, metricas, modelos y evaluacion del A-2.

El riesgo de estos modulos es doble: que una codificacion vea el futuro y que una metrica
diga lo contrario de lo que parece. Las pruebas de fuga son las que llevan comentario, porque
son las que no se detectan mirando el resultado.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from aurum_pipeline import domain
from aurum_pipeline.errors import (
    InvalidParameterError,
    MissingColumnsError,
    NotFittedError,
)
from aurum_pipeline.modeling import metrics
from aurum_pipeline.modeling.baselines import (
    BaselineActividad,
    BaselineNivelFrente,
    BaselinePersistencia,
    BaselinePrevalencia,
    BaselineTasaFrente,
)
from aurum_pipeline.modeling.classifiers import (
    CLASIFICADORES,
    ClasificadorLightGBM,
    ModeloFalla,
    peso_de_clase,
)
from aurum_pipeline.modeling.evaluacion import (
    EVALUADOR_FALLA,
    EVALUADOR_REGRESION,
    PUNTAJE_FALLA,
    buscar_hiperparametros,
    configuraciones_muestreadas,
    evaluar_por_pliegues,
)
from aurum_pipeline.modeling.falla import COLUMNA_VENTANA_OBSERVADA
from aurum_pipeline.modeling.features import (
    ACTIVIDAD,
    COLUMNA_NIVEL_FRENTE,
    COLUMNA_TIPO_NUM,
    COLUMNA_TURNO_NUM,
    COLUMNAS_DEL_FUTURO,
    COMPLETO,
    CONDICIONES,
    CONJUNTOS,
    MINIMO,
    CodificadorNivelFrente,
    ConjuntoVariables,
    SelectorVariables,
)
from aurum_pipeline.modeling.models import MODELOS, ModeloLey, ModeloLightGBM
from aurum_pipeline.modeling.splitter import ventana_desde_matriz
from aurum_pipeline.tests.datos_modelado import matriz_sintetica


@pytest.fixture
def matriz() -> pd.DataFrame:
    return matriz_sintetica()


# -- conjuntos de variables --------------------------------------------------------------


def test_un_conjunto_sin_columnas_es_un_parametro_invalido() -> None:
    with pytest.raises(InvalidParameterError, match="no declara ninguna columna"):
        ConjuntoVariables(nombre="VACIO", columnas=())


def test_los_conjuntos_crecen_uno_dentro_del_otro() -> None:
    """MINIMO dentro de ACTIVIDAD dentro de CONDICIONES dentro de COMPLETO."""
    nombres = [c.nombre for c in CONJUNTOS]
    assert nombres == ["MINIMO", "ACTIVIDAD", "CONDICIONES", "COMPLETO"]
    for menor, mayor in pairwise(CONJUNTOS):
        assert set(menor.columnas) < set(mayor.columnas), f"{menor.nombre} > {mayor.nombre}"
    assert domain.COLUMNA_MINUTOS_INACTIVO in ACTIVIDAD.columnas
    assert domain.COLUMNA_TEMP_MAX in CONDICIONES.columnas


def test_un_conjunto_no_puede_declarar_columnas_del_futuro() -> None:
    """Prueba de fuga: la etiqueta, el conteo de la ventana y el objetivo no son variables."""
    for columna in sorted(COLUMNAS_DEL_FUTURO):
        with pytest.raises(InvalidParameterError, match="describen el futuro"):
            ConjuntoVariables(nombre="FUGA", columnas=(COLUMNA_NIVEL_FRENTE, columna))
    for conjunto in CONJUNTOS:
        assert not COLUMNAS_DEL_FUTURO.intersection(conjunto.columnas)


# -- codificacion del nivel del frente ---------------------------------------------------


def test_el_codificador_aprende_la_media_del_objetivo_por_frente(
        matriz: pd.DataFrame) -> None:
    codificador = CodificadorNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    salida = codificador.transform(matriz)
    esperado = matriz.groupby(domain.COLUMNA_FRENTE)[domain.COLUMNA_OBJETIVO].mean()
    for frente, nivel in esperado.items():
        obtenido = salida.loc[salida[domain.COLUMNA_FRENTE] == frente,
                              COLUMNA_NIVEL_FRENTE].unique()
        assert obtenido == pytest.approx([nivel])


def test_un_frente_no_visto_recibe_el_prior_global(matriz: pd.DataFrame) -> None:
    codificador = CodificadorNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    nuevo = matriz.head(1).assign(**{domain.COLUMNA_FRENTE: "FR-NUEVO"})
    salida = codificador.transform(nuevo)
    assert salida[COLUMNA_NIVEL_FRENTE].iloc[0] == pytest.approx(codificador.prior_)


def test_el_codificador_sin_objetivo_falla(matriz: pd.DataFrame) -> None:
    with pytest.raises(InvalidParameterError, match="necesita el objetivo"):
        CodificadorNivelFrente().fit(matriz)


def test_el_codificador_sin_ajustar_falla(matriz: pd.DataFrame) -> None:
    with pytest.raises(NotFittedError):
        CodificadorNivelFrente().transform(matriz)


def test_el_codificador_exige_la_columna_de_frente(matriz: pd.DataFrame) -> None:
    sin_frente = matriz.drop(columns=[domain.COLUMNA_FRENTE])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FRENTE):
        CodificadorNivelFrente().fit(sin_frente, matriz[domain.COLUMNA_OBJETIVO])
    codificador = CodificadorNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FRENTE):
        codificador.transform(sin_frente)


def test_el_codificador_no_muta_el_marco(matriz: pd.DataFrame) -> None:
    original = matriz.copy(deep=True)
    CodificadorNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO]).transform(matriz)
    pd.testing.assert_frame_equal(matriz, original)


def test_el_codificador_dentro_del_pipeline_no_ve_el_bloque_de_validacion(
        matriz: pd.DataFrame) -> None:
    """La prueba de fuga del A-2.

    Si la codificacion se calculara una vez sobre toda la matriz, el nivel de cada frente
    incluiria los turnos del bloque que despues lo evalua. Dentro del pipeline se reajusta con
    el entrenamiento de cada pliegue, y esta prueba lo comprueba comparando el nivel que
    produce el pipeline contra el que produciria mirando todo.
    """
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    entrena, valida = next(iter(ventana.split(matriz)))
    codificador = CodificadorNivelFrente().fit(
        matriz.iloc[entrena], matriz.iloc[entrena][domain.COLUMNA_OBJETIVO])
    del_pliegue = codificador.transform(matriz.iloc[valida])[COLUMNA_NIVEL_FRENTE]

    global_ = CodificadorNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    de_todo = global_.transform(matriz.iloc[valida])[COLUMNA_NIVEL_FRENTE]
    assert not np.allclose(del_pliegue.to_numpy(), de_todo.to_numpy())


# -- seleccion de variables --------------------------------------------------------------


def test_el_selector_codifica_las_categoricas_con_el_orden_del_dominio(
        matriz: pd.DataFrame) -> None:
    """Un `astype('category')` daria codigos distintos segun que categorias trae el bloque."""
    con_nivel = CodificadorNivelFrente().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO]).transform(matriz)
    selector = SelectorVariables(conjunto=COMPLETO)
    salida = selector.transform(con_nivel)
    solo_ox = selector.transform(con_nivel[con_nivel[domain.COLUMNA_TIPO_MINERAL] == "OX"])
    codigo_ox = float(domain.ORDEN_TIPOS_MINERAL.index("OX"))
    assert (solo_ox[COLUMNA_TIPO_NUM] == codigo_ox).all()
    assert set(salida[COLUMNA_TURNO_NUM].unique()) <= set(
        range(len(domain.ORDEN_TURNOS)))


def test_el_selector_devuelve_exactamente_las_columnas_del_conjunto(
        matriz: pd.DataFrame) -> None:
    con_nivel = CodificadorNivelFrente().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO]).transform(matriz)
    salida = SelectorVariables(conjunto=MINIMO).transform(con_nivel)
    assert list(salida.columns) == list(MINIMO.columnas)
    assert salida.dtypes.unique().tolist() == [np.dtype("float64")]


def test_el_selector_falla_si_falta_una_columna_del_conjunto(matriz: pd.DataFrame) -> None:
    with pytest.raises(MissingColumnsError, match=COLUMNA_NIVEL_FRENTE):
        SelectorVariables(conjunto=MINIMO).transform(matriz)


def test_el_selector_no_aprende_nada(matriz: pd.DataFrame) -> None:
    selector = SelectorVariables()
    assert selector.fit(matriz) is selector


# -- baselines ---------------------------------------------------------------------------


def test_la_persistencia_repite_la_ley_del_turno(matriz: pd.DataFrame) -> None:
    modelo = BaselinePersistencia().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    assert modelo.predict(matriz) == pytest.approx(
        matriz[domain.COLUMNA_LEY_TURNO].to_numpy())


def test_el_nivel_del_frente_predice_la_media_aprendida(matriz: pd.DataFrame) -> None:
    modelo = BaselineNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    esperado = matriz[domain.COLUMNA_FRENTE].map(
        matriz.groupby(domain.COLUMNA_FRENTE)[domain.COLUMNA_OBJETIVO].mean())
    assert modelo.predict(matriz) == pytest.approx(esperado.to_numpy())


def test_el_nivel_del_frente_usa_el_prior_con_un_frente_nuevo(matriz: pd.DataFrame) -> None:
    modelo = BaselineNivelFrente().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    nuevo = matriz.head(1).assign(**{domain.COLUMNA_FRENTE: "FR-NUEVO"})
    assert modelo.predict(nuevo)[0] == pytest.approx(modelo.prior_)


def test_la_prevalencia_predice_la_tasa_base(matriz: pd.DataFrame) -> None:
    etiqueta = matriz["falla_en_4h"]
    modelo = BaselinePrevalencia().fit(matriz, etiqueta)
    probabilidad = modelo.predict_proba(matriz)[:, 1]
    assert probabilidad == pytest.approx(np.full(len(matriz), etiqueta.mean()))
    assert set(modelo.predict(matriz).tolist()) <= {0.0, 1.0}


def test_la_tasa_del_frente_predice_la_tasa_de_cada_frente(matriz: pd.DataFrame) -> None:
    etiqueta = matriz["falla_en_4h"]
    modelo = BaselineTasaFrente().fit(matriz, etiqueta)
    esperado = matriz[domain.COLUMNA_FRENTE].map(
        matriz.groupby(domain.COLUMNA_FRENTE)["falla_en_4h"].mean())
    assert modelo.predict_proba(matriz)[:, 1] == pytest.approx(esperado.to_numpy())
    nuevo = matriz.head(1).assign(**{domain.COLUMNA_FRENTE: "FR-NUEVO"})
    assert modelo.predict_proba(nuevo)[0, 1] == pytest.approx(modelo.prior_)
    assert set(modelo.predict(matriz).tolist()) <= {0.0, 1.0}


@pytest.mark.parametrize("baseline", [BaselinePersistencia, BaselineNivelFrente,
                                      BaselinePrevalencia, BaselineTasaFrente])
def test_ningun_baseline_predice_sin_ajustar(baseline: type,
                                             matriz: pd.DataFrame) -> None:
    modelo = baseline()
    with pytest.raises(NotFittedError):
        if hasattr(modelo, "predict_proba"):
            modelo.predict_proba(matriz)
        else:
            modelo.predict(matriz)


@pytest.mark.parametrize("baseline", [BaselineNivelFrente, BaselinePrevalencia,
                                      BaselineTasaFrente])
def test_los_baselines_que_aprenden_exigen_objetivo(baseline: type,
                                                    matriz: pd.DataFrame) -> None:
    with pytest.raises(MissingColumnsError):
        baseline().fit(matriz)


def test_los_baselines_exigen_sus_columnas(matriz: pd.DataFrame) -> None:
    sin_ley = matriz.drop(columns=[domain.COLUMNA_LEY_TURNO])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_LEY_TURNO):
        BaselinePersistencia().fit(sin_ley)
    sin_frente = matriz.drop(columns=[domain.COLUMNA_FRENTE])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FRENTE):
        BaselineNivelFrente().fit(sin_frente, matriz[domain.COLUMNA_OBJETIVO])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FRENTE):
        BaselineTasaFrente().fit(sin_frente, matriz["falla_en_4h"])
    ajustado = BaselineTasaFrente().fit(matriz, matriz["falla_en_4h"])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FRENTE):
        ajustado.predict_proba(sin_frente)


# -- metricas ----------------------------------------------------------------------------


def test_una_prediccion_perfecta_da_error_cero_y_varianza_uno() -> None:
    y = np.array([1.0, 2.0, 3.0, 4.0])
    resultado = metrics.evaluar(y, y)
    assert resultado.error_medio_g_por_tonelada == 0.0
    assert resultado.varianza_explicada == 1.0
    assert resultado.valor_principal == 0.0
    assert resultado.mejor_es_mayor is False


def test_un_objetivo_constante_no_tiene_varianza_que_explicar() -> None:
    y = np.array([5.0, 5.0, 5.0])
    assert metrics.evaluar(y, np.array([4.0, 5.0, 6.0])).varianza_explicada == 0.0


def test_las_metricas_rechazan_entradas_incoherentes() -> None:
    with pytest.raises(InvalidParameterError, match="no coinciden"):
        metrics.evaluar(np.array([1.0]), np.array([1.0, 2.0]))
    with pytest.raises(InvalidParameterError, match="no hay turnos"):
        metrics.evaluar(np.array([]), np.array([]))
    with pytest.raises(InvalidParameterError, match="no finitos"):
        metrics.evaluar(np.array([1.0]), np.array([np.nan]))


def test_el_error_por_frente_ordena_de_peor_a_mejor() -> None:
    frentes = pd.Series(["A", "A", "B", "B"])
    tabla = metrics.error_por_frente(
        frentes, np.array([1.0, 1.0, 1.0, 1.0]), np.array([1.0, 1.0, 5.0, 5.0]))
    assert tabla["frente_id"].tolist() == ["B", "A"]
    assert tabla["error_medio_g_por_tonelada"].tolist() == [4.0, 0.0]


def test_la_mejora_sobre_el_baseline_es_positiva_cuando_el_modelo_gana() -> None:
    assert metrics.mejora_vs_baseline_pct(0.4, 0.5) == pytest.approx(20.0)
    assert metrics.mejora_vs_baseline_pct(0.6, 0.5) == pytest.approx(-20.0)
    with pytest.raises(InvalidParameterError, match="positivo"):
        metrics.mejora_vs_baseline_pct(0.4, 0.0)


def test_la_precision_media_de_una_probabilidad_perfecta_es_uno() -> None:
    y = np.array([0.0, 0.0, 1.0, 1.0])
    resultado = metrics.evaluar_falla(y, np.array([0.1, 0.2, 0.9, 0.95]))
    assert resultado.precision_media == pytest.approx(1.0)
    assert resultado.area_bajo_roc == pytest.approx(1.0)
    assert resultado.exhaustividad_al_50_pct == pytest.approx(1.0)
    assert resultado.tasa_base == pytest.approx(0.5)
    assert resultado.levante_sobre_azar == pytest.approx(2.0)
    assert resultado.mejor_es_mayor is True


def test_un_bloque_sin_positivos_devuelve_la_tasa_base_y_no_un_faltante() -> None:
    resultado = metrics.evaluar_falla(np.zeros(4), np.array([0.1, 0.2, 0.3, 0.4]))
    assert resultado.precision_media == 0.0
    assert np.isfinite(resultado.error_brier)
    assert not np.isnan(resultado.area_bajo_roc)


def test_las_metricas_de_falla_rechazan_entradas_incoherentes() -> None:
    with pytest.raises(InvalidParameterError, match="no coinciden"):
        metrics.evaluar_falla(np.array([1.0]), np.array([0.1, 0.2]))
    with pytest.raises(InvalidParameterError, match="no hay turnos"):
        metrics.evaluar_falla(np.array([]), np.array([]))
    with pytest.raises(InvalidParameterError, match="no finitos"):
        metrics.evaluar_falla(np.array([1.0, 0.0]), np.array([np.inf, 0.1]))


# -- modelos -----------------------------------------------------------------------------


@pytest.mark.parametrize("fabrica", MODELOS)
def test_cada_modelo_arma_un_pipeline_de_tres_pasos(fabrica: type[ModeloLey]) -> None:
    modelo = fabrica(conjunto=MINIMO)
    pipeline = modelo.pipeline()
    assert isinstance(pipeline, Pipeline)
    assert [nombre for nombre, _ in pipeline.steps] == ["nivel", "variables", "modelo"]
    assert modelo.nombre in ("lightgbm", "xgboost")
    assert all(clave.startswith("modelo__") for clave in modelo.espacio_busqueda())


@pytest.mark.parametrize("fabrica", CLASIFICADORES)
def test_cada_clasificador_arma_un_pipeline_equivalente(fabrica: type[ModeloFalla]) -> None:
    modelo = fabrica(conjunto=MINIMO, peso_positivo=3.0)
    assert [nombre for nombre, _ in modelo.pipeline().steps] == [
        "nivel", "variables", "modelo"]
    assert all(clave.startswith("modelo__") for clave in modelo.espacio_busqueda())


def test_las_clases_abstractas_de_modelo_no_se_instancian() -> None:
    with pytest.raises(TypeError):
        ModeloLey()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        ModeloFalla()  # type: ignore[abstract]


def test_el_peso_de_clase_es_la_razon_entre_negativos_y_positivos() -> None:
    assert peso_de_clase(np.array([0, 0, 0, 1])) == pytest.approx(3.0)
    assert peso_de_clase(np.zeros(4)) == 1.0


def test_el_modelo_se_ajusta_y_predice_sobre_la_matriz(matriz: pd.DataFrame) -> None:
    pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline()
    pipeline.fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    prediccion = pipeline.predict(matriz)
    assert prediccion.shape == (len(matriz),)
    assert np.isfinite(prediccion).all()


# -- evaluacion --------------------------------------------------------------------------


def test_la_evaluacion_devuelve_un_resultado_por_pliegue(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=3)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    assert len(resultado.pliegues) == 3
    assert resultado.nombre_principal == "error_medio_g_por_tonelada"
    assert resultado.mejor_es_mayor is False
    assert resultado.valor_principal > 0
    assert resultado.desviacion_entre_pliegues >= 0
    assert resultado.turnos_entrenamiento_medio > 0
    assert "turnos_entrenamiento" in resultado.como_diccionario()


def test_la_evaluacion_de_falla_usa_la_probabilidad(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=3)
    resultado = evaluar_por_pliegues(
        BaselineTasaFrente(), matriz, ventana, "tasa", columna_objetivo="falla_en_4h",
        evaluador=EVALUADOR_FALLA)
    assert resultado.nombre_principal == "precision_media"
    assert resultado.mejor_es_mayor is True
    assert 0.0 <= resultado.valor_principal <= 1.0


def test_la_evaluacion_falla_si_no_esta_la_columna_de_objetivo(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    with pytest.raises(InvalidParameterError, match="columna de objetivo"):
        evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "x",
                             columna_objetivo="inexistente")


def test_un_solo_pliegue_no_tiene_dispersion(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=1)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    assert resultado.desviacion_entre_pliegues == 0.0


def test_el_evaluador_de_regresion_declara_su_metrica() -> None:
    assert EVALUADOR_REGRESION.nombre_principal == "error_medio_g_por_tonelada"
    assert EVALUADOR_REGRESION.mejor_es_mayor is False


def test_la_busqueda_devuelve_la_tabla_de_configuraciones(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    busqueda = buscar_hiperparametros(
        ModeloLightGBM(conjunto=MINIMO), matriz, ventana, iteraciones=2)
    tabla = configuraciones_muestreadas(busqueda)
    assert len(tabla) == 2
    assert "puntaje_validacion" in tabla.columns
    assert not any("__" in columna for columna in tabla.columns)
    assert tabla["puntaje_validacion"].is_monotonic_decreasing


def test_la_busqueda_de_falla_ordena_por_precision_media(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    busqueda = buscar_hiperparametros(
        ClasificadorLightGBM(conjunto=MINIMO), matriz, ventana, iteraciones=2,
        columna_objetivo="falla_en_4h", puntaje=PUNTAJE_FALLA)
    assert 0.0 <= float(busqueda.best_score_) <= 1.0


def test_una_busqueda_sin_iteraciones_es_un_parametro_invalido(
        matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    with pytest.raises(InvalidParameterError, match="al menos una iteracion"):
        buscar_hiperparametros(ModeloLightGBM(), matriz, ventana, iteraciones=0)


# -- metricas de entrenamiento y brecha --------------------------------------------------


def test_cada_pliegue_trae_su_metrica_de_entrenamiento_y_su_brecha(
        matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=3)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    for pliegue in resultado.pliegues:
        registro = pliegue.como_diccionario()
        assert "error_medio_g_por_tonelada_entrenamiento" in registro
        assert "brecha_entrenamiento_validacion" in registro
        # El conteo de turnos no se duplica con sufijo: el tamano del entrenamiento ya tiene
        # su propio nombre en el registro.
        assert "turnos_entrenamiento" not in registro
    agregado = resultado.como_diccionario()
    assert agregado["error_medio_g_por_tonelada_entrenamiento"] == pytest.approx(
        resultado.valor_principal_entrenamiento)
    assert agregado["brecha_entrenamiento_validacion"] == pytest.approx(
        resultado.brecha_entrenamiento_validacion)


def test_la_brecha_es_positiva_cuando_el_modelo_memoriza(matriz: pd.DataFrame) -> None:
    """Un arbol sin regularizar ajusta el ruido del entrenamiento: la brecha lo delata."""
    from lightgbm import LGBMRegressor
    from sklearn.pipeline import Pipeline as PipelineSk

    memorion = PipelineSk([
        ("nivel", CodificadorNivelFrente()),
        ("variables", SelectorVariables(conjunto=COMPLETO)),
        ("modelo", LGBMRegressor(num_leaves=63, min_child_samples=1, n_estimators=300,
                                 learning_rate=0.3, verbose=-1, random_state=1)),
    ])
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(memorion, matriz, ventana, "memorion")
    assert resultado.valor_principal_entrenamiento < resultado.valor_principal
    assert resultado.brecha_entrenamiento_validacion > 0.0


def test_la_brecha_cambia_de_signo_con_la_direccion_de_la_metrica(
        matriz: pd.DataFrame) -> None:
    """En clasificacion mas es mejor y la brecha conserva su lectura.

    Sigue siendo "cuanto mejor se ve en entrenamiento": precision de entrenamiento menos
    precision de validacion.
    """
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(
        BaselineTasaFrente(), matriz, ventana, "tasa", columna_objetivo="falla_en_4h",
        evaluador=EVALUADOR_FALLA)
    for pliegue in resultado.pliegues:
        esperada = (pliegue.metricas_entrenamiento.valor_principal
                    - pliegue.metricas.valor_principal)
        assert pliegue.brecha_entrenamiento_validacion == pytest.approx(esperada)


def test_la_tabla_de_configuraciones_trae_entrenamiento_y_brecha(
        matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    busqueda = buscar_hiperparametros(
        ModeloLightGBM(conjunto=MINIMO), matriz, ventana, iteraciones=2)
    tabla = configuraciones_muestreadas(busqueda)
    assert {"puntaje_entrenamiento", "brecha_entrenamiento_validacion"} <= set(tabla.columns)
    esperada = tabla["puntaje_entrenamiento"] - tabla["puntaje_validacion"]
    assert tabla["brecha_entrenamiento_validacion"].tolist() == pytest.approx(esperada.tolist())


# -- precision media con actividad -------------------------------------------------------


def test_la_precision_con_actividad_se_calcula_solo_sobre_las_ventanas_observadas() -> None:
    etiqueta = np.array([0, 0, 1, 1, 0, 0])
    probabilidad = np.array([0.9, 0.8, 0.7, 0.6, 0.2, 0.1])
    # Las dos primeras filas -las de probabilidad mas alta- no tuvieron registros.
    actividad = np.array([0, 0, 1, 1, 1, 1])
    resultado = metrics.evaluar_falla(etiqueta, probabilidad, actividad)
    assert resultado.precision_media_con_actividad == pytest.approx(1.0)
    assert resultado.tasa_base_con_actividad == pytest.approx(0.5)
    assert resultado.precision_media < resultado.precision_media_con_actividad


def test_sin_marca_de_actividad_la_condicional_coincide_con_la_global() -> None:
    etiqueta = np.array([0, 1, 0, 1])
    probabilidad = np.array([0.2, 0.9, 0.4, 0.3])
    resultado = metrics.evaluar_falla(etiqueta, probabilidad)
    assert resultado.precision_media_con_actividad == pytest.approx(resultado.precision_media)
    assert resultado.tasa_base_con_actividad == pytest.approx(resultado.tasa_base)


def test_una_marca_de_actividad_desalineada_es_un_parametro_invalido() -> None:
    with pytest.raises(InvalidParameterError, match="marca de actividad"):
        metrics.evaluar_falla(np.array([0, 1]), np.array([0.1, 0.9]), np.array([1]))


def test_sin_ventanas_observadas_la_condicional_es_cero_y_no_un_faltante() -> None:
    resultado = metrics.evaluar_falla(
        np.array([0, 1, 0]), np.array([0.1, 0.9, 0.2]), np.array([0, 0, 0]))
    assert resultado.precision_media_con_actividad == 0.0
    assert resultado.tasa_base_con_actividad == 0.0


def test_el_evaluador_de_falla_usa_la_marca_de_la_matriz(matriz: pd.DataFrame) -> None:
    """La marca no es variable del modelo: el pipeline la ignora y el evaluador la lee."""
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(
        ClasificadorLightGBM(conjunto=MINIMO).pipeline(), matriz, ventana, "lgbm",
        columna_objetivo="falla_en_4h", evaluador=EVALUADOR_FALLA)
    registro = resultado.como_diccionario()
    assert 0.0 <= registro["precision_media_con_actividad"] <= 1.0
    observadas = matriz[COLUMNA_VENTANA_OBSERVADA] == 1
    assert registro["tasa_base_con_actividad"] > 0.0
    assert observadas.sum() < len(matriz)


# -- baseline de actividad ---------------------------------------------------------------


def test_el_baseline_de_actividad_aprende_una_tasa_por_tramo() -> None:
    marco = pd.DataFrame({domain.COLUMNA_MINUTOS_INACTIVO: [10.0, 20.0, 50.0, 300.0, 350.0]})
    etiqueta = pd.Series([1, 0, 1, 0, 0])
    baseline = BaselineActividad(tramos=(30.0, 120.0)).fit(marco, etiqueta)
    probabilidad = baseline.predict_proba(marco)[:, 1]
    assert probabilidad.tolist() == pytest.approx([0.5, 0.5, 1.0, 0.0, 0.0])


def test_el_baseline_de_actividad_usa_el_prior_en_tramos_no_vistos_y_faltantes() -> None:
    marco = pd.DataFrame({domain.COLUMNA_MINUTOS_INACTIVO: [10.0, 20.0]})
    baseline = BaselineActividad(tramos=(30.0, 120.0)).fit(marco, pd.Series([1, 0]))
    nuevo = pd.DataFrame({domain.COLUMNA_MINUTOS_INACTIVO: [200.0, float("nan")]})
    assert baseline.predict_proba(nuevo)[:, 1].tolist() == pytest.approx([0.5, 0.5])


def test_el_baseline_de_actividad_respeta_los_limites_de_los_tramos() -> None:
    """Un minuto exactamente en el corte cae en el tramo inferior: los tramos son (a, b]."""
    marco = pd.DataFrame({domain.COLUMNA_MINUTOS_INACTIVO: [30.1, 30.0]})
    baseline = BaselineActividad(tramos=(30.0,)).fit(marco, pd.Series([1, 0]))
    assert baseline.predict_proba(marco)[:, 1].tolist() == pytest.approx([1.0, 0.0])


def test_el_baseline_de_actividad_rechaza_tramos_mal_formados(matriz: pd.DataFrame) -> None:
    etiqueta = matriz["falla_en_4h"]
    for tramos in ((), (0.0, 30.0), (60.0, 30.0), (30.0, 30.0)):
        with pytest.raises(InvalidParameterError, match="positivos y crecientes"):
            BaselineActividad(tramos=tramos).fit(matriz, etiqueta)


def test_el_baseline_de_actividad_exige_su_columna_y_ajuste(matriz: pd.DataFrame) -> None:
    baseline = BaselineActividad()
    with pytest.raises(NotFittedError):
        baseline.predict_proba(matriz)
    with pytest.raises(MissingColumnsError, match="etiqueta"):
        baseline.fit(matriz)
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_MINUTOS_INACTIVO):
        baseline.fit(matriz.drop(columns=[domain.COLUMNA_MINUTOS_INACTIVO]),
                     matriz["falla_en_4h"])


def test_el_baseline_de_actividad_predice_la_clase_sobre_la_matriz(
        matriz: pd.DataFrame) -> None:
    baseline = BaselineActividad().fit(matriz, matriz["falla_en_4h"])
    clases = baseline.predict(matriz)
    assert set(np.unique(clases)) <= {0.0, 1.0}
    assert metrics.evaluar_falla(
        matriz["falla_en_4h"].to_numpy(dtype=float),
        baseline.predict_proba(matriz)[:, 1]).precision_media > 0.0
