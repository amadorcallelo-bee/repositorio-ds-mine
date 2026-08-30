"""Pruebas de la etiqueta de falla a cuatro horas.

Lo que hay que comprobar aqui es la ventana: que empiece al cierre del bloque horario del
turno y no al abrirlo ni al primer evento mas seis horas, que sea cerrada por la derecha y
abierta por la izquierda, y que no mire eventos de otro grupo. Un error en cualquiera de esas
cosas produce una etiqueta que se ve razonable y que el modelo aprende al reves.
"""

from __future__ import annotations

import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError, MissingColumnsError
from aurum_pipeline.modeling.falla import (
    COLUMNA_EVENTOS_VENTANA,
    COLUMNA_FALLA_HORIZONTE,
    COLUMNA_VENTANA_OBSERVADA,
    ConstructorEtiquetaFalla,
)

INICIO = pd.Timestamp("2025-03-01 00:00:00")


def celda(frente: str, horas: int, cierre: int | None = None) -> dict[str, object]:
    """Una celda cuyo bloque empieza a las `horas` del primer dia y cierra seis horas despues.

    `cierre` permite separar el primer evento del cierre del bloque, que es justo lo que la
    etiqueta tiene que distinguir.
    """
    return {
        domain.COLUMNA_FRENTE: frente,
        domain.COLUMNA_INICIO_TURNO: INICIO + pd.Timedelta(hours=horas),
        domain.COLUMNA_CIERRE_TURNO: INICIO + pd.Timedelta(
            hours=horas + 6 if cierre is None else cierre),
    }


def evento_local(frente: str, horas: float, falla: str | None) -> dict[str, object]:
    """Un evento en hora local, con o sin codigo de falla."""
    return {
        domain.COLUMNA_FRENTE: frente,
        domain.COLUMNA_INICIO_TURNO: INICIO + pd.Timedelta(hours=horas),
        domain.COLUMNA_FALLA: falla,
    }


@pytest.fixture
def constructor() -> ConstructorEtiquetaFalla:
    return ConstructorEtiquetaFalla()


def test_una_falla_dentro_de_la_ventana_marca_la_celda(
        constructor: ConstructorEtiquetaFalla) -> None:
    # El turno va de la hora 0 a la 6; la ventana es (6, 10].
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 8.0, "H-HIDRA-02")])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [1]
    assert salida[COLUMNA_VENTANA_OBSERVADA].tolist() == [1]


def test_una_falla_dentro_del_propio_turno_no_marca_la_celda(
        constructor: ConstructorEtiquetaFalla) -> None:
    """La ventana empieza al cerrar el turno: lo que ya paso no es una prediccion."""
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 3.0, "H-HIDRA-02")])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [0]


def test_una_falla_despues_de_la_ventana_no_marca_la_celda(
        constructor: ConstructorEtiquetaFalla) -> None:
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 11.0, "H-HIDRA-02")])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [0]


def test_la_ventana_es_cerrada_por_la_derecha_y_abierta_por_la_izquierda(
        constructor: ConstructorEtiquetaFalla) -> None:
    matriz = pd.DataFrame([celda("FR-A", 0)])
    justo_al_cerrar = pd.DataFrame([evento_local("FR-A", 6.0, "H-HIDRA-02")])
    justo_al_limite = pd.DataFrame([evento_local("FR-A", 10.0, "H-HIDRA-02")])
    assert constructor.agregar(matriz, justo_al_cerrar)[
        COLUMNA_FALLA_HORIZONTE].tolist() == [0]
    assert constructor.agregar(matriz, justo_al_limite)[
        COLUMNA_FALLA_HORIZONTE].tolist() == [1]


def test_la_falla_de_otro_frente_no_contamina(
        constructor: ConstructorEtiquetaFalla) -> None:
    matriz = pd.DataFrame([celda("FR-A", 0), celda("FR-B", 0)])
    eventos = pd.DataFrame([evento_local("FR-B", 8.0, "H-HIDRA-02")])
    salida = constructor.agregar(matriz, eventos)
    assert salida.set_index(domain.COLUMNA_FRENTE)[
        COLUMNA_FALLA_HORIZONTE].to_dict() == {"FR-A": 0, "FR-B": 1}


def test_una_ventana_sin_registros_se_marca_como_no_observada(
        constructor: ConstructorEtiquetaFalla) -> None:
    """No es lo mismo "no fallo" que "no habia nadie perforando"."""
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 100.0, None)])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [0]
    assert salida[COLUMNA_VENTANA_OBSERVADA].tolist() == [0]


