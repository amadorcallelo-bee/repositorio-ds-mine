"""Contratos de entrada y salida del servicio de inferencia.

**Los rangos del diccionario no son todos validaciones.** El diccionario de variables publica
dos cosas distintas bajo la misma forma: `pres_hidraul_bar` entre 180 y 240 bar es un rango
**operacional**, y `vibracion_rms_ms2` por encima de 12 o `temp_motor_c` por encima de 95 son
**alertas**. Ninguno de los dos describe lo imposible. Si Pydantic rechazara con 422 todo lo
que sale del rango publicado, la API rechazaria exactamente los turnos por los que alguien
llama a preguntar: los que estan fuera de lo normal.

La regla que sigue este modulo es entonces: se rechaza lo que no puede existir -una presion
negativa, una corona girando hacia atras, una temperatura bajo el cero absoluto- y se acepta
marcando lo que esta fuera de rango operacional. Las marcas viajan en la respuesta, de modo
que quien consume la API sabe que el turno era anomalo sin tener que reimplementar los
umbrales del diccionario por su cuenta.

**Los rezagos son opcionales.** El modelo los usa, pero un llamador que solo tiene las
condiciones actuales debe poder preguntar igual: sin ellos, el pipeline cae al nivel del
frente, que sobre el conjunto de prueba cuesta 0.0003 g/t frente a la media viva. Exigirlos
habria obligado al servicio a mantener un almacen de estado por una diferencia que no se mide.
Lo mismo vale para el resumen de actividad y por umbral del turno -minutos de inactividad al
cierre, maximos y conteos sobre el umbral-: son opcionales, y los arboles tratan el faltante
de forma nativa.
"""

from __future__ import annotations

from typing import Annotated, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from aurum_pipeline import domain
from aurum_pipeline.modeling.features import tipos_de_servicio

#: Los cuatro turnos y los cuatro tipos de mineral, como tipos cerrados. Un valor fuera de
#: estas listas si es un error del llamador: no existe un turno "D3".
CodigoTurno = Literal["N2", "D1", "D2", "N1"]
TipoMineral = Literal["OX", "SUL", "MIX", "EST"]


#: Alias de tipo, uno por magnitud, acotados por el limite **fisico** y no por el rango
#: operacional del diccionario. Se escriben como alias y no se generan con una funcion para
#: que mypy los verifique: una funcion que devuelva un `Annotated` es opaca al verificador y
#: convierte el contrato de la API en algo que solo se comprueba en ejecucion.
_LIMITES = domain.LIMITES_FISICOS

LeyGramosPorTonelada = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_LEY][0], le=_LIMITES[domain.COLUMNA_LEY][1])]
ToneladasRom = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_TONELAJE][0],
                 le=_LIMITES[domain.COLUMNA_TONELAJE][1])]
PresionBar = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_PRESION][0],
                 le=_LIMITES[domain.COLUMNA_PRESION][1])]
RevolucionesPorMinuto = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_RPM][0], le=_LIMITES[domain.COLUMNA_RPM][1])]
AvanceMetrosPorMinuto = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_AVANCE][0], le=_LIMITES[domain.COLUMNA_AVANCE][1])]
FlujoLitrosPorMinuto = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_AGUA][0], le=_LIMITES[domain.COLUMNA_AGUA][1])]
VibracionMetrosPorSegundo2 = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_VIBRACION][0],
                 le=_LIMITES[domain.COLUMNA_VIBRACION][1])]
TemperaturaCelsius = Annotated[
    float, Field(ge=_LIMITES[domain.COLUMNA_TEMPERATURA][0],
                 le=_LIMITES[domain.COLUMNA_TEMPERATURA][1])]


