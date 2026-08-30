"""Pruebas de la particion temporal y de las dos estrategias de ventana.

La matriz de estas pruebas se escribe a mano y no se construye con `ConstructorMatrizTurno`:
el particionador solo necesita dos columnas de instantes, y fabricarlas directamente hace que
un fallo aqui senale al particionador y no al constructor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor
from sklearn.model_selection import RandomizedSearchCV, cross_val_score

from aurum_pipeline import domain
from aurum_pipeline.errors import (
    EmptyPartitionError,
    InvalidParameterError,
    MisalignedIndexError,
    MissingColumnsError,
)
from aurum_pipeline.modeling.splitter import (
    ParticionTemporal,
    VentanaExpansiva,
    VentanaTemporal,
    ventana_desde_matriz,
)


def matriz_de_turnos(cantidad: int, horas_entre_turnos: int = 6) -> pd.DataFrame:
    """Turnos consecutivos de un unico frente, cada uno apuntando al siguiente."""
    paso = pd.Timedelta(hours=horas_entre_turnos)
    inicio = pd.Series([pd.Timestamp("2024-01-01") + paso * k for k in range(cantidad)])
    # El objetivo de cada turno ocurre en el turno inmediatamente siguiente; el ultimo
    # apunta a un turno que la matriz no contiene, como pasa en la matriz real antes de
    # descartar las filas sin objetivo.
    objetivo = inicio.shift(-1)
    objetivo.iloc[-1] = inicio.iloc[-1] + paso
    return pd.DataFrame({
        domain.COLUMNA_INICIO_TURNO: inicio,
        domain.COLUMNA_INICIO_OBJETIVO: objetivo,
        domain.COLUMNA_LEY_TURNO: np.arange(cantidad, dtype=float),
        domain.COLUMNA_OBJETIVO: np.arange(1, cantidad + 1, dtype=float),
    })


@pytest.fixture
def matriz() -> pd.DataFrame:
    return matriz_de_turnos(240)


# -- particion de prueba ----------------------------------------------------------------


def test_la_prueba_es_la_cola_del_calendario(matriz: pd.DataFrame) -> None:
    desarrollo, prueba = ParticionTemporal(proporcion_prueba=0.25).dividir(matriz)
    assert len(desarrollo) + len(prueba) == len(matriz)
    assert (desarrollo[domain.COLUMNA_INICIO_TURNO].max()
            < prueba[domain.COLUMNA_INICIO_TURNO].min())


def test_la_particion_guarda_su_fecha_de_corte(matriz: pd.DataFrame) -> None:
    particion = ParticionTemporal(proporcion_prueba=0.20)
    particion.dividir(matriz)
    assert particion.fecha_corte_ is not None
    assert isinstance(particion.fecha_corte_, pd.Timestamp)


def test_una_proporcion_fuera_de_rango_es_un_parametro_invalido() -> None:
    with pytest.raises(InvalidParameterError, match="proporcion_prueba"):
        ParticionTemporal(proporcion_prueba=1.0)


def test_particionar_una_matriz_vacia_falla(matriz: pd.DataFrame) -> None:
    with pytest.raises(EmptyPartitionError, match="no tiene filas"):
        ParticionTemporal().dividir(matriz.iloc[0:0])


def test_particionar_sin_la_columna_de_inicio_falla_nombrandola(
        matriz: pd.DataFrame) -> None:
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_INICIO_TURNO):
        ParticionTemporal().dividir(matriz.drop(columns=[domain.COLUMNA_INICIO_TURNO]))


def test_un_solo_instante_repetido_no_admite_corte() -> None:
    repetida = matriz_de_turnos(4)
    repetida[domain.COLUMNA_INICIO_TURNO] = pd.Timestamp("2024-01-01")
    with pytest.raises(EmptyPartitionError, match="deja desarrollo"):
        ParticionTemporal().dividir(repetida)


# -- contrato de la ventana -------------------------------------------------------------


def test_la_ventana_abstracta_no_se_puede_instanciar(matriz: pd.DataFrame) -> None:
    with pytest.raises(TypeError):
        VentanaTemporal(  # type: ignore[abstract]
            matriz[domain.COLUMNA_INICIO_TURNO], matriz[domain.COLUMNA_INICIO_OBJETIVO])


def test_el_numero_de_pliegues_es_el_declarado(matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=4)
    assert ventana.get_n_splits() == 4
    assert len(list(ventana.split(matriz))) == 4


def test_los_nombres_identifican_la_estrategia(matriz: pd.DataFrame) -> None:
    assert ventana_desde_matriz(matriz).nombre == "expansiva"
    assert ventana_desde_matriz(matriz).meses is None
    assert ventana_desde_matriz(matriz, meses=6).nombre == "deslizante_6m"
    assert ventana_desde_matriz(matriz, meses=6).meses == 6


def test_las_dos_estrategias_comparten_los_bloques_de_validacion(
        matriz: pd.DataFrame) -> None:
    """Es la condicion para que compararlas signifique algo."""
    expansiva = ventana_desde_matriz(matriz)
    deslizante = ventana_desde_matriz(matriz, meses=1)
    validaciones_e = [val.tolist() for _, val in expansiva.split(matriz)]
    validaciones_d = [val.tolist() for _, val in deslizante.split(matriz)]
    assert validaciones_e == validaciones_d


def test_cada_turno_valida_a_lo_sumo_una_vez(matriz: pd.DataFrame) -> None:
    validados = [i for _, val in ventana_desde_matriz(matriz).split(matriz) for i in val]
    assert len(validados) == len(set(validados))


def test_el_ultimo_bloque_incluye_el_instante_final(matriz: pd.DataFrame) -> None:
    """El borde derecho del ultimo bloque es cerrado; si no, la ultima fila no valida nunca."""
    ventana = ventana_desde_matriz(matriz)
    ultimo = list(ventana.split(matriz))[-1][1]
    assert len(matriz) - 1 in ultimo.tolist()


# -- direccion temporal y purga ---------------------------------------------------------


def test_el_entrenamiento_es_siempre_anterior_a_la_validacion(
        matriz: pd.DataFrame) -> None:
    inicio = matriz[domain.COLUMNA_INICIO_TURNO]
    for entrena, valida in ventana_desde_matriz(matriz).split(matriz):
        assert inicio.iloc[entrena].max() < inicio.iloc[valida].min()


def test_ninguna_fila_de_entrenamiento_predice_dentro_del_bloque_de_validacion(
        matriz: pd.DataFrame) -> None:
    """La purga: sin ella el modelo ve el bloque que lo evalua y la metrica queda inflada."""
    inicio = matriz[domain.COLUMNA_INICIO_TURNO]
    objetivo = matriz[domain.COLUMNA_INICIO_OBJETIVO]
    for entrena, valida in ventana_desde_matriz(matriz).split(matriz):
        comienzo_bloque = inicio.iloc[valida].min()
        assert (objetivo.iloc[entrena] < comienzo_bloque).all()


def test_la_purga_descarta_la_fila_pegada_a_la_frontera(matriz: pd.DataFrame) -> None:
    """Sin purga, la ultima fila anterior al bloque entraria: su objetivo cae adentro."""
    inicio = matriz[domain.COLUMNA_INICIO_TURNO]
    entrena, valida = next(iter(ventana_desde_matriz(matriz).split(matriz)))
    comienzo_bloque = inicio.iloc[valida].min()
    anteriores = np.flatnonzero((inicio < comienzo_bloque).to_numpy())
    assert anteriores[-1] not in entrena.tolist()
    assert len(entrena) == len(anteriores) - 1


def test_la_expansiva_entrena_con_toda_la_historia_previa(matriz: pd.DataFrame) -> None:
    inicio = matriz[domain.COLUMNA_INICIO_TURNO]
    entrena, _ = list(ventana_desde_matriz(matriz).split(matriz))[-1]
    assert inicio.iloc[entrena].min() == inicio.min()


def test_la_deslizante_no_mira_mas_atras_que_su_longitud(matriz: pd.DataFrame) -> None:
    inicio = matriz[domain.COLUMNA_INICIO_TURNO]
    ventana = ventana_desde_matriz(matriz, meses=1)
    for entrena, valida in ventana.split(matriz):
        limite = inicio.iloc[valida].min() - pd.DateOffset(months=1)
        assert inicio.iloc[entrena].min() >= limite


def test_la_deslizante_entrena_con_menos_filas_que_la_expansiva(
        matriz: pd.DataFrame) -> None:
    ultima_e = list(ventana_desde_matriz(matriz).split(matriz))[-1][0]
    ultima_d = list(ventana_desde_matriz(matriz, meses=1).split(matriz))[-1][0]
    assert len(ultima_d) < len(ultima_e)


# -- precondiciones ---------------------------------------------------------------------


def test_una_matriz_de_otro_tamano_falla_en_lugar_de_partir_mal(
        matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz)
    with pytest.raises(MisalignedIndexError, match="mismo orden"):
        list(ventana.split(matriz.head(10)))


def test_indices_temporales_de_distinto_largo_fallan(matriz: pd.DataFrame) -> None:
    with pytest.raises(MisalignedIndexError):
        VentanaExpansiva(matriz[domain.COLUMNA_INICIO_TURNO],
                         matriz[domain.COLUMNA_INICIO_OBJETIVO].head(3))


def test_un_indice_temporal_vacio_falla(matriz: pd.DataFrame) -> None:
    vacia = matriz.iloc[0:0]
    with pytest.raises(EmptyPartitionError, match="no tiene filas"):
        VentanaExpansiva(vacia[domain.COLUMNA_INICIO_TURNO],
                         vacia[domain.COLUMNA_INICIO_OBJETIVO])


def test_menos_de_un_pliegue_es_un_parametro_invalido(matriz: pd.DataFrame) -> None:
    with pytest.raises(InvalidParameterError, match="pliegues"):
        ventana_desde_matriz(matriz, pliegues=0)


def test_una_ventana_de_cero_meses_es_un_parametro_invalido(matriz: pd.DataFrame) -> None:
    with pytest.raises(InvalidParameterError, match="meses positivos"):
        ventana_desde_matriz(matriz, meses=0)


def test_un_pliegue_sin_entrenamiento_falla_en_lugar_de_devolver_vacio() -> None:
    """Una ventana mas corta que el hueco entre bloques deja el entrenamiento vacio."""
    corta = matriz_de_turnos(60, horas_entre_turnos=24 * 30)
    with pytest.raises(EmptyPartitionError, match="filas de entrenamiento"):
        list(ventana_desde_matriz(corta, meses=1).split(corta))


def test_construir_la_ventana_sin_las_columnas_temporales_falla(
        matriz: pd.DataFrame) -> None:
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_INICIO_OBJETIVO):
        ventana_desde_matriz(matriz.drop(columns=[domain.COLUMNA_INICIO_OBJETIVO]))


def test_el_indice_de_la_matriz_no_altera_los_pliegues(matriz: pd.DataFrame) -> None:
    """El particionador trabaja por posicion: un indice desplazado no debe cambiar nada."""
    desplazada = matriz.copy()
    desplazada.index = pd.RangeIndex(start=1000, stop=1000 + len(matriz))
    esperado = [(e.tolist(), v.tolist()) for e, v in ventana_desde_matriz(matriz).split(matriz)]
    obtenido = [(e.tolist(), v.tolist())
                for e, v in ventana_desde_matriz(desplazada).split(desplazada)]
    assert obtenido == esperado


# -- integracion con scikit-learn -------------------------------------------------------


def test_scikit_learn_consume_estos_pliegues(matriz: pd.DataFrame) -> None:
    """Si esto falla, `RandomizedSearchCV` armaria su propia particion aleatoria."""
    variables = matriz[[domain.COLUMNA_LEY_TURNO]].to_numpy()
    objetivo = matriz[domain.COLUMNA_OBJETIVO].to_numpy()
    puntajes = cross_val_score(
        DummyRegressor(strategy="mean"), variables, objetivo,
        cv=ventana_desde_matriz(matriz), scoring="neg_mean_absolute_error")
    assert len(puntajes) == domain.PLIEGUES_VALIDACION
    assert np.isfinite(puntajes).all()


def test_la_busqueda_aleatoria_respeta_estos_pliegues(matriz: pd.DataFrame) -> None:
    """El consumidor real del splitter es `RandomizedSearchCV`.

    Si no aceptara este objeto como `cv`, armaria por dentro una particion aleatoria y
    echaria a perder la estructura temporal: los hiperparametros quedarian elegidos con
    informacion del futuro.
    """
    variables = matriz[[domain.COLUMNA_LEY_TURNO]].to_numpy()
    objetivo = matriz[domain.COLUMNA_OBJETIVO].to_numpy()
    busqueda = RandomizedSearchCV(
        DummyRegressor(),
        {"strategy": ["mean", "median"]},
        n_iter=2,
        cv=ventana_desde_matriz(matriz),
        scoring="neg_mean_absolute_error",
        random_state=0,
    ).fit(variables, objetivo)
    assert busqueda.n_splits_ == domain.PLIEGUES_VALIDACION
    assert busqueda.best_params_["strategy"] in ("mean", "median")