def test_una_ventana_con_registros_sin_falla_queda_observada(
        constructor: ConstructorEtiquetaFalla) -> None:
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 8.0, None)])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [0]
    assert salida[COLUMNA_VENTANA_OBSERVADA].tolist() == [1]


def test_agrupar_por_equipo_da_una_etiqueta_distinta() -> None:
    """La variante que pide la letra del enunciado se construye cambiando un parametro."""
    matriz = pd.DataFrame([{**celda("FR-A", 0), domain.COLUMNA_EQUIPO: "EQ-01"},
                           {**celda("FR-A", 0), domain.COLUMNA_EQUIPO: "EQ-02"}])
    eventos = pd.DataFrame([
        {**evento_local("FR-A", 8.0, "H-HIDRA-02"), domain.COLUMNA_EQUIPO: "EQ-01"}])
    por_equipo = ConstructorEtiquetaFalla(columna_grupo=domain.COLUMNA_EQUIPO)
    salida = por_equipo.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [1, 0]


def test_el_horizonte_configurable_cambia_la_ventana() -> None:
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 11.0, "H-HIDRA-02")])
    largo = ConstructorEtiquetaFalla(horizonte_horas=8)
    assert largo.agregar(matriz, eventos)[COLUMNA_FALLA_HORIZONTE].tolist() == [1]


def test_no_muta_la_matriz_recibida(constructor: ConstructorEtiquetaFalla) -> None:
    matriz = pd.DataFrame([celda("FR-A", 0)])
    original = matriz.copy(deep=True)
    constructor.agregar(matriz, pd.DataFrame([evento_local("FR-A", 8.0, "X")]))
    pd.testing.assert_frame_equal(matriz, original)


def test_los_parametros_no_positivos_son_invalidos() -> None:
    with pytest.raises(InvalidParameterError, match="horizonte"):
        ConstructorEtiquetaFalla(horizonte_horas=0)


def test_faltan_columnas_falla_nombrandolas(
        constructor: ConstructorEtiquetaFalla) -> None:
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([evento_local("FR-A", 8.0, "X")])
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_CIERRE_TURNO):
        constructor.agregar(matriz.drop(columns=[domain.COLUMNA_CIERRE_TURNO]), eventos)
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_FALLA):
        constructor.agregar(matriz, eventos.drop(columns=[domain.COLUMNA_FALLA]))


# -- el cierre es el del reloj -----------------------------------------------------------


def test_la_ventana_se_cuenta_desde_el_cierre_del_bloque_y_no_desde_el_primer_evento(
        constructor: ConstructorEtiquetaFalla) -> None:
    """Reproduce el defecto: la ventana se contaba desde el primer evento mas seis horas.

    Con primer evento a la hora 2 y cierre a la 6, una falla a la hora 7 esta en la ventana
    (6, 10]; contar desde el primer evento la habria dejado fuera de (8, 12].
    """
    matriz = pd.DataFrame([celda("FR-A", 2, cierre=6)])
    eventos = pd.DataFrame([evento_local("FR-A", 7.0, "H-HIDRA-02")])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [1]


def test_una_falla_entre_el_primer_evento_mas_seis_horas_y_el_cierre_ya_no_cuenta(
        constructor: ConstructorEtiquetaFalla) -> None:
    """El espejo del anterior.

    Una falla a la hora 11 esta fuera de (6, 10] aunque la definicion vieja la habria
    contado dentro de (8, 12].
    """
    matriz = pd.DataFrame([celda("FR-A", 2, cierre=6)])
    eventos = pd.DataFrame([evento_local("FR-A", 11.0, "H-HIDRA-02")])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_FALLA_HORIZONTE].tolist() == [0]


def test_los_eventos_de_la_ventana_se_cuentan(
        constructor: ConstructorEtiquetaFalla) -> None:
    """El conteo es el techo del problema: con eventos independientes fija la probabilidad."""
    matriz = pd.DataFrame([celda("FR-A", 0)])
    eventos = pd.DataFrame([
        evento_local("FR-A", 5.0, None),   # dentro del turno, no de la ventana
        evento_local("FR-A", 7.0, None),
        evento_local("FR-A", 9.5, None),
        evento_local("FR-A", 10.0, None),  # justo al limite, cerrado por la derecha
        evento_local("FR-A", 10.5, None),  # despues del limite
    ])
    salida = constructor.agregar(matriz, eventos)
    assert salida[COLUMNA_EVENTOS_VENTANA].tolist() == [3]
    assert salida[COLUMNA_VENTANA_OBSERVADA].tolist() == [1]
