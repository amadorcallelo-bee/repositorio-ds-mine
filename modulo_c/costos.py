"""Volumetria y modelo de costos de la plataforma UMLC del Ejercicio C-1.

Existe para que ninguna cifra de `decisiones_arquitectura.md` sea una afirmacion de prosa.
Cada numero publicado en ese documento sale de ejecutar este modulo, y `tests/test_costos.py`
fija esos numeros: si manana cambia una tarifa y alguien la corrige aqui sin actualizar el
documento, la prueba falla. Es la unica forma de que la vigencia de un documento la haga
cumplir una maquina y no la memoria de quien lo escribio.

Dos decisiones de construccion que tienen alternativa razonable:

Solo biblioteca estandar. Se descarto usar pandas, que esta en el entorno del Modulo A,
porque este modulo debe correr en la maquina de un evaluador sin activar ningun entorno
virtual y sin competir por la venv compartida. La aritmetica es de sumas y productos: una
dependencia aqui solo agrega superficie de fallo.

`Decimal` y no `float`. Son cifras monetarias. El redondeo binario de `float` no cambiaria
la conclusion a esta escala, pero un modelo de costos que se cita en una decision de
presupuesto no puede depender de que el error sea pequeno.

Toda tarifa lleva su fuente adjunta en el propio objeto `Tarifa`, porque una cifra sin
procedencia no es verificable y el ejercicio pide costos con respaldo. Las tarifas de Azure
salen de la Azure Retail Prices API, que es la lista oficial de Microsoft en JSON y sin
autenticacion, region East US, consultada el 2026-08-30.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Final

# --- Alias del dominio ---

#: Importe monetario en dolares. Se nombra para que ninguna firma diga `Decimal` a secas y
#: haya que deducir del nombre del parametro si es dinero, una tasa o un conteo.
Dinero = Decimal

#: Linea de la estimacion anual: nombre del rubro contra su importe.
Rubros = dict[str, Dinero]

HORAS_ANIO: Final[Decimal] = Decimal("8760")
MESES_ANIO: Final[Decimal] = Decimal("12")
DIAS_ANIO: Final[Decimal] = Decimal("365")
SEGUNDOS_ANIO: Final[Decimal] = Decimal("31536000")
BYTES_POR_GB: Final[Decimal] = Decimal("1073741824")

FUENTE_AZURE: Final[str] = "Azure Retail Prices API, East US, consultada 2026-08-30"
FUENTE_MICROSOFT: Final[str] = "Microsoft, lista publica de Power BI, vigente desde 2025-04-01"


@dataclass(frozen=True)
class Tarifa:
    """Un precio de lista con su unidad y su procedencia.

    La fuente viaja pegada al valor y no en un comentario aparte para que sea imposible
    copiar la cifra a otro calculo dejando atras su respaldo.
    """

    valor: Decimal
    unidad: str
    fuente: str


# --- Tarifas de lista ---

FABRIC_CU_HORA: Final[Tarifa] = Tarifa(Decimal("0.18"), "USD por CU-hora", FUENTE_AZURE)
FABRIC_CU_RESERVA_ANUAL: Final[Tarifa] = Tarifa(
    Decimal("938.00"), "USD por CU-anio, reserva de 1 anio", FUENTE_AZURE
)
POWER_BI_PRO_MES: Final[Tarifa] = Tarifa(
    Decimal("14"), "USD por usuario-mes", FUENTE_MICROSOFT
)
DBU_JOBS: Final[Tarifa] = Tarifa(
    Decimal("0.30"), "USD por DBU-hora, Premium Jobs Compute", FUENTE_AZURE
)
DBU_INTERACTIVO: Final[Tarifa] = Tarifa(
    Decimal("0.55"), "USD por DBU-hora, Premium All-purpose Compute", FUENTE_AZURE
)
VM_BAJO_DEMANDA: Final[Tarifa] = Tarifa(
    Decimal("0.226"), "USD por hora, Standard_D4ds_v5 Linux", FUENTE_AZURE
)
VM_SPOT: Final[Tarifa] = Tarifa(
    Decimal("0.047709"), "USD por hora, Standard_D4ds_v5 Spot", FUENTE_AZURE
)
ADLS_CALIENTE: Final[Tarifa] = Tarifa(
    Decimal("0.0208"), "USD por GB-mes, ADLS Gen2 Hot LRS", FUENTE_AZURE
)
ADLS_FRIO: Final[Tarifa] = Tarifa(
    Decimal("0.0152"), "USD por GB-mes, ADLS Gen2 Cool LRS", FUENTE_AZURE
)
ADLS_ARCHIVO: Final[Tarifa] = Tarifa(
    Decimal("0.00099"), "USD por GB-mes, ADLS Gen2 Archive LRS", FUENTE_AZURE
)
EVENT_HUBS_TU_HORA: Final[Tarifa] = Tarifa(
    Decimal("0.03"), "USD por hora, Standard Throughput Unit", FUENTE_AZURE
)
EVENT_HUBS_MILLON: Final[Tarifa] = Tarifa(
    Decimal("0.028"), "USD por millon de eventos de ingreso", FUENTE_AZURE
)
EVENT_HUBS_CAPTURA_HORA: Final[Tarifa] = Tarifa(
    Decimal("0.10"), "USD por hora, Standard Capture", FUENTE_AZURE
)
EMBEDDING_MIL_TOKENS: Final[Tarifa] = Tarifa(
    Decimal("0.00013"), "USD por 1K tokens, text-embedding-3-large", FUENTE_AZURE
)
LLM_ENTRADA_MIL_TOKENS: Final[Tarifa] = Tarifa(
    Decimal("0.00015"), "USD por 1K tokens de entrada, gpt-4o-mini global", FUENTE_AZURE
)
LLM_SALIDA_MIL_TOKENS: Final[Tarifa] = Tarifa(
    Decimal("0.0006"), "USD por 1K tokens de salida, gpt-4o-mini global", FUENTE_AZURE
)


@dataclass(frozen=True)
class FuenteDeSenales:
    """Un conjunto de activos que emiten senales al mismo periodo de muestreo."""

    nombre: str
    activos: int
    senales_por_activo: int

    @property
    def senales(self) -> int:
        """Numero total de senales que emite la fuente."""
        return self.activos * self.senales_por_activo


@dataclass(frozen=True)
class Volumetria:
    """Cuanto dato genera al ano el escenario del C-1.

    Se calcula y no se estima de memoria porque el argumento central del documento depende
    de esta cifra: el escenario suena a gran volumen y no lo es, y esa diferencia decide la
    plataforma. El escalado parte del extracto real de la UMLC -10 equipos y 13 frentes en
    una unidad- llevado a 3 minas, 1 planta y 2 depositos de relaves.
    """

    fuentes: tuple[FuenteDeSenales, ...]
    periodo_muestreo_seg: int = 30

    @property
    def senales_totales(self) -> int:
        """Suma de senales de todas las fuentes."""
        return sum(fuente.senales for fuente in self.fuentes)

    @property
    def lecturas_por_anio(self) -> Decimal:
        """Lecturas de telemetria al ano, a periodo de muestreo constante."""
        return Decimal(self.senales_totales) * SEGUNDOS_ANIO / Decimal(self.periodo_muestreo_seg)

    def gigabytes_por_anio(self, bytes_por_lectura: int) -> Decimal:
        """Tamano anual de la telemetria en Delta comprimido.

        Parameters
        ----------
        bytes_por_lectura
            Peso de una fila estrecha ya comprimida. Se evalua en un rango porque depende
            del orden de las columnas y del factor de compresion que logre Parquet.
        """
        return self.lecturas_por_anio * Decimal(bytes_por_lectura) / BYTES_POR_GB


@dataclass(frozen=True)
class CapacidadFabric:
    """Costo de la capacidad de Microsoft Fabric y su punto de indiferencia con las licencias.

    La segunda parte es la que importa: los visores gratuitos empiezan en F64, y el reflejo
    del mercado es comprar F64 para no pagar licencias Pro. Este objeto calcula a partir de
    cuantos visores esa compra deja de ser un derroche, en vez de discutirlo por intuicion.
    """

    unidades_capacidad: int

    @property
    def mensual_pago_por_uso(self) -> Dinero:
        """Costo mensual de la capacidad encendida todo el mes, sin compromiso."""
        return FABRIC_CU_HORA.valor * Decimal(self.unidades_capacidad) * HORAS_ANIO / MESES_ANIO

    @property
    def mensual_reservado(self) -> Dinero:
        """Costo mensual equivalente de la reserva a un ano."""
        return FABRIC_CU_RESERVA_ANUAL.valor * Decimal(self.unidades_capacidad) / MESES_ANIO

    @property
    def descuento_reserva(self) -> Decimal:
        """Fraccion que ahorra la reserva frente al pago por uso."""
        return Decimal("1") - self.mensual_reservado / self.mensual_pago_por_uso

    def visores_de_indiferencia(self, alterna: CapacidadFabric) -> Decimal:
        """Visores Pro a los que esta capacidad y `alterna` cuestan lo mismo.

        Parameters
        ----------
        alterna
            La capacidad mayor, que incluye visualizacion sin licencia por usuario.
        """
        return (alterna.mensual_reservado - self.mensual_reservado) / POWER_BI_PRO_MES.valor


@dataclass(frozen=True)
class ClusterDatabricks:
    """Costo de un clon de trabajo de Databricks, contando la maquina y no solo el DBU.

    Existe porque el error de presupuesto mas comun en Databricks es cotizar el DBU y
    olvidar la VM subyacente, que se factura aparte. El objeto expone las dos piezas por
    separado para que el documento pueda citar cuanto agrega la maquina sobre el DBU.
    """

    nodos: int
    dbu_por_nodo: Decimal = Decimal("1")
    tarifa_dbu: Tarifa = DBU_JOBS
    tarifa_vm: Tarifa = VM_BAJO_DEMANDA

    @property
    def costo_por_nodo_hora(self) -> Dinero:
        """Costo de un nodo durante una hora, DBU mas maquina."""
        return self.tarifa_dbu.valor * self.dbu_por_nodo + self.tarifa_vm.valor

    @property
    def sobrecosto_de_la_maquina(self) -> Decimal:
        """Fraccion que la VM agrega sobre el DBU."""
        return self.tarifa_vm.valor / (self.tarifa_dbu.valor * self.dbu_por_nodo)

    def costo_anual(self, horas_por_dia: Decimal) -> Dinero:
        """Costo anual del clon operando el numero de horas diarias indicado."""
        return Decimal(self.nodos) * self.costo_por_nodo_hora * horas_por_dia * DIAS_ANIO


@dataclass(frozen=True)
class Almacenamiento:
    """Costo anual del lago, separando telemetria de imagenes de dron.

    Se separan porque responden a preguntas distintas: la telemetria esta bien acotada por
    el extracto real, mientras que el volumen de dron es el dato mas debil del modelo. Que
    vivan en campos distintos permite la prueba de sensibilidad que el documento publica.
    """

    telemetria_gb_anio: Decimal
    anios_retenidos: Decimal
    dron_gb_anio: Decimal
    anios_dron_en_archivo: Decimal = Decimal("4")

    @property
    def costo_anual(self) -> Dinero:
        """Costo anual con telemetria en caliente, un ano de dron en frio y el resto en archivo."""
        telemetria = self.telemetria_gb_anio * self.anios_retenidos * ADLS_CALIENTE.valor
        dron_frio = self.dron_gb_anio * ADLS_FRIO.valor
        dron_archivo = self.dron_gb_anio * self.anios_dron_en_archivo * ADLS_ARCHIVO.valor
        return (telemetria + dron_frio + dron_archivo) * MESES_ANIO


@dataclass(frozen=True)
class IngestaEventHubs:
    """Costo anual de la ingesta de telemetria con captura a Delta activada.

    Se modela sobre Event Hubs y no sobre IoT Hub porque las senales llegan agregadas desde
    seis pasarelas y no como seis mil dispositivos independientes: pagar precio por
    dispositivo por un trafico que cabe en una sola unidad de rendimiento es un error de
    dimensionamiento, no una diferencia de preferencia.
    """

    lecturas_por_anio: Decimal
    unidades_rendimiento: int = 1

    @property
    def costo_anual(self) -> Dinero:
        """Costo anual de unidades de rendimiento, eventos de ingreso y captura."""
        unidades = EVENT_HUBS_TU_HORA.valor * Decimal(self.unidades_rendimiento) * HORAS_ANIO
        eventos = self.lecturas_por_anio / Decimal("1000000") * EVENT_HUBS_MILLON.valor
        captura = EVENT_HUBS_CAPTURA_HORA.valor * HORAS_ANIO
        return unidades + eventos + captura


@dataclass(frozen=True)
class AsistenteRag:
    """Costo de tokens del asistente sobre los 800 documentos tecnicos reales.

    Se calcula aparte del rubro agregado de servicios porque la conclusion es
    contraintuitiva y conviene poder citarla sola: indexar el corpus completo cuesta
    alrededor de un dolar, una sola vez. Lo que cuesta un RAG no son los tokens.
    """

    documentos: int
    tokens_por_documento: int
    consultas_por_dia: int
    tokens_entrada_por_consulta: int
    tokens_salida_por_consulta: int

    @property
    def costo_indexacion(self) -> Dinero:
        """Costo unico de vectorizar el corpus completo."""
        tokens = Decimal(self.documentos) * Decimal(self.tokens_por_documento)
        return tokens / Decimal("1000") * EMBEDDING_MIL_TOKENS.valor

    def costo_anual_consultas(
        self, entrada: Tarifa = LLM_ENTRADA_MIL_TOKENS, salida: Tarifa = LLM_SALIDA_MIL_TOKENS
    ) -> Dinero:
        """Costo anual de responder consultas.

        Parameters
        ----------
        entrada, salida
            Tarifas por millar de tokens. Se parametrizan para poder contrastar un modelo
            economico contra uno de frontera y mostrar que la conclusion no cambia.
        """
        consultas = Decimal(self.consultas_por_dia) * DIAS_ANIO
        costo_entrada = consultas * Decimal(self.tokens_entrada_por_consulta) / Decimal("1000")
        costo_salida = consultas * Decimal(self.tokens_salida_por_consulta) / Decimal("1000")
        return costo_entrada * entrada.valor + costo_salida * salida.valor


@dataclass(frozen=True)
class Escenario:
    """Los supuestos que separan el extremo bajo del extremo alto de la estimacion.

    El ejercicio pide un rango y no un numero, asi que los supuestos son parte del
    resultado: publicar 30 mil dolares sin decir sobre que hipotesis descansa no es una
    estimacion, es una cifra.
    """

    nombre: str
    unidades_capacidad: int
    visores_power_bi: int
    horas_diarias_de_jobs: Decimal
    horas_mensuales_interactivas: Decimal
    telemetria_gb_anio: Decimal
    dron_gb_anio: Decimal
    servicios_y_red: Dinero
    usa_spot_en_jobs: bool


@dataclass(frozen=True)
class EstimacionAnual:
    """Estimacion anual de la plataforma para un escenario dado."""

    escenario: Escenario
    volumetria: Volumetria
    anios_retenidos: Decimal = Decimal("5")
    nodos_por_cluster: int = 3

    @property
    def rubros(self) -> Rubros:
        """Importe anual de cada linea de la factura."""
        capacidad = CapacidadFabric(self.escenario.unidades_capacidad)
        licencias = (
            Decimal(self.escenario.visores_power_bi) * POWER_BI_PRO_MES.valor * MESES_ANIO
        )
        jobs = ClusterDatabricks(
            nodos=self.nodos_por_cluster,
            tarifa_vm=VM_SPOT if self.escenario.usa_spot_en_jobs else VM_BAJO_DEMANDA,
        )
        interactivo = ClusterDatabricks(
            nodos=self.nodos_por_cluster, tarifa_dbu=DBU_INTERACTIVO
        )
        almacenamiento = Almacenamiento(
            telemetria_gb_anio=self.escenario.telemetria_gb_anio,
            anios_retenidos=self.anios_retenidos,
            dron_gb_anio=self.escenario.dron_gb_anio,
        )
        ingesta = IngestaEventHubs(self.volumetria.lecturas_por_anio)
        return {
            "Fabric y licencias Power BI": capacidad.mensual_reservado * MESES_ANIO + licencias,
            "Databricks jobs": jobs.costo_anual(self.escenario.horas_diarias_de_jobs),
            "Databricks interactivo": interactivo.costo_anual(
                self.escenario.horas_mensuales_interactivas * MESES_ANIO / DIAS_ANIO
            ),
            "Almacenamiento": almacenamiento.costo_anual,
            "Ingesta": ingesta.costo_anual,
            "Servicios, RAG, red y borde": self.escenario.servicios_y_red,
        }

    @property
    def total(self) -> Dinero:
        """Suma de todos los rubros."""
        return sum(self.rubros.values(), Decimal("0"))

    def participacion(self, rubro: str) -> Decimal:
        """Fraccion del total que representa un rubro."""
        return self.rubros[rubro] / self.total


# --- Parametros del escenario C-1 ---

#: Escalado del extracto real de la UMLC al escenario del enunciado. Las 13 senales por
#: equipo son las columnas de sensor del diccionario de variables; los 250 tags de planta y
#: los 60 por deposito son ordenes de magnitud tipicos de un DCS y de una instrumentacion
#: geotecnica, y se declaran como supuesto porque el enunciado no los da.
FUENTES_UMLC: Final[tuple[FuenteDeSenales, ...]] = (
    FuenteDeSenales("Equipos de perforacion, 3 minas", activos=30, senales_por_activo=13),
    FuenteDeSenales("Planta de procesamiento", activos=1, senales_por_activo=250),
    FuenteDeSenales("Depositos de relaves", activos=2, senales_por_activo=60),
)

VOLUMETRIA_UMLC: Final[Volumetria] = Volumetria(FUENTES_UMLC)

#: Rango de peso de una fila de telemetria ya comprimida en Delta.
BYTES_POR_LECTURA_BAJO: Final[int] = 40
BYTES_POR_LECTURA_ALTO: Final[int] = 120

#: 104 vuelos al ano por 15 y por 60 GB. Es el dato mas debil del modelo y el documento lo
#: declara asi; la prueba de sensibilidad muestra que tendria que errar por un factor de
#: diez para cambiar alguna conclusion.
DRON_GB_ANIO_BAJO: Final[Decimal] = Decimal("1560")
DRON_GB_ANIO_ALTO: Final[Decimal] = Decimal("6240")

ESCENARIO_BAJO: Final[Escenario] = Escenario(
    nombre="bajo",
    unidades_capacidad=8,
    visores_power_bi=25,
    horas_diarias_de_jobs=Decimal("3"),
    horas_mensuales_interactivas=Decimal("20"),
    telemetria_gb_anio=Decimal("30"),
    dron_gb_anio=DRON_GB_ANIO_BAJO,
    servicios_y_red=Decimal("3000"),
    usa_spot_en_jobs=True,
)

ESCENARIO_ALTO: Final[Escenario] = Escenario(
    nombre="alto",
    unidades_capacidad=16,
    visores_power_bi=40,
    horas_diarias_de_jobs=Decimal("8"),
    horas_mensuales_interactivas=Decimal("60"),
    telemetria_gb_anio=Decimal("89"),
    dron_gb_anio=DRON_GB_ANIO_ALTO,
    servicios_y_red=Decimal("12000"),
    usa_spot_en_jobs=False,
)

ASISTENTE_UMLC: Final[AsistenteRag] = AsistenteRag(
    documentos=800,
    tokens_por_documento=10000,
    consultas_por_dia=30,
    tokens_entrada_por_consulta=6000,
    tokens_salida_por_consulta=400,
)

#: Tarifas de un modelo de frontera, en USD por millon de tokens, expresadas por millar para
#: contrastarlas con `gpt-4o-mini`. No salen de la lista de Azure: son el orden de magnitud
#: publico de esa gama y se usan solo para mostrar que la conclusion resiste el cambio.
LLM_FRONTERA_ENTRADA: Final[Tarifa] = Tarifa(
    Decimal("3") / Decimal("1000"), "USD por 1K tokens de entrada", "orden de magnitud publico"
)
LLM_FRONTERA_SALIDA: Final[Tarifa] = Tarifa(
    Decimal("15") / Decimal("1000"), "USD por 1K tokens de salida", "orden de magnitud publico"
)


@dataclass(frozen=True)
class Reporte:
    """Impresion del modelo completo, que es lo que alimenta al documento.

    Se separa del calculo para que las clases anteriores sigan siendo consultables desde una
    prueba sin pasar por la salida de texto.
    """

    volumetria: Volumetria = VOLUMETRIA_UMLC
    escenarios: tuple[Escenario, Escenario] = field(
        default=(ESCENARIO_BAJO, ESCENARIO_ALTO)
    )

    def imprimir(self) -> None:
        """Escribe el modelo completo en la salida estandar."""
        self._imprimir_volumetria()
        self._imprimir_fabric()
        self._imprimir_databricks()
        self._imprimir_totales()
        self._imprimir_sensibilidad_dron()
        self._imprimir_asistente()

    def _imprimir_volumetria(self) -> None:
        print("== Volumetria del escenario ==")
        for fuente in self.volumetria.fuentes:
            print(f"  {fuente.nombre:<34} {fuente.senales:>5} senales")
        print(f"  {'TOTAL':<34} {self.volumetria.senales_totales:>5} senales")
        print(f"  lecturas por anio: {self.volumetria.lecturas_por_anio:,.0f}")
        bajo = self.volumetria.gigabytes_por_anio(BYTES_POR_LECTURA_BAJO)
        alto = self.volumetria.gigabytes_por_anio(BYTES_POR_LECTURA_ALTO)
        print(f"  telemetria: {bajo:,.0f} a {alto:,.0f} GB por anio comprimida")

    def _imprimir_fabric(self) -> None:
        print("\n== Capacidad Fabric, USD por mes ==")
        for cu in (2, 4, 8, 16, 64):
            capacidad = CapacidadFabric(cu)
            print(
                f"  F{cu:<3} pago por uso {capacidad.mensual_pago_por_uso:>8,.0f}"
                f" | reservado {capacidad.mensual_reservado:>8,.0f}"
                f" | descuento {capacidad.descuento_reserva * 100:>4.1f}%"
            )
        f8, f64 = CapacidadFabric(8), CapacidadFabric(64)
        indiferencia = f8.visores_de_indiferencia(f64)
        print(f"  indiferencia entre F8 mas Pro y F64: {indiferencia:,.0f} visores")
        for visores in (25, 40, 80):
            costo = f8.mensual_reservado + Decimal(visores) * POWER_BI_PRO_MES.valor
            print(
                f"    {visores:>3} visores -> F8 mas Pro {costo:>8,.0f}"
                f" contra F64 {f64.mensual_reservado:>8,.0f}"
            )

    def _imprimir_databricks(self) -> None:
        print("\n== Databricks: peso de la maquina sobre el DBU ==")
        nodo = ClusterDatabricks(nodos=1)
        print(
            f"  DBU {DBU_JOBS.valor} mas VM {VM_BAJO_DEMANDA.valor}"
            f" = {nodo.costo_por_nodo_hora} USD por nodo-hora"
        )
        print(f"  la maquina agrega {nodo.sobrecosto_de_la_maquina * 100:.0f}% sobre el DBU")
        con_spot = ClusterDatabricks(nodos=1, tarifa_vm=VM_SPOT)
        ahorro = Decimal("1") - con_spot.costo_por_nodo_hora / nodo.costo_por_nodo_hora
        print(f"  con Spot en los workers el nodo-hora baja {ahorro * 100:.0f}%")

    def _imprimir_totales(self) -> None:
        print("\n== Estimacion anual, USD ==")
        bajo = EstimacionAnual(self.escenarios[0], self.volumetria)
        alto = EstimacionAnual(self.escenarios[1], self.volumetria)
        for rubro in bajo.rubros:
            print(
                f"  {rubro:<30} {bajo.rubros[rubro]:>10,.0f} - {alto.rubros[rubro]:>10,.0f}"
                f"   ({bajo.participacion(rubro) * 100:>4.1f}% - "
                f"{alto.participacion(rubro) * 100:>4.1f}%)"
            )
        print(f"  {'TOTAL':<30} {bajo.total:>10,.0f} - {alto.total:>10,.0f}")

    def _imprimir_sensibilidad_dron(self) -> None:
        print("\n== Sensibilidad: cuanto tendria que crecer el dron para importar ==")
        alto = self.escenarios[1]
        for factor in (1, 5, 10, 50):
            escenario = replace(alto, dron_gb_anio=alto.dron_gb_anio * factor)
            estimacion = EstimacionAnual(escenario, self.volumetria)
            print(
                f"  dron x{factor:<3} -> {escenario.dron_gb_anio:>9,.0f} GB por anio"
                f" | almacenamiento {estimacion.rubros['Almacenamiento']:>8,.0f} USD"
                f" | {estimacion.participacion('Almacenamiento') * 100:>4.1f}% del total"
            )

    def _imprimir_asistente(self) -> None:
        print("\n== Asistente RAG sobre 800 documentos ==")
        indexacion = ASISTENTE_UMLC.costo_indexacion
        print(f"  indexacion inicial del corpus: {indexacion:,.2f} USD, una vez")
        economico = ASISTENTE_UMLC.costo_anual_consultas()
        frontera = ASISTENTE_UMLC.costo_anual_consultas(
            LLM_FRONTERA_ENTRADA, LLM_FRONTERA_SALIDA
        )
        print(f"  consultas con gpt-4o-mini:     {economico:,.2f} USD por anio")
        print(f"  consultas con modelo frontera: {frontera:,.2f} USD por anio")


def main() -> None:
    """Imprime el modelo completo."""
    Reporte().imprimir()


if __name__ == "__main__":
    main()
