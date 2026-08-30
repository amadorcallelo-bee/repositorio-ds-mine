"""Reglas del dominio OPUS-MINE que necesita el lakehouse.

Replica de forma deliberada las constantes del Modulo A que aqui hacen falta (nombres de
columna, centinela, turnos, rangos y factores de recuperacion) en lugar de importarlas:
los notebooks se despliegan a Databricks como un Asset Bundle que solo contiene
`modulo_b/`, y un import cruzado obligaria a empaquetar tambien `modulo_a`. La fuente de
verdad sigue siendo `aurum_pipeline/domain.py`; si un valor cambia alli, cambia aqui en el
mismo commit.

Las cifras que no vienen del Modulo A tienen su fuente al lado: el rango del sensor de
avance sale del manual del equipo y las recuperaciones metalurgicas, de la ecuacion que el
Ejercicio A-2 despejo del propio extracto.
"""

from __future__ import annotations

from typing import Final, Literal

# --- Columnas del extracto, en el orden del CSV. No se renombran: lo prohibe el enunciado.

COLUMNA_TIEMPO: Final[str] = "ts_opus_utc"
COLUMNA_FRENTE: Final[str] = "frente_id"
COLUMNA_TURNO: Final[str] = "turno_cod"
COLUMNA_LEY: Final[str] = "ley_au_gpT"
COLUMNA_TONELAJE: Final[str] = "ton_rom_acum"
COLUMNA_PRESION: Final[str] = "pres_hidraul_bar"
COLUMNA_RPM: Final[str] = "rpm_corona"
COLUMNA_AVANCE: Final[str] = "avance_mmin"
COLUMNA_AGUA: Final[str] = "agua_iny_lmin"
COLUMNA_VIBRACION: Final[str] = "vibracion_rms_ms2"
COLUMNA_TEMPERATURA: Final[str] = "temp_motor_c"
COLUMNA_OPERADOR: Final[str] = "op_id"
COLUMNA_EQUIPO: Final[str] = "equipo_id"
COLUMNA_FALLA: Final[str] = "falla_cod"
COLUMNA_PRODUCCION: Final[str] = "prod_estimada_oz"
COLUMNA_TIPO_MINERAL: Final[str] = "tipo_mineral"
COLUMNA_SECTOR: Final[str] = "sector_geol"
COLUMNA_MANTENIMIENTO: Final[str] = "flag_mant_prev"

COLUMNAS_EXTRACTO: Final[tuple[str, ...]] = (
    COLUMNA_TIEMPO, COLUMNA_FRENTE, COLUMNA_TURNO, COLUMNA_LEY, COLUMNA_TONELAJE,
    COLUMNA_PRESION, COLUMNA_RPM, COLUMNA_AVANCE, COLUMNA_AGUA, COLUMNA_VIBRACION,
    COLUMNA_TEMPERATURA, COLUMNA_OPERADOR, COLUMNA_EQUIPO, COLUMNA_FALLA, COLUMNA_PRODUCCION,
    COLUMNA_TIPO_MINERAL, COLUMNA_SECTOR, COLUMNA_MANTENIMIENTO,
)

#: Clave natural de un evento. El EDA demostro que ningun par de registros comparte
#: instante, asi que `ts_opus_utc` solo ya identifica; se agrega el frente porque es la
#: garantia que si sobrevive a un sistema con varias perforadoras en paralelo.
CLAVE_EVENTO: Final[tuple[str, str]] = (COLUMNA_TIEMPO, COLUMNA_FRENTE)

# --- Columnas que agrega bronze: la metadata de ingesta que exige el enunciado.

COLUMNA_ARCHIVO_FUENTE: Final[str] = "archivo_fuente"
COLUMNA_TS_INGESTA: Final[str] = "ts_ingesta"
COLUMNA_FECHA_INGESTA: Final[str] = "fecha_ingesta"
COLUMNA_LOTE: Final[str] = "lote_id"
#: Columna donde Auto Loader deja lo que no encaja en el esquema explicito. Se conserva
#: en bronze porque es la evidencia de que el archivo fuente cambio de forma.
COLUMNA_RESCATE: Final[str] = "_rescued_data"

# --- Columnas que agrega silver.

COLUMNA_TS_LOCAL: Final[str] = "ts_local"
COLUMNA_FECHA_LOCAL: Final[str] = "fecha_local"
COLUMNA_ANIO_MES: Final[str] = "anio_mes"
COLUMNA_TURNO_OPUS: Final[str] = "turno_cod_opus"
COLUMNA_TURNO_DISCREPANTE: Final[str] = "turno_discrepante"
COLUMNA_LEY_VALIDA: Final[str] = "ley_valida"
COLUMNA_FUENTE_TIPO: Final[str] = "fuente_tipo_mineral"
COLUMNA_FECHA_CORRECCION: Final[str] = "fecha_correccion"
COLUMNA_LOTE_CORRECCION: Final[str] = "lote_correccion"
COLUMNA_MOTIVOS_RECHAZO: Final[str] = "motivos_rechazo"
COLUMNA_ES_DUPLICADO: Final[str] = "es_duplicado"

