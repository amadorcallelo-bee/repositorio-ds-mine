"""Pruebas de las estrategias de chunking: cada genero produce la unidad que se argumenta."""

from __future__ import annotations

import pytest

from rag_minero.chunking import (
    ChunkingInforme,
    ChunkingManual,
    ChunkingProcedimiento,
    Trozador,
    extraer_codigos,
    extraer_frentes,
    renderizar_fila,
)
from rag_minero.tests.datos import corpus, informe, manual, procedimiento

# --- extraccion de codigos y frentes ---


def test_extraer_codigos_reconoce_las_familias_del_corpus() -> None:
    texto = (
        "Reportar H-HIDRA-02 y M-MOTOR-07; ver PT-02, CP-03, R-01, ROL-SUP-01, "
        "AC-L8-BP-2241, MANT-500H-FILTROS, F-PERF-007-A, OREAS-13P, OPUS-TELEM-v2, SX-01."
    )
    codigos = extraer_codigos(texto)
    for esperado in (
        "H-HIDRA-02", "M-MOTOR-07", "PT-02", "CP-03", "R-01", "ROL-SUP-01",
        "AC-L8-BP-2241", "MANT-500H-FILTROS", "F-PERF-007-A", "OREAS-13P", "OPUS-TELEM", "SX-01",
    ):
        assert esperado in codigos, esperado
    assert "OPUS-TELEM-" not in codigos


def test_extraer_codigos_no_repite_y_conserva_el_orden() -> None:
    assert extraer_codigos("PT-01 y PT-02 y PT-01") == ["PT-01", "PT-02"]


def test_extraer_frentes() -> None:
    assert extraer_frentes("FR-S2-03 y FR-S1 y FR-S2-03") == ["FR-S2-03", "FR-S1"]


# --- renderizado de filas ---


def test_renderizar_fila_pone_la_primera_celda_como_sujeto() -> None:
    texto = renderizar_fila(("Código", "Umbral", "Acción"), ("CP-03", "<140 bar", "Detener."))
    assert texto == "CP-03 — Umbral: <140 bar; Acción: Detener."


def test_renderizar_fila_sin_cabecera_o_desalineada_cae_a_barras() -> None:
    assert renderizar_fila((), ("a", "b")) == "a | b"
    assert renderizar_fila(("A",), ("a", "b")) == "a | b"


def test_renderizar_fila_de_una_sola_columna() -> None:
    assert renderizar_fila(("A",), ("solo",)) == "solo"


# --- procedimiento: paso y fila como unidad ---


def test_procedimiento_produce_un_chunk_por_paso_y_por_fila() -> None:
    chunks = ChunkingProcedimiento().trocear(procedimiento())
    pasos = [c for c in chunks if "paso" in c.metadata]
    filas = [c for c in chunks if "fila" in c.metadata]
    assert [c.metadata["paso"] for c in pasos] == ["Paso 2 — Inicio controlado", "Paso 5 — Parada programada"]
    assert [c.metadata["fila"] for c in filas] == ["CP-02", "CP-03"]


def test_la_fila_conserva_condicion_y_accion_juntas_con_su_contexto() -> None:
    chunks = ChunkingProcedimiento().trocear(procedimiento())
    cp03 = next(c for c in chunks if c.metadata.get("fila") == "CP-03")
    assert cp03.page_content.startswith("[PET-TEST-001 · Criterios de Parada Inmediata] CP-03")
    assert "<140 bar" in cp03.page_content and "H-HIDRA-02" in cp03.page_content
    assert cp03.metadata["codigos"] == "PET-TEST-001;CP-03;H-HIDRA-02"


def test_los_encabezados_de_seccion_no_son_chunks() -> None:
    chunks = ChunkingProcedimiento().trocear(procedimiento())
    assert all(c.metadata["elemento"] != "encabezado" for c in chunks)


# --- informe: tabla entera y prosa solapada ---


