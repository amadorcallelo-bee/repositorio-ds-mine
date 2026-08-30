"""Constantes del dominio operacional OPUS-MINE.

Son reglas de negocio, no detalles de implementacion: el centinela de la sonda XRF, los
rangos publicados en el diccionario de variables y el desfase horario de la unidad. Viven
en un unico modulo porque cambian por decision del area de operaciones y no por un refactor
del pipeline, y porque repartirlas por los transformadores obliga a buscarlas en cuatro
archivos cuando el diccionario se actualice.

Los nombres de columna se declaran aqui por la misma razon y porque el enunciado prohibe
renombrarlos: si el codigo los escribe literales en veinte lugares, un cambio del extracto
se convierte en una caceria de cadenas.
"""

from __future__ import annotations

from typing import Final

# --- Nombres de columna del extracto (nomenclatura interna OPUS, no se renombran) ---

COLUMNA_TIEMPO: Final[str] = "ts_opus_utc"
COLUMNA_FRENTE: Final[str] = "frente_id"
COLUMNA_TIPO_MINERAL: Final[str] = "tipo_mineral"
COLUMNA_LEY: Final[str] = "ley_au_gpT"
COLUMNA_EQUIPO: Final[str] = "equipo_id"
COLUMNA_TEMPERATURA: Final[str] = "temp_motor_c"
COLUMNA_VIBRACION: Final[str] = "vibracion_rms_ms2"
COLUMNA_PRESION: Final[str] = "pres_hidraul_bar"
COLUMNA_RPM: Final[str] = "rpm_corona"
COLUMNA_AVANCE: Final[str] = "avance_mmin"

# --- Reglas del dominio ---

#: Valor con que la sonda XRF codifica "sin lectura valida" dentro del dominio numerico.
#: No es un valor de ley: una ley de oro negativa no existe fisicamente.
CENTINELA_LEY: Final[float] = -1.0

#: Desfase de la hora local de operacion respecto a UTC, deducido del extracto: cada hora
#: UTC cae en un unico turno y restando cinco horas los turnos empiezan en punto.
DESFASE_LOCAL_HORAS: Final[int] = 5

#: Gramos en una onza troy, para convertir ley por tonelaje a onzas.
OZ_TROY_EN_GRAMOS: Final[float] = 31.1035

#: Rangos operacionales publicados en el diccionario de variables, como (minimo, maximo).
#: `None` significa que el diccionario no publica ese extremo.
RANGOS_SENSORES: Final[dict[str, tuple[float | None, float | None]]] = {
    "pres_hidraul_bar": (180.0, 240.0),
    "rpm_corona": (800.0, 1400.0),
    "vibracion_rms_ms2": (None, 12.0),
    "temp_motor_c": (None, 95.0),
}

#: Umbral de temperatura donde el extracto muestra el salto real de la tasa de falla: por
#: debajo ronda el 2% y por encima se estabiliza en 22%. Esta siete grados por debajo del
#: apagado automatico que publica el diccionario, y captura cuatro veces mas fallas.
UMBRAL_TEMP_RIESGO: Final[float] = 88.0

#: Temperatura de referencia para medir el sobrecalentamiento del motor. Se toma el minimo
#: observado en el extracto, que actua como proxy de la temperatura ambiente de la unidad.
#: Existe porque el grado Celsius es una escala de intervalo con cero arbitrario: un cociente
#: sobre grados absolutos cambia de orden si se mide en kelvin, y deja de ser una magnitud
#: fisica. Medido sobre un incremento con cero real, el cociente si lo es.
TEMPERATURA_REFERENCIA_C: Final[float] = 38.0

#: Ventana temporal con que el imputador busca lecturas vecinas, en dias.
VENTANA_IMPUTACION_DIAS: Final[int] = 7

#: Minimo de lecturas validas en la ventana para imputar. Por debajo, la fila se marca.
MINIMO_REGISTROS_IMPUTACION: Final[int] = 5
