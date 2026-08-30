"""El asistente: puerta de dominio, recuperacion hibrida, generacion con citas y verificacion.

La cadena es deliberadamente corta y cada eslabon es un objeto que se prueba solo:

1. La puerta de dominio rechaza antes de recuperar, con la cobertura lexica de la pregunta.
2. El almacen devuelve los `k` chunks mas relevantes; el mejor score denso vuelve a pasar
   por la puerta, para rechazar preguntas con vocabulario minero que no tienen pasaje.
3. El modelo responde solo con los pasajes, citando el identificador de cada chunk, y con
   la instruccion explicita de decir que algo no esta en la documentacion antes que
   completarlo.
4. El verificador contrasta cada cifra y cada codigo de la respuesta con los pasajes; si
   alguno no tiene respaldo, la respuesta se bloquea y se conserva el borrador para
   auditoria.

El modelo se inyecta como `BaseChatModel` de LangChain. En la demo es el endpoint que
nombra `RAG_MODELO_GENERADOR` a traves de `ChatDatabricks`, con temperatura cero porque un
asistente de procedimientos de seguridad no debe variar su respuesta entre dos consultas
iguales; en las pruebas es un modelo falso con respuestas fijas.

Dos decisiones existen por los modelos que razonan antes de responder (DeepSeek V4 Flash, el
generador de la corrida final). La primera es el tope de salida: un modelo de razonamiento
gasta cientos de tokens pensando y, si el tope se agota ahi, devuelve una cadena vacia con
`finish_reason="length"`; se midio con la pregunta cruzada del golden set: 439 tokens de
salida para cuatro frases visibles, y con un tope de 200 la respuesta llego vacia. La
segunda es que el texto se extrae solo de los bloques `text` del mensaje, porque el
razonamiento puede llegar como bloque aparte, y una respuesta vacia se trata como fallo
declarado y no como respuesta valida.

Todo consumo de tokens pasa por `PresupuestoTokens`, que se niega a llamar al modelo si la
estimacion de la siguiente llamada superaria el tope. Es la cuenta que protege los 40 USD
del trial: el costo no se controla mirando la factura despues sino contando antes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from rag_minero.errores import PresupuestoExcedidoError
from rag_minero.guardrails import PuertaDeDominio, Veredicto, Verificacion, VerificadorDeHechos
from rag_minero.indice import AlmacenVectorial, Resultado

INSTRUCCIONES: Final[str] = """Eres el asistente de documentacion tecnica de la Unidad Minera La
Cornisa (UMLC). Respondes preguntas de operadores, supervisores, geologos y mantenimiento
sobre procedimientos, informes geologicos y manuales de equipo.

Reglas, en orden de prioridad:
1. Responde unicamente con la informacion de los PASAJES. No uses conocimiento propio sobre
   equipos, leyes de mineral ni procedimientos.
2. Si los pasajes no contienen la respuesta, di exactamente: "No esta en la documentacion
   disponible." y explica en una frase que documento haria falta. No completes con cifras
   plausibles: una especificacion inventada puede causar un accidente.
