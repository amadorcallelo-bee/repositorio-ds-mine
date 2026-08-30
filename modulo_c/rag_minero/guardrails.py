"""Guardrails del asistente: rechazo fuera de dominio y verificacion de hechos.

Los dos mecanismos son deterministas y no llaman a ningun modelo, por dos razones. La
primera es de evaluacion: un guardrail que depende de un LLM no se puede probar con una
prueba unitaria ni calibrar con un conjunto de control sin gastar tokens. La segunda es de
seguridad: el mecanismo que impide inventar una especificacion no puede ser el mismo tipo
de componente que la inventa.

Puerta de dominio. Una pregunta entra si comparte vocabulario con el corpus: se mide la
fraccion de sus terminos de contenido que existen en los chunks indexados. Una receta de
paella no comparte ninguno; una pregunta por la presion hidraulica comparte casi todos. El
umbral no se fija a mano: `Calibrador` lo deriva del golden set y de las preguntas fuera de
dominio, y reporta cuantas de cada lado quedan del lado correcto. El recuperador puede
sumar un segundo criterio, el score del mejor chunk, cuando esta disponible.

Verificador de hechos. Toda cifra con unidad y todo codigo alfanumerico que aparezca en la
respuesta debe existir en los pasajes recuperados; si no, la respuesta se bloquea y se
reporta que hecho carece de respaldo. Es el «no inventa especificaciones» del enunciado
convertido en una regla que una prueba puede reproducir: preguntar por la presion maxima de
una Sandvik DL432, que el manual no cubre, produce una respuesta sin cifras o una
respuesta bloqueada, nunca una cifra plausible.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from rag_minero.chunking import PATRON_CODIGO, PATRON_FRENTE

# --- Vocabulario y puerta de dominio ---

PALABRAS_VACIAS: Final[frozenset[str]] = frozenset(
    {
    "a", "al", "ante", "aquel", "aquella", "aunque", "bajo", "cada", "como", "con", "cual",
    "cuales", "cuando", "cuanta", "cuantas", "cuanto", "cuantos", "de", "debe", "deben",
    "deber", "debes", "debo", "del", "desde", "donde", "e", "el", "en", "entre", "era", "eran",
    "es", "esa", "esas", "ese", "esos", "esta", "estan", "estar", "estas", "este", "estos",
    "fue", "fueron", "hace", "hacen", "hacer", "hacia", "hago", "haria", "hasta", "hay", "la",
    "las", "le", "les", "lo", "los", "mas", "me", "menos", "mi", "mis", "muy", "ni", "no",
    "nos", "nuestra", "nuestro", "o", "otra", "otro", "para", "pero", "poder", "por", "porque",
    "puede", "pueden", "puedes", "puedo", "que", "quien", "quienes", "se", "segun", "ser",
    "si", "sin", "sino", "sobre", "son", "su", "sus", "tan", "tanto", "te", "tener", "tiene",
    "tienen", "toda", "todas", "todo", "todos", "tras", "tu", "tus", "u", "un", "una", "unas",
    "unos", "y",
    }
)
LONGITUD_MINIMA: Final[int] = 4


def normalizar_termino(termino: str) -> str:
    """Minusculas y sin tildes, para que «presión» y «presion» sean el mismo termino."""
    sin_tildes = unicodedata.normalize("NFKD", termino)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def terminos_de_contenido(texto: str) -> list[str]:
    """Palabras y codigos con contenido: sin palabras vacias ni terminos de tres letras."""
    codigos = [normalizar_termino(c) for c in PATRON_CODIGO.findall(texto)]
    codigos += [normalizar_termino(f) for f in PATRON_FRENTE.findall(texto)]
    sin_codigos = PATRON_FRENTE.sub(" ", PATRON_CODIGO.sub(" ", texto))
    palabras = re.findall(r"[a-záéíóúñü]+", sin_codigos.lower())
    contenido = [
        normalizar_termino(p)
        for p in palabras
        if len(p) >= LONGITUD_MINIMA and normalizar_termino(p) not in PALABRAS_VACIAS
    ]
    return list(dict.fromkeys(codigos + contenido))


@dataclass(frozen=True)
class Vocabulario:
    """Los terminos de contenido del corpus indexado."""

    terminos: frozenset[str]

    @classmethod
    def desde_textos(cls, textos: Iterable[str]) -> Vocabulario:
        """Construye el vocabulario a partir de los textos de los chunks."""
        terminos: set[str] = set()
        for texto in textos:
            terminos.update(terminos_de_contenido(texto))
        return cls(frozenset(terminos))

    def cobertura(self, pregunta: str) -> float:
        """Fraccion de los terminos de contenido de la pregunta que existen en el corpus."""
        terminos = terminos_de_contenido(pregunta)
        if not terminos:
            return 0.0
        return sum(1 for t in terminos if t in self.terminos) / len(terminos)


@dataclass(frozen=True)
class Veredicto:
    """Resultado de la puerta de dominio."""

    aceptada: bool
    motivo: str
    cobertura: float
    mejor_score: float | None = None


class PuertaDeDominio:
    """Decide si una pregunta pertenece al dominio minero-operacional del corpus.

    Combina la cobertura lexica con, si se le entrega, el score del mejor chunk recuperado.
    La cobertura sola ya separa el conjunto de control; el score protege contra preguntas
    que usan vocabulario del dominio para pedir algo que no esta en los documentos.
    """

    def __init__(
        self,
        vocabulario: Vocabulario,
        cobertura_minima: float,
        score_minimo: float | None = None,
    ) -> None:
        if not 0.0 <= cobertura_minima <= 1.0:
            raise ValueError("cobertura_minima debe estar entre 0 y 1")
        self._vocabulario = vocabulario
        self.cobertura_minima = cobertura_minima
        self.score_minimo = score_minimo

    def evaluar(self, pregunta: str, mejor_score: float | None = None) -> Veredicto:
        """Acepta o rechaza la pregunta y explica por que."""
        cobertura = self._vocabulario.cobertura(pregunta)
        if cobertura < self.cobertura_minima:
            motivo = (
                f"fuera de dominio: solo el {cobertura:.0%} de los terminos de la pregunta "
                "aparece en la documentacion minera indexada"
            )
            return Veredicto(False, motivo, cobertura, mejor_score)
        if (
            self.score_minimo is not None
            and mejor_score is not None
            and mejor_score < self.score_minimo
        ):
            motivo = f"sin pasajes relevantes: el mejor score fue {mejor_score:.2f}"
            return Veredicto(False, motivo, cobertura, mejor_score)
        return Veredicto(True, "pregunta del dominio", cobertura, mejor_score)


@dataclass(frozen=True)
class Calibracion:
    """Umbral derivado de los conjuntos de control y cuanto los separa."""

    cobertura_minima: float
    aceptadas_del_dominio: int
    total_del_dominio: int
    rechazadas_fuera: int
    total_fuera: int

    @property
    def separa_perfectamente(self) -> bool:
        """Verdadero si ningun caso de control queda del lado equivocado."""
        return (
            self.aceptadas_del_dominio == self.total_del_dominio
            and self.rechazadas_fuera == self.total_fuera
        )


class Calibrador:
    """Deriva el umbral de cobertura de los dos conjuntos de control.

    Si las coberturas son separables, el umbral es el punto medio entre la peor pregunta
    del dominio y la mejor de fuera; si no lo son, se elige el que maximiza los aciertos.
    En ambos casos se reporta el resultado en vez de asumirlo.
    """

    def __init__(self, vocabulario: Vocabulario) -> None:
        self._vocabulario = vocabulario

    def calibrar(self, del_dominio: Sequence[str], fuera: Sequence[str]) -> Calibracion:
        """Calcula el umbral y cuenta los aciertos de cada lado."""
        if not del_dominio or not fuera:
            raise ValueError("se necesitan preguntas de los dos lados para calibrar")
        dentro = sorted(self._vocabulario.cobertura(p) for p in del_dominio)
        afuera = sorted(self._vocabulario.cobertura(p) for p in fuera)
        if afuera[-1] < dentro[0]:
            umbral = (afuera[-1] + dentro[0]) / 2
        else:
            candidatos = sorted(set(dentro + afuera))
            umbral = max(
                candidatos,
                key=lambda u: sum(d >= u for d in dentro) + sum(a < u for a in afuera),
            )
        return Calibracion(
            cobertura_minima=umbral,
            aceptadas_del_dominio=sum(d >= umbral for d in dentro),
            total_del_dominio=len(dentro),
            rechazadas_fuera=sum(a < umbral for a in afuera),
            total_fuera=len(afuera),
        )


# --- Verificador de hechos ---

#: Las citas `[DOC#estrategia#022]` se quitan antes de extraer hechos: el 022 es un
#: identificador de chunk, no una cifra que la respuesta afirme.
PATRON_CITA: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*#[^\]]*\]")
PATRON_CIFRA: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9#/-])(-?\d+(?:[.,]\d+)*)\s*"
    r"(%|°C|bar|RPM|rpm|m/s²|m/s2|L/min|g/t|kW|kN|kg|mm|min|h\b|m\b|L\b|días|dias|USD|oz|ppm"
    r"|unidades|juegos|turnos|registros|metros|segundos|minutos|horas)?"
)
FRASES_SIN_RESPALDO: Final[tuple[str, ...]] = (
    "no esta en la documentacion",
    "no figura en la documentacion",
    "no aparece en los documentos",
    "no cubre",
    "no dispongo de",
)


def _normalizar_numero(numero: str) -> str:
    """`2,280` y `2280` son el mismo numero; `9.21` conserva su decimal."""
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", numero):
        return numero.replace(",", "")
    return numero.replace(",", ".")


def extraer_hechos(texto: str) -> list[str]:
    """Cifras y codigos que el texto afirma, normalizados para compararlos."""
    texto = PATRON_CITA.sub(" ", texto)
    hechos = [_normalizar_numero(n) for n, _ in PATRON_CIFRA.findall(texto)]
    hechos += PATRON_CODIGO.findall(texto)
    hechos += PATRON_FRENTE.findall(texto)
    return list(dict.fromkeys(hechos))


@dataclass(frozen=True)
class Verificacion:
    """Resultado del verificador: que hechos tienen respaldo y cuales no."""

    aprobada: bool
    respaldados: tuple[str, ...]
    sin_respaldo: tuple[str, ...]
    declara_falta_de_respaldo: bool


class VerificadorDeHechos:
    """Bloquea una respuesta si afirma una cifra o un codigo que no esta en los pasajes."""

    def verificar(self, respuesta: str, contextos: Sequence[str]) -> Verificacion:
        """Contrasta cada hecho de la respuesta contra el texto de los pasajes recuperados."""
        contexto = " ".join(contextos)
        hechos_contexto = set(extraer_hechos(contexto))
        respaldados: list[str] = []
        sin_respaldo: list[str] = []
        for hecho in extraer_hechos(respuesta):
            destino = respaldados if hecho in hechos_contexto else sin_respaldo
            destino.append(hecho)
        declara = any(f in normalizar_termino(respuesta) for f in FRASES_SIN_RESPALDO)
        return Verificacion(
            aprobada=not sin_respaldo,
            respaldados=tuple(respaldados),
            sin_respaldo=tuple(sin_respaldo),
            declara_falta_de_respaldo=declara,
        )
