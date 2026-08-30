"""Conjuntos de variables y codificacion del frente para la regresion de ley.

Dos piezas y una razon de diseno que las une.

**El nivel del frente se codifica dentro de un `Pipeline` de scikit-learn, no antes.** La
codificacion por objetivo de `frente_id` es, literalmente, el baseline: la media de la ley
del frente. Si se calculara una vez sobre toda la matriz y despues se partiera en pliegues,
cada bloque de validacion estaria evaluado con una media que lo incluye. No daria error;
daria una metrica mejor de la que el modelo puede sostener. Al vivir dentro del pipeline, la
codificacion se reajusta con las filas de entrenamiento de cada pliegue y `RandomizedSearchCV`
la reajusta tambien en cada configuracion que prueba.

El leave-one-out del `AurumShiftEncoder` del A-1 resuelve el mismo problema en un contexto
distinto: alli las filas no tienen orden temporal y basta con excluir la propia. Aqui hay
orden, y excluir solo la propia fila seguiria dejando entrar el futuro del frente.

**Los conjuntos de variables tienen nombre porque son una hipotesis cada uno.** El enunciado
pide justificar las decisiones de modelado, y "que variables aportan" es una de ellas: el
conjunto se elige comparando los cuatro sobre los mismos pliegues y la comparacion queda
registrada en MLflow, no resuelta por criterio. `ACTIVIDAD` existe por una medicion sobre el
extracto: la etiqueta de falla a cuatro horas reproduce la de eventos independientes a 3.3%
cada uno, de modo que anticipar la falla es anticipar si el frente sigue operando. Si ese
conjunto empata con `COMPLETO`, la tesis queda probada por la propia fase A.

**Ninguna columna que describa el futuro puede entrar a un conjunto.** El objetivo, el
instante del objetivo, la etiqueta de falla y el conteo de eventos de la ventana viven en la
matriz porque el particionador y las metricas los necesitan; un conjunto que los declare es
un error de construccion y falla al instanciarse, no en la primera peticion real.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Self

import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError, MissingColumnsError, NotFittedError
from aurum_pipeline.modeling.falla import (
    COLUMNA_EVENTOS_VENTANA,
    COLUMNA_FALLA_HORIZONTE,
    COLUMNA_VENTANA_OBSERVADA,
)

logger = logging.getLogger(__name__)

#: Nombre de la columna que produce la codificacion del frente.
COLUMNA_NIVEL_FRENTE: Final[str] = "nivel_frente"

#: Nombres de las columnas numericas derivadas de las categoricas.
COLUMNA_TURNO_NUM: Final[str] = "turno_num"
COLUMNA_TIPO_NUM: Final[str] = "tipo_num"

#: Columnas de la matriz que describen el futuro del turno y por eso no son variables.
COLUMNAS_DEL_FUTURO: Final[frozenset[str]] = frozenset({
    domain.COLUMNA_OBJETIVO,
    domain.COLUMNA_INICIO_OBJETIVO,
    COLUMNA_FALLA_HORIZONTE,
    COLUMNA_VENTANA_OBSERVADA,
    COLUMNA_EVENTOS_VENTANA,
})


@dataclass(frozen=True)
class ConjuntoVariables:
    """Un conjunto de variables con nombre, que es la unidad que se compara en la fase A."""

    nombre: str
    columnas: tuple[str, ...]

    def __post_init__(self) -> None:
        """Un conjunto sin columnas no es una hipotesis, y uno que mira el futuro es una fuga."""
        if not self.columnas:
            raise InvalidParameterError(
                f"el conjunto de variables {self.nombre!r} no declara ninguna columna")
        del_futuro = COLUMNAS_DEL_FUTURO.intersection(self.columnas)
        if del_futuro:
            raise InvalidParameterError(
                f"el conjunto de variables {self.nombre!r} declara columnas que describen "
                f"el futuro del turno: {', '.join(sorted(del_futuro))}")


#: Solo el nivel del frente. Es el conjunto que reproduce el baseline dentro de un modelo, y
#: sirve para verificar que la conclusion sobre la ventana temporal no dependa del conjunto.
MINIMO: Final[ConjuntoVariables] = ConjuntoVariables(
    nombre="MINIMO",
    columnas=(COLUMNA_NIVEL_FRENTE,),
)

#: El frente y la continuidad operativa del turno: cuantos registros tuvo y cuanto llevaba
#: sin registrar al cierre. Es la hipotesis de que la etiqueta de falla se predice por
#: actividad y no por estado mecanico.
ACTIVIDAD: Final[ConjuntoVariables] = ConjuntoVariables(
    nombre="ACTIVIDAD",
    columnas=(
        COLUMNA_NIVEL_FRENTE,
        COLUMNA_TURNO_NUM,
        "eventos_turno",
        domain.COLUMNA_MINUTOS_INACTIVO,
    ),
)

#: El frente activo y las condiciones del turno actual, que es lo que el enunciado describe
#: como entrada del problema. Incluye el resumen por umbral de temperatura y vibracion, para
#: que la objecion "la media destruye el escalon" se responda dentro del experimento.
CONDICIONES: Final[ConjuntoVariables] = ConjuntoVariables(
    nombre="CONDICIONES",
    columnas=(
        *ACTIVIDAD.columnas,
        domain.COLUMNA_LEY_TURNO,
        COLUMNA_TIPO_NUM,
        "lecturas_ley_turno",
        "fallas_turno",
        "mantenimiento_turno",
        domain.COLUMNA_TONELAJE,
        domain.COLUMNA_PRESION,
        domain.COLUMNA_RPM,
        domain.COLUMNA_AVANCE,
        domain.COLUMNA_AGUA,
        domain.COLUMNA_VIBRACION,
        domain.COLUMNA_TEMPERATURA,
        domain.COLUMNA_TEMP_MAX,
        domain.COLUMNA_EVENTOS_TEMP_RIESGO,
        domain.COLUMNA_VIB_MAX,
        domain.COLUMNA_EVENTOS_VIB_ALERTA,
    ),
)

#: Lo anterior mas la historia del frente. Los rezagos son causales y el enunciado no acota
#: las variables del modelo: el contrato de la API es otra cosa y se resuelve alli.
COMPLETO: Final[ConjuntoVariables] = ConjuntoVariables(
    nombre="COMPLETO",
    columnas=(
        *CONDICIONES.columnas,
        "ley_rezago_1",
        "ley_rezago_2",
        "ley_media_3",
        "ley_desv_3",
        "ley_media_10",
        "ley_desv_10",
        "dias_desde_turno_previo",
        "turnos_previos_frente",
    ),
)

#: Los cuatro conjuntos en el orden en que se comparan; cada uno contiene al anterior.
CONJUNTOS: Final[tuple[ConjuntoVariables, ...]] = (MINIMO, ACTIVIDAD, CONDICIONES, COMPLETO)

#: Columnas que el pipeline construye por dentro y que por tanto nadie tiene que enviarle.
DERIVADAS: Final[dict[str, str]] = {
    COLUMNA_NIVEL_FRENTE: domain.COLUMNA_FRENTE,
    COLUMNA_TURNO_NUM: domain.COLUMNA_TURNO,
    COLUMNA_TIPO_NUM: domain.COLUMNA_TIPO_MINERAL,
}


#: Columnas de entrada que son categoricas; el resto viaja como flotante.
CATEGORICAS_DE_ENTRADA: Final[tuple[str, ...]] = (
    domain.COLUMNA_FRENTE, domain.COLUMNA_TURNO, domain.COLUMNA_TIPO_MINERAL,
)


def tipos_de_servicio(marco: pd.DataFrame) -> pd.DataFrame:
    """Deja el marco con los tipos del contrato de entrada: categoricas y flotantes.

    Todo lo numerico viaja como `float64`, incluidos los conteos. No es un descuido: varias
    de esas columnas son opcionales en el servicio, y un entero de pandas no puede
    representar un faltante. MLflow infiere la firma del ejemplo que se le registra y despues
    la hace cumplir, de modo que una firma con `long` rechazaria la peticion en cuanto el
    llamador omitiera un rezago. Es la misma recomendacion que da MLflow al inferir enteros.

    Se aplica en los dos extremos -al ejemplo que define la firma y al marco que arma el
    servicio- para que no puedan separarse.
    """
    numericas = [columna for columna in marco.columns
                 if columna not in CATEGORICAS_DE_ENTRADA]
    convertido = marco.copy()
    convertido[numericas] = convertido[numericas].astype("float64")
    return convertido


def columnas_de_entrada(conjunto: ConjuntoVariables) -> tuple[str, ...]:
    """Columnas crudas que hay que darle al pipeline para que pueda predecir.

    No es lo mismo que `conjunto.columnas`: tres de ellas las construye el propio pipeline
    -el nivel del frente y los codigos de turno y de mineral-, y lo que hay que enviarle son
    las columnas de las que salen.

    Existe porque es el contrato de entrada del modelo, y de el sale tanto el `input_example`
    con que MLflow infiere la firma como la comprobacion de que el esquema del servicio la
    cubre. Sin un unico lugar que lo defina, la firma registrada y el contrato de la API se
    separan en silencio y la primera peticion real falla por esquema.
    """
    columnas: list[str] = [domain.COLUMNA_FRENTE]
    for columna in conjunto.columnas:
        origen = DERIVADAS.get(columna)
        if origen is None:
            columnas.append(columna)
        elif origen not in columnas:
            columnas.append(origen)
    return tuple(dict.fromkeys(columnas))


class CodificadorNivelFrente(BaseEstimator, TransformerMixin):
    """Codifica `frente_id` por la media del objetivo en las filas de entrenamiento.

    Hereda de `BaseEstimator` y `TransformerMixin` porque necesita el contrato de
    scikit-learn: `clone` reconstruye el objeto en cada pliegue y en cada configuracion de la
    busqueda, y sin `get_params` heredado eso no funciona. Es herencia para compartir
    contrato, que es para lo unico que este proyecto la usa.

    Un frente que no aparecio en el entrenamiento recibe el nivel medio global. Es la unica
    respuesta honesta: sin historia de ese frente no hay nada que decir de su ley, y devolver
    un faltante obligaria a cada modelo a inventar su propia politica.
    """

    def __init__(self, columna_frente: str = domain.COLUMNA_FRENTE) -> None:
        self.columna_frente = columna_frente

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """Aprende el nivel de cada frente con el objetivo de las filas recibidas."""
        if y is None:
            raise InvalidParameterError(
                "CodificadorNivelFrente necesita el objetivo para codificar el frente")
        if self.columna_frente not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_frente])
        objetivo = pd.Series(y).to_numpy()
        niveles = pd.Series(objetivo, index=X[self.columna_frente].to_numpy())
        self.niveles_: pd.Series = niveles.groupby(level=0).mean()
        self.prior_: float = float(niveles.mean())
        logger.debug("%s: nivel aprendido para %d frentes, prior %.4f",
                     type(self).__name__, len(self.niveles_), self.prior_)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Agrega `nivel_frente` sin tocar ninguna otra columna."""
        if not hasattr(self, "niveles_"):
            raise NotFittedError(type(self).__name__)
        if self.columna_frente not in X.columns:
            raise MissingColumnsError(type(self).__name__, [self.columna_frente])
        salida = X.copy()
        salida[COLUMNA_NIVEL_FRENTE] = (
            salida[self.columna_frente].map(self.niveles_).fillna(self.prior_))
        return salida


