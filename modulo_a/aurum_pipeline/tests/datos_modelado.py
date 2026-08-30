"""Datos sinteticos para las pruebas del modelado del A-2.

Igual que el resto de las pruebas del proyecto, no leen `OP_AURUM_extract.csv`: se
construyen marcos pequenos y deterministas para que cada prueba falle por el motivo que
declara y no porque el extracto cambio.

El generador de aqui produce eventos ya imputados -sin centinela- porque el constructor de
la matriz exige que el imputador haya corrido antes, y esa precondicion se prueba aparte.
"""

from __future__ import annotations

import pandas as pd

from aurum_pipeline import domain

#: Instante local en que empieza el primer turno de los marcos de prueba, ya en UTC.
INICIO_UTC = pd.Timestamp("2025-01-06 11:00:00")

#: Hora local de comienzo de cada turno, segun el desfase del dominio.
HORA_TURNO: dict[str, int] = {"D1": 6, "D2": 12, "N1": 18, "N2": 0}

#: Orden cronologico de los turnos dentro de una misma fecha local: N2 va de 00:00 a
#: 05:59, de modo que abre la jornada y no la cierra.
TURNOS_EN_ORDEN: tuple[str, ...] = ("N2", "D1", "D2", "N1")


def evento(
    dia: int,
    turno: str,
    frente: str,
    ley: float,
    minuto: int = 0,
    tipo: str = "OX",
    equipo: str = "EQ-01",
    falla: str | None = None,
    temperatura: float = 70.0,
) -> dict[str, object]:
    """Un evento OPUS con todas las columnas que el constructor de la matriz exige.

    `dia` y `turno` se traducen a un instante UTC, de modo que las pruebas escriban
    "segundo turno del dia tres" en lugar de un timestamp completo.
    """
    local = (pd.Timestamp("2025-01-06 00:00:00")
             + pd.Timedelta(days=dia, hours=HORA_TURNO[turno], minutes=minuto))
    return {
        domain.COLUMNA_TIEMPO: local + pd.Timedelta(hours=domain.DESFASE_LOCAL_HORAS),
        domain.COLUMNA_FRENTE: frente,
        domain.COLUMNA_TURNO: turno,
        domain.COLUMNA_LEY: ley,
        domain.COLUMNA_TIPO_MINERAL: tipo,
        domain.COLUMNA_EQUIPO: equipo,
        domain.COLUMNA_SECTOR: "Veta-Sur",
        domain.COLUMNA_FALLA: falla,
        domain.COLUMNA_MANTENIMIENTO: 0,
        domain.COLUMNA_TONELAJE: 100.0,
        domain.COLUMNA_PRESION: 200.0,
        domain.COLUMNA_RPM: 1000.0,
        domain.COLUMNA_AVANCE: 1.5,
        domain.COLUMNA_AGUA: 50.0,
        domain.COLUMNA_VIBRACION: 5.0,
        domain.COLUMNA_TEMPERATURA: temperatura,
    }


def marco_eventos(eventos: list[dict[str, object]]) -> pd.DataFrame:
    """Marco OPUS a partir de una lista de eventos, en el orden en que se escriben."""
    return pd.DataFrame(eventos)


def eventos_seguidos(
    frente: str,
    leyes: list[float],
    eventos_por_turno: int = 2,
    dia_inicial: int = 0,
) -> list[dict[str, object]]:
    """Turnos consecutivos de un frente, uno por cada ley, con varios eventos cada uno.

    Los turnos avanzan D1, D2, N1, N2 y cambian de dia al completar los cuatro, que es como
    se comporta el extracto real.
    """
    generados: list[dict[str, object]] = []
    for indice, ley in enumerate(leyes):
        dia = dia_inicial + indice // len(TURNOS_EN_ORDEN)
        turno = TURNOS_EN_ORDEN[indice % len(TURNOS_EN_ORDEN)]
        for repeticion in range(eventos_por_turno):
            generados.append(
                evento(dia, turno, frente, ley, minuto=repeticion * 20))
    return generados