#: Sensor con rango operacional publicado y la bandera de alerta que produce en silver.
ALERTAS: Final[dict[str, str]] = {
    COLUMNA_PRESION: "alerta_presion",
    COLUMNA_RPM: "alerta_rpm",
    COLUMNA_VIBRACION: "alerta_vibracion",
    COLUMNA_TEMPERATURA: "alerta_temperatura",
}

FUENTE_OPUS: Final[str] = "OPUS"
FUENTE_LAB: Final[str] = "LAB"

# --- Columnas de un lote de reclasificacion del laboratorio.

COLUMNA_TIPO_LAB: Final[str] = "tipo_mineral_lab"
COLUMNA_FECHA_ANALISIS: Final[str] = "fecha_analisis"
COLUMNA_LABORATORIO: Final[str] = "laboratorio"
COLUMNA_MUESTRA: Final[str] = "muestra_id"

# --- Reglas del dominio.

#: Zona horaria de la operacion. Se usa el nombre IANA y no un desfase fijo de -5 h: hoy
#: Peru no aplica horario de verano, pero eso es una decision del pais y no del pipeline,
#: y un desfase escrito a mano no se enteraria del cambio.
ZONA_HORARIA: Final[str] = "America/Lima"

#: Valor con que OPUS registra la perdida de comunicacion de la sonda XRF (manual del
#: equipo, seccion 3). No es una ley: no indica mineral esteril ni ley cero.
CENTINELA_LEY: Final[float] = -1.0
#: Codigo de falla que el operador debe registrar cuando la perdida de la sonda persiste.
CODIGO_FALLA_SONDA: Final[str] = "E-ELEC-04"

Turno = Literal["N2", "D1", "D2", "N1"]
#: Orden cronologico de los turnos dentro de una fecha local: N2 abre la jornada a las
#: 00:00 y N1 la cierra a las 23:59. Es el mismo orden que dedujo el EDA del Modulo A.
ORDEN_TURNOS: Final[tuple[str, ...]] = ("N2", "D1", "D2", "N1")
DURACION_TURNO_HORAS: Final[int] = 6
#: Hora local en que empieza cada turno, derivada del orden y no escrita aparte.
HORA_INICIO_TURNO: Final[dict[str, int]] = {
    turno: posicion * DURACION_TURNO_HORAS for posicion, turno in enumerate(ORDEN_TURNOS)
}

TIPOS_MINERAL: Final[tuple[str, ...]] = ("OX", "SUL", "MIX", "EST")
SECTORES: Final[tuple[str, ...]] = (
    "Veta-Principal", "Veta-Sur", "Cuerpo-Central", "Rampa-Norte",
)

#: Rangos operacionales del diccionario, como (minimo, maximo). Salirse de ellos es una
#: alerta que silver marca, no un motivo de rechazo: son justamente los registros que a
#: operaciones le interesa mirar.
RANGOS_OPERACIONALES: Final[dict[str, tuple[float | None, float | None]]] = {
    COLUMNA_PRESION: (180.0, 240.0),
    COLUMNA_RPM: (800.0, 1400.0),
    COLUMNA_VIBRACION: (None, 12.0),
    COLUMNA_TEMPERATURA: (None, 95.0),
}

#: Lo que no puede existir fisicamente. Un valor fuera de estos limites no es una alerta
#: sino un registro corrupto, y va a cuarentena. Coinciden con los del servicio del A-2.
LIMITES_FISICOS: Final[dict[str, tuple[float, float]]] = {
    COLUMNA_PRESION: (0.0, 1000.0),
    COLUMNA_RPM: (0.0, 5000.0),
    COLUMNA_AVANCE: (0.0, 100.0),
    COLUMNA_AGUA: (0.0, 1000.0),
    COLUMNA_VIBRACION: (0.0, 200.0),
    COLUMNA_TEMPERATURA: (-273.15, 500.0),
    COLUMNA_LEY: (0.0, 1000.0),
    COLUMNA_TONELAJE: (0.0, 100000.0),
    COLUMNA_PRODUCCION: (0.0, 1000000.0),
}

#: Tope del rango normal del sensor de avance LVDT LV-01 (manual Atlas Copco L8, seccion
#: 3: 0.3 a 3.5 m/min). Es el unico avance de referencia documentado: el manual no publica
#: un avance nominal y el PET solo limita a 0.8 m/min los primeros 50 cm de cada taladro.
AVANCE_MAXIMO_MMIN: Final[float] = 3.5

