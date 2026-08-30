"""Pruebas del almacen local hibrido y de la parte pura del adaptador de Databricks."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from rag_minero.chunking import Trozador
from rag_minero.errores import ConfiguracionError, IndiceVacioError
from rag_minero.indice import (
    COLUMNAS_TABLA,
    AlmacenDatabricks,
    AlmacenLocal,
    ConfiguracionDatabricks,
    fusion_reciproca,
    sql_crear_tabla,
    sql_insertar,
    tokenizar_lexico,
)
from rag_minero.tests.datos import corpus
from rag_minero.tests.embeddings import EmbeddingsPorTerminos

# --- fusion y tokenizacion ---


def test_fusion_reciproca_premia_lo_que_aparece_en_las_dos_listas() -> None:
    fusion = fusion_reciproca([["a", "b", "c"], ["c", "a", "d"]])
    assert list(fusion)[:2] == ["a", "c"]
    assert fusion["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fusion["d"] == pytest.approx(1 / 63)


def test_fusion_reciproca_de_listas_vacias_es_vacia() -> None:
    assert fusion_reciproca([[], []]) == {}


def test_tokenizar_lexico_conserva_el_codigo_entero_y_sus_partes() -> None:
    tokens = tokenizar_lexico("Reportar H-HIDRA-02 (presión)")
    assert "h-hidra-02" in tokens and "hidra" in tokens and "02" in tokens
    assert "presion" in tokens


# --- almacen local ---


@pytest.fixture
def almacen() -> Iterator[AlmacenLocal]:
    local = AlmacenLocal(EmbeddingsPorTerminos(), coleccion=f"prueba-{uuid4().hex[:8]}")
    local.indexar(Trozador.por_genero_y_elemento().trocear(corpus()))
    yield local
    local.vaciar()


def test_indexar_cuenta_los_chunks(almacen: AlmacenLocal) -> None:
    assert almacen.cantidad == len(Trozador.por_genero_y_elemento().trocear(corpus()))


def test_buscar_antes_de_indexar_falla_con_error_propio() -> None:
    vacio = AlmacenLocal(EmbeddingsPorTerminos(), coleccion=f"vacio-{uuid4().hex[:8]}")
    with pytest.raises(IndiceVacioError):
        vacio.buscar("presión")


def test_indexar_una_lista_vacia_no_cambia_nada(almacen: AlmacenLocal) -> None:
    antes = almacen.cantidad
    assert almacen.indexar([]) == antes


def test_un_codigo_exacto_se_recupera_primero(almacen: AlmacenLocal) -> None:
    resultados = almacen.buscar("H-HIDRA-05", k=3)
    assert resultados[0].documento.metadata["fila"] == "H-HIDRA-05"
    assert resultados[0].origen in ("lexico", "hibrido")


def test_una_pregunta_en_lenguaje_natural_recupera_la_fila_correcta(almacen: AlmacenLocal) -> None:
    resultados = almacen.buscar("¿cuál es la presión hidráulica máxima?", k=3)
    ids = [r.documento.metadata.get("fila") for r in resultados]
    assert "Presión hidráulica máxima" in ids


def test_la_advertencia_responde_a_la_pregunta_por_el_centinela(almacen: AlmacenLocal) -> None:
    resultados = almacen.buscar("qué significa ley_au_gpT = -1 sonda XRF centinela", k=3)
    assert any(r.documento.metadata.get("prioridad") == "alta" for r in resultados)


def test_los_filtros_restringen_por_documento(almacen: AlmacenLocal) -> None:
    resultados = almacen.buscar("presión", k=5, filtros={"documento": "PET-TEST-001"})
    assert resultados
    assert all(r.documento.metadata["documento"] == "PET-TEST-001" for r in resultados)


def test_varios_filtros_se_combinan_con_y(almacen: AlmacenLocal) -> None:
    resultados = almacen.buscar("presión", k=5, filtros={"documento": "PET-TEST-001", "elemento": "tabla"})
    assert resultados
    assert all(r.documento.metadata["elemento"] == "tabla" for r in resultados)


def test_un_filtro_sin_coincidencias_devuelve_vacio(almacen: AlmacenLocal) -> None:
    assert almacen.buscar("presión", k=5, filtros={"documento": "NO-EXISTE"}) == []


def test_k_limita_el_numero_de_resultados(almacen: AlmacenLocal) -> None:
    assert len(almacen.buscar("presión", k=2)) == 2


def test_los_resultados_traen_score_denso_cuando_vienen_de_chroma(almacen: AlmacenLocal) -> None:
    resultados = almacen.buscar("presión hidráulica máxima", k=3)
    assert any(r.score_denso is not None for r in resultados)
    assert all(r.score > 0 for r in resultados)


def test_vaciar_deja_el_almacen_sin_chunks(almacen: AlmacenLocal) -> None:
    almacen.vaciar()
    assert almacen.cantidad == 0
    with pytest.raises(IndiceVacioError):
        almacen.buscar("presión")
    almacen.indexar(Trozador.por_genero_y_elemento().trocear(corpus()))


def test_un_multiplicador_invalido_falla() -> None:
    with pytest.raises(ValueError):
        AlmacenLocal(EmbeddingsPorTerminos(), multiplicador_candidatos=0)


# --- configuracion y SQL del adaptador de Databricks ---

ENTORNO = {
    "RAG_CATALOG": "workspace",
    "RAG_SCHEMA": "rag_minero",
    "RAG_VS_ENDPOINT": "rag-endpoint",
    "RAG_WAREHOUSE_ID": "abc123",
    "DATABRICKS_CONFIG_PROFILE": "amador-prueba",
}


def test_la_configuracion_se_lee_del_entorno_con_valores_por_defecto() -> None:
    config = ConfiguracionDatabricks.desde_entorno(ENTORNO)
    assert config.tabla_completa == "workspace.rag_minero.chunks"
    assert config.indice_completo == "workspace.rag_minero.chunks_index"
    assert config.modelo_embeddings == "databricks-qwen3-embedding-0-6b"
    assert config.perfil == "amador-prueba"


@pytest.mark.parametrize("faltante", ["RAG_CATALOG", "RAG_SCHEMA", "RAG_VS_ENDPOINT", "RAG_WAREHOUSE_ID"])
def test_una_variable_ausente_falla_al_arranque_nombrandola(faltante: str) -> None:
    entorno = {k: v for k, v in ENTORNO.items() if k != faltante}
    with pytest.raises(ConfiguracionError, match=faltante):
        ConfiguracionDatabricks.desde_entorno(entorno)


def test_una_variable_en_blanco_cuenta_como_ausente() -> None:
    with pytest.raises(ConfiguracionError, match="RAG_SCHEMA"):
        ConfiguracionDatabricks.desde_entorno({**ENTORNO, "RAG_SCHEMA": "   "})


def test_el_ddl_activa_change_data_feed() -> None:
    ddl = sql_crear_tabla("workspace.rag_minero.chunks")
    assert "delta.enableChangeDataFeed = true" in ddl
    assert all(columna in ddl for columna in COLUMNAS_TABLA)


def test_el_insert_escapa_comillas_y_serializa_booleanos() -> None:
    chunk = Document(
        id="X#1",
        page_content="Manguera 3/4\" DN 600mm, o'ring",
        metadata={"chunk_id": "X#1", "documento": "MAN", "vigente": True, "pagina": 3, "extra": "ignorado"},
    )
    sentencia = sql_insertar("t", [chunk])
    assert "\\'ring" in sentencia and "true" in sentencia and " 3," in sentencia
    assert "ignorado" not in sentencia
    assert sentencia.startswith("INSERT INTO t (chunk_id, texto, documento")


class _ClienteVsFalso:
    def __init__(self) -> None:
        self.endpoints: set[str] = set()
        self.indices: dict[str, _IndiceFalso] = {}
        self.llamadas: list[str] = []

    def list_endpoints(self) -> dict[str, list[dict[str, str]]]:
        return {"endpoints": [{"name": n} for n in self.endpoints]}

    def create_endpoint_and_wait(self, name: str) -> None:
        self.llamadas.append("crear_endpoint")
        self.endpoints.add(name)

    def delete_endpoint(self, name: str) -> None:
        self.llamadas.append("borrar_endpoint")
        self.endpoints.discard(name)

    def get_index(self, endpoint_name: str, index_name: str) -> _IndiceFalso:
        if index_name not in self.indices:
            raise RuntimeError("no existe")
        return self.indices[index_name]

    def create_delta_sync_index(self, **kwargs: object) -> None:
        self.llamadas.append("crear_indice")
        self.indices[str(kwargs["index_name"])] = _IndiceFalso()

    def delete_index(self, endpoint_name: str, index_name: str) -> None:
        self.llamadas.append("borrar_indice")
        self.indices.pop(index_name, None)


class _IndiceFalso:
    def __init__(self) -> None:
        self.sincronizado = False

    def sync(self) -> None:
        self.sincronizado = True

    def describe(self) -> dict[str, dict[str, object]]:
        return {"status": {"ready": True}}


class _Estado:
    def __init__(self, valor: str) -> None:
        self.value = valor


class _Status:
    def __init__(self, estado: str) -> None:
        self.state = _Estado(estado)
        self.error = None


class _Respuesta:
    def __init__(self, estado: str) -> None:
        self.statement_id = "s1"
        self.status = _Status(estado)


class _SqlFalso:
    def __init__(self) -> None:
        self.sentencias: list[str] = []

    def execute_statement(self, statement: str, warehouse_id: str, wait_timeout: str) -> _Respuesta:
        self.sentencias.append(statement)
        return _Respuesta("SUCCEEDED")

    def get_statement(self, statement_id: str) -> _Respuesta:
        return _Respuesta("SUCCEEDED")


class _WorkspaceFalso:
    def __init__(self) -> None:
        self.statement_execution = _SqlFalso()


@pytest.fixture
def databricks() -> tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso]:
    cliente, workspace = _ClienteVsFalso(), _WorkspaceFalso()
    almacen = AlmacenDatabricks(
        ConfiguracionDatabricks.desde_entorno(ENTORNO), workspace=workspace, cliente_vs=cliente
    )
    return almacen, cliente, workspace


def test_el_endpoint_se_crea_y_borra_solo_por_llamada_explicita(
    databricks: tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso],
) -> None:
    almacen, cliente, _ = databricks
    assert not almacen.endpoint_existe()
    almacen.crear_endpoint()
    almacen.crear_endpoint()
    assert almacen.endpoint_existe() and cliente.llamadas.count("crear_endpoint") == 1
    almacen.borrar_endpoint()
    assert not almacen.endpoint_existe()


def test_indexar_crea_la_tabla_inserta_y_crea_el_indice_la_primera_vez(
    databricks: tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso],
) -> None:
    almacen, cliente, workspace = databricks
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    assert almacen.indexar(chunks) == len(chunks)
    assert workspace.statement_execution.sentencias[0].startswith("CREATE OR REPLACE TABLE")
    assert workspace.statement_execution.sentencias[1].startswith("INSERT INTO")
    assert cliente.llamadas == ["crear_indice"]


def test_indexar_por_segunda_vez_sincroniza_en_vez_de_recrear(
    databricks: tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso],
) -> None:
    almacen, cliente, _ = databricks
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    almacen.indexar(chunks)
    almacen.indexar(chunks)
    assert cliente.llamadas == ["crear_indice"]
    assert cliente.indices[almacen.configuracion.indice_completo].sincronizado


def test_vaciar_borra_indice_y_tabla_pero_no_el_endpoint(
    databricks: tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso],
) -> None:
    almacen, cliente, workspace = databricks
    almacen.crear_endpoint()
    almacen.indexar(Trozador.por_genero_y_elemento().trocear(corpus()))
    almacen.vaciar()
    assert almacen.cantidad == 0
    assert "borrar_indice" in cliente.llamadas and "borrar_endpoint" not in cliente.llamadas
    assert workspace.statement_execution.sentencias[-1].startswith("DROP TABLE IF EXISTS")


def test_una_sentencia_fallida_se_reporta_con_su_estado(
    databricks: tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso],
) -> None:
    almacen, _, workspace = databricks

    def fallar(statement: str, warehouse_id: str, wait_timeout: str) -> _Respuesta:
        return _Respuesta("FAILED")

    workspace.statement_execution.execute_statement = fallar  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="FAILED"):
        almacen.indexar([])


def test_la_espera_del_indice_falla_con_el_estado_si_nunca_queda_listo(
    databricks: tuple[AlmacenDatabricks, _ClienteVsFalso, _WorkspaceFalso],
) -> None:
    almacen, cliente, _ = databricks
    cliente.indices[almacen.configuracion.indice_completo] = _IndiceFalso()
    cliente.indices[almacen.configuracion.indice_completo].describe = lambda: {  # type: ignore[method-assign]
        "status": {"ready": False, "detailed_state": "PROVISIONING"}
    }
    with pytest.raises(TimeoutError, match="PROVISIONING"):
        almacen._esperar_indice(intervalo=0.0, maximo=0.0)
