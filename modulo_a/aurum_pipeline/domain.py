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
COLUMNA_AGUA: Final[str] = "agua_iny_lmin"
COLUMNA_TURNO: Final[str] = "turno_cod"
COLUMNA_TONELAJE: Final[str] = "ton_rom_acum"
COLUMNA_FALLA: Final[str] = "falla_cod"
COLUMNA_SECTOR: Final[str] = "sector_geol"
COLUMNA_OPERADOR: Final[str] = "op_id"
COLUMNA_MANTENIMIENTO: Final[str] = "flag_mant_prev"
COLUMNA_PRODUCCION: Final[str] = "prod_estimada_oz"

# --- Nombres que produce el Ejercicio A-2 (no existen en el extracto) ---
#
# La unidad de modelado del A-2 no es el evento sino el turno de un frente, asi que estas
# columnas nombran una celda `(frente_id, fecha_local, turno_cod)` y su objetivo. Viven aqui
# por la misma razon que las anteriores: se escriben en el constructor de la matriz, en el
# particionador y en el servicio de inferencia, y un cambio de nombre no puede obligar a
# buscar cadenas en tres paquetes.

COLUMNA_FECHA_LOCAL: Final[str] = "fecha_local"
COLUMNA_INICIO_TURNO: Final[str] = "inicio_turno_local"
COLUMNA_LEY_TURNO: Final[str] = "ley_turno"
COLUMNA_OBJETIVO: Final[str] = "ley_turno_siguiente"
COLUMNA_INICIO_OBJETIVO: Final[str] = "inicio_turno_siguiente"

#: Cierre del bloque horario del turno segun el reloj. Es el momento de la prediccion: desde
#: aqui se cuenta la ventana de falla y hasta aqui se mide la inactividad del frente.
COLUMNA_CIERRE_TURNO: Final[str] = "cierre_turno_local"

#: Resumen del turno que la media destruye. La relacion de la temperatura con la falla es un
#: escalon en 88 C y la de la vibracion, una alerta en 12 m/s2: el maximo y el conteo de
#: lecturas sobre el umbral conservan el escalon que el promedio del turno diluye. Los
#: minutos de inactividad al cierre son la senal causal mas directa de que el frente sigue
#: operando, que es lo que la etiqueta de falla a cuatro horas mide en este extracto.
COLUMNA_MINUTOS_INACTIVO: Final[str] = "minutos_inactivo_al_cierre"
COLUMNA_TEMP_MAX: Final[str] = "temp_max_turno"
COLUMNA_EVENTOS_TEMP_RIESGO: Final[str] = "eventos_temp_riesgo"
COLUMNA_VIB_MAX: Final[str] = "vib_max_turno"
COLUMNA_EVENTOS_VIB_ALERTA: Final[str] = "eventos_vib_alerta"

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

#: Proporcion del calendario reservada al conjunto de prueba. Se corta por fecha y no por
#: numero de filas: con frentes que se apagan por semanas, cortar por filas mezclaria las
#: mismas fechas en los dos lados de la particion.
PROPORCION_PRUEBA: Final[float] = 0.20

#: Bloques de validacion del walk-forward sobre el periodo de desarrollo.
PLIEGUES_VALIDACION: Final[int] = 5

#: Rezagos de la ley, en turnos del mismo frente, que entran a la matriz supervisada. El
#: turno actual no aparece aqui porque ya es una columna propia: es el rezago cero respecto
#: del objetivo.
REZAGOS_TURNO: Final[tuple[int, ...]] = (1, 2)

#: Ventanas moviles de la ley, en turnos del mismo frente. Diez turnos son unos dos dias y
#: medio de operacion continua del frente; tres, poco menos de un dia.
VENTANAS_MOVILES_TURNO: Final[tuple[int, ...]] = (3, 10)

#: Orden cronologico de los turnos dentro de una misma fecha local. N2 va de 00:00 a 05:59,
#: de modo que abre la jornada y no la cierra. El orden importa porque es el que se usa para
#: codificar el turno como numero: un orden arbitrario le daria al modelo una distancia
#: inventada entre turnos que no se corresponde con el reloj.
ORDEN_TURNOS: Final[tuple[str, ...]] = ("N2", "D1", "D2", "N1")

