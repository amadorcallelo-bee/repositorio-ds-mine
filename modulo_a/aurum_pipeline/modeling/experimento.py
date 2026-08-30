"""El experimento del A-2, en tres fases secuenciales, para los dos problemas.

Vive en un modulo y no en el notebook porque el notebook no se puede probar. Aqui la
orquestacion tiene pruebas y el notebook queda como lo que debe ser: la narracion de un
resultado, no el lugar donde se decide.

**Tres fases y no una rejilla completa.** La rejilla de tres conjuntos de variables por cinco
ventanas por dos modelos son treinta combinaciones sobre 3985 turnos, y eso es buscar ruido
con mas presupuesto. En cambio:

- **Fase A, variables.** Ventana expansiva fija e hiperparametros por defecto; se comparan los
  cuatro conjuntos con los dos modelos y, en clasificacion, cada combinacion con y sin peso
  de clase. Elige el conjunto y el peso.
- **Fase B, ventana temporal.** Las cinco estrategias con los dos modelos, con busqueda
  aleatoria anidada dentro de cada estrategia para que cada una compita en su mejor
  configuracion. Se corre con el conjunto ganador de la fase A y tambien con `MINIMO`, para
  verificar que la conclusion sobre la ventana no dependa de lo elegido antes: es la unica
  interaccion entre fases que preocupa. La expansiva es la hipotesis por defecto y solo la
  desplaza una deslizante que la supere por mas de la desviacion entre pliegues.
- **Fase C, prueba.** La combinacion ganadora se reajusta sobre el desarrollo -todo, o los
  meses de la ventana elegida- y se evalua **una sola vez** contra los baselines. Una segunda
  mirada al conjunto de prueba lo convertiria en validacion.

**Regresion y clasificacion comparten la clase y difieren en una configuracion.** Lo unico
que cambia entre los dos problemas es el objetivo, los modelos, los baselines y como se juzga
una prediccion; todo eso viaja en `ConfiguracionProblema`. Escribir dos orquestadores
gemelos habria significado que cada correccion de la particion o del registro se hiciera dos
veces, y que tarde o temprano se hiciera solo en uno.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd
from sklearn.base import BaseEstimator, clone
from sklearn.model_selection import RandomizedSearchCV

from aurum_pipeline import domain
from aurum_pipeline.errors import EmptyPartitionError, InvalidParameterError, NotFittedError
from aurum_pipeline.modeling.baselines import (
    BaselineActividad,
    BaselineNivelFrente,
    BaselinePersistencia,
    BaselinePrevalencia,
    BaselineTasaFrente,
)
from aurum_pipeline.modeling.classifiers import CLASIFICADORES, peso_de_clase
from aurum_pipeline.modeling.evaluacion import (
    BRECHA,
    EVALUADOR_FALLA,
    EVALUADOR_REGRESION,
    PUNTAJE_FALLA,
    PUNTAJE_REGRESION,
    SUFIJO_ENTRENAMIENTO,
    Evaluador,
    FabricaModelo,
    Metricas,
    ResultadoEvaluacion,
    buscar_hiperparametros,
    configuraciones_muestreadas,
    evaluar_por_pliegues,
)
from aurum_pipeline.modeling.falla import COLUMNA_FALLA_HORIZONTE
from aurum_pipeline.modeling.features import (
    CONJUNTOS,
    MINIMO,
    ConjuntoVariables,
    columnas_de_entrada,
    tipos_de_servicio,
)
from aurum_pipeline.modeling.metrics import error_por_frente
from aurum_pipeline.modeling.models import MODELOS
from aurum_pipeline.modeling.splitter import VentanaTemporal, ventana_desde_matriz
from aurum_pipeline.modeling.tracking import RegistroExperimento, huella_de_datos

logger = logging.getLogger(__name__)

#: Longitudes de ventana deslizante que se comparan contra la expansiva, en meses. El `None`
#: es la expansiva y encabeza la lista porque es la hipotesis por defecto.
VENTANAS_COMPARADAS: tuple[int | None, ...] = (None, 18, 12, 6, 3)

#: Nombre con que el peso de la clase positiva queda en las tablas y en MLflow. Uno significa
#: sin peso; la razon negativos/positivos, la perdida reequilibrada.
COLUMNA_PESO: str = "peso_clase_positiva"

#: Valor del peso cuando la perdida no se reequilibra.
SIN_PESO: float = 1.0


@dataclass(frozen=True)
class ConfiguracionProblema:
    """Todo lo que distingue la regresion de ley de la clasificacion de falla.

    `compara_peso_de_clase` dice dos cosas a la vez: que las fabricas del problema aceptan un
    peso de clase, y que la fase A debe correr cada combinacion con y sin el. Solo la
    clasificacion lo activa; un regresor no tiene clases que pesar.
    """

    nombre: str
    columna_objetivo: str
    evaluador: Evaluador
    puntaje: str
    fabricas: tuple[type, ...]
    baselines: tuple[tuple[str, type], ...]
    modelo_registrado: str
    experimento: str
    compara_peso_de_clase: bool = False


#: Regresion de la ley del turno siguiente.
REGRESION_LEY: ConfiguracionProblema = ConfiguracionProblema(
    nombre="ley",
    columna_objetivo=domain.COLUMNA_OBJETIVO,
    evaluador=EVALUADOR_REGRESION,
    puntaje=PUNTAJE_REGRESION,
    fabricas=MODELOS,
    baselines=(("baseline_persistencia", BaselinePersistencia),
               ("baseline_nivel_frente", BaselineNivelFrente)),
    modelo_registrado=domain.MODELO_LEY_REGISTRADO,
    experimento=domain.EXPERIMENTO_LEY,
)

#: Clasificacion de falla en las proximas cuatro horas.
CLASIFICACION_FALLA: ConfiguracionProblema = ConfiguracionProblema(
    nombre="falla_4h",
    columna_objetivo=COLUMNA_FALLA_HORIZONTE,
    evaluador=EVALUADOR_FALLA,
    puntaje=PUNTAJE_FALLA,
    fabricas=CLASIFICADORES,
    baselines=(("baseline_prevalencia", BaselinePrevalencia),
               ("baseline_tasa_frente", BaselineTasaFrente),
               ("baseline_actividad", BaselineActividad)),
    modelo_registrado=domain.MODELO_FALLA_REGISTRADO,
    experimento=domain.EXPERIMENTO_FALLA,
    compara_peso_de_clase=True,
)


@dataclass
class ResultadoFinal:
    """Lo que deja la fase de prueba: el modelo ganador y como le fue contra los baselines."""

    problema: str
    modelo: str
    conjunto: str
    ventana: str
    metricas: Metricas
    metricas_baselines: dict[str, Metricas]
    detalle_por_frente: pd.DataFrame
    pipeline: BaseEstimator
    mejor_es_mayor: bool
    turnos_entrenamiento: int

    @property
    def le_gana_al_baseline_fuerte(self) -> bool:
        """Si el modelo supera al baseline mas exigente sobre el conjunto de prueba.

        El baseline fuerte es el ultimo de la configuracion: el nivel del frente en regresion
        y la tasa de falla por tramo de inactividad en clasificacion.
        """
        fuerte = list(self.metricas_baselines.values())[-1].valor_principal
        propio = self.metricas.valor_principal
        return propio > fuerte if self.mejor_es_mayor else propio < fuerte


@dataclass
class Experimento:
    """Orquesta las tres fases de un problema y deja cada resultado registrado en MLflow.

    Recibe la matriz ya partida en desarrollo y prueba: quien decide la particion es
    `ParticionTemporal`, y mezclarlo aqui haria que este objeto tuviera dos motivos para
    cambiar.
    """

    desarrollo: pd.DataFrame
    prueba: pd.DataFrame
    registro: RegistroExperimento
    problema: ConfiguracionProblema = REGRESION_LEY
    iteraciones_busqueda: int = domain.ITERACIONES_BUSQUEDA
    pliegues: int = domain.PLIEGUES_VALIDACION
    tabla_variables_: pd.DataFrame = field(default_factory=pd.DataFrame)
    tabla_ventanas_: pd.DataFrame = field(default_factory=pd.DataFrame)
    conjunto_elegido_: ConjuntoVariables | None = None
    ventana_elegida_: int | None = None
    fabrica_elegida_: type | None = None
    peso_elegido_: float = SIN_PESO
    margen_ventana_: float = 0.0
    umbral_ventana_: float = 0.0

    def __post_init__(self) -> None:
        """Comprueba que las dos particiones sirven y deja la huella del insumo registrada."""
        for nombre, particion in (("desarrollo", self.desarrollo), ("prueba", self.prueba)):
            if particion.empty:
                raise InvalidParameterError(f"la particion de {nombre} no tiene filas")
            if self.problema.columna_objetivo not in particion.columns:
                raise InvalidParameterError(
                    f"la particion de {nombre} no trae la columna "
                    f"{self.problema.columna_objetivo!r}")
        # El registro apunta al experimento del problema: un mismo objeto de seguimiento
        # sirve para los dos, y cada uno deja sus corridas donde corresponde.
        self.registro.usar_experimento(self.problema.experimento)
        self.registro.etiquetas_comunes["hash_extracto"] = huella_de_datos(self.desarrollo)

    # -- fase A: conjunto de variables --------------------------------------------------

    def fase_variables(self) -> pd.DataFrame:
        """Compara los cuatro conjuntos con los dos modelos bajo la ventana expansiva.

        En clasificacion cada combinacion corre ademas con y sin peso de clase, porque el
        peso es una decision de modelado que se mide y no se supone: a nivel de turno el
        desbalance es moderado y la metrica principal es insensible al umbral, asi que su
        unico efecto seguro es sobre la calibracion. La fase elige el conjunto y el peso a la
        vez, y las fases siguientes los conservan.
        """
        ventana = self._ventana(None)
        filas = []
        for conjunto in CONJUNTOS:
            for fabrica in self.problema.fabricas:
                for peso in self._pesos_comparados():
                    modelo = self._construir(fabrica, conjunto, peso)
                    nombre = f"{modelo.nombre}__variables_{conjunto.nombre}"
                    if self.problema.compara_peso_de_clase:
                        nombre += "__sin_peso" if peso == SIN_PESO else "__con_peso"
                    resultado = self._evaluar(modelo.pipeline(), ventana, nombre)
                    self.registro.registrar_evaluacion(
                        resultado,
                        parametros={"modelo": modelo.nombre,
                                    "conjunto_variables": conjunto.nombre,
                                    "estrategia_ventana": ventana.nombre,
                                    "variables": len(conjunto.columnas),
                                    **self._parametro_peso(peso)},
                        fase=f"fase_a__variables__{self.problema.nombre}")
                    filas.append(self._fila(resultado, modelo.nombre, conjunto.nombre,
                                            ventana.nombre, peso=peso))

        self.tabla_variables_ = self._ordenar(pd.DataFrame(filas))
        mejor = self.tabla_variables_.iloc[0]
        self.conjunto_elegido_ = next(
            c for c in CONJUNTOS if c.nombre == mejor["conjunto_variables"])
        if self.problema.compara_peso_de_clase:
            self.peso_elegido_ = float(mejor[COLUMNA_PESO])
        logger.info("Fase A de %s: gana el conjunto %s con peso de clase %.4f",
                    self.problema.nombre, self.conjunto_elegido_.nombre, self.peso_elegido_)
        return self.tabla_variables_

    # -- fase B: ventana temporal -------------------------------------------------------

    def fase_ventana(self) -> pd.DataFrame:
        """Compara las cinco estrategias de ventana, con busqueda aleatoria anidada.

        Los baselines entran a la comparacion bajo cada estrategia: sirven para mostrar cuanto
        de la sensibilidad a la ventana es del modelo y cuanto del problema.
        """
        if self.conjunto_elegido_ is None:
            raise NotFittedError(f"{type(self).__name__}.fase_variables")

        conjuntos = [self.conjunto_elegido_]
        if self.conjunto_elegido_.nombre != MINIMO.nombre:
            conjuntos.append(MINIMO)

        filas = []
        for meses in VENTANAS_COMPARADAS:
            ventana = self._ventana(meses)
            filas.extend(self._baselines_bajo(ventana))
            for conjunto in conjuntos:
                for fabrica in self.problema.fabricas:
                    filas.append(self._buscar_y_evaluar(fabrica, conjunto, ventana, meses))

        self.tabla_ventanas_ = self._ordenar(pd.DataFrame(filas))
        mejor = self._elegir_ventana(self.tabla_ventanas_)
        self.ventana_elegida_ = None if mejor["meses_ventana"] == "" else int(
            mejor["meses_ventana"])
        self.fabrica_elegida_ = next(
            f for f in self.problema.fabricas
            if self._construir(f, MINIMO).nombre == mejor["modelo"])
        logger.info("Fase B de %s: gana %s con ventana %s",
                    self.problema.nombre, mejor["modelo"], mejor["estrategia_ventana"])
        return self.tabla_ventanas_

    def _elegir_ventana(self, tabla: pd.DataFrame) -> pd.Series:
        """Fila ganadora de la fase B, con la expansiva como hipotesis por defecto.

        La mejor deslizante solo desplaza a la mejor expansiva si la supera por mas de la
        desviacion entre pliegues de la expansiva. Sin esta regla, "el maximo gana" convierte
        un empate en una eleccion: sobre el extracto la deslizante de doce meses gano por
        0.0003 g/t con 0.016 de desviacion entre pliegues, y el modelo quedo registrado con
        una ventana que la propia documentacion llamaba empate. No es una regla sobre
        hiperparametros -esos se eligen por el maximo, y la brecha registrada dice cuanto
        cuesta- sino sobre una decision de diseno con hipotesis declarada: no se abandona por
        una diferencia que no se distingue del ruido.
        """
        modelos = tabla[~tabla["modelo"].str.startswith("baseline")]
        candidata = modelos.iloc[0]
        expansivas = modelos[modelos["meses_ventana"] == ""]
        if expansivas.empty:
            return candidata
        referencia = expansivas.iloc[0]
        principal = self.problema.evaluador.nombre_principal
        signo = 1.0 if self.problema.evaluador.mejor_es_mayor else -1.0
        self.margen_ventana_ = float(signo * (candidata[principal] - referencia[principal]))
        self.umbral_ventana_ = float(referencia["desviacion_entre_pliegues"])
        if candidata["meses_ventana"] != "" and self.margen_ventana_ <= self.umbral_ventana_:
            logger.info("Fase B de %s: %s supera a la expansiva por %.4f, menos que la "
                        "desviacion entre pliegues %.4f; se conserva la expansiva",
                        self.problema.nombre, candidata["estrategia_ventana"],
                        self.margen_ventana_, self.umbral_ventana_)
            return referencia
        return candidata

    def _recortar_desarrollo(self, meses: int | None) -> pd.DataFrame:
        """Desarrollo con que se reajusta el modelo final: todo, o los meses de la ventana.

        La estrategia de ventana gobernaba solo los pliegues de la busqueda y el reajuste
        final usaba todo el desarrollo, de modo que un modelo registrado como deslizante habia
        entrenado con toda la historia. Aqui la ventana se honra midiendola desde el comienzo
        de la prueba, que es el papel que el bloque de validacion tenia en la fase B. Los
        baselines siguen ajustandose con todo el desarrollo: son la referencia, y la fase B
        mostro que la historia completa es su mejor configuracion.
        """
        if meses is None:
            return self.desarrollo
        desde = self.prueba[domain.COLUMNA_INICIO_TURNO].min() - pd.DateOffset(months=meses)
        recorte: pd.DataFrame = self.desarrollo.loc[
            self.desarrollo[domain.COLUMNA_INICIO_TURNO] >= desde].reset_index(drop=True)
        if recorte.empty:
            raise EmptyPartitionError(
                f"la ventana de {meses} meses no deja turnos de desarrollo desde {desde}")
        return recorte

    # -- fase C: prueba -----------------------------------------------------------------

    def fase_prueba(self) -> ResultadoFinal:
        """Reajusta la combinacion ganadora sobre todo el desarrollo y la evalua una vez."""
        if self.fabrica_elegida_ is None or self.conjunto_elegido_ is None:
            raise NotFittedError(f"{type(self).__name__}.fase_ventana")

        objetivo_desarrollo = self.desarrollo[self.problema.columna_objetivo]
        fase = f"fase_c__prueba__{self.problema.nombre}"
        # El ejemplo que se registra es la entrada del servicio y no una fila de la matriz:
        # de el sale la firma que MLflow hace cumplir en cada peticion, y una fila completa
        # exigiria mandarle al modelo hasta su propio objetivo.
        ejemplo = tipos_de_servicio(
            self.prueba.loc[:, list(columnas_de_entrada(self.conjunto_elegido_))].head(3))

        modelo = self._construir(self.fabrica_elegida_, self.conjunto_elegido_)
        busqueda = self._buscar(modelo, self._ventana(self.ventana_elegida_))
        desarrollo_final = self._recortar_desarrollo(self.ventana_elegida_)
        pipeline = clone(busqueda.best_estimator_).fit(
            desarrollo_final, desarrollo_final[self.problema.columna_objetivo])
        metricas = self._medir(pipeline, self.prueba)

        baselines: dict[str, Metricas] = {}
        for nombre, fabrica_baseline in self.problema.baselines:
            ajustado = fabrica_baseline().fit(self.desarrollo, objetivo_desarrollo)
            baselines[nombre] = self._medir(ajustado, self.prueba)
            self.registro.registrar_modelo(
                ajustado, f"prueba__{self.problema.nombre}__{nombre}",
                parametros={"modelo": nombre, "conjunto_variables": "-",
                            "estrategia_ventana": "-"},
                metricas=baselines[nombre].como_diccionario(),
                ejemplo=ejemplo, fase=fase,
                nombre_artefacto=f"modelo_{self.problema.nombre}")

        final = ResultadoFinal(
            problema=self.problema.nombre,
            modelo=modelo.nombre,
            conjunto=self.conjunto_elegido_.nombre,
            ventana=self._ventana(self.ventana_elegida_).nombre,
            metricas=metricas,
            metricas_baselines=baselines,
            detalle_por_frente=self._detalle_por_frente(pipeline),
            pipeline=pipeline,
            mejor_es_mayor=self.problema.evaluador.mejor_es_mayor,
            turnos_entrenamiento=len(desarrollo_final),
        )
        self.registro.registrar_modelo(
            pipeline, f"prueba__{self.problema.nombre}__{modelo.nombre}_ganador",
            parametros={"modelo": modelo.nombre,
                        "conjunto_variables": self.conjunto_elegido_.nombre,
                        "estrategia_ventana": final.ventana,
                        "turnos_entrenamiento_final": len(desarrollo_final),
                        **self._parametro_peso(self.peso_elegido_),
                        **busqueda.best_params_},
            metricas=metricas.como_diccionario(),
            ejemplo=ejemplo,
            fase=fase,
            artefactos={"detalle_por_frente": final.detalle_por_frente,
                        "hiperparametros_muestreados": configuraciones_muestreadas(busqueda)},
            nombre_artefacto=f"modelo_{self.problema.nombre}",
            registrar_como=self.problema.modelo_registrado,
            alias=domain.ALIAS_PRODUCCION)
        logger.info("Fase C de %s: %s = %.4f, le gana al baseline fuerte: %s",
                    self.problema.nombre, self.problema.evaluador.nombre_principal,
                    metricas.valor_principal, final.le_gana_al_baseline_fuerte)
        return final

    # -- interno ------------------------------------------------------------------------

    def _construir(
        self,
        fabrica: type,
        conjunto: ConjuntoVariables,
        peso: float | None = None,
    ) -> FabricaModelo:
        """Instancia la fabrica del modelo, con el peso de clase pedido o el ya elegido."""
        if self.problema.compara_peso_de_clase:
            elegido = self.peso_elegido_ if peso is None else peso
            modelo: FabricaModelo = fabrica(conjunto=conjunto, peso_positivo=elegido)
            return modelo
        return fabrica(conjunto=conjunto)  # type: ignore[no-any-return]

    def _pesos_comparados(self) -> tuple[float, ...]:
        """Los pesos que la fase A compara: sin peso, y la razon negativos/positivos."""
        if not self.problema.compara_peso_de_clase:
            return (SIN_PESO,)
        return (SIN_PESO, peso_de_clase(self.desarrollo[self.problema.columna_objetivo]))

    def _parametro_peso(self, peso: float) -> dict[str, float]:
        """El peso como parametro de MLflow, solo en el problema que lo compara."""
        if not self.problema.compara_peso_de_clase:
            return {}
        return {COLUMNA_PESO: round(peso, 4)}

    def _ventana(self, meses: int | None) -> VentanaTemporal:
        return ventana_desde_matriz(self.desarrollo, meses=meses, pliegues=self.pliegues)

    def _evaluar(
        self, estimador: BaseEstimator, ventana: VentanaTemporal, nombre: str,
    ) -> ResultadoEvaluacion:
        return evaluar_por_pliegues(
            estimador, self.desarrollo, ventana, nombre,
            columna_objetivo=self.problema.columna_objetivo,
            evaluador=self.problema.evaluador)

    def _buscar(
        self, modelo: FabricaModelo, ventana: VentanaTemporal,
    ) -> RandomizedSearchCV:
        return buscar_hiperparametros(
            modelo, self.desarrollo, ventana, iteraciones=self.iteraciones_busqueda,
            columna_objetivo=self.problema.columna_objetivo, puntaje=self.problema.puntaje)

    def _medir(self, estimador: BaseEstimator, particion: pd.DataFrame) -> Metricas:
        return self.problema.evaluador(
            estimador, particion, particion[self.problema.columna_objetivo])

    def _detalle_por_frente(self, pipeline: BaseEstimator) -> pd.DataFrame:
        """Error por frente en regresion; en clasificacion, probabilidad media contra real."""
        objetivo = self.prueba[self.problema.columna_objetivo].to_numpy(dtype=float)
        if self.problema.evaluador.mejor_es_mayor:
            probabilidad = pipeline.predict_proba(self.prueba)[:, 1]
            return (
                pd.DataFrame({domain.COLUMNA_FRENTE: self.prueba[domain.COLUMNA_FRENTE],
                              "probabilidad_media": probabilidad,
                              "tasa_real": objetivo})
                .groupby(domain.COLUMNA_FRENTE)
                .agg(probabilidad_media=("probabilidad_media", "mean"),
                     tasa_real=("tasa_real", "mean"), turnos=("tasa_real", "size"))
                .reset_index()
                .sort_values("tasa_real", ascending=False)
                .reset_index(drop=True)
            )
        return error_por_frente(
            self.prueba[domain.COLUMNA_FRENTE], objetivo, pipeline.predict(self.prueba))

    def _baselines_bajo(self, ventana: VentanaTemporal) -> list[dict[str, object]]:
        """Evalua los dos baselines del problema bajo una estrategia de ventana."""
        filas = []
        for nombre, fabrica_baseline in self.problema.baselines:
            resultado = self._evaluar(
                fabrica_baseline(), ventana, f"{nombre}__{ventana.nombre}")
            self.registro.registrar_evaluacion(
                resultado,
                parametros={"modelo": nombre, "conjunto_variables": "-",
                            "estrategia_ventana": ventana.nombre,
                            "meses_ventana": ventana.meses},
                fase=f"fase_b__ventana__{self.problema.nombre}")
            filas.append(self._fila(resultado, nombre, "-", ventana.nombre, ventana.meses))
        return filas

    def _buscar_y_evaluar(
        self,
        fabrica: type,
        conjunto: ConjuntoVariables,
        ventana: VentanaTemporal,
        meses: int | None,
    ) -> dict[str, object]:
        """Busca hiperparametros y evalua el mejor pipeline sobre los mismos pliegues."""
        modelo = self._construir(fabrica, conjunto)
        busqueda = self._buscar(modelo, ventana)
        nombre = f"{modelo.nombre}__{ventana.nombre}__{conjunto.nombre}"
        resultado = self._evaluar(clone(busqueda.best_estimator_), ventana, nombre)
        self.registro.registrar_evaluacion(
            resultado,
            parametros={"modelo": modelo.nombre, "conjunto_variables": conjunto.nombre,
                        "estrategia_ventana": ventana.nombre, "meses_ventana": ventana.meses,
                        "iteraciones_busqueda": self.iteraciones_busqueda,
                        **self._parametro_peso(self.peso_elegido_),
                        **busqueda.best_params_},
            fase=f"fase_b__ventana__{self.problema.nombre}",
            artefactos={"hiperparametros_muestreados": configuraciones_muestreadas(busqueda)})
        return self._fila(resultado, modelo.nombre, conjunto.nombre, ventana.nombre, meses)

    def _fila(
        self,
        resultado: ResultadoEvaluacion,
        modelo: str,
        conjunto: str,
        ventana: str,
        meses: int | None = None,
        peso: float | None = None,
    ) -> dict[str, object]:
        """Una fila de la tabla comparativa, con los nombres del negocio.

        Lleva la metrica de entrenamiento y la brecha al lado de la de validacion, para que
        la tabla muestre no solo cual combinacion acierta mas sino cual memoriza mas.
        """
        fila: dict[str, object] = {
            "modelo": modelo,
            "conjunto_variables": conjunto,
            "estrategia_ventana": ventana,
            "meses_ventana": "" if meses is None else meses,
        }
        if self.problema.compara_peso_de_clase:
            fila[COLUMNA_PESO] = "" if peso is None else round(peso, 4)
        fila.update({
            resultado.nombre_principal: resultado.valor_principal,
            f"{resultado.nombre_principal}{SUFIJO_ENTRENAMIENTO}":
                resultado.valor_principal_entrenamiento,
            BRECHA: resultado.brecha_entrenamiento_validacion,
            "desviacion_entre_pliegues": resultado.desviacion_entre_pliegues,
            "turnos_entrenamiento": resultado.turnos_entrenamiento_medio,
        })
        return fila

    def _ordenar(self, tabla: pd.DataFrame) -> pd.DataFrame:
        columna = self.problema.evaluador.nombre_principal
        return tabla.sort_values(
            columna, ascending=not self.problema.evaluador.mejor_es_mayor
        ).reset_index(drop=True)