#: Factor de recuperacion con que OPUS calcula `prod_estimada_oz`, despejado en el A-2 de
#: la propia ecuacion (desviacion del orden de 5e-6). Se usan estos y no los rangos del
#: informe geologico porque el recalculo tras una reclasificacion debe reproducir la formula
#: de OPUS con el tipo nuevo; que los dos no coincidan es un hallazgo, no un parametro.
FACTOR_RECUPERACION: Final[dict[str, float]] = {
    "EST": 0.10, "MIX": 0.83, "OX": 0.87, "SUL": 0.91,
}
OZ_TROY_EN_GRAMOS: Final[float] = 31.1035

# --- Nombres del lakehouse. Siguen el arbol del enunciado: catalogo, tres esquemas por
# --- capa y uno para los reportes de calidad.

CATALOGO: Final[str] = "lakehouse_umlc"
ESQUEMA_BRONZE: Final[str] = "bronze"
ESQUEMA_SILVER: Final[str] = "silver"
ESQUEMA_GOLD: Final[str] = "gold"
ESQUEMA_DQ: Final[str] = "dq_reports"
TABLA_OPUS_RAW: Final[str] = "opus_raw"
TABLA_INGESTA_LOG: Final[str] = "ingesta_log"
TABLA_OPUS_CLEAN: Final[str] = "opus_clean"
TABLA_CUARENTENA: Final[str] = "opus_cuarentena"
TABLA_REPORTE_CALIDAD: Final[str] = "reporte_calidad"
TABLA_KPI_TURNO: Final[str] = "aurum_kpi_turno"
VOLUMEN_LANDING: Final[str] = "landing"

#: Columnas del Z-ORDER de gold: las consultas del B-2 filtran por frente y por rango de
#: fechas a la vez, y la partición no puede servir a dos dimensiones.
COLUMNAS_ZORDER_GOLD: Final[tuple[str, str]] = (COLUMNA_FRENTE, COLUMNA_FECHA_LOCAL)
#: Grano de gold: una fila por frente, fecha local y turno.
CLAVE_TURNO: Final[tuple[str, str, str]] = (COLUMNA_FRENTE, COLUMNA_FECHA_LOCAL, COLUMNA_TURNO)
#: Propiedad de la tabla gold donde queda la ultima version de silver incorporada.
PROPIEDAD_VERSION_SILVER: Final[str] = "umlc.version_silver_procesada"

# --- Ejercicio B-3: monitoreo de deriva, reentrenamiento y promocion de modelos ---

#: Ventanas del monitor de deriva. El enunciado dice "los ultimos 30 dias como referencia";
#: se lee como: la referencia son los 30 dias anteriores a la ventana que se evalua, y la
#: ventana evaluada son los ultimos 7 dias con datos. La alternativa -anclar la referencia
#: al momento del entrenamiento- vigilaria al modelo y no al proceso, y el enunciado pide
#: vigilar las variables.
VENTANA_REFERENCIA_DIAS: Final[int] = 30
VENTANA_EVALUACION_DIAS: Final[int] = 7

#: Variables criticas que vigila el monitor, como las nombra el enunciado.
VARIABLES_DERIVA: Final[tuple[str, str]] = (COLUMNA_LEY, COLUMNA_VIBRACION)

#: Deciles de la referencia como bins del PSI, y los umbrales de la convencion de industria
#: que el propio enunciado usa: menos de 0.1 estable, 0.1 a 0.2 moderado, mas de 0.2 critico.
BINS_PSI: Final[int] = 10
PSI_MODERADO: Final[float] = 0.1
PSI_CRITICO: Final[float] = 0.2

#: Degradacion de la metrica que dispara el reentrenamiento: MAE actual > baseline * 1.15.
DEGRADACION_MAE_MAXIMA: Final[float] = 0.15

#: Nombres del registro de modelos y del experimento, en lenguaje de operacion como el A-2.
ESQUEMA_MODELOS: Final[str] = "modelos"
MODELO_LEY_REGISTRADO: Final[str] = "aurum_ley_turno_siguiente"
ALIAS_PRODUCCION: Final[str] = "produccion"
ALIAS_STAGING: Final[str] = "staging"
EXPERIMENTO_MLOPS: Final[str] = "mlops_ley_turno_siguiente"
TABLA_MONITOR_DERIVA: Final[str] = "monitor_deriva"

#: Metricas con los mismos nombres que el A-2 dejo en MLflow, para que el registro de la
#: nube y el local se lean igual.
METRICA_ERROR: Final[str] = "error_medio_g_por_tonelada"
METRICA_ERROR_ENTRENAMIENTO: Final[str] = "error_medio_g_por_tonelada_entrenamiento"
METRICA_BRECHA: Final[str] = "brecha_entrenamiento_validacion"
