"""Pruebas del constructor de la matriz supervisada por turno.

El riesgo de este modulo no es equivocarse en una media: es que el objetivo o alguna feature
de historia vea el futuro. Por eso la mitad de las pruebas comprueban direccion temporal y no
valores.
"""

from __future__ import annotations

import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import (
    InvalidParameterError,
    MissingColumnsError,
    SentinelNotImputedError,
)
from aurum_pipeline.modeling.dataset import ConstructorMatrizTurno, matriz_a_numpy
from aurum_pipeline.tests.datos_modelado import evento, eventos_seguidos, marco_eventos


@pytest.fixture
def constructor() -> ConstructorMatrizTurno:
    return ConstructorMatrizTurno()


@pytest.fixture
def cuatro_turnos() -> pd.DataFrame:
    """Cuatro turnos consecutivos de un frente con leyes 1, 2, 3 y 4."""
    return marco_eventos(eventos_seguidos("FR-A", [1.0, 2.0, 3.0, 4.0]))


# -- agregacion -------------------------------------------------------------------------


def test_agrega_una_fila_por_turno(constructor: ConstructorMatrizTurno,
                                   cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    # Cuatro turnos producen tres pares: el ultimo no tiene turno siguiente.
    assert len(matriz) == 3
    assert matriz["eventos_turno"].tolist() == [2, 2, 2]


def test_la_ley_del_turno_es_la_media_de_sus_lecturas(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos([
        evento(0, "N2", "FR-A", 4.0, minuto=0),
        evento(0, "N2", "FR-A", 6.0, minuto=20),
        evento(0, "D1", "FR-A", 9.0),
    ])
    matriz = constructor.construir(marco)
    assert matriz[domain.COLUMNA_LEY_TURNO].iloc[0] == pytest.approx(5.0)
    assert matriz["lecturas_ley_turno"].iloc[0] == 2


def test_las_leyes_reconstruidas_no_entran_al_promedio(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos([
        evento(0, "N2", "FR-A", 4.0, minuto=0),
        evento(0, "N2", "FR-A", 100.0, minuto=20),
        evento(0, "D1", "FR-A", 9.0),
    ])
    imputadas = pd.Index([1])
    matriz = constructor.construir(marco, indices_imputados=imputadas)
    assert matriz[domain.COLUMNA_LEY_TURNO].iloc[0] == pytest.approx(4.0)
    assert matriz["lecturas_ley_turno"].iloc[0] == 1


def test_un_turno_sin_ninguna_lectura_medida_rompe_los_dos_pares_que_toca(
        constructor: ConstructorMatrizTurno) -> None:
    """Un turno sin ley medida no puede ser fila ni objetivo, y se pierden ambos pares.

    Es el costo de promediar solo lecturas medidas, y esta acotado: en el extracto real son
    11 celdas de 4019, de modo que se pierden unos 22 pares de 3985.
    """
    marco = marco_eventos([
        evento(0, "N2", "FR-A", 4.0),
        evento(0, "D1", "FR-A", 5.0),
        evento(0, "D2", "FR-A", 6.0),
        evento(0, "N1", "FR-A", 7.0),
    ])
    # Se marca como reconstruida la unica lectura del segundo turno: queda sin ley.
    matriz = constructor.construir(marco, indices_imputados=pd.Index([1]))
    assert matriz[domain.COLUMNA_TURNO].tolist() == ["D2"]
    assert matriz[domain.COLUMNA_OBJETIVO].tolist() == [7.0]


def test_la_moda_no_revienta_con_una_categoria_toda_nula(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos(eventos_seguidos("FR-A", [1.0, 2.0]))
    marco[domain.COLUMNA_TIPO_MINERAL] = None
    matriz = constructor.construir(marco)
    assert matriz[domain.COLUMNA_TIPO_MINERAL].isna().all()


# -- objetivo ---------------------------------------------------------------------------


def test_el_objetivo_es_la_ley_del_turno_siguiente(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    assert matriz[domain.COLUMNA_LEY_TURNO].tolist() == [1.0, 2.0, 3.0]
    assert matriz[domain.COLUMNA_OBJETIVO].tolist() == [2.0, 3.0, 4.0]


def test_el_objetivo_ocurre_siempre_despues_del_turno_que_lo_predice(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    assert (matriz[domain.COLUMNA_INICIO_OBJETIVO]
            > matriz[domain.COLUMNA_INICIO_TURNO]).all()


def test_el_objetivo_nunca_viene_de_otro_frente(
        constructor: ConstructorMatrizTurno) -> None:
    # Dos frentes intercalados en el tiempo: si el desplazamiento no agrupara por frente,
    # la ley de FR-B se colaria como objetivo de FR-A.
    marco = marco_eventos(
        eventos_seguidos("FR-A", [1.0, 2.0, 3.0], eventos_por_turno=1)
        + eventos_seguidos("FR-B", [50.0, 60.0, 70.0], eventos_por_turno=1))
    matriz = constructor.construir(marco)
    de_a = matriz[matriz[domain.COLUMNA_FRENTE] == "FR-A"]
    assert de_a[domain.COLUMNA_OBJETIVO].tolist() == [2.0, 3.0]


def test_el_ultimo_turno_de_cada_frente_se_descarta(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos(
        eventos_seguidos("FR-A", [1.0, 2.0], eventos_por_turno=1)
        + eventos_seguidos("FR-B", [7.0, 8.0], eventos_por_turno=1))
    matriz = constructor.construir(marco)
    assert len(matriz) == 2
    assert matriz[domain.COLUMNA_LEY_TURNO].tolist() == [1.0, 7.0]


# -- historia causal --------------------------------------------------------------------


def test_el_rezago_trae_el_turno_anterior_y_falta_en_el_primero(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    assert pd.isna(matriz["ley_rezago_1"].iloc[0])
    assert matriz["ley_rezago_1"].tolist()[1:] == [1.0, 2.0]


def test_ninguna_feature_de_historia_reproduce_el_objetivo(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    objetivo = matriz[domain.COLUMNA_OBJETIVO]
    for columna in constructor.columnas_generadas():
        if columna in ("dias_desde_turno_previo", "turnos_previos_frente"):
            continue
        assert not objetivo.equals(matriz[columna]), f"{columna} replica el objetivo"


def test_la_media_movil_incluye_el_turno_actual_y_no_el_siguiente(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    # Turnos con ley 1, 2, 3: la media de tres del tercer turno es 2.0, no 3.0 (que
    # incluiria el objetivo) ni 1.5 (que excluiria el turno actual).
    assert matriz["ley_media_3"].tolist() == pytest.approx([1.0, 1.5, 2.0])


def test_la_desviacion_movil_falta_con_un_solo_turno(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    assert pd.isna(matriz["ley_desv_3"].iloc[0])
    assert matriz["ley_desv_3"].iloc[1] == pytest.approx(0.7071, abs=1e-4)


def test_los_dias_desde_el_turno_previo_miden_el_hueco(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos([
        evento(0, "N2", "FR-A", 1.0),
        evento(0, "D1", "FR-A", 2.0),
        evento(10, "D1", "FR-A", 3.0),
    ])
    matriz = constructor.construir(marco)
    assert pd.isna(matriz["dias_desde_turno_previo"].iloc[0])
    assert matriz["dias_desde_turno_previo"].iloc[1] == pytest.approx(0.25)


def test_los_turnos_previos_del_frente_cuentan_desde_cero(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    assert matriz["turnos_previos_frente"].tolist() == [0, 1, 2]


def test_la_fecha_local_no_parte_el_turno_de_noche(
        constructor: ConstructorMatrizTurno) -> None:
    # N2 va de 00:00 a 05:59 local: sus eventos tienen que caer en la misma jornada.
    marco = marco_eventos([
        evento(1, "N2", "FR-A", 1.0, minuto=0),
        evento(1, "N2", "FR-A", 3.0, minuto=300),
        evento(1, "D1", "FR-A", 5.0),
    ])
    matriz = constructor.construir(marco)
    assert len(matriz) == 1
    assert matriz["eventos_turno"].iloc[0] == 2


# -- precondiciones ---------------------------------------------------------------------


def test_el_centinela_sin_imputar_falla_con_mensaje_propio(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos([
        evento(0, "N2", "FR-A", domain.CENTINELA_LEY),
        evento(0, "D1", "FR-A", 5.0),
    ])
    with pytest.raises(SentinelNotImputedError, match="AurumImputer"):
        constructor.construir(marco)


def test_una_columna_faltante_falla_nombrandola(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_SECTOR):
        constructor.construir(cuatro_turnos.drop(columns=[domain.COLUMNA_SECTOR]))


def test_un_rezago_no_positivo_es_un_parametro_invalido() -> None:
    with pytest.raises(InvalidParameterError, match="rezagos"):
        ConstructorMatrizTurno(rezagos=(0,))


def test_una_ventana_movil_de_un_turno_es_un_parametro_invalido() -> None:
    with pytest.raises(InvalidParameterError, match="ventana movil"):
        ConstructorMatrizTurno(ventanas_moviles=(1,))


def test_no_muta_el_marco_recibido(constructor: ConstructorMatrizTurno,
                                   cuatro_turnos: pd.DataFrame) -> None:
    original = cuatro_turnos.copy(deep=True)
    constructor.construir(cuatro_turnos)
    pd.testing.assert_frame_equal(cuatro_turnos, original)


def test_un_frente_con_un_solo_turno_devuelve_matriz_vacia(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos([evento(0, "N2", "FR-A", 1.0)])
    matriz = constructor.construir(marco)
    assert matriz.empty


def test_las_columnas_generadas_estan_todas_en_la_matriz(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    assert set(constructor.columnas_generadas()) <= set(matriz.columns)


# -- utilidad de paso a los modelos -----------------------------------------------------


def test_matriz_a_numpy_extrae_las_columnas_pedidas(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    arreglo = matriz_a_numpy(matriz, (domain.COLUMNA_LEY_TURNO, "turnos_previos_frente"))
    assert arreglo.shape == (3, 2)
    assert arreglo[:, 0].tolist() == [1.0, 2.0, 3.0]


def test_matriz_a_numpy_falla_si_falta_una_columna(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    matriz = constructor.construir(cuatro_turnos)
    with pytest.raises(MissingColumnsError, match="inexistente"):
        matriz_a_numpy(matriz, ("inexistente",))


def test_una_clave_de_celda_nula_falla_en_lugar_de_inventar_un_frente(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    con_nulo = cuatro_turnos.copy()
    con_nulo.loc[0, domain.COLUMNA_FRENTE] = None
    with pytest.raises(InvalidParameterError, match=domain.COLUMNA_FRENTE):
        constructor.construir(con_nulo)


def test_el_orden_de_los_eventos_de_entrada_no_altera_la_matriz(
        constructor: ConstructorMatrizTurno, cuatro_turnos: pd.DataFrame) -> None:
    """El extracto llega ordenado, pero el resultado no puede depender de que llegue asi."""
    desordenado = cuatro_turnos.iloc[::-1].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        constructor.construir(cuatro_turnos), constructor.construir(desordenado))


# -- cierre del turno y resumen por umbral ------------------------------------------------


def test_el_cierre_del_turno_es_el_fin_del_bloque_horario(
        constructor: ConstructorMatrizTurno) -> None:
    """El cierre sale del reloj, no de los eventos.

    Un turno N2 cierra a las 06:00 aunque su primer evento llegue a las 00:00 y el ultimo
    a las 00:20.
    """
    marco = marco_eventos(eventos_seguidos("FR-A", [1.0, 2.0], eventos_por_turno=2))
    matriz = constructor.construir(marco)
    assert matriz[domain.COLUMNA_TURNO].tolist() == ["N2"]
    assert matriz[domain.COLUMNA_CIERRE_TURNO].iloc[0] == pd.Timestamp("2025-01-06 06:00:00")
    assert matriz[domain.COLUMNA_MINUTOS_INACTIVO].iloc[0] == pytest.approx(340.0)


def test_el_cierre_no_depende_de_cuando_llego_el_primer_evento(
        constructor: ConstructorMatrizTurno) -> None:
    """Reproduce el defecto: primer evento mas seis horas no es el cierre del turno."""
    marco = marco_eventos([
        evento(0, "D1", "FR-A", 4.0, minuto=200),
        evento(0, "D1", "FR-A", 5.0, minuto=250),
        evento(0, "D2", "FR-A", 6.0),
    ])
    matriz = constructor.construir(marco)
    assert matriz[domain.COLUMNA_CIERRE_TURNO].iloc[0] == pd.Timestamp("2025-01-06 12:00:00")
    assert matriz[domain.COLUMNA_MINUTOS_INACTIVO].iloc[0] == pytest.approx(110.0)


def test_el_resumen_por_umbral_conserva_el_escalon_que_la_media_diluye(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos([
        evento(0, "N2", "FR-A", 4.0, minuto=0, temperatura=70.0),
        evento(0, "N2", "FR-A", 4.0, minuto=20, temperatura=97.0),
        evento(0, "N2", "FR-A", 4.0, minuto=40, temperatura=71.0),
        evento(0, "D1", "FR-A", 5.0),
    ])
    marco.loc[1, domain.COLUMNA_VIBRACION] = 14.0
    matriz = constructor.construir(marco)
    primera = matriz.iloc[0]
    assert primera[domain.COLUMNA_TEMPERATURA] < domain.UMBRAL_TEMP_RIESGO
    assert primera[domain.COLUMNA_TEMP_MAX] == pytest.approx(97.0)
    assert primera[domain.COLUMNA_EVENTOS_TEMP_RIESGO] == 1
    assert primera[domain.COLUMNA_VIB_MAX] == pytest.approx(14.0)
    assert primera[domain.COLUMNA_EVENTOS_VIB_ALERTA] == 1


def test_un_sensor_faltante_no_cuenta_como_excedencia(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos(eventos_seguidos("FR-A", [1.0, 2.0], eventos_por_turno=2))
    marco.loc[0, domain.COLUMNA_TEMPERATURA] = None
    matriz = constructor.construir(marco)
    assert matriz[domain.COLUMNA_EVENTOS_TEMP_RIESGO].iloc[0] == 0


def test_un_codigo_de_turno_fuera_del_dominio_falla_con_excepcion_propia(
        constructor: ConstructorMatrizTurno) -> None:
    marco = marco_eventos(eventos_seguidos("FR-A", [1.0, 2.0]))
    marco[domain.COLUMNA_TURNO] = "D3"
    with pytest.raises(InvalidParameterError, match="D3"):
        constructor.construir(marco)
