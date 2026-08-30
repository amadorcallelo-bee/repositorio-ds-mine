"""Un modelo de embeddings de juguete para las pruebas del almacen local.

`DeterministicFakeEmbedding` de LangChain es reproducible pero no significa nada: dos
textos parecidos reciben vectores independientes. Para probar que la fusion hibrida y los
filtros hacen lo que se argumenta hace falta un embedding donde «presion hidraulica» y
«presion hidraulica maxima» esten cerca. Este lo consigue proyectando cada termino
normalizado a una dimension por hash y sumando: es una bolsa de palabras con vectores de
tamano fijo, suficiente para que la busqueda densa recupere lo que comparte vocabulario.
"""

from __future__ import annotations

import hashlib
import math

from langchain_core.embeddings import Embeddings

from rag_minero.guardrails import terminos_de_contenido


class EmbeddingsPorTerminos(Embeddings):
    """Bolsa de terminos proyectada por hash a un vector unitario de `dimension` entradas."""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def _vector(self, texto: str) -> list[float]:
        vector = [0.0] * self.dimension
        for termino in terminos_de_contenido(texto):
            indice = int(hashlib.sha1(termino.encode()).hexdigest(), 16) % self.dimension
            vector[indice] += 1.0
        norma = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norma for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectores de una lista de textos."""
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """Vector de una consulta."""
        return self._vector(text)
