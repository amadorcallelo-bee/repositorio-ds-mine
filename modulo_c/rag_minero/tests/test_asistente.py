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
    MENSAJE_VACIO,
    MOTIVO_TRUNCADA,
    MOTIVO_VACIO,
    SALIDA_MAXIMA,
    Asistente,
    PresupuestoTokens,
    _texto_de,
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


def test_salida_maxima_invalida_falla(almacen: AlmacenLocal, puerta: PuertaDeDominio) -> None:
    with pytest.raises(ValueError):
        _asistente(almacen, puerta, "x", salida_maxima=0)


# --- modelos que razonan antes de responder ---


def test_el_tope_de_salida_por_defecto_cubre_el_razonamiento_previo(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    asistente = _asistente(almacen, puerta, "Respuesta sin cifras.", presupuesto=PresupuestoTokens(maximo=100_000))
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert SALIDA_MAXIMA == 1500
    assert respuesta.tokens_salida == SALIDA_MAXIMA


def test_una_respuesta_vacia_se_declara_como_fallo_y_no_como_respuesta(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    presupuesto = PresupuestoTokens(maximo=100_000)
    asistente = _asistente(almacen, puerta, "   ", presupuesto=presupuesto)
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert respuesta.bloqueada and not respuesta.rechazada and not respuesta.exitosa
    assert respuesta.texto == MENSAJE_VACIO and respuesta.motivo == MOTIVO_VACIO
    assert respuesta.verificacion is None and respuesta.borrador == ""
    assert len(respuesta.fuentes) == 6
    assert presupuesto.llamadas == 1


def test_el_texto_descarta_los_bloques_de_razonamiento_en_lista() -> None:
    mensaje = AIMessage(
        content=[
            {"type": "reasoning", "reasoning": "El pasaje dice 280 bar, asi que..."},
            {"type": "text", "text": "La presión máxima es 280 bar."},
        ]
    )
    assert _texto_de(mensaje) == "La presión máxima es 280 bar."


def test_el_texto_descarta_los_bloques_de_razonamiento_serializados_en_json() -> None:
    mensaje = AIMessage(
        content='[{"type": "reasoning", "summary": [{"text": "pienso"}]}, {"type": "text", "text": "Son 280 bar."}]'
    )
    assert _texto_de(mensaje) == "Son 280 bar."


def test_el_texto_concatena_bloques_de_texto_y_cadenas_sueltas() -> None:
    mensaje = AIMessage(content=["Son ", {"text": "280 bar"}, {"type": "text", "text": "."}])
    assert _texto_de(mensaje) == "Son 280 bar."


@pytest.mark.parametrize(
    "texto",
    [
        "[PET-PERF-007#procedimiento#022] Se detiene la perforación.",
        "[1, 2, 3]",
        '["a", "b"]',
        '[{"sin_tipo": 1}]',
        "[]",
        "[no es json",
        "",
    ],
)
def test_una_cadena_que_no_es_una_lista_de_bloques_se_devuelve_tal_cual(texto: str) -> None:
    assert _texto_de(AIMessage(content=texto)) == texto


def test_una_salida_cortada_por_el_tope_se_entrega_pero_lo_declara(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    class ModeloCortado(FakeListChatModel):
        def invoke(self, *args: object, **kwargs: object) -> AIMessage:
            return AIMessage(
                content="La presión hidráulica máxima es 280 bar y",
                response_metadata={"finish_reason": "length"},
            )

    asistente = Asistente(almacen, ModeloCortado(responses=["x"]), puerta)
    respuesta = asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?")
    assert respuesta.exitosa and respuesta.motivo == MOTIVO_TRUNCADA
    assert respuesta.texto.endswith(" y")


def test_una_salida_completa_no_se_marca_como_truncada(
    almacen: AlmacenLocal, puerta: PuertaDeDominio
) -> None:
    class ModeloCompleto(FakeListChatModel):
        def invoke(self, *args: object, **kwargs: object) -> AIMessage:
            return AIMessage(
                content="La presión hidráulica máxima es 280 bar.",
                response_metadata={"finish_reason": "stop"},
            )

    asistente = Asistente(almacen, ModeloCompleto(responses=["x"]), puerta)
    assert asistente.responder("¿Cuál es la presión hidráulica máxima del equipo?").motivo == "respondida"
