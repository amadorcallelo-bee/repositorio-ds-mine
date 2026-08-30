"""Pruebas del flujo de la demo: configuracion, pasos gratis y cierre, sin tocar Databricks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_minero.errores import ConfiguracionError
from rag_minero.flujo import DOCUMENTOS, Configuracion, Flujo, Resultados
from rag_minero.tests.embeddings import EmbeddingsPorTerminos


def _entorno(directorio: Path, **extra: str) -> dict[str, str]:
    return {"RAG_PDF_DIR": str(directorio), **extra}


def _directorio_con_pdf_vacios(tmp_path: Path) -> Path:
    for nombre in DOCUMENTOS:
        (tmp_path / nombre).write_bytes(b"%PDF-1.4")
    return tmp_path


# --- configuracion ---


def test_la_configuracion_exige_el_directorio_de_pdf() -> None:
    with pytest.raises(ConfiguracionError, match="RAG_PDF_DIR"):
        Configuracion.desde_entorno({})


def test_la_configuracion_nombra_los_pdf_que_faltan(tmp_path: Path) -> None:
    with pytest.raises(ConfiguracionError, match=r"PET-PERF-007\.pdf"):
        Configuracion.desde_entorno(_entorno(tmp_path))


def test_la_configuracion_toma_valores_por_defecto(tmp_path: Path) -> None:
    config = Configuracion.desde_entorno(_entorno(_directorio_con_pdf_vacios(tmp_path)))
    assert config.almacen == "local"
    assert config.tokens_maximos == 400_000
    assert config.modelo_generador == "databricks-claude-sonnet-5"


def test_la_configuracion_lee_almacen_y_tope(tmp_path: Path) -> None:
    entorno = _entorno(
        _directorio_con_pdf_vacios(tmp_path),
        RAG_ALMACEN="databricks",
        RAG_TOKENS_MAXIMOS="1234",
        DATABRICKS_CONFIG_PROFILE="perfil",
        RAG_MODELO_GENERADOR="databricks-qwen3-next-80b-a3b-instruct",
        RAG_MODELO_JUEZ="databricks-meta-llama-3-3-70b-instruct",
    )
    config = Configuracion.desde_entorno(entorno)
    assert (config.almacen, config.tokens_maximos, config.perfil) == ("databricks", 1234, "perfil")
    assert config.modelo_generador == "databricks-qwen3-next-80b-a3b-instruct"
    assert config.modelo_juez == "databricks-meta-llama-3-3-70b-instruct"
    assert config.modelo_embeddings == "databricks-qwen3-embedding-0-6b"


def test_un_almacen_desconocido_falla(tmp_path: Path) -> None:
    entorno = _entorno(_directorio_con_pdf_vacios(tmp_path), RAG_ALMACEN="pinecone")
    with pytest.raises(ConfiguracionError, match="RAG_ALMACEN"):
        Configuracion.desde_entorno(entorno)


# --- resultados ---


def test_los_resultados_se_guardan_como_json_legible(tmp_path: Path) -> None:
    resultados = Resultados(chunks_por_variante={"fijo": 27}, ragas_resumen={"faithfulness": 0.9})
    ruta = resultados.guardar(tmp_path / "salida")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["chunks_por_variante"] == {"fijo": 27}
    assert datos["ragas_resumen"]["faithfulness"] == 0.9


# --- pasos gratis sobre los PDF reales ---


@pytest.mark.integracion
def test_los_pasos_gratis_del_flujo_corren_sin_modelo(directorio_pdf: Path, tmp_path: Path) -> None:
    config = Configuracion(directorio_pdf=directorio_pdf, directorio_salida=tmp_path)
    flujo = Flujo(config, embeddings=EmbeddingsPorTerminos())

    documentos = flujo.cargar_documentos()
    assert [d.codigo for d in documentos] == [
        "PET-PERF-007",
        "INFORME-GEO-VETA-SUR-2024",
        "MANUAL-ATLAS-COPCO-L8",
    ]

    chunks = flujo.trocear()
    assert len(chunks) == flujo.resultados.chunks_por_variante["informe+manual+procedimiento"]
    assert set(flujo.resultados.chunks_por_variante) == {"informe+manual+procedimiento", "seccion", "fijo"}

    calibracion = flujo.calibrar()
    assert calibracion.rechazadas_fuera == calibracion.total_fuera == 10
    assert calibracion.aceptadas_del_dominio >= 9
    assert flujo.puerta is not None

    ablacion = flujo.ablacion()
    assert len(ablacion) == 3 * 10
    assert "| Variante |" in flujo.resultados.ablacion_tabla

    almacen = flujo.construir_almacen()
    assert almacen.cantidad == len(chunks)
    ruta = flujo.cerrar(almacen)
    assert ruta.is_file()
    almacen.vaciar()


def test_calibrar_antes_de_trocear_falla(tmp_path: Path) -> None:
    config = Configuracion(directorio_pdf=_directorio_con_pdf_vacios(tmp_path))
    flujo = Flujo(config, embeddings=EmbeddingsPorTerminos())
    with pytest.raises(RuntimeError, match="trocear"):
        flujo.calibrar()