class SelectorVariables(BaseEstimator, TransformerMixin):
    """Traduce las categoricas a codigos estables y deja solo las columnas del conjunto.

    La traduccion usa el orden declarado en el dominio y no un `astype('category')`, que
    asigna codigos segun las categorias presentes en el marco: dos pliegues con distinto
    surtido de turnos producirian codificaciones distintas para el mismo turno.
    """

    def __init__(self, conjunto: ConjuntoVariables = COMPLETO) -> None:
        self.conjunto = conjunto

    def fit(self, X: pd.DataFrame, y: pd.Series | None = None) -> Self:
        """No aprende nada: la codificacion de categoricas es un mapa fijo del dominio."""
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Devuelve un marco con las columnas del conjunto, todas numericas."""
        preparado = X.copy()
        if domain.COLUMNA_TURNO in preparado.columns:
            preparado[COLUMNA_TURNO_NUM] = self._codificar(
                preparado[domain.COLUMNA_TURNO], domain.ORDEN_TURNOS)
        if domain.COLUMNA_TIPO_MINERAL in preparado.columns:
            preparado[COLUMNA_TIPO_NUM] = self._codificar(
                preparado[domain.COLUMNA_TIPO_MINERAL], domain.ORDEN_TIPOS_MINERAL)

        faltantes = set(self.conjunto.columnas) - set(preparado.columns)
        if faltantes:
            raise MissingColumnsError(type(self).__name__, faltantes)
        return preparado.loc[:, list(self.conjunto.columnas)].astype(float)

    @staticmethod
    def _codificar(serie: pd.Series, orden: tuple[str, ...]) -> pd.Series:
        """Mapea cada categoria a su posicion en el orden del dominio; lo no visto es faltante."""
        mapa = {categoria: posicion for posicion, categoria in enumerate(orden)}
        return serie.map(mapa).astype(float)
