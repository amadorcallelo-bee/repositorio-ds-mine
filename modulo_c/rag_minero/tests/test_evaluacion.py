"""Pruebas de la evaluacion: carga del golden set, ablacion sin modelo y RAGAS con jueces falsos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from rag_minero.asistente import Asistente, PresupuestoTokens
from rag_minero.chunking import Trozador
from rag_minero.errores import ConfiguracionError, PresupuestoExcedidoError
from rag_minero.evaluacion import (
    Ablacion,
    CasoOro,
    EvaluadorRagas,
    GoldenSet,
    PreguntasControl,
    contiene_referencia,
    precision_de_contexto,
    recall_de_referencias,
)
from rag_minero.guardrails import PuertaDeDominio, Vocabulario
from rag_minero.indice import AlmacenLocal
from rag_minero.tests.datos import corpus
from rag_minero.tests.embeddings import EmbeddingsPorTerminos

RAIZ = Path(__file__).parent.parent


# --- carga ---


def test_el_golden_set_real_carga_diez_casos_completos() -> None:
    golden = GoldenSet.cargar(RAIZ / "golden_set.json")
    assert len(golden.casos) == 10
    assert len(golden.preguntas) == 10
    assert all(c.contextos_referencia for c in golden.casos)


def test_las_preguntas_de_control_reales_cargan() -> None:
    control = PreguntasControl.cargar(RAIZ / "preguntas_control.json")
    assert len(control.fuera_de_dominio) == 10
    assert len(control.sin_respaldo_documental) == 3


def _escribir(tmp_path: Path, contenido: dict[str, Any]) -> Path:
    ruta = tmp_path / "golden.json"
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    return ruta


def test_un_golden_set_vacio_falla(tmp_path: Path) -> None:
    with pytest.raises(ConfiguracionError, match="no tiene casos"):
        GoldenSet.cargar(_escribir(tmp_path, {"casos": []}))


def test_un_golden_set_con_ids_repetidos_falla(tmp_path: Path) -> None:
    caso = {"id": "a", "pregunta": "p", "respuesta_esperada": "r", "contextos_referencia": ["c"]}
    with pytest.raises(ConfiguracionError, match="repetidos"):
        GoldenSet.cargar(_escribir(tmp_path, {"casos": [caso, caso]}))


def test_un_caso_sin_referencias_falla_nombrando_el_caso(tmp_path: Path) -> None:
    caso = {"id": "geo-9", "pregunta": "p", "respuesta_esperada": "r", "contextos_referencia": []}
    with pytest.raises(ConfiguracionError, match="geo-9"):
        GoldenSet.cargar(_escribir(tmp_path, {"casos": [caso]}))


def test_un_control_sin_preguntas_fuera_de_dominio_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "control.json"
    ruta.write_text(json.dumps({"fuera_de_dominio": []}), encoding="utf-8")
    with pytest.raises(ConfiguracionError):
        PreguntasControl.cargar(ruta)


# --- metricas sin modelo ---


def test_contiene_referencia_tolera_el_renderizado_de_fila() -> None:
    chunk = "[PET · Criterios] CP-03 — Condición: Pérdida de presión hidráulica; Umbral: <140 bar; Acción: Detener. Reportar H-HIDRA-02."
    referencia = "CP-03 Pérdida de presión hidráulica <140 bar durante operación Detener. Reportar H-HIDRA-02."
    assert contiene_referencia(chunk, referencia)
    assert not contiene_referencia("texto sin relación alguna", referencia)
    assert not contiene_referencia(chunk, "")


def test_precision_de_contexto_premia_lo_relevante_arriba() -> None:
    referencias = ["alfa beta gama delta"]
    arriba = ["alfa beta gama delta", "ruido uno", "ruido dos"]
    abajo = ["ruido uno", "ruido dos", "alfa beta gama delta"]
    assert precision_de_contexto(arriba, referencias) == pytest.approx(1.0)
    assert precision_de_contexto(abajo, referencias) == pytest.approx(1 / 3)


def test_precision_de_contexto_sin_relevantes_es_cero() -> None:
    assert precision_de_contexto(["ruido"], ["alfa beta gama delta"]) == 0.0
    assert precision_de_contexto([], ["alfa beta gama delta"]) == 0.0


def test_precision_de_contexto_con_dos_relevantes_intercalados() -> None:
    recuperados = ["alfa beta gama delta", "ruido", "uno dos tres cuatro"]
    referencias = ["alfa beta gama delta", "uno dos tres cuatro"]
    assert precision_de_contexto(recuperados, referencias) == pytest.approx((1.0 + 2 / 3) / 2)


def test_recall_cuenta_las_referencias_cubiertas() -> None:
    recuperados = ["alfa beta gama delta", "ruido"]
    assert recall_de_referencias(recuperados, ["alfa beta gama delta", "uno dos tres cuatro"]) == 0.5
    assert recall_de_referencias(recuperados, []) == 0.0


# --- ablacion sobre el corpus sintetico ---


def _golden_sintetico() -> GoldenSet:
    return GoldenSet(
        (
            CasoOro(
                "cp03", "PET-TEST-001", "condicion-accion",
                "¿Qué hago si la presión hidráulica cae por debajo de 140 bar?",
                "Detener y reportar H-HIDRA-02.",
                ("CP-03 Pérdida de presión hidráulica <140 bar Detener. Reportar H-HIDRA-02.",),
            ),
            CasoOro(
                "spec", "MANUAL-TEST-L8", "especificacion",
                "¿Cuál es la presión hidráulica máxima?",
                "280 bar, no operar sobre 260.",
                ("Presión hidráulica máxima 280 bar No operar >260 bar.",),
            ),
            CasoOro(
                "geo", "INFORME-TEST-2024", "comparacion",
                "¿Qué frente tuvo la mayor ley media?",
                "FR-S2-03 con 9.21 g/t.",
                ("FR-S2-03 231 9.21",),
            ),
        )
    )


def _fabrica() -> AlmacenLocal:
    return AlmacenLocal(EmbeddingsPorTerminos(), coleccion=f"ablacion-{uuid4().hex[:8]}")


def test_la_ablacion_corre_todas_las_variantes_y_limpia_cada_almacen() -> None:
    ablacion = Ablacion(corpus(), _golden_sintetico(), _fabrica, k=4)
    variantes = [Trozador.por_genero_y_elemento(), Trozador.solo_genero(), Trozador.tamano_fijo()]
    resultados = ablacion.ejecutar(variantes)
    assert len(resultados) == 3 * 3
    resumen = Ablacion.resumen(resultados)
    assert set(resumen) == {"informe+manual+procedimiento", "seccion", "fijo"}
    assert resumen["informe+manual+procedimiento"]["recall"] >= resumen["fijo"]["recall"]
    assert resumen["informe+manual+procedimiento"]["precision"] > 0


def test_la_tabla_de_ablacion_tiene_una_fila_por_variante() -> None:
    resultados = Ablacion(corpus(), _golden_sintetico(), _fabrica, k=3).ejecutar([Trozador.tamano_fijo()])
    tabla = Ablacion.tabla_markdown(resultados)
    assert tabla.startswith("| Variante | PET-TEST-001 | MANUAL-TEST-L8 | INFORME-TEST-2024 | Media |")
    assert tabla.count("\n") == 2 and "| fijo |" in tabla


def test_un_k_invalido_en_la_ablacion_falla() -> None:
    with pytest.raises(ValueError):
        Ablacion(corpus(), _golden_sintetico(), _fabrica, k=0)


# --- RAGAS con jueces falsos ---


class _Resultado:
    def __init__(self, valor: float) -> None:
        self.value = valor


class _JuezFalso:
    def __init__(self, valor: float) -> None:
        self.valor = valor
        self.llamadas: list[dict[str, Any]] = []

    async def ascore(self, **kwargs: Any) -> _Resultado:
        self.llamadas.append(kwargs)
        return _Resultado(self.valor)


def _asistente(respuesta: str, presupuesto: PresupuestoTokens | None = None) -> tuple[Asistente, AlmacenLocal]:
    almacen = _fabrica()
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    almacen.indexar(chunks)
    puerta = PuertaDeDominio(Vocabulario.desde_textos(c.page_content for c in chunks), 0.4)
    modelo = FakeListChatModel(responses=[respuesta] * 10)
    return Asistente(almacen, modelo, puerta, presupuesto=presupuesto), almacen


def test_el_evaluador_puntua_cada_caso_respondido_con_las_tres_metricas() -> None:
    asistente, almacen = _asistente("Respuesta sin cifras que contrastar.")
    try:
        fiel, relevante, preciso = _JuezFalso(0.9), _JuezFalso(0.8), _JuezFalso(0.7)
        evaluador = EvaluadorRagas(asistente, fiel, relevante, preciso)
        resultados = evaluador.evaluar(_golden_sintetico())
        assert [r.faithfulness for r in resultados] == [0.9, 0.9, 0.9]
        assert len(fiel.llamadas) == 3 and "retrieved_contexts" in fiel.llamadas[0]
        assert "reference" in preciso.llamadas[0] and "retrieved_contexts" not in relevante.llamadas[0]
        assert not fiel.llamadas[0]["retrieved_contexts"][0].startswith("[PET-TEST-001#")
        resumen = EvaluadorRagas.resumen(resultados)
        assert resumen == {"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.7, "respondidas": 3.0}
    finally:
        almacen.vaciar()


def test_un_caso_bloqueado_queda_sin_metricas_y_no_llama_al_juez() -> None:
    asistente, almacen = _asistente("La presión máxima es 999 bar.")
    try:
        juez = _JuezFalso(1.0)
        resultados = EvaluadorRagas(asistente, juez, juez, juez).evaluar(_golden_sintetico())
        assert all(r.faithfulness is None for r in resultados)
        assert juez.llamadas == []
        assert EvaluadorRagas.resumen(resultados)["respondidas"] == 0.0
        assert "bloqueo" in EvaluadorRagas.tabla_markdown(resultados) or "sin respaldo" in EvaluadorRagas.tabla_markdown(resultados)
    finally:
        almacen.vaciar()


def test_el_evaluador_reserva_y_registra_el_presupuesto_del_juez() -> None:
    presupuesto = PresupuestoTokens(maximo=1_000_000)
    asistente, almacen = _asistente("Respuesta sin cifras.", presupuesto)
    try:
        juez = _JuezFalso(0.5)
        EvaluadorRagas(asistente, juez, juez, juez, presupuesto=presupuesto, tokens_por_metrica=100).evaluar(
            _golden_sintetico()
        )
        assert presupuesto.llamadas == 3 * 4
    finally:
        almacen.vaciar()


def test_el_evaluador_se_detiene_si_el_presupuesto_no_alcanza_para_el_juez() -> None:
    presupuesto = PresupuestoTokens(maximo=5_000)
    asistente, almacen = _asistente("Respuesta sin cifras.", presupuesto)
    try:
        juez = _JuezFalso(0.5)
        evaluador = EvaluadorRagas(asistente, juez, juez, juez, presupuesto=presupuesto, tokens_por_metrica=9000)
        with pytest.raises(PresupuestoExcedidoError):
            evaluador.evaluar(_golden_sintetico())
    finally:
        almacen.vaciar()


def test_la_tabla_de_ragas_tiene_una_fila_por_caso() -> None:
    asistente, almacen = _asistente("Respuesta sin cifras.")
    try:
        juez = _JuezFalso(0.5)
        resultados = EvaluadorRagas(asistente, juez, juez, juez).evaluar(_golden_sintetico())
        tabla = EvaluadorRagas.tabla_markdown(resultados)
        assert tabla.count("\n") == 2 + 3 - 1 and "| cp03 |" in tabla and "0.50" in tabla
    finally:
        almacen.vaciar()