#: Duracion de un turno en horas, deducida del extracto: los cuatro turnos cubren el dia sin
#: solaparse y cada uno empieza en punto en hora local.
DURACION_TURNO_HORAS: Final[int] = 6

#: Hora local en que empieza cada turno, derivada del orden cronologico y no escrita aparte,
#: para que un cambio en el orden no deje dos tablas que contradecirse.
HORA_INICIO_TURNO: Final[dict[str, int]] = {
    turno: posicion * DURACION_TURNO_HORAS for posicion, turno in enumerate(ORDEN_TURNOS)
}

#: Tramos de minutos de inactividad al cierre con que el baseline de actividad aprende una
#: tasa de falla. La distribucion es bimodal -mediana 32 minutos, percentil 90 en 271-, y
#: los cortes separan "sigue perforando" de "se apago" con margen a ambos lados.
TRAMOS_INACTIVIDAD_MINUTOS: Final[tuple[float, ...]] = (30.0, 60.0, 120.0, 240.0)

#: Orden de los tipos de mineral, tomado del diccionario de variables. Aqui el orden no
#: codifica ninguna magnitud: es solo una convencion estable para que la misma categoria
#: reciba siempre el mismo codigo entre corridas.
ORDEN_TIPOS_MINERAL: Final[tuple[str, ...]] = ("OX", "SUL", "MIX", "EST")

#: Nombres de los experimentos en MLflow, uno por problema. Se separan porque un panel que
#: mezcle regresion y clasificacion bajo un solo nombre obliga a filtrar por etiqueta para
#: entender que se esta mirando.
EXPERIMENTO_LEY: Final[str] = "ley_oro_turno_siguiente"
EXPERIMENTO_FALLA: Final[str] = "falla_mecanica_4h"

#: Nombre con que el modelo de ley queda en el Model Registry, y alias que la API resuelve.
MODELO_LEY_REGISTRADO: Final[str] = "aurum_ley_turno_siguiente"
MODELO_FALLA_REGISTRADO: Final[str] = "aurum_falla_4h"
ALIAS_PRODUCCION: Final[str] = "produccion"

#: Configuraciones que muestrea la busqueda aleatoria de hiperparametros. Veinte y no mas
#: porque el techo del problema esta a cinco diezmilesimas del baseline: gastar mas computo
#: en la busqueda no compra exactitud, y a n_iter=20 el experimento completo corre en unos
#: trece minutos, que es un notebook que el evaluador puede reejecutar.
ITERACIONES_BUSQUEDA: Final[int] = 20

#: Semilla unica de todo el modulo de modelado, para que la busqueda aleatoria y los modelos
#: sean reproducibles entre corridas.
SEMILLA: Final[int] = 20250506

#: Limites fisicos de cada sensor, como (minimo, maximo). Son distintos de RANGOS_SENSORES y
#: la diferencia es deliberada: `RANGOS_SENSORES` publica el rango **operacional** -presion
#: entre 180 y 240 bar, vibracion hasta 12 m/s2- y salirse de el es una alerta, no un
#: imposible. Lo que esta tabla acota es lo que no puede existir: una presion negativa, una
#: corona girando hacia atras, una temperatura bajo el cero absoluto. El servicio de
#: inferencia rechaza lo segundo y acepta marcando lo primero, porque un 422 sobre un valor
#: de alerta rechazaria justo los registros que a operaciones le interesa consultar.
LIMITES_FISICOS: Final[dict[str, tuple[float, float]]] = {
    "pres_hidraul_bar": (0.0, 1000.0),
    "rpm_corona": (0.0, 5000.0),
    "avance_mmin": (0.0, 100.0),
    "agua_iny_lmin": (0.0, 1000.0),
    "vibracion_rms_ms2": (0.0, 200.0),
    "temp_motor_c": (-273.15, 500.0),
    "ley_au_gpT": (0.0, 1000.0),
    "ton_rom_acum": (0.0, 100000.0),
}
