"""Almacenes vectoriales: Databricks Vector Search como destino y Chroma con BM25 en local.

Los dos implementan el mismo contrato, `AlmacenVectorial`, y consumen los mismos chunks.
Lo portable entre ambos no es el indice sino la tabla de chunks con sus metadatos: en
Databricks esa tabla es Delta y el indice Delta Sync se construye sobre ella con
embeddings gestionados por la plataforma; en local la misma lista de `Document` alimenta a
Chroma y a BM25. Cambiar de almacen es cambiar un adaptador, no rehacer el chunking.

La recuperacion es hibrida en los dos. En mina se pregunta por codigo —`H-HIDRA-02`,
`AC-L8-BP-2241`— y los embeddings densos son malos con alfanumericos; la busqueda lexica los
encuentra exactos. Databricks fusiona denso y lexico en el motor (`query_type="HYBRID"`);
en local la fusion la hace `fusion_reciproca`, que es el mismo algoritmo de fusion
reciproca de rangos y por eso los dos almacenes son comparables en la evaluacion.

Se descarto Azure AI Search, que tambien es hibrido nativo, porque el C-1 eligio Databricks
como plataforma de datos y modelos, y el asistente debe vivir donde viven los documentos y
el catalogo que gobierna su clasificacion.

Costo: el endpoint de Vector Search se factura por hora desde que existe un indice y hasta
24 horas despues de borrar el ultimo. Por eso `AlmacenDatabricks` no crea el endpoint por
su cuenta: `crear_endpoint` y `borrar_endpoint` son llamadas explicitas y el flujo de
trabajo las ejecuta dentro de una misma sesion.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Final, Literal

from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from rag_minero.chunking import Metadatos
from rag_minero.errores import ConfiguracionError, IndiceVacioError

Origen = Literal["denso", "lexico", "hibrido"]


@dataclass(frozen=True)
class Resultado:
    """Un chunk recuperado, con el score de fusion y el score denso si existe.

    El score denso se conserva aparte porque la puerta de dominio lo usa como segundo
    criterio: una pregunta con vocabulario minero pero sin ningun pasaje cercano se rechaza.
    """

    documento: Document
    score: float
    origen: Origen
    score_denso: float | None = None

    @property
    def chunk_id(self) -> str:
        """Identificador del chunk recuperado."""
        return str(self.documento.metadata["chunk_id"])


class AlmacenVectorial(ABC):
    """Contrato de un almacen: indexar chunks, buscar por consulta con filtros, vaciar."""

    nombre: ClassVar[str]

    @abstractmethod
    def indexar(self, chunks: Sequence[Document]) -> int:
        """Indexa los chunks y devuelve cuantos quedaron indexados."""

    @abstractmethod
    def buscar(
        self, consulta: str, k: int = 6, filtros: Metadatos | None = None
    ) -> list[Resultado]:
        """Los `k` chunks mas relevantes, con filtros de igualdad sobre metadatos."""

    @abstractmethod
    def vaciar(self) -> None:
        """Elimina todo lo indexado."""

    @property
    @abstractmethod
    def cantidad(self) -> int:
        """Numero de chunks indexados."""


# --- Fusion reciproca de rangos y tokenizacion lexica ---

CONSTANTE_RRF: Final[int] = 60


def fusion_reciproca(listas: Sequence[Sequence[str]], k: int = CONSTANTE_RRF) -> dict[str, float]:
    """Fusion reciproca de rangos: cada lista aporta `1 / (k + posicion)` a cada identificador.

    Es la fusion que usan Databricks y Azure para su busqueda hibrida. No necesita que los
    scores denso y lexico sean comparables, que es justamente el problema que resuelve.
    """
    puntajes: dict[str, float] = {}
    for lista in listas:
        for posicion, identificador in enumerate(lista, start=1):
            puntajes[identificador] = puntajes.get(identificador, 0.0) + 1.0 / (k + posicion)
    return dict(sorted(puntajes.items(), key=lambda par: par[1], reverse=True))


def tokenizar_lexico(texto: str) -> list[str]:
    """Tokens para BM25: sin tildes, en minusculas, con los codigos enteros y tambien partidos.

    `H-HIDRA-02` se indexa como `h-hidra-02`, `h`, `hidra` y `02`, para que encuentre tanto
    la consulta con el codigo exacto como la que solo dice «hidra».
    """
    sin_tildes = unicodedata.normalize("NFKD", texto)
    plano = "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", plano):
        tokens.append(token)
        if "-" in token:
            tokens.extend(token.split("-"))
    return tokens


def _cumple_filtros(documento: Document, filtros: Metadatos | None) -> bool:
    return not filtros or all(documento.metadata.get(k) == v for k, v in filtros.items())


def _filtro_chroma(filtros: Metadatos | None) -> dict[str, Any] | None:
    if not filtros:
        return None
    if len(filtros) == 1:
        return dict(filtros)
    return {"$and": [{clave: valor} for clave, valor in filtros.items()]}


class AlmacenLocal(AlmacenVectorial):
    """Chroma para lo denso y BM25 para lo lexico, fusionados con RRF.

    Es el almacen de las pruebas y del evaluador sin workspace. Chroma no trae busqueda
    lexica con ranking, asi que BM25 vive al lado sobre la misma lista de chunks; se
    descarto Qdrant en modo local, que si trae vectores dispersos, porque agregaba una
    dependencia para hacer lo que `fusion_reciproca` hace en veinte lineas.
    """

    nombre = "chroma+bm25"

    def __init__(
        self,
        embeddings: Embeddings,
        directorio: Path | None = None,
        coleccion: str = "rag_minero",
        multiplicador_candidatos: int = 3,
    ) -> None:
        if multiplicador_candidatos < 1:
            raise ValueError("multiplicador_candidatos debe ser al menos 1")
        self._fabrica: Callable[[], Chroma] = lambda: Chroma(
            collection_name=coleccion,
            embedding_function=embeddings,
            persist_directory=str(directorio) if directorio else None,
            # Distancia coseno: la relevancia queda en [0, 1] y es comparable entre modelos.
            collection_metadata={"hnsw:space": "cosine"},
        )
        self._chroma = self._fabrica()
        self._chunks: list[Document] = []
        self._bm25: BM25Retriever | None = None
        self._multiplicador = multiplicador_candidatos

    @property
    def cantidad(self) -> int:
        """Chunks indexados en esta sesion."""
        return len(self._chunks)

    def indexar(self, chunks: Sequence[Document]) -> int:
        """Agrega los chunks a Chroma y reconstruye el indice BM25 sobre todos los conocidos."""
        if not chunks:
            return self.cantidad
        self._chroma.add_documents(list(chunks), ids=[str(c.id) for c in chunks])
        self._chunks.extend(chunks)
        self._bm25 = BM25Retriever.from_documents(
            self._chunks, preprocess_func=tokenizar_lexico, k=len(self._chunks)
        )
        return self.cantidad

    def buscar(
        self, consulta: str, k: int = 6, filtros: Metadatos | None = None
    ) -> list[Resultado]:
        """Busqueda hibrida: candidatos densos y lexicos fusionados por RRF; los `k` mejores."""
        if self._bm25 is None or not self._chunks:
            raise IndiceVacioError(self.nombre)
        candidatos = max(k * self._multiplicador, k)
        densos = self._chroma.similarity_search_with_relevance_scores(
            consulta, k=min(candidatos, self.cantidad), filter=_filtro_chroma(filtros)
        )
        score_denso = {str(d.metadata["chunk_id"]): s for d, s in densos}
        lexicos = [
            d for d in self._bm25.invoke(consulta) if _cumple_filtros(d, filtros)
        ][:candidatos]
        por_id = {str(d.metadata["chunk_id"]): d for d, _ in densos}
        por_id.update({str(d.metadata["chunk_id"]): d for d in lexicos})
        fusion = fusion_reciproca(
            [list(score_denso), [str(d.metadata["chunk_id"]) for d in lexicos]]
        )
        ids_lexicos = {str(d.metadata["chunk_id"]) for d in lexicos}
        resultados: list[Resultado] = []
        for identificador, score in list(fusion.items())[:k]:
            en_denso, en_lexico = identificador in score_denso, identificador in ids_lexicos
            origen: Origen = "lexico"
            if en_denso and en_lexico:
                origen = "hibrido"
            elif en_denso:
                origen = "denso"
            resultados.append(
                Resultado(por_id[identificador], score, origen, score_denso.get(identificador))
            )
        return resultados

    def vaciar(self) -> None:
        """Borra la coleccion de Chroma y el indice BM25."""
        self._chroma.delete_collection()
        self._chroma = self._fabrica()
        self._chunks = []
        self._bm25 = None


# --- Databricks Vector Search ---

COSTO_ENDPOINT_USD_HORA: Final[str] = "0.28"
COLUMNAS_TABLA: Final[tuple[str, ...]] = (
    "chunk_id",
    "texto",
    "documento",
    "genero",
    "titulo_documento",
    "version",
    "clasificacion",
    "vigente",
    "seccion",
    "elemento",
    "pagina",
    "estrategia",
    "codigos",
    "frentes",
)


@dataclass(frozen=True)
class ConfiguracionDatabricks:
    """Recursos del workspace, leidos del entorno y validados al arranque.

    Ningun nombre de catalogo, endpoint ni warehouse vive en el codigo: son del entorno,
    como la ruta del CSV en el Modulo A.
    """

    catalogo: str
    esquema: str
    endpoint: str
    warehouse_id: str
    tabla: str = "chunks"
    modelo_embeddings: str = "databricks-qwen3-embedding-0-6b"
    perfil: str | None = None

    @classmethod
    def desde_entorno(cls, entorno: dict[str, str] | None = None) -> ConfiguracionDatabricks:
        """Lee `RAG_CATALOG`, `RAG_SCHEMA`, `RAG_VS_ENDPOINT` y `RAG_WAREHOUSE_ID`, obligatorias."""
        valores = entorno if entorno is not None else dict(os.environ)
        requeridas = {
            "RAG_CATALOG": "catalogo de Unity Catalog",
            "RAG_SCHEMA": "esquema del catalogo",
            "RAG_VS_ENDPOINT": "nombre del endpoint de Vector Search",
            "RAG_WAREHOUSE_ID": "id del SQL warehouse para crear la tabla de chunks",
        }
        for variable, detalle in requeridas.items():
            if not valores.get(variable, "").strip():
                raise ConfiguracionError(variable, f"falta la variable ({detalle})")
        return cls(
            catalogo=valores["RAG_CATALOG"].strip(),
            esquema=valores["RAG_SCHEMA"].strip(),
            endpoint=valores["RAG_VS_ENDPOINT"].strip(),
            warehouse_id=valores["RAG_WAREHOUSE_ID"].strip(),
            tabla=valores.get("RAG_TABLE", "chunks").strip() or "chunks",
            modelo_embeddings=valores.get("RAG_EMBEDDING_ENDPOINT", "").strip()
            or "databricks-qwen3-embedding-0-6b",
            perfil=valores.get("DATABRICKS_CONFIG_PROFILE") or None,
        )

    @property
    def tabla_completa(self) -> str:
        """`catalogo.esquema.tabla` de la tabla Delta de chunks."""
        return f"{self.catalogo}.{self.esquema}.{self.tabla}"

    @property
    def indice_completo(self) -> str:
        """`catalogo.esquema.tabla_index` del indice Delta Sync."""
        return f"{self.tabla_completa}_index"


def _literal_sql(valor: object) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int):
        return str(valor)
    return "'" + str(valor).replace("\\", "\\\\").replace("'", "\\'") + "'"


def sql_crear_tabla(tabla: str) -> str:
    """DDL de la tabla de chunks con Change Data Feed, que el indice Delta Sync exige."""
    return (
        f"CREATE OR REPLACE TABLE {tabla} ("
        "chunk_id STRING NOT NULL, texto STRING, documento STRING, genero STRING, "
        "titulo_documento STRING, version STRING, clasificacion STRING, vigente BOOLEAN, "
        "seccion STRING, elemento STRING, pagina INT, estrategia STRING, codigos STRING, "
        "frentes STRING) TBLPROPERTIES (delta.enableChangeDataFeed = true)"
    )


def sql_insertar(tabla: str, chunks: Iterable[Document]) -> str:
    """INSERT con una fila por chunk; los metadatos que no son columna se descartan."""
    filas: list[str] = []
    for chunk in chunks:
        valores = {**chunk.metadata, "texto": chunk.page_content}
        literales = ", ".join(_literal_sql(valores.get(c, "")) for c in COLUMNAS_TABLA)
        filas.append(f"({literales})")
    return f"INSERT INTO {tabla} ({', '.join(COLUMNAS_TABLA)}) VALUES " + ", ".join(filas)


@dataclass
class AlmacenDatabricks(AlmacenVectorial):
    """Tabla Delta de chunks mas indice Delta Sync con embeddings gestionados, consulta hibrida.

    Los clientes se inyectan para poder probar la logica sin workspace; en uso normal se
    construyen desde el perfil de la CLI. La clase no crea el endpoint: eso cuesta dinero
    por hora y se decide fuera, con `crear_endpoint` y `borrar_endpoint`.
    """

    nombre: ClassVar[str] = "databricks-vector-search"
    configuracion: ConfiguracionDatabricks
    workspace: Any = None
    cliente_vs: Any = None
    _cantidad: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Construye el cliente del workspace desde el perfil de la CLI si no se inyecto."""
        if self.workspace is None:
            from databricks.sdk import WorkspaceClient

            self.workspace = WorkspaceClient(profile=self.configuracion.perfil)

    def _credenciales(self) -> tuple[str, str]:
        configuracion = self.workspace.config
        token = configuracion.authenticate().get("Authorization", "").removeprefix("Bearer ")
        return str(configuracion.host), token.strip()

    def _cliente(self) -> Any:
        """El cliente inyectado o uno nuevo con token fresco.

        El cliente de Vector Search no lee el perfil OAuth de la CLI y el token que el SDK
        negocia caduca en una hora; construirlo en cada operacion evita que una espera larga
        -crear el indice tarda casi media hora- termine con "Invalid Token".
        """
        if self.cliente_vs is not None:
            return self.cliente_vs
        from databricks.ai_search.client import VectorSearchClient

        host, token = self._credenciales()
        return VectorSearchClient(
            workspace_url=host, personal_access_token=token, disable_notice=True
        )

    @property
    def cantidad(self) -> int:
        """Chunks cargados en la tabla en esta sesion."""
        return self._cantidad

    # --- ciclo de vida del endpoint, explicito por su costo ---

    def endpoint_existe(self) -> bool:
        """Verdadero si el endpoint ya esta creado en el workspace."""
        nombres = [e["name"] for e in self._cliente().list_endpoints().get("endpoints", [])]
        return self.configuracion.endpoint in nombres

    def crear_endpoint(self) -> None:
        """Crea el endpoint estandar y espera a que este listo. Cuesta 0.28 USD por hora."""
        if not self.endpoint_existe():
            self._cliente().create_endpoint_and_wait(self.configuracion.endpoint)

    def borrar_endpoint(self) -> None:
        """Borra el endpoint; la facturacion se detiene 24 horas despues del ultimo indice."""
        if self.endpoint_existe():
            self._cliente().delete_endpoint(self.configuracion.endpoint)

    # --- contrato ---

    def indexar(self, chunks: Sequence[Document]) -> int:
        """Reescribe la tabla Delta, crea o sincroniza el indice y espera a que este listo."""
        tabla = self.configuracion.tabla_completa
        self._ejecutar_sql(sql_crear_tabla(tabla))
        if chunks:
            self._ejecutar_sql(sql_insertar(tabla, chunks))
        self._cantidad = len(chunks)
        indice = self._indice_o_none()
        if indice is None:
            self._cliente().create_delta_sync_index(
                endpoint_name=self.configuracion.endpoint,
                index_name=self.configuracion.indice_completo,
                primary_key="chunk_id",
                source_table_name=tabla,
                pipeline_type="TRIGGERED",
                embedding_source_column="texto",
                embedding_model_endpoint_name=self.configuracion.modelo_embeddings,
                columns_to_sync=list(COLUMNAS_TABLA),
            )
        else:
            self._sincronizar_cuando_se_pueda(indice)
        self._esperar_indice()
        return self._cantidad

    def buscar(
        self, consulta: str, k: int = 6, filtros: Metadatos | None = None
    ) -> list[Resultado]:
        """Consulta hibrida del motor; el score devuelto es el de la fusion de Databricks."""
        from databricks_langchain import DatabricksVectorSearch

        host, token = self._credenciales()
        almacen = DatabricksVectorSearch(
            index_name=self.configuracion.indice_completo,
            endpoint=self.configuracion.endpoint,
            columns=[c for c in COLUMNAS_TABLA if c != "texto"],
            client_args={
                "workspace_url": host,
                "personal_access_token": token,
                "disable_notice": True,
            },
        )
        pares = almacen.similarity_search_with_score(
            consulta, k=k, filter=dict(filtros) if filtros else None, query_type="HYBRID"
        )
        return [Resultado(doc, float(score), "hibrido", None) for doc, score in pares]

    def vaciar(self) -> None:
        """Borra el indice y la tabla; el endpoint se conserva hasta `borrar_endpoint`."""
        if self._indice_o_none() is not None:
            self._cliente().delete_index(
                endpoint_name=self.configuracion.endpoint,
                index_name=self.configuracion.indice_completo,
            )
        self._ejecutar_sql(f"DROP TABLE IF EXISTS {self.configuracion.tabla_completa}")
        self._cantidad = 0

    # --- ayudantes ---

    def _sincronizar_cuando_se_pueda(
        self, indice: Any, intervalo: float = 20.0, maximo: float = 1800.0
    ) -> None:
        """Dispara la sincronizacion cuando el pipeline del indice admite una nueva.

        Un indice recien creado o con una sincronizacion en curso rechaza `sync()` con
        "not ready to sync"; se reintenta hasta que el pipeline termine la anterior.
        """
        inicio = time.monotonic()
        while True:
            try:
                indice.sync()
                return
            except Exception as error:  # el cliente no tipa este rechazo
                if "not ready to sync" not in str(error):
                    raise
                if time.monotonic() - inicio > maximo:
                    mensaje = f"El indice no admitio sincronizar en {maximo:.0f} s"
                    raise TimeoutError(mensaje) from error
                time.sleep(intervalo)

    def _esperar_indice(self, intervalo: float = 20.0, maximo: float = 3600.0) -> None:
        """Espera a que el indice este listo consultandolo con un cliente fresco cada vez."""
        inicio = time.monotonic()
        while True:
            indice = self._indice_o_none()
            estado = indice.describe().get("status", {}) if indice is not None else {}
            if estado.get("ready"):
                return
            if time.monotonic() - inicio > maximo:
                raise TimeoutError(
                    f"El indice no quedo listo en {maximo:.0f} s: {estado.get('detailed_state')}"
                )
            time.sleep(intervalo)

    def _indice_o_none(self) -> Any:
        try:
            return self._cliente().get_index(
                endpoint_name=self.configuracion.endpoint,
                index_name=self.configuracion.indice_completo,
            )
        except Exception:
            return None

    def _ejecutar_sql(self, sentencia: str) -> None:
        api = self.workspace.statement_execution
        respuesta = api.execute_statement(
            statement=sentencia,
            warehouse_id=self.configuracion.warehouse_id,
            wait_timeout="50s",
        )
        while respuesta.status is not None and respuesta.status.state is not None and (
            respuesta.status.state.value in ("PENDING", "RUNNING")
        ):
            time.sleep(2)
            respuesta = api.get_statement(respuesta.statement_id)
        status = respuesta.status
        estado = status.state.value if status and status.state else "?"
        if estado != "SUCCEEDED":
            detalle = status.error.message if status and status.error else estado
            raise RuntimeError(f"La sentencia SQL fallo ({estado}): {detalle}")
