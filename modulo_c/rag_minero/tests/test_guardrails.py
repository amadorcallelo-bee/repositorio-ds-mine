"""Pruebas de los guardrails: la puerta de dominio se calibra y el verificador bloquea."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_minero.chunking import Trozador
from rag_minero.guardrails import (
    Calibrador,
    PuertaDeDominio,
    VerificadorDeHechos,
    Vocabulario,
    extraer_hechos,
    normalizar_termino,
    terminos_de_contenido,
)
from rag_minero.tests.datos import corpus

CONTROL = json.loads((Path(__file__).parent.parent / "preguntas_control.json").read_text())
GOLDEN = json.loads((Path(__file__).parent.parent / "golden_set.json").read_text())


@pytest.fixture
def vocabulario() -> Vocabulario:
    chunks = Trozador.por_genero_y_elemento().trocear(corpus())
    return Vocabulario.desde_textos(c.page_content for c in chunks)


# --- terminos ---


def test_normalizar_termino_quita_tildes_y_mayusculas() -> None:
    assert normalizar_termino("Presión") == "presion"
    assert normalizar_termino("H-HIDRA-02") == "h-hidra-02"


def test_terminos_de_contenido_excluye_vacias_y_cortas_pero_conserva_codigos() -> None:
    terminos = terminos_de_contenido("¿Qué debo hacer si la presión cae y reporto H-HIDRA-02 en FR-S2-03?")
    assert "presion" in terminos and "reporto" in terminos
    assert "h-hidra-02" in terminos and "fr-s2-03" in terminos
    assert "que" not in terminos and "debo" not in terminos and "cae" not in terminos
    assert "hidra" not in terminos


# --- vocabulario y cobertura ---


def test_una_pregunta_del_dominio_tiene_cobertura_alta(vocabulario: Vocabulario) -> None:
    assert vocabulario.cobertura("¿Cuál es la presión hidráulica máxima del equipo?") >= 0.6


def test_una_pregunta_de_cocina_tiene_cobertura_baja(vocabulario: Vocabulario) -> None:
    assert vocabulario.cobertura("¿Cómo preparo una paella valenciana para seis personas?") <= 0.2


def test_una_pregunta_sin_terminos_de_contenido_tiene_cobertura_cero(vocabulario: Vocabulario) -> None:
    assert vocabulario.cobertura("¿Y eso?") == 0.0


# --- puerta de dominio ---


def test_la_puerta_rechaza_fuera_de_dominio_con_motivo(vocabulario: Vocabulario) -> None:
    puerta = PuertaDeDominio(vocabulario, cobertura_minima=0.4)
    veredicto = puerta.evaluar("¿Quién ganó la Copa Libertadores de 2023?")
    assert not veredicto.aceptada
    assert "fuera de dominio" in veredicto.motivo


def test_la_puerta_acepta_una_pregunta_del_dominio(vocabulario: Vocabulario) -> None:
    puerta = PuertaDeDominio(vocabulario, cobertura_minima=0.4)
    assert puerta.evaluar("¿Qué hago si la presión hidráulica cae durante la perforación?").aceptada


def test_la_puerta_usa_el_score_cuando_se_le_entrega(vocabulario: Vocabulario) -> None:
    puerta = PuertaDeDominio(vocabulario, cobertura_minima=0.4, score_minimo=0.3)
    pregunta = "¿Cuál es la presión hidráulica máxima?"
    assert puerta.evaluar(pregunta, mejor_score=0.8).aceptada
    rechazo = puerta.evaluar(pregunta, mejor_score=0.1)
    assert not rechazo.aceptada and "sin pasajes relevantes" in rechazo.motivo


def test_la_puerta_ignora_el_score_si_no_se_configuro(vocabulario: Vocabulario) -> None:
    puerta = PuertaDeDominio(vocabulario, cobertura_minima=0.4)
    assert puerta.evaluar("¿Cuál es la presión hidráulica máxima?", mejor_score=0.0).aceptada


def test_una_cobertura_minima_fuera_de_rango_falla(vocabulario: Vocabulario) -> None:
    with pytest.raises(ValueError):
        PuertaDeDominio(vocabulario, cobertura_minima=1.5)


def test_el_limite_exacto_del_umbral_se_acepta(vocabulario: Vocabulario) -> None:
    pregunta = "presión hidráulica"
    puerta = PuertaDeDominio(vocabulario, cobertura_minima=vocabulario.cobertura(pregunta))
    assert puerta.evaluar(pregunta).aceptada


# --- calibracion con los conjuntos de control reales ---


def test_el_calibrador_separa_el_golden_set_de_las_preguntas_fuera_de_dominio(
    vocabulario: Vocabulario,
) -> None:
    del_dominio = [c["pregunta"] for c in GOLDEN["casos"]]
    calibracion = Calibrador(vocabulario).calibrar(del_dominio, CONTROL["fuera_de_dominio"])
    assert calibracion.rechazadas_fuera == calibracion.total_fuera == 10
    assert calibracion.aceptadas_del_dominio >= 8
    assert 0.0 < calibracion.cobertura_minima < 1.0


def test_el_calibrador_elige_el_punto_medio_cuando_separa() -> None:
    vocabulario = Vocabulario(frozenset({"presion", "hidraulica", "corona"}))
    calibracion = Calibrador(vocabulario).calibrar(
        ["presion hidraulica corona"], ["paella valenciana receta"]
    )
    assert calibracion.separa_perfectamente
    assert calibracion.cobertura_minima == pytest.approx(0.5)


def test_el_calibrador_maximiza_aciertos_cuando_no_separa() -> None:
    vocabulario = Vocabulario(frozenset({"alfa", "beta", "gama"}))
    calibracion = Calibrador(vocabulario).calibrar(
        ["alfa beta", "alfa zeta"], ["alfa beta gama zeta omega", "zeta omega"]
    )
    assert not calibracion.separa_perfectamente
    assert calibracion.cobertura_minima == pytest.approx(0.5)
    assert calibracion.aceptadas_del_dominio + calibracion.rechazadas_fuera == 3


def test_el_calibrador_exige_los_dos_conjuntos(vocabulario: Vocabulario) -> None:
    with pytest.raises(ValueError):
        Calibrador(vocabulario).calibrar([], ["x"])


# --- verificador de hechos ---


def test_extraer_hechos_normaliza_miles_y_decimales_y_toma_codigos() -> None:
    hechos = extraer_hechos("Ley 9.21 g/t, 2,280 USD, 1,500 RPM, rango 160\u2013200 bar, código H-HIDRA-02 en FR-S2-03.")
    for esperado in ("9.21", "2280", "1500", "160", "200", "H-HIDRA-02", "FR-S2-03"):
        assert esperado in hechos, esperado


def test_extraer_hechos_no_toma_los_digitos_de_un_codigo_como_cifra() -> None:
    assert "02" not in extraer_hechos("Reportar H-HIDRA-02.")


def test_una_respuesta_con_cifras_respaldadas_se_aprueba() -> None:
    contexto = ["Presión hidráulica máxima — Especificación: 280; Unidad: bar; No operar >260 bar."]
    verificacion = VerificadorDeHechos().verificar("La presión máxima es 280 bar y no se opera sobre 260 bar.", contexto)
    assert verificacion.aprobada
    assert set(verificacion.respaldados) == {"280", "260"}


def test_una_cifra_inventada_bloquea_la_respuesta_y_se_nombra() -> None:
    contexto = ["Presión hidráulica máxima — Especificación: 280; Unidad: bar."]
    verificacion = VerificadorDeHechos().verificar("La Sandvik DL432 soporta 300 bar.", contexto)
    assert not verificacion.aprobada
    assert verificacion.sin_respaldo == ("300",)


def test_un_codigo_inventado_bloquea_la_respuesta() -> None:
    contexto = ["CP-03 — Acción inmediata: Detener. Reportar H-HIDRA-02."]
    verificacion = VerificadorDeHechos().verificar("Reportar H-HIDRA-09.", contexto)
    assert not verificacion.aprobada and "H-HIDRA-09" in verificacion.sin_respaldo


def test_una_respuesta_sin_hechos_se_aprueba_y_declara_falta_de_respaldo() -> None:
    verificacion = VerificadorDeHechos().verificar(
        "Esa especificación no está en la documentación disponible.", ["texto sin relacion"]
    )
    assert verificacion.aprobada and verificacion.declara_falta_de_respaldo
    assert verificacion.respaldados == () and verificacion.sin_respaldo == ()


def test_los_miles_con_coma_del_contexto_respaldan_la_cifra_sin_coma() -> None:
    verificacion = VerificadorDeHechos().verificar("El precio es 2280 USD por onza.", ["Au = USD 2,280/oz"])
    assert verificacion.aprobada


def test_el_verificador_no_se_deja_enganar_por_un_contexto_vacio() -> None:
    verificacion = VerificadorDeHechos().verificar("Son 280 bar.", [])
    assert not verificacion.aprobada
