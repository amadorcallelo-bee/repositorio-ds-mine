"""Estrategias de chunking por genero de documento y por tipo de elemento.

La decision central del Ejercicio C-2 vive aqui. El genero del documento elige la
estrategia, porque decide que elementos existen: un procedimiento tiene pasos y criterios
de parada, un informe tiene prosa argumentativa y tablas comparativas, un manual tiene
especificaciones y diagnosticos. Dentro de cada estrategia, el tipo de elemento fija la
unidad de recuperacion, porque es lo que decide como pregunta quien usa el documento:

- Procedimiento: quien pregunta busca «que hago si...». La unidad es el paso o la fila de
  tabla con su codigo, porque partir una fila separa la condicion de la accion.
- Informe: quien pregunta compara y cruza secciones. La prosa va por seccion con
  solapamiento y las tablas van enteras, porque trocear una tabla por filas mata la
  pregunta comparativa («que frente tuvo mayor ley»).
- Manual: quien pregunta busca un hecho atomico por codigo. La unidad es la fila rendida
  como frase («Presion hidraulica maxima: 280 bar»), y la advertencia es indivisible.

Cada chunk lleva delante el codigo del documento y la seccion, porque una fila suelta como
«PT-02 | 160-200 bar» no significa nada sin saber que es una verificacion pre-turno del
PET-PERF-007. Y cada chunk lleva en sus metadatos los codigos alfanumericos y los frentes
que menciona, porque en mina se pregunta por codigo y la busqueda lexica los necesita como
campo exacto.

Se incluyen dos estrategias de control, una de tamano fijo y otra que solo respeta el genero
cortando por seccion, para que la ablacion del README mida contra ellas y la decision quede
demostrada y no argumentada. La linea base usa el splitter recursivo de LangChain, que es lo
que usaria cualquiera que no mirara los documentos.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from typing import ClassVar, Final

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_minero.documentos import (
    DocumentoTecnico,
    Elemento,
    Fila,
    TipoDocumento,
    TipoElemento,
    renderizar_tabla,
)

# --- Tipos del dominio ---

#: Valor escalar admitido como metadato por Chroma y por Databricks Vector Search. Las listas
#: se serializan con punto y coma porque ninguno de los dos acepta listas en filtros.
Escalar = str | int | bool
Metadatos = dict[str, Escalar]

#: Las alternativas mas especificas van primero: la generica `X-YYYY-NN` capturaria
#: `F-PERF-007` y dejaria fuera el sufijo `-A` del formulario.
PATRON_CODIGO: Final[re.Pattern[str]] = re.compile(
    r"\b(?:F-PERF-\d{3}-[AB]|AC-L8-[A-Z]{2}-[A-Z0-9]{3,4}|MANT-[0-9A-Z]+(?:-[A-Z]+)?"
    r"|OREAS-\d{2}[A-Z]|OPUS-[A-Z0-9]+(?:-[A-Z0-9]+)*|[A-Z]{1,4}-[A-Z]{2,6}-\d{2,3}"
    r"|(?:PT|CP|R|ROL)-[A-Z]*-?\d{2}|[A-Z]{2}-\d{2})\b"
)
PATRON_FRENTE: Final[re.Pattern[str]] = re.compile(r"\bFR-[A-Z]\d(?:-\d{2})?\b")
SEPARADOR_LISTA: Final[str] = ";"


def extraer_codigos(texto: str) -> list[str]:
    """Codigos alfanumericos del texto, sin repetir y en orden de aparicion."""
    return list(dict.fromkeys(PATRON_CODIGO.findall(texto)))


def extraer_frentes(texto: str) -> list[str]:
    """Identificadores de frente (`FR-S2-03`) que menciona el texto."""
    return list(dict.fromkeys(PATRON_FRENTE.findall(texto)))


def renderizar_fila(cabecera: Fila, fila: Fila) -> str:
    """Una fila como frase autocontenida: la primera celda como sujeto y el resto etiquetado.

    «PT-02 — Parametro: Presion hidraulica en frio; Rango Aceptable: 160-200 bar; ...» se
    entiende sin la tabla; «PT-02 | Presion hidraulica en frio | 160-200 bar» no.
    """
    if not cabecera or len(cabecera) != len(fila):
        return " | ".join(fila)
    pares = zip(cabecera[1:], fila[1:], strict=True)
    resto = "; ".join(f"{titulo}: {valor}" for titulo, valor in pares)
    return f"{fila[0]} — {resto}" if resto else fila[0]


class EstrategiaChunking(ABC):
    """Contrato de una estrategia: un documento entra, una lista de chunks con metadatos sale.

    Las subclases solo deciden la unidad; la identidad del chunk, el prefijo de contexto y
    los metadatos comunes los pone la clase base, para que las tres estrategias produzcan
    chunks comparables en la ablacion.
    """

    nombre: ClassVar[str]

    def trocear(self, documento: DocumentoTecnico) -> list[Document]:
        """Chunks del documento, numerados y con metadatos completos."""
        chunks: list[Document] = []
        for indice, (elemento, cuerpo, extra) in enumerate(self._unidades(documento)):
            texto = f"[{documento.codigo} · {elemento.seccion}] {cuerpo}"
            identificador = f"{documento.codigo}#{self.nombre}#{indice:03d}"
            metadatos = self._metadatos(documento, elemento, texto)
            metadatos.update(extra)
            metadatos["chunk_id"] = identificador
            chunks.append(Document(id=identificador, page_content=texto, metadata=metadatos))
        return chunks

    def trocear_todos(self, documentos: Iterable[DocumentoTecnico]) -> list[Document]:
        """Chunks de varios documentos, en orden."""
        return [chunk for documento in documentos for chunk in self.trocear(documento)]

    @abstractmethod
    def _unidades(self, documento: DocumentoTecnico) -> Iterator[tuple[Elemento, str, Metadatos]]:
        """Cada unidad de recuperacion: el elemento de origen, su texto y metadatos propios."""

    def _metadatos(self, documento: DocumentoTecnico, elemento: Elemento, texto: str) -> Metadatos:
        return {
            "documento": documento.codigo,
            "genero": documento.tipo.value,
            "titulo_documento": documento.titulo,
            "version": documento.version,
            "clasificacion": documento.clasificacion,
            "vigente": True,
            "seccion": elemento.seccion,
            "elemento": elemento.tipo.value,
            "pagina": elemento.pagina,
            "estrategia": self.nombre,
            "codigos": SEPARADOR_LISTA.join(extraer_codigos(texto)),
            "frentes": SEPARADOR_LISTA.join(extraer_frentes(texto)),
        }


def _prosa_troceada(elemento: Elemento, tamano: int, solapamiento: int) -> Iterator[str]:
    """Prosa entera si cabe en `tamano`; si no, trozos solapados que no parten oraciones."""
    if len(elemento.texto) <= tamano:
        yield elemento.texto
        return
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=tamano, chunk_overlap=solapamiento, separators=[". ", "; ", ", ", " "]
    )
    yield from splitter.split_text(elemento.texto)


class ChunkingProcedimiento(EstrategiaChunking):
    """PET: un chunk por paso y un chunk por fila de tabla, con su codigo delante.

    Se descarto agrupar la tabla entera: quien opera pregunta por una condicion concreta y
    la fila es la unidad que junta condicion, umbral y accion.
    """

    nombre = "procedimiento"

    def _unidades(self, documento: DocumentoTecnico) -> Iterator[tuple[Elemento, str, Metadatos]]:
        for elemento in documento.elementos:
            if elemento.tipo is TipoElemento.ENCABEZADO:
                continue
            if elemento.tipo is TipoElemento.TABLA:
                for fila in elemento.filas:
                    yield elemento, renderizar_fila(elemento.cabecera, fila), {"fila": fila[0]}
            elif elemento.tipo is TipoElemento.PASO:
                yield elemento, f"{elemento.titulo}. {elemento.texto}", {"paso": elemento.titulo}
            else:
                yield elemento, elemento.texto, {}


class ChunkingInforme(EstrategiaChunking):
    """Informe: prosa por seccion con solapamiento y tablas enteras.

    La tabla entera conserva la fila TOTAL junto a las filas que suma, y la prosa por
    seccion conserva la referencia cruzada (el tramo 320-380 m aparece en el resumen, en la
    geologia estructural y en la recomendacion R-01, y los tres chunks quedan etiquetados
    con el mismo frente).
    """

    nombre = "informe"
    tamano: ClassVar[int] = 900
    solapamiento: ClassVar[int] = 150

    def _unidades(self, documento: DocumentoTecnico) -> Iterator[tuple[Elemento, str, Metadatos]]:
        for elemento in documento.elementos:
            if elemento.tipo is TipoElemento.ENCABEZADO:
                continue
            if elemento.tipo is TipoElemento.TABLA:
                cuerpo = renderizar_tabla(elemento.cabecera, elemento.filas)
                yield elemento, cuerpo, {"filas": len(elemento.filas)}
            else:
                for trozo in _prosa_troceada(elemento, self.tamano, self.solapamiento):
                    yield elemento, trozo, {}


class ChunkingManual(EstrategiaChunking):
    """Manual: una fila por chunk como hecho atomico, y la advertencia indivisible.

    La advertencia lleva `prioridad=alta` para que el recuperador pueda reforzarla: una
    pregunta sobre la sonda XRF debe traer el aviso de que -1 no es ley cero antes que la
    fila de calibracion.
    """

    nombre = "manual"

    def _unidades(self, documento: DocumentoTecnico) -> Iterator[tuple[Elemento, str, Metadatos]]:
        for elemento in documento.elementos:
            if elemento.tipo is TipoElemento.ENCABEZADO:
                continue
            if elemento.tipo is TipoElemento.TABLA:
                for fila in elemento.filas:
                    yield elemento, renderizar_fila(elemento.cabecera, fila), {"fila": fila[0]}
            elif elemento.tipo is TipoElemento.ADVERTENCIA:
                yield elemento, elemento.texto, {"prioridad": "alta"}
            else:
                yield elemento, elemento.texto, {}


class ChunkingPorSeccion(EstrategiaChunking):
    """Control «solo genero»: respeta las secciones del documento pero ignora el elemento.

    Existe para la ablacion. Si esta estrategia igualara a la de genero mas elemento, el
    argumento de que el tipo de elemento importa quedaria refutado.
    """

    nombre = "seccion"
    tamano: ClassVar[int] = 1500
    solapamiento: ClassVar[int] = 200

    def _unidades(self, documento: DocumentoTecnico) -> Iterator[tuple[Elemento, str, Metadatos]]:
        for seccion, elementos in _por_seccion(documento.elementos):
            cuerpo = " ".join(e.texto for e in elementos if e.tipo is not TipoElemento.ENCABEZADO)
            representante = Elemento(
                tipo=TipoElemento.PROSA,
                texto=cuerpo,
                seccion=seccion,
                pagina=elementos[0].pagina,
                orden=elementos[0].orden,
            )
            for trozo in _prosa_troceada(representante, self.tamano, self.solapamiento):
                yield representante, trozo, {}


class ChunkingTamanoFijo(EstrategiaChunking):
    """Linea base: el texto completo troceado a tamano fijo con solapamiento.

    Es lo que produce cualquier tutorial de RAG y lo que la ablacion tiene que superar.
    """

    nombre = "fijo"
    tamano: ClassVar[int] = 800
    solapamiento: ClassVar[int] = 120

    def _unidades(self, documento: DocumentoTecnico) -> Iterator[tuple[Elemento, str, Metadatos]]:
        texto = "\n".join(e.texto for e in documento.elementos)
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.tamano, chunk_overlap=self.solapamiento
        )
        representante = Elemento(
            tipo=TipoElemento.PROSA, texto=texto, seccion="documento completo", pagina=1, orden=0
        )
        for trozo in splitter.split_text(texto):
            yield representante, trozo, {}


def _por_seccion(elementos: Sequence[Elemento]) -> Iterator[tuple[str, list[Elemento]]]:
    actual: list[Elemento] = []
    for elemento in elementos:
        if actual and elemento.seccion != actual[0].seccion:
            yield actual[0].seccion, actual
            actual = []
        actual.append(elemento)
    if actual:
        yield actual[0].seccion, actual


class Trozador:
    """Enruta cada documento a su estrategia por genero.

    Las variantes de control (`solo_genero`, `tamano_fijo`) aplican la misma estrategia a
    todos los generos, que es justamente lo que la ablacion quiere medir.
    """

    def __init__(self, estrategias: dict[TipoDocumento, EstrategiaChunking]) -> None:
        self._estrategias = estrategias

    @classmethod
    def por_genero_y_elemento(cls) -> Trozador:
        """La configuracion propuesta: una estrategia distinta por genero."""
        return cls(
            {
                TipoDocumento.PROCEDIMIENTO: ChunkingProcedimiento(),
                TipoDocumento.INFORME: ChunkingInforme(),
                TipoDocumento.MANUAL: ChunkingManual(),
            }
        )

    @classmethod
    def solo_genero(cls) -> Trozador:
        """Control: corta por seccion en todos los generos."""
        return cls(dict.fromkeys(TipoDocumento, ChunkingPorSeccion()))

    @classmethod
    def tamano_fijo(cls) -> Trozador:
        """Linea base: tamano fijo en todos los generos."""
        return cls(dict.fromkeys(TipoDocumento, ChunkingTamanoFijo()))

    @property
    def nombre(self) -> str:
        """Nombre de la variante, para etiquetar la ablacion."""
        nombres = sorted({e.nombre for e in self._estrategias.values()})
        return "+".join(nombres)

    def trocear(self, documentos: Iterable[DocumentoTecnico]) -> list[Document]:
        """Chunks de todos los documentos, cada uno con la estrategia de su genero."""
        return [
            chunk
            for documento in documentos
            for chunk in self._estrategias[documento.tipo].trocear(documento)
        ]