def test_informe_conserva_la_tabla_entera_con_la_fila_total() -> None:
    chunks = ChunkingInforme().trocear(informe())
    tabla = next(c for c in chunks if c.metadata["elemento"] == "tabla")
    assert tabla.metadata["filas"] == 3
    assert "TOTAL SECTOR" in tabla.page_content and "FR-S2-03" in tabla.page_content
    assert tabla.metadata["frentes"] == "FR-S1-02;FR-S2-03"


def test_informe_trocea_la_prosa_larga_con_solapamiento() -> None:
    chunks = [c for c in ChunkingInforme().trocear(informe()) if c.metadata["elemento"] == "prosa"]
    assert len(chunks) >= 2
    assert all(len(c.page_content) <= ChunkingInforme.tamano + 80 for c in chunks)
    primero, segundo = chunks[0].page_content, chunks[1].page_content
    cola = primero[-60:].split("] ")[-1]
    assert any(oracion in segundo for oracion in cola.split(". ") if len(oracion) > 20)


def test_informe_conserva_la_clasificacion_confidencial_en_cada_chunk() -> None:
    assert all(c.metadata["clasificacion"] == "CONFIDENCIAL" for c in ChunkingInforme().trocear(informe()))


# --- manual: fila como hecho atomico y advertencia indivisible ---


def test_manual_rinde_cada_especificacion_como_frase() -> None:
    chunks = ChunkingManual().trocear(manual())
    presion = next(c for c in chunks if c.metadata.get("fila") == "Presión hidráulica máxima")
    assert "Especificación: 280; Unidad: bar" in presion.page_content


def test_manual_marca_la_advertencia_con_prioridad_alta_e_indivisible() -> None:
    chunks = ChunkingManual().trocear(manual())
    advertencias = [c for c in chunks if c.metadata.get("prioridad") == "alta"]
    assert len(advertencias) == 1
    assert "E-ELEC-04" in advertencias[0].metadata["codigos"]
    assert "-1" in advertencias[0].page_content


# --- trozador y variantes de control ---


def test_el_trozador_enruta_cada_documento_a_su_estrategia() -> None:
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    estrategias = {c.metadata["documento"]: c.metadata["estrategia"] for c in chunks}
    assert estrategias == {
        "PET-TEST-001": "procedimiento",
        "INFORME-TEST-2024": "informe",
        "MANUAL-TEST-L8": "manual",
    }


def test_los_identificadores_son_unicos_dentro_de_cada_variante() -> None:
    for trozador in (Trozador.por_genero_y_elemento(), Trozador.solo_genero(), Trozador.tamano_fijo()):
        chunks = trozador.trocear(corpus())
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids)), trozador.nombre
        assert all(c.metadata["chunk_id"] == c.id for c in chunks)


def test_las_variantes_de_control_tienen_nombre_propio() -> None:
    assert Trozador.solo_genero().nombre == "seccion"
    assert Trozador.tamano_fijo().nombre == "fijo"
    assert Trozador.por_genero_y_elemento().nombre == "informe+manual+procedimiento"


def test_solo_genero_produce_un_chunk_por_seccion_corta() -> None:
    chunks = Trozador.solo_genero().trocear([procedimiento()])
    secciones = [c.metadata["seccion"] for c in chunks]
    assert secciones == ["Encabezado", "Procedimiento de Operacion", "Criterios de Parada Inmediata"]


def test_tamano_fijo_respeta_el_tope_de_tamano() -> None:
    chunks = Trozador.tamano_fijo().trocear(corpus())
    assert chunks
    assert all(len(c.page_content) <= 800 + 60 for c in chunks)


@pytest.mark.parametrize("trozador", [Trozador.por_genero_y_elemento(), Trozador.solo_genero()])
def test_todo_chunk_lleva_los_metadatos_comunes(trozador: Trozador) -> None:
    claves = {"documento", "genero", "seccion", "elemento", "pagina", "clasificacion", "vigente", "codigos", "frentes", "chunk_id"}
    for chunk in trozador.trocear(corpus()):
        assert claves <= chunk.metadata.keys()
        assert chunk.metadata["vigente"] is True