3. Cita el identificador del pasaje que respalda cada afirmacion, entre corchetes, tal como
   aparece: [PET-PERF-007#procedimiento#022].
4. Conserva las cifras, unidades y codigos exactamente como estan en los pasajes.
5. Si dos pasajes se contradicen, dilo y cita ambos.
6. Responde en espanol, en pocas frases, sin preambulos."""

PLANTILLA: Final[ChatPromptTemplate] = ChatPromptTemplate.from_messages(
    [
        ("system", INSTRUCCIONES),
        ("human", "PASAJES:\n{contexto}\n\nPREGUNTA: {pregunta}"),
    ]
)

#: Aproximacion de caracteres por token para estimar antes de llamar; se sobreestima a
#: proposito, porque la cuenta protege un presupuesto y no una metrica.
CARACTERES_POR_TOKEN: Final[int] = 3
#: Tope de tokens de salida por llamada. Cubre el razonamiento previo de un modelo que piensa
#: antes de escribir (ver el docstring del modulo); con 600 la pregunta cruzada quedaba justa.
SALIDA_MAXIMA: Final[int] = 1500
MENSAJE_RECHAZO: Final[str] = (
    "Solo puedo responder preguntas sobre la documentacion tecnica minera de la UMLC "
    "(procedimientos, informes geologicos y manuales de equipo)."
)
MENSAJE_BLOQUEO: Final[str] = (
    "La respuesta generada afirmaba datos que no estan respaldados por la documentacion "
    "recuperada y se bloqueo por seguridad. Consulta el documento original."
)
MENSAJE_VACIO: Final[str] = (
    "El modelo no produjo una respuesta (agoto su salida o devolvio un mensaje vacio). "
    "Consulta el documento original o repite la pregunta."
)
MOTIVO_VACIO: Final[str] = "respuesta vacia: el modelo no devolvio texto"
MOTIVO_TRUNCADA: Final[str] = "respondida, pero la salida se corto en el tope de tokens"


@dataclass
class PresupuestoTokens:
    """Tope de tokens de una sesion, con reserva antes de cada llamada.

    `reservar` se llama con la estimacion de la siguiente llamada y falla si la agotaria;
    `registrar` anota el consumo real que reporto el modelo. Si el modelo no reporta uso,
    se registra la estimacion, que es conservadora.
    """

    maximo: int
    consumidos: int = 0
    llamadas: int = field(default=0, init=False)

    def reservar(self, estimado: int) -> None:
        """Falla antes de la llamada si el consumo acumulado mas el estimado supera el tope."""
        if self.consumidos + estimado > self.maximo:
            raise PresupuestoExcedidoError(self.consumidos + estimado, self.maximo)

    def registrar(self, entrada: int, salida: int) -> None:
        """Anota el consumo real de una llamada."""
        self.consumidos += entrada + salida
        self.llamadas += 1


@dataclass(frozen=True)
class Respuesta:
    """Lo que el asistente devuelve: el texto final y toda la evidencia de como llego a el."""

    pregunta: str
    texto: str
    rechazada: bool
    bloqueada: bool
    motivo: str
    fuentes: tuple[str, ...]
    contextos: tuple[str, ...]
    veredicto: Veredicto
    verificacion: Verificacion | None = None
    borrador: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0

    @property
    def exitosa(self) -> bool:
        """Verdadero si hubo respuesta y paso la verificacion."""
        return not self.rechazada and not self.bloqueada


def _texto_de(mensaje: AIMessage) -> str:
    """Solo los bloques `text` del mensaje; el razonamiento, venga como venga, se descarta.

    Un modelo que razona puede entregar el contenido como cadena, como lista de bloques
    (`{"type": "reasoning", ...}` delante de `{"type": "text", ...}`) o como esa misma lista
    serializada en JSON. Una cadena que no es JSON de bloques se devuelve tal cual, asi que
    una respuesta que empieza por una cita entre corchetes no se confunde con una lista.
    """
    contenido: str | list[str | dict[str, Any]] = mensaje.content
    if isinstance(contenido, str):
        bloques = _bloques_desde_json(contenido)
        if bloques is None:
            return contenido
        contenido = bloques
    partes: list[str] = []
    for parte in contenido:
        if isinstance(parte, str):
            partes.append(parte)
        elif parte.get("type", "text") == "text":
            partes.append(str(parte.get("text", "")))
    return "".join(partes)


def _bloques_desde_json(texto: str) -> list[str | dict[str, Any]] | None:
    """La lista de bloques si `texto` es su serializacion JSON; `None` en cualquier otro caso."""
    recortado = texto.strip()
    if not recortado.startswith("["):
        return None
    try:
        candidato = json.loads(recortado)
    except json.JSONDecodeError:
        return None
    if not isinstance(candidato, list) or not candidato:
        return None
    if not all(isinstance(b, dict) and "type" in b for b in candidato):
        return None
    return list(candidato)


def _truncada(mensaje: AIMessage) -> bool:
    """Verdadero si el proveedor reporto que la salida se corto por el tope de tokens."""
    return str(mensaje.response_metadata.get("finish_reason", "")).lower() == "length"


def _uso_de(mensaje: AIMessage, estimado_entrada: int, estimado_salida: int) -> tuple[int, int]:
    uso = mensaje.usage_metadata
    if uso is None:
        return estimado_entrada, estimado_salida
    entrada = int(uso.get("input_tokens", estimado_entrada))
    salida = int(uso.get("output_tokens", estimado_salida))
    return entrada, salida


class Asistente:
    """Orquesta puerta, almacen, modelo y verificador para responder una pregunta."""

    def __init__(
        self,
        almacen: AlmacenVectorial,
        modelo: BaseChatModel,
        puerta: PuertaDeDominio,
        verificador: VerificadorDeHechos | None = None,
        k: int = 6,
        presupuesto: PresupuestoTokens | None = None,
        salida_maxima: int = SALIDA_MAXIMA,
    ) -> None:
        if k < 1:
            raise ValueError("k debe ser al menos 1")
        if salida_maxima < 1:
            raise ValueError("salida_maxima debe ser al menos 1")
        self._almacen = almacen
        self._modelo = modelo
        self._puerta = puerta
        self._verificador = verificador or VerificadorDeHechos()
        self._k = k
        self._presupuesto = presupuesto
        self._salida_maxima = salida_maxima

    def recuperar(self, pregunta: str) -> list[Resultado]:
        """Los pasajes que el asistente usaria, sin llamar al modelo."""
        return self._almacen.buscar(pregunta, k=self._k)

    def responder(self, pregunta: str) -> Respuesta:
        """Responde o rechaza la pregunta y devuelve toda la evidencia del proceso."""
        veredicto = self._puerta.evaluar(pregunta)
        if not veredicto.aceptada:
            return self._rechazo(pregunta, veredicto)

        resultados = self.recuperar(pregunta)
        scores = [r.score_denso for r in resultados if r.score_denso is not None]
        veredicto = self._puerta.evaluar(pregunta, max(scores) if scores else None)
        if not veredicto.aceptada or not resultados:
            return self._rechazo(pregunta, veredicto)

        contextos = tuple(f"[{r.chunk_id}] {r.documento.page_content}" for r in resultados)
        entrada = PLANTILLA.format_messages(contexto="\n\n".join(contextos), pregunta=pregunta)
        estimado_entrada = sum(len(str(m.content)) for m in entrada) // CARACTERES_POR_TOKEN
        if self._presupuesto is not None:
            self._presupuesto.reservar(estimado_entrada + self._salida_maxima)

        mensaje = self._modelo.invoke(entrada)
        if not isinstance(mensaje, AIMessage):
            raise TypeError("el modelo debe devolver un AIMessage")
        borrador = _texto_de(mensaje).strip()
        tokens_entrada, tokens_salida = _uso_de(mensaje, estimado_entrada, self._salida_maxima)
        if self._presupuesto is not None:
            self._presupuesto.registrar(tokens_entrada, tokens_salida)
        if not borrador:
            return Respuesta(
                pregunta=pregunta,
                texto=MENSAJE_VACIO,
                rechazada=False,
                bloqueada=True,
                motivo=MOTIVO_VACIO,
                fuentes=tuple(r.chunk_id for r in resultados),
                contextos=contextos,
                veredicto=veredicto,
                tokens_entrada=tokens_entrada,
                tokens_salida=tokens_salida,
            )

        verificacion = self._verificador.verificar(
            borrador, [r.documento.page_content for r in resultados]
        )
        bloqueada = not verificacion.aprobada
        if bloqueada:
            motivo = "sin respaldo: " + ", ".join(verificacion.sin_respaldo)
        elif _truncada(mensaje):
            motivo = MOTIVO_TRUNCADA
        else:
            motivo = "respondida"
        return Respuesta(
            pregunta=pregunta,
            texto=MENSAJE_BLOQUEO if bloqueada else borrador,
            rechazada=False,
            bloqueada=bloqueada,
            motivo=motivo,
            fuentes=tuple(r.chunk_id for r in resultados),
            contextos=contextos,
            veredicto=veredicto,
            verificacion=verificacion,
            borrador=borrador,
            tokens_entrada=tokens_entrada,
            tokens_salida=tokens_salida,
        )

    @staticmethod
    def _rechazo(pregunta: str, veredicto: Veredicto) -> Respuesta:
        return Respuesta(
            pregunta=pregunta,
            texto=MENSAJE_RECHAZO,
            rechazada=True,
            bloqueada=False,
            motivo=veredicto.motivo,
            fuentes=(),
            contextos=(),
            veredicto=veredicto,
        )


def crear_modelo_databricks(
    endpoint: str = "databricks-claude-sonnet-5", salida_maxima: int = SALIDA_MAXIMA
) -> BaseChatModel:
    """`ChatDatabricks` sobre un endpoint de Foundation Model APIs, con temperatura cero.

    `salida_maxima` es el mismo tope que reserva el `Asistente`: si difieren, el presupuesto
    cuenta una cosa y el modelo puede gastar otra.
    """
    from databricks_langchain import ChatDatabricks

    modelo: BaseChatModel = ChatDatabricks(
        endpoint=endpoint, temperature=0.0, max_tokens=salida_maxima
    )
    return modelo


def contextos_planos(respuesta: Respuesta) -> Sequence[str]:
    """Los pasajes sin el prefijo de identificador, como los espera RAGAS."""
    return [c.split("] ", 1)[1] if "] " in c else c for c in respuesta.contextos]
