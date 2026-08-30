"""Pruebas del orquestador de las tres fases.

Corren con la matriz sintetica, dos pliegues y dos iteraciones de busqueda: lo que se prueba
es que las fases encadenen, que respeten el orden y que el conjunto de prueba se mire una sola
vez, no que el modelo acierte. Probar la exactitud con datos sinteticos mediria el generador.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import EmptyPartitionError, InvalidParameterError, NotFittedError
from aurum_pipeline.modeling.evaluacion import BRECHA, SUFIJO_ENTRENAMIENTO
from aurum_pipeline.modeling.experimento import (
    CLASIFICACION_FALLA,
    COLUMNA_PESO,
    REGRESION_LEY,
    SIN_PESO,
    VENTANAS_COMPARADAS,
    Experimento,
)
from aurum_pipeline.modeling.splitter import ParticionTemporal
from aurum_pipeline.modeling.tracking import RegistroExperimento
from aurum_pipeline.tests.datos_modelado import matriz_sintetica


@pytest.fixture
def particiones() -> tuple[pd.DataFrame, pd.DataFrame]:
    matriz = matriz_sintetica(frentes=3, turnos_por_frente=40)
    return ParticionTemporal(proporcion_prueba=0.25).dividir(matriz)


@pytest.fixture
def registro(tmp_path: Path) -> RegistroExperimento:
    return RegistroExperimento(uri=f"sqlite:///{tmp_path}/mlflow.db",
                               experimento="experimento_de_prueba")


def construir(
    particiones: tuple[pd.DataFrame, pd.DataFrame],
    registro: RegistroExperimento,
    problema: object = REGRESION_LEY,
) -> Experimento:
    desarrollo, prueba = particiones
    return Experimento(
        desarrollo=desarrollo, prueba=prueba, registro=registro,
        problema=problema, iteraciones_busqueda=2, pliegues=2)  # type: ignore[arg-type]


# -- precondiciones ----------------------------------------------------------------------


def test_una_particion_vacia_es_un_parametro_invalido(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    desarrollo, prueba = particiones
    with pytest.raises(InvalidParameterError, match="desarrollo"):
        Experimento(desarrollo=desarrollo.iloc[0:0], prueba=prueba, registro=registro)


def test_una_particion_sin_el_objetivo_es_un_parametro_invalido(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    desarrollo, prueba = particiones
    with pytest.raises(InvalidParameterError, match=domain.COLUMNA_OBJETIVO):
        Experimento(desarrollo=desarrollo.drop(columns=[domain.COLUMNA_OBJETIVO]),
                    prueba=prueba, registro=registro)


def test_las_fases_exigen_su_orden(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro)
    with pytest.raises(NotFittedError, match="fase_variables"):
        experimento.fase_ventana()
    with pytest.raises(NotFittedError, match="fase_ventana"):
        experimento.fase_prueba()


def test_la_huella_del_insumo_queda_como_etiqueta(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    construir(particiones, registro)
    assert "hash_extracto" in registro.etiquetas_comunes


# -- fase A ------------------------------------------------------------------------------


def test_la_fase_de_variables_compara_los_cuatro_conjuntos_con_los_dos_modelos(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro)
    tabla = experimento.fase_variables()
    assert len(tabla) == 8
    assert set(tabla["conjunto_variables"]) == {"MINIMO", "ACTIVIDAD", "CONDICIONES",
                                                "COMPLETO"}
    assert set(tabla["modelo"]) == {"lightgbm", "xgboost"}
    assert experimento.conjunto_elegido_ is not None
    # La regresion no compara pesos de clase: la columna ni siquiera aparece.
    assert COLUMNA_PESO not in tabla.columns
    # La tabla queda ordenada de mejor a peor segun la metrica principal del problema.
    columna = REGRESION_LEY.evaluador.nombre_principal
    assert tabla[columna].is_monotonic_increasing


def test_las_tablas_traen_entrenamiento_y_brecha(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro)
    tabla = experimento.fase_variables()
    columna = REGRESION_LEY.evaluador.nombre_principal
    assert f"{columna}{SUFIJO_ENTRENAMIENTO}" in tabla.columns
    assert BRECHA in tabla.columns
    assert tabla[BRECHA].notna().all()


# -- fase B ------------------------------------------------------------------------------


def test_la_fase_de_ventana_cubre_las_cinco_estrategias(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro)
    experimento.fase_variables()
    tabla = experimento.fase_ventana()
    assert len(set(tabla["estrategia_ventana"])) == len(VENTANAS_COMPARADAS)
    assert {"baseline_persistencia", "baseline_nivel_frente"} <= set(tabla["modelo"])
    assert experimento.fabrica_elegida_ is not None


def test_la_ventana_elegida_nunca_es_un_baseline(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    """El baseline puede ganar la tabla; lo que se promueve a la fase C es un modelo."""
    experimento = construir(particiones, registro)
    experimento.fase_variables()
    experimento.fase_ventana()
    assert experimento.fabrica_elegida_ is not None
    assert experimento.fabrica_elegida_ in REGRESION_LEY.fabricas


# -- fase C ------------------------------------------------------------------------------


def test_la_fase_de_prueba_registra_el_modelo_con_alias(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    import mlflow

    experimento = construir(particiones, registro)
    experimento.fase_variables()
    experimento.fase_ventana()
    final = experimento.fase_prueba()

    assert final.problema == "ley"
    assert set(final.metricas_baselines) == {"baseline_persistencia", "baseline_nivel_frente"}
    # Con la expansiva, el modelo final entrena con todo el desarrollo; asi queda registrado.
    if experimento.ventana_elegida_ is None:
        assert final.turnos_entrenamiento == len(experimento.desarrollo)
    assert isinstance(final.le_gana_al_baseline_fuerte, bool)
    assert not final.detalle_por_frente.empty
    cargado = mlflow.pyfunc.load_model(
        f"models:/{domain.MODELO_LEY_REGISTRADO}@{domain.ALIAS_PRODUCCION}")
    assert len(cargado.predict(experimento.prueba.head(2))) == 2


# -- clasificacion -----------------------------------------------------------------------


def test_el_mismo_orquestador_corre_la_clasificacion(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    """La unica diferencia entre los dos problemas es la configuracion que se le pasa."""
    experimento = construir(particiones, registro, problema=CLASIFICACION_FALLA)
    tabla = experimento.fase_variables()
    assert CLASIFICACION_FALLA.evaluador.nombre_principal in tabla.columns
    # En clasificacion mas es mejor, asi que la tabla ordena al reves que en regresion.
    assert tabla[CLASIFICACION_FALLA.evaluador.nombre_principal].is_monotonic_decreasing


def test_la_fase_de_variables_de_falla_compara_con_y_sin_peso_de_clase(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    """Cuatro conjuntos por dos modelos por dos pesos: el peso se mide, no se supone."""
    experimento = construir(particiones, registro, problema=CLASIFICACION_FALLA)
    tabla = experimento.fase_variables()
    assert len(tabla) == 16
    pesos = set(tabla[COLUMNA_PESO])
    assert SIN_PESO in pesos and len(pesos) == 2
    assert max(pesos) > SIN_PESO
    # El peso elegido es el de la fila ganadora y las fases siguientes lo conservan.
    assert experimento.peso_elegido_ == tabla.iloc[0][COLUMNA_PESO]
    experimento.fase_ventana()
    corridas = registro.tabla_de_corridas(fase="fase_b__ventana__falla_4h")
    de_modelos = corridas[~corridas["tags.mlflow.runName"].str.startswith("baseline")]
    assert set(de_modelos[f"params.{COLUMNA_PESO}"].astype(float)) == {
        experimento.peso_elegido_}


def test_la_clasificacion_llega_hasta_la_prueba(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro, problema=CLASIFICACION_FALLA)
    experimento.fase_variables()
    experimento.fase_ventana()
    final = experimento.fase_prueba()
    assert final.problema == "falla_4h"
    assert set(final.metricas_baselines) == {
        "baseline_prevalencia", "baseline_tasa_frente", "baseline_actividad"}
    assert "probabilidad_media" in final.detalle_por_frente.columns
    assert 0.0 <= final.metricas.valor_principal <= 1.0
    assert "precision_media_con_actividad" in final.metricas.como_diccionario()


def test_la_fase_de_ventana_agrega_el_conjunto_minimo_como_verificacion(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    """Si gana un conjunto grande, MINIMO entra igual para verificar la conclusion."""
    from aurum_pipeline.modeling.features import COMPLETO

    experimento = construir(particiones, registro)
    experimento.fase_variables()
    experimento.conjunto_elegido_ = COMPLETO
    tabla = experimento.fase_ventana()
    modelos = tabla[~tabla["modelo"].str.startswith("baseline")]
    assert set(modelos["conjunto_variables"]) == {"COMPLETO", "MINIMO"}


# -- la ventana como hipotesis por defecto -----------------------------------------------


def tabla_de_ventanas(
        expansiva: float, deslizante: float, desviacion: float = 0.01) -> pd.DataFrame:
    """Tabla minima de fase B para la regresion: una expansiva, una deslizante y un baseline."""
    principal = REGRESION_LEY.evaluador.nombre_principal
    filas = [
        {"modelo": "xgboost", "estrategia_ventana": "deslizante_12m", "meses_ventana": 12,
         principal: deslizante, "desviacion_entre_pliegues": desviacion},
        {"modelo": "lightgbm", "estrategia_ventana": "expansiva", "meses_ventana": "",
         principal: expansiva, "desviacion_entre_pliegues": desviacion},
        {"modelo": "baseline_nivel_frente", "estrategia_ventana": "expansiva",
         "meses_ventana": "", principal: 0.0, "desviacion_entre_pliegues": 0.0},
    ]
    return pd.DataFrame(filas).sort_values(principal).reset_index(drop=True)


def test_una_deslizante_que_gana_por_menos_de_la_desviacion_no_desplaza_a_la_expansiva(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    """Reproduce el defecto: 0.3803 contra 0.3806 con 0.016 de desviacion era un empate."""
    experimento = construir(particiones, registro)
    elegida = experimento._elegir_ventana(tabla_de_ventanas(0.3806, 0.3803, 0.016))
    assert elegida["estrategia_ventana"] == "expansiva"
    assert experimento.margen_ventana_ == pytest.approx(0.0003)
    assert experimento.umbral_ventana_ == pytest.approx(0.016)


def test_una_deslizante_que_gana_por_mas_de_la_desviacion_si_desplaza_a_la_expansiva(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro)
    elegida = experimento._elegir_ventana(tabla_de_ventanas(0.40, 0.35, 0.01))
    assert elegida["estrategia_ventana"] == "deslizante_12m"


def test_si_la_expansiva_es_la_mejor_se_elige_sin_mas(
        particiones: tuple[pd.DataFrame, pd.DataFrame],
        registro: RegistroExperimento) -> None:
    experimento = construir(particiones, registro)
    elegida = experimento._elegir_ventana(tabla_de_ventanas(0.35, 0.40, 0.01))
    assert elegida["estrategia_ventana"] == "expansiva"
    assert experimento.margen_ventana_ == pytest.approx(0.0)


def test_el_reajuste_final_honra_la_ventana_deslizante(
        registro: RegistroExperimento) -> None:
    """Reproduce el defecto: el modelo registrado como deslizante entrenaba con todo."""
    matriz = matriz_sintetica(frentes=2, turnos_por_frente=200)
    desarrollo, prueba = ParticionTemporal(proporcion_prueba=0.25).dividir(matriz)
    experimento = Experimento(desarrollo=desarrollo, prueba=prueba, registro=registro,
                              iteraciones_busqueda=2, pliegues=2)
    completo = experimento._recortar_desarrollo(None)
    recorte = experimento._recortar_desarrollo(1)
    assert len(completo) == len(desarrollo)
    assert 0 < len(recorte) < len(desarrollo)
    desde = prueba[domain.COLUMNA_INICIO_TURNO].min() - pd.DateOffset(months=1)
    assert (recorte[domain.COLUMNA_INICIO_TURNO] >= desde).all()
    with pytest.raises(EmptyPartitionError, match="no deja turnos"):
        experimento.prueba = prueba.assign(**{
            domain.COLUMNA_INICIO_TURNO: prueba[domain.COLUMNA_INICIO_TURNO]
            + pd.DateOffset(years=20)})
        experimento._recortar_desarrollo(1)