class CondicionesTurno(BaseModel):
    """Estado de un frente al cerrar un turno, tal como lo envia el sistema OPUS.

    Es la entrada de `/predict`: el frente activo, las condiciones del turno que termina y,
    opcionalmente, la historia reciente de ese frente.
    """

    model_config = ConfigDict(extra="forbid")

    frente_id: str = Field(min_length=1, max_length=32,
                           description="Frente de extraccion activo, formato FR-{zona}-{num}")
    turno_cod: CodigoTurno = Field(description="Turno que termina")
    tipo_mineral: TipoMineral = Field(description="Clasificacion geologica del turno")

    ley_turno: LeyGramosPorTonelada = Field(
        description="Ley de oro medida en el turno, en g/t")
    ton_rom_acum: ToneladasRom = Field(description="Toneladas ROM del turno")
    pres_hidraul_bar: PresionBar = Field(
        description="Presion hidraulica media del turno, en bar")
    rpm_corona: RevolucionesPorMinuto = Field(
        description="Revoluciones medias de la corona")
    avance_mmin: AvanceMetrosPorMinuto = Field(
        description="Velocidad media de avance, en m/min")
    agua_iny_lmin: FlujoLitrosPorMinuto = Field(
        description="Flujo medio de agua de inyeccion, en L/min")
    vibracion_rms_ms2: VibracionMetrosPorSegundo2 = Field(
        description="Vibracion RMS media del turno, en m/s2")
    temp_motor_c: TemperaturaCelsius = Field(
        description="Temperatura media del motor, en grados Celsius")

    eventos_turno: int = Field(default=1, ge=1, le=1000,
                               description="Registros OPUS que componen el turno")
    lecturas_ley_turno: int = Field(default=1, ge=0, le=1000,
                                    description="Lecturas validas de la sonda XRF en el turno")
    fallas_turno: int = Field(default=0, ge=0, le=1000,
                              description="Codigos de falla registrados en el turno")
    mantenimiento_turno: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Proporcion del turno en ventana de mantenimiento preventivo")

    ley_rezago_1: float | None = Field(
        default=None, ge=0.0, description="Ley del turno anterior del mismo frente, en g/t")
    ley_rezago_2: float | None = Field(
        default=None, ge=0.0, description="Ley de dos turnos atras del mismo frente, en g/t")
    ley_media_3: float | None = Field(
        default=None, ge=0.0, description="Media movil de la ley en tres turnos, en g/t")
    ley_desv_3: float | None = Field(
        default=None, ge=0.0, description="Desviacion movil de la ley en tres turnos")
    ley_media_10: float | None = Field(
        default=None, ge=0.0, description="Media movil de la ley en diez turnos, en g/t")
    ley_desv_10: float | None = Field(
        default=None, ge=0.0, description="Desviacion movil de la ley en diez turnos")
    dias_desde_turno_previo: float | None = Field(
        default=None, ge=0.0, le=3650.0,
        description="Dias transcurridos desde el turno anterior del frente")
    turnos_previos_frente: int | None = Field(
        default=None, ge=0, description="Turnos del frente anteriores a este")

    minutos_inactivo_al_cierre: float | None = Field(
        default=None, ge=0.0, le=float(domain.DURACION_TURNO_HORAS * 60),
        description="Minutos entre la ultima lectura del frente y el cierre del turno")
    temp_max_turno: TemperaturaCelsius | None = Field(
        default=None, description="Temperatura maxima del motor en el turno, en grados Celsius")
    eventos_temp_riesgo: int | None = Field(
        default=None, ge=0, le=1000,
        description=f"Lecturas del turno por encima de {domain.UMBRAL_TEMP_RIESGO:g} C")
    vib_max_turno: VibracionMetrosPorSegundo2 | None = Field(
        default=None, description="Vibracion RMS maxima del turno, en m/s2")
    eventos_vib_alerta: int | None = Field(
        default=None, ge=0, le=1000,
        description="Lecturas del turno por encima de la alerta de vibracion del diccionario")

    def alertas(self) -> list[str]:
        """Rangos operacionales del diccionario que este turno no cumple.

        Se calculan aqui y no en el modelo porque son una regla del dominio publicada en el
        diccionario, no una salida aprendida: valen igual con o sin modelo cargado.
        """
        avisos: list[str] = []
        for columna, (minimo, maximo) in domain.RANGOS_SENSORES.items():
            valor = float(getattr(self, columna))
            if minimo is not None and valor < minimo:
                avisos.append(f"{columna} por debajo del rango operacional ({valor} < {minimo})")
            if maximo is not None and valor > maximo:
                avisos.append(f"{columna} por encima del rango operacional ({valor} > {maximo})")
        if self.lecturas_ley_turno == 0:
            avisos.append("el turno no tiene ninguna lectura valida de la sonda XRF")
        return avisos

    def como_marco(self) -> pd.DataFrame:
        """Fila unica con los nombres de columna que el pipeline espera.

        Los nombres son los internos de OPUS porque el enunciado prohibe renombrarlos, y esa
        restriccion llega hasta el contrato de la API: renombrar aqui obligaria a traducir en
        los dos sentidos y a mantener el mapa sincronizado con el modelo.
        """
        # La conversion de tipos la hace `tipos_de_servicio`, el mismo lugar del que sale el
        # ejemplo con que se registra la firma del modelo: si las dos reglas vivieran
        # separadas, la firma y el contrato de la API se separarian en silencio.
        return tipos_de_servicio(pd.DataFrame([self.model_dump()]))


class PrediccionTurno(BaseModel):
    """Respuesta de `/predict`: la ley estimada, la probabilidad de falla y las alertas."""

    model_config = ConfigDict(extra="forbid")

    frente_id: str = Field(description="Frente sobre el que se predice")
    ley_estimada: float = Field(description="Ley de oro estimada del proximo turno, en g/t")
    prob_falla_4h: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Probabilidad de falla mecanica en las proximas 4 horas")
    alertas: list[str] = Field(
        default_factory=list,
        description="Rangos operacionales del diccionario que el turno enviado no cumple")
    modelo_ley: str = Field(description="Modelo de ley que produjo la estimacion")
    modelo_falla: str | None = Field(
        default=None, description="Modelo de falla que produjo la probabilidad")


class EstadoServicio(BaseModel):
    """Respuesta de `/health`: si el servicio puede responder y con que modelos."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["listo", "sin_modelo"] = Field(description="Estado del servicio")
    modelo_ley: str | None = Field(default=None, description="Modelo de ley cargado")
    modelo_falla: str | None = Field(default=None, description="Modelo de falla cargado")
    uri_seguimiento: str = Field(description="Backend de MLflow desde el que se carga")