def matriz_sintetica(
    frentes: int = 3,
    turnos_por_frente: int = 40,
    semilla: int = 7,
) -> pd.DataFrame:
    """Matriz supervisada sintetica con todas las columnas que usan los modelos.

    Imita la estructura del extracto en lo que importa para probar el modelado: cada frente
    tiene su propio nivel de ley y el objetivo es ese nivel mas ruido, que es exactamente lo
    que el EDA midio. Asi el baseline del nivel del frente es dificil de superar tambien aqui,
    y una prueba que afirme lo contrario esta detectando un defecto y no un dato distinto.
    """
    import numpy as np

    generador = np.random.default_rng(semilla)
    filas = []
    for indice_frente in range(frentes):
        nivel = 3.0 + 4.0 * indice_frente
        inicio = pd.Timestamp("2024-01-01") + pd.Timedelta(hours=6 * indice_frente)
        for turno in range(turnos_por_frente):
            momento = inicio + pd.Timedelta(hours=6 * turno)
            # La etiqueta imita la estructura medida en el extracto: es cero cuando el frente
            # no registra en la ventana, y la inactividad al cierre anticipa esa continuidad.
            sigue_operando = generador.random() < 0.85
            minutos_inactivo = (generador.uniform(1.0, 40.0) if sigue_operando
                                else generador.uniform(120.0, 360.0))
            filas.append({
                domain.COLUMNA_FRENTE: f"FR-{indice_frente}",
                domain.COLUMNA_FECHA_LOCAL: momento.normalize(),
                domain.COLUMNA_TURNO: TURNOS_EN_ORDEN[turno % len(TURNOS_EN_ORDEN)],
                domain.COLUMNA_INICIO_TURNO: momento,
                domain.COLUMNA_CIERRE_TURNO: momento + pd.Timedelta(hours=6),
                domain.COLUMNA_INICIO_OBJETIVO: momento + pd.Timedelta(hours=6),
                domain.COLUMNA_LEY_TURNO: nivel + generador.normal(0, 0.3),
                domain.COLUMNA_OBJETIVO: nivel + generador.normal(0, 0.3),
                domain.COLUMNA_TIPO_MINERAL: "OX" if turno % 2 else "SUL",
                domain.COLUMNA_EQUIPO: f"EQ-{indice_frente}",
                domain.COLUMNA_SECTOR: "Veta-Sur",
                "eventos_turno": 12,
                "lecturas_ley_turno": 11,
                "fallas_turno": int(generador.random() < 0.2),
                "mantenimiento_turno": 0.0,
                domain.COLUMNA_TONELAJE: 100.0 + generador.normal(0, 5),
                domain.COLUMNA_PRESION: 200.0 + generador.normal(0, 5),
                domain.COLUMNA_RPM: 1000.0 + generador.normal(0, 50),
                domain.COLUMNA_AVANCE: 1.5 + generador.normal(0, 0.1),
                domain.COLUMNA_AGUA: 50.0 + generador.normal(0, 2),
                domain.COLUMNA_VIBRACION: 5.0 + generador.normal(0, 1),
                domain.COLUMNA_TEMPERATURA: 70.0 + generador.normal(0, 5),
                "ley_rezago_1": nivel + generador.normal(0, 0.3),
                "ley_rezago_2": nivel + generador.normal(0, 0.3),
                "ley_media_3": nivel,
                "ley_desv_3": 0.3,
                "ley_media_10": nivel,
                "ley_desv_10": 0.3,
                "dias_desde_turno_previo": 0.25,
                "turnos_previos_frente": turno,
                domain.COLUMNA_MINUTOS_INACTIVO: minutos_inactivo,
                domain.COLUMNA_TEMP_MAX: 80.0 + abs(generador.normal(0, 8)),
                domain.COLUMNA_EVENTOS_TEMP_RIESGO: int(generador.random() < 0.3),
                domain.COLUMNA_VIB_MAX: 7.0 + abs(generador.normal(0, 3)),
                domain.COLUMNA_EVENTOS_VIB_ALERTA: 0,
                "falla_en_4h": int(sigue_operando and generador.random() < 0.3),
                "ventana_con_registros": int(sigue_operando),
                "eventos_en_ventana": 10 if sigue_operando else 0,
            })
    return (pd.DataFrame(filas)
            .sort_values(domain.COLUMNA_INICIO_TURNO)
            .reset_index(drop=True))
