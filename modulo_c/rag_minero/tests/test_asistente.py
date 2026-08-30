"""Pruebas del asistente con un modelo falso: la cadena rechaza, responde, bloquea y cuenta."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from rag_minero.asistente import (
    MENSAJE_BLOQUEO,
    MENSAJE_RECHAZO,
    Asistente,
    PresupuestoTokens,
    contextos_planos,
)
from rag_minero.chunking import Trozador
from rag_minero.errores import PresupuestoExcedidoError
from rag_minero.guardrails import PuertaDeDominio, Vocabulario
from rag_minero.indice import AlmacenLocal
from rag_minero.tests.datos import corpus
from rag_minero.tests.embeddings import EmbeddingsPorTerminos


@pytest.fixture
def almacen() -> Iterator[AlmacenLocal]:
    local = AlmacenLocal(EmbeddingsPorTerminos(), coleccion=f"asistente-{uuid4().hex[:8]}")
    local.indexar(Trozador.por_genero_y_elemento().trocear(corpus()))
    yield local
    local.vaciar()


@pytest.fixture
def puerta(almacen: AlmacenLocal) -> PuertaDeDominio:
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    return PuertaDeDominio(Vocabulario.desde_textos(c.page_content for c in chunks), 0.4)


def _asistente(almacen: AlmacenLocal, puerta: PuertaDeDominio, *respuestas: str, **extra: object) -> Asistente:
    modelo = FakeListChatModel(responses=list(respuestas))
    return Asistente(almacen, modelo, puerta, **extra)  # type: ignore[arg-type]


# --- rechazo ---


def test_una_pregunta_fuera_de_dominio_se_rechaza_sin_llamar_al_modelo(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    asistente = _asistente(almacen, puerta, "no deberia usarse")
    respuesta = asistente.responder("¿Cómo preparo una paella valenciana?")
    assert respuesta.rechazada and not respuesta.bloqueada
    assert respuesta.texto == MENSAJE_RECHAZO
    assert respuesta.fuentes == () and respuesta.tokens_entrada == 0
    assert "fuera de dominio" in respuesta.motivo


def test_una_pregunta_con_vocabulario_pero_sin_pasaje_cercano_se_rechaza_por_score(
    almacen: AlmacenLocal,
) -> None:
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    estricta = PuertaDeDominio(
        Vocabulario.desde_textos(c.page_content for c in chunks), 0.0, score_minimo=1.01
    )
    asistente = _asistente(almacen, estricta, "no deberia usarse")
    respuesta = asistente.responder("presión hidráulica máxima")
    assert respuesta.rechazada and "sin pasajes relevantes" in respuesta.motivo


# --- respuesta ---


def test_una_respuesta_respaldada_se_devuelve_con_sus_fuentes(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    asistente = _asistente(
        almacen, puerta, "La presión hidráulica máxima es 280 bar y no se opera sobre 260 bar."
    )
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert respuesta.exitosa
    assert "280 bar" in respuesta.texto
    assert respuesta.verificacion is not None and respuesta.verificacion.aprobada
    assert any("Presión hidráulica máxima" in c for c in respuesta.contextos)
    assert len(respuesta.fuentes) == len(respuesta.contextos) == 6


def test_k_limita_los_pasajes_que_recibe_el_modelo(almacen: AlmacenLocal, puerta: PuertaDeDominio) -> None:
    asistente = _asistente(almacen, puerta, "Respuesta sin cifras.", k=2)
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert len(respuesta.fuentes) == 2


def test_contextos_planos_quita_el_identificador(almacen: AlmacenLocal, puerta: PuertaDeDominio) -> None:
    asistente = _asistente(almacen, puerta, "Respuesta sin cifras.", k=1)
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    planos = contextos_planos(respuesta)
    assert len(planos) == 1 and not planos[0].startswith("[MANUAL-TEST-L8#")
    assert respuesta.contextos[0].startswith("[MANUAL-TEST-L8#")


# --- bloqueo ---


def test_una_cifra_inventada_bloquea_la_respuesta_y_conserva_el_borrador(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    asistente = _asistente(almacen, puerta, "La presión hidráulica máxima es 300 bar.")
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert respuesta.bloqueada and not respuesta.rechazada and not respuesta.exitosa
    assert respuesta.texto == MENSAJE_BLOQUEO
    assert respuesta.borrador == "La presión hidráulica máxima es 300 bar."
    assert respuesta.motivo == "sin respaldo: 300"


def test_una_negativa_honesta_no_se_bloquea(almacen: AlmacenLocal, puerta: PuertaDeDominio) -> None:
    asistente = _asistente(almacen, puerta, "No esta en la documentacion disponible.")
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima de la Sandvik DL432?")
    assert respuesta.exitosa
    assert respuesta.verificacion is not None and respuesta.verificacion.declara_falta_de_respaldo


# --- presupuesto ---


def test_el_presupuesto_reserva_antes_y_registra_despues() -> None:
    presupuesto = PresupuestoTokens(maximo=1000)
    presupuesto.reservar(600)
    presupuesto.registrar(500, 50)
    assert presupuesto.consumidos == 550 and presupuesto.llamadas == 1
    with pytest.raises(PresupuestoExcedidoError, match="1,000"):
        presupuesto.reservar(600)


def test_el_limite_exacto_del_presupuesto_se_permite() -> None:
    presupuesto = PresupuestoTokens(maximo=100)
    presupuesto.reservar(100)


def test_el_asistente_se_detiene_antes_de_llamar_si_no_hay_presupuesto(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    asistente = _asistente(almacen, puerta, "no deberia usarse", presupuesto=PresupuestoTokens(maximo=10))
    with pytest.raises(PresupuestoExcedidoError):
        asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")


def test_el_asistente_registra_el_consumo_estimado_si_el_modelo_no_lo_reporta(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    presupuesto = PresupuestoTokens(maximo=100_000)
    asistente = _asistente(almacen, puerta, "Respuesta sin cifras.", presupuesto=presupuesto)
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert presupuesto.llamadas == 1
    assert presupuesto.consumidos == respuesta.tokens_entrada + respuesta.tokens_salida > 0


def test_el_asistente_usa_el_consumo_real_cuando_el_modelo_lo_reporta(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    class ModeloConUso(FakeListChatModel):
        def invoke(self, *args: object, **kwargs: object) -> AIMessage:
            return AIMessage(
                content="Respuesta sin cifras.",
                usage_metadata={"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290},
            )

    presupuesto = PresupuestoTokens(maximo=100_000)
    asistente = Asistente(almacen, ModeloConUso(responses=["x"]), puerta, presupuesto=presupuesto)
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert (respuesta.tokens_entrada, respuesta.tokens_salida) == (1234, 56)
    assert presupuesto.consumidos == 1290


def test_un_k_invalido_falla(almacen: AlmacenLocal, puerta: PuertaDeDominio) -> None:
    with pytest.raises(ValueError):
        _asistente(almacen, puerta, "x", k=0)
