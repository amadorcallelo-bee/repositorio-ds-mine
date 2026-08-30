"""Evaluacion del asistente: golden set, ablacion de chunking y metricas RAGAS.

Hay dos evaluaciones distintas y conviene no confundirlas.

La ablacion no usa ningun modelo. Compara las variantes de chunking midiendo, para cada
pregunta del golden set, si los pasajes de referencia aparecen entre los chunks
recuperados. La precision de contexto se calcula con la misma formula que la variante sin
LLM de RAGAS —precision acumulada en cada posicion relevante, promediada sobre los
relevantes— y el recall cuenta que fraccion de las referencias quedo cubierta. Es gratis,
determinista y se corre en cada cambio del chunking; es la prueba de que la estrategia por
genero y elemento supera a la linea base, y si dejara de superarla, lo diria.

RAGAS si usa un modelo juez y por eso cuesta dinero. Se reportan las tres metricas que pide
el enunciado: `faithfulness` (la respuesta se sostiene en los pasajes), `answer_relevancy`
(la respuesta atiende la pregunta) y `context_precision` (los pasajes recuperados son los
que la respuesta esperada necesita). El juez y el generador son el mismo modelo, Sonnet 5,
y ese sesgo de autoevaluacion se declara en el README: lo compensan `context_precision`,
que juzga la recuperacion y no la respuesta, y el verificador de hechos, que no juzga nada.

Las metricas se inyectan como objetos con `ascore`, que es la interfaz de RAGAS 0.4, para
que la evaluacion se pruebe con jueces falsos y el juez real solo entre por
`EvaluadorRagas.con_databricks`. Toda llamada al juez pasa por el mismo presupuesto de
tokens que el asistente.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from rag_minero.asistente import Asistente, PresupuestoTokens, Respuesta, contextos_planos
from rag_minero.chunking import Trozador
from rag_minero.documentos import DocumentoTecnico
from rag_minero.errores import ConfiguracionError
from rag_minero.indice import AlmacenVectorial, tokenizar_lexico

# --- Golden set y preguntas de control ---


@dataclass(frozen=True)
class CasoOro:
    """Una pregunta con su respuesta esperada y los pasajes literales que la sostienen."""

    id: str
    documento: str
    tipo_pregunta: str
    pregunta: str
    respuesta_esperada: str
    contextos_referencia: tuple[str, ...]


@dataclass(frozen=True)
class GoldenSet:
    """Los casos de evaluacion, validados al cargar para fallar antes de gastar tokens."""

    casos: tuple[CasoOro, ...]

    @classmethod
    def cargar(cls, ruta: Path) -> GoldenSet:
        """Lee el JSON y valida que cada caso este completo y que los ids no se repitan."""
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        casos = [
            CasoOro(
                id=str(c.get("id", "")),
                documento=str(c.get("documento", "")),
                tipo_pregunta=str(c.get("tipo_pregunta", "")),
                pregunta=str(c.get("pregunta", "")),
                respuesta_esperada=str(c.get("respuesta_esperada", "")),
                contextos_referencia=tuple(str(x) for x in c.get("contextos_referencia", [])),
            )
            for c in datos.get("casos", [])
        ]
        if not casos:
            raise ConfiguracionError(str(ruta), "el golden set no tiene casos")
        ids = [c.id for c in casos]
        if len(ids) != len(set(ids)):
            raise ConfiguracionError(str(ruta), "hay ids repetidos en el golden set")
        for caso in casos:
            completo = bool(
                caso.id and caso.pregunta and caso.respuesta_esperada and caso.contextos_referencia
            )
            if not completo:
                raise ConfiguracionError(str(ruta), f"el caso {caso.id or '?'} esta incompleto")
        return cls(tuple(casos))

    @property
    def preguntas(self) -> list[str]:
        """Solo las preguntas, para calibrar la puerta de dominio."""
        return [c.pregunta for c in self.casos]


@dataclass(frozen=True)
class PreguntasControl:
    """Preguntas fuera de dominio y preguntas del dominio sin respaldo en los documentos."""

    fuera_de_dominio: tuple[str, ...]
    sin_respaldo_documental: tuple[str, ...]

    @classmethod
    def cargar(cls, ruta: Path) -> PreguntasControl:
        """Lee el JSON de control."""
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        fuera = tuple(str(p) for p in datos.get("fuera_de_dominio", []))
        sin_respaldo = tuple(str(p) for p in datos.get("sin_respaldo_documental", []))
        if not fuera:
            raise ConfiguracionError(str(ruta), "no hay preguntas fuera de dominio")
        return cls(fuera, sin_respaldo)


# --- Ablacion sin modelo ---

UMBRAL_CONTENCION: Final[float] = 0.6


def contiene_referencia(chunk: str, referencia: str, umbral: float = UMBRAL_CONTENCION) -> bool:
    """Verdadero si el chunk contiene al menos `umbral` de los tokens de la referencia.

    Se compara por tokens y no por subcadena porque el chunk rinde las filas como frases
    («PT-02 — Parametro: ...») y la referencia es la fila literal del PDF.
    """
    tokens_referencia = set(tokenizar_lexico(referencia))
    if not tokens_referencia:
        return False
    tokens_chunk = set(tokenizar_lexico(chunk))
    return len(tokens_referencia & tokens_chunk) / len(tokens_referencia) >= umbral


def precision_de_contexto(recuperados: Sequence[str], referencias: Sequence[str]) -> float:
    """Precision de contexto sin LLM, con la formula de RAGAS.

    `sum_k(precision@k * rel_k) / sum_k(rel_k)`, donde `rel_k` vale 1 si el chunk en la
    posicion `k` contiene alguna referencia. Premia que lo relevante quede arriba.
    """
    relevancias = [int(any(contiene_referencia(c, r) for r in referencias)) for c in recuperados]
    total = sum(relevancias)
    if total == 0:
        return 0.0
    acumulado = 0.0
    vistos = 0
    for posicion, relevante in enumerate(relevancias, start=1):
        vistos += relevante
        if relevante:
            acumulado += vistos / posicion
    return acumulado / total


def recall_de_referencias(recuperados: Sequence[str], referencias: Sequence[str]) -> float:
    """Fraccion de las referencias que aparece en algun chunk recuperado."""
    if not referencias:
        return 0.0
    encontradas = sum(1 for r in referencias if any(contiene_referencia(c, r) for c in recuperados))
    return encontradas / len(referencias)


@dataclass(frozen=True)
class ResultadoAblacion:
    """Metricas de recuperacion de un caso bajo una variante de chunking."""

    variante: str
    documento: str
    caso_id: str
    precision: float
    recall: float
    chunks_indexados: int


class Ablacion:
    """Corre el golden set contra cada variante de chunking sobre un almacen nuevo cada vez.

    La fabrica de almacenes se inyecta para que la ablacion corra en local con embeddings
    de prueba y en Databricks con los reales, sin cambiar el codigo.
    """

    def __init__(
        self,
        documentos: Sequence[DocumentoTecnico],
        golden: GoldenSet,
        fabrica_almacen: Callable[[], AlmacenVectorial],
        k: int = 6,
    ) -> None:
        if k < 1:
            raise ValueError("k debe ser al menos 1")
        self._documentos = documentos
        self._golden = golden
        self._fabrica = fabrica_almacen
        self._k = k

    def ejecutar(self, variantes: Sequence[Trozador]) -> list[ResultadoAblacion]:
        """Indexa cada variante, recupera para cada caso y mide precision y recall."""
        resultados: list[ResultadoAblacion] = []
        for variante in variantes:
            almacen = self._fabrica()
            chunks = variante.trocear(self._documentos)
            cantidad = almacen.indexar(chunks)
            try:
                for caso in self._golden.casos:
                    recuperados = almacen.buscar(caso.pregunta, k=self._k)
                    textos = [r.documento.page_content for r in recuperados]
                    resultados.append(
                        ResultadoAblacion(
                            variante=variante.nombre,
                            documento=caso.documento,
                            caso_id=caso.id,
                            precision=precision_de_contexto(textos, caso.contextos_referencia),
                            recall=recall_de_referencias(textos, caso.contextos_referencia),
                            chunks_indexados=cantidad,
                        )
                    )
            finally:
                almacen.vaciar()
        return resultados

    @staticmethod
    def resumen(resultados: Sequence[ResultadoAblacion]) -> dict[str, dict[str, float]]:
        """Precision y recall medios por variante."""
        salida: dict[str, dict[str, float]] = {}
        for variante in dict.fromkeys(r.variante for r in resultados):
            propios = [r for r in resultados if r.variante == variante]
            salida[variante] = {
                "precision": statistics.fmean(r.precision for r in propios),
                "recall": statistics.fmean(r.recall for r in propios),
                "chunks": float(propios[0].chunks_indexados),
            }
        return salida

    @staticmethod
    def tabla_markdown(resultados: Sequence[ResultadoAblacion]) -> str:
        """Tabla variante x documento con precision y recall medios, para el README."""
        variantes = list(dict.fromkeys(r.variante for r in resultados))
        documentos = list(dict.fromkeys(r.documento for r in resultados))
        lineas = [
            "| Variante | " + " | ".join(documentos) + " | Media |",
            "|---|" + "---|" * (len(documentos) + 1),
        ]
        for variante in variantes:
            celdas: list[str] = []
            for documento in documentos:
                propios = [
                    r for r in resultados if r.variante == variante and r.documento == documento
                ]
                celdas.append(_celda(propios))
            todos = [r for r in resultados if r.variante == variante]
            lineas.append(f"| {variante} | " + " | ".join(celdas) + f" | {_celda(todos)} |")
        return "\n".join(lineas)


def _celda(resultados: Sequence[ResultadoAblacion]) -> str:
    if not resultados:
        return "-"
    precision = statistics.fmean(r.precision for r in resultados)
    recall = statistics.fmean(r.recall for r in resultados)
    return f"P {precision:.2f} / R {recall:.2f}"


# --- RAGAS ---


class Metrica(Protocol):
    """Lo que la evaluacion necesita de una metrica de RAGAS 0.4: un `ascore` asincrono."""

    async def ascore(self, **kwargs: Any) -> Any:
        """Puntua una muestra y devuelve un resultado con `.value`."""
        ...


class _MetricaRagas:
    """Adapta una metrica real de RAGAS, cuya firma es posicional, al contrato por kwargs."""

    def __init__(self, metrica: Any) -> None:
        self._metrica = metrica

    async def ascore(self, **kwargs: Any) -> Any:
        """Delega en la metrica real."""
        return await self._metrica.ascore(**kwargs)


@dataclass(frozen=True)
class MetricasCaso:
    """Las tres metricas de un caso, o `None` si el asistente no respondio."""

    caso_id: str
    documento: str
    respuesta: Respuesta
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None


#: Estimacion conservadora de tokens por llamada del juez: pasajes mas pregunta mas
#: respuesta mas la salida estructurada que RAGAS le pide.
TOKENS_POR_METRICA: Final[int] = 9000


class EvaluadorRagas:
    """Responde el golden set con el asistente y puntua cada respuesta con RAGAS."""

    def __init__(
        self,
        asistente: Asistente,
        faithfulness: Metrica,
        answer_relevancy: Metrica,
        context_precision: Metrica,
        presupuesto: PresupuestoTokens | None = None,
        tokens_por_metrica: int = TOKENS_POR_METRICA,
    ) -> None:
        self._asistente = asistente
        self._metricas = {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_precision": context_precision,
        }
        self._presupuesto = presupuesto
        self._tokens_por_metrica = tokens_por_metrica

    @classmethod
    def con_databricks(
        cls,
        asistente: Asistente,
        host: str,
        token: str,
        modelo_juez: str = "databricks-claude-sonnet-5",
        modelo_embeddings: str = "databricks-qwen3-embedding-0-6b",
        presupuesto: PresupuestoTokens | None = None,
    ) -> EvaluadorRagas:
        """Juez y embeddings de RAGAS sobre Foundation Model APIs, que expone la API de OpenAI."""
        from openai import AsyncOpenAI
        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, Faithfulness

        cliente = AsyncOpenAI(base_url=f"{host.rstrip('/')}/serving-endpoints", api_key=token)
        juez = llm_factory(modelo_juez, provider="openai", client=cliente)
        embeddings: Any = embedding_factory(provider="openai", model=modelo_embeddings, client=cliente)
        return cls(
            asistente,
            faithfulness=_MetricaRagas(Faithfulness(llm=juez)),
            answer_relevancy=_MetricaRagas(AnswerRelevancy(llm=juez, embeddings=embeddings)),
            context_precision=_MetricaRagas(ContextPrecision(llm=juez)),
            presupuesto=presupuesto,
        )

    def evaluar(self, golden: GoldenSet) -> list[MetricasCaso]:
        """Responde y puntua cada caso; un caso rechazado o bloqueado queda sin metricas."""
        return [self._evaluar_caso(caso) for caso in golden.casos]

    def _evaluar_caso(self, caso: CasoOro) -> MetricasCaso:
        respuesta = self._asistente.responder(caso.pregunta)
        if not respuesta.exitosa:
            return MetricasCaso(caso.id, caso.documento, respuesta, None, None, None)
        if self._presupuesto is not None:
            self._presupuesto.reservar(self._tokens_por_metrica * len(self._metricas))
        contextos = list(contextos_planos(respuesta))
        valores = asyncio.run(self._puntuar(caso, respuesta, contextos))
        if self._presupuesto is not None:
            for _ in self._metricas:
                self._presupuesto.registrar(self._tokens_por_metrica, 0)
        return MetricasCaso(
            caso.id,
            caso.documento,
            respuesta,
            valores["faithfulness"],
            valores["answer_relevancy"],
            valores["context_precision"],
        )

    async def _puntuar(
        self, caso: CasoOro, respuesta: Respuesta, contextos: list[str]
    ) -> dict[str, float]:
        faithfulness = await self._metricas["faithfulness"].ascore(
            user_input=caso.pregunta, response=respuesta.texto, retrieved_contexts=contextos
        )
        relevancy = await self._metricas["answer_relevancy"].ascore(
            user_input=caso.pregunta, response=respuesta.texto
        )
        precision = await self._metricas["context_precision"].ascore(
            user_input=caso.pregunta,
            reference=caso.respuesta_esperada,
            retrieved_contexts=contextos,
        )
        return {
            "faithfulness": float(faithfulness.value),
            "answer_relevancy": float(relevancy.value),
            "context_precision": float(precision.value),
        }

    @staticmethod
    def resumen(resultados: Sequence[MetricasCaso]) -> dict[str, float]:
        """Media de cada metrica sobre los casos que tuvieron respuesta."""
        salida: dict[str, float] = {}
        for nombre in ("faithfulness", "answer_relevancy", "context_precision"):
            valores = [getattr(r, nombre) for r in resultados if getattr(r, nombre) is not None]
            salida[nombre] = statistics.fmean(valores) if valores else 0.0
        salida["respondidas"] = float(sum(1 for r in resultados if r.respuesta.exitosa))
        return salida

    @staticmethod
    def tabla_markdown(resultados: Sequence[MetricasCaso]) -> str:
        """Tabla por caso, para el README."""
        lineas = [
            "| Caso | Documento | Faithfulness | Answer relevancy | Context precision | Estado |",
            "|---|---|---|---|---|---|",
        ]
        for r in resultados:
            estado = "respondida" if r.respuesta.exitosa else r.respuesta.motivo
            lineas.append(
                f"| {r.caso_id} | {r.documento} | {_num(r.faithfulness)} | "
                f"{_num(r.answer_relevancy)} | {_num(r.context_precision)} | {estado} |"
            )
        return "\n".join(lineas)


def _num(valor: float | None) -> str:
    return "-" if valor is None else f"{valor:.2f}"
