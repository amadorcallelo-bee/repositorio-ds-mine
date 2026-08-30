"""Pruebas del servicio de inferencia.

La prueba central de este modulo es la distincion entre rango operacional y limite fisico: un
valor de alerta tiene que entrar y volver marcado, y solo lo imposible tiene que producir un
422. Es la decision de diseno que se toma en `schemas.py` y la que, si se rompe, deja la API
rechazando exactamente los turnos por los que alguien llama a preguntar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aurum_pipeline import domain
from aurum_pipeline.modeling.features import (
    COMPLETO,
    CONJUNTOS,
    columnas_de_entrada,
    tipos_de_servicio,
)
from aurum_pipeline.modeling.models import ModeloLightGBM
from aurum_pipeline.serving.app import CLAVE_PREDICTOR, crear_aplicacion
from aurum_pipeline.serving.predictor import (
    VARIABLE_MODELO_FALLA,
    VARIABLE_MODELO_LEY,
    ModeloNoDisponibleError,
    PredictorAurum,
    uri_modelo,
)
from aurum_pipeline.serving.schemas import CondicionesTurno
from aurum_pipeline.tests.datos_modelado import matriz_sintetica

TURNO_NORMAL: dict[str, Any] = {
    "frente_id": "FR-0",
    "turno_cod": "D1",
    "tipo_mineral": "OX",
    "ley_turno": 8.0,
    "ton_rom_acum": 100.0,
    "pres_hidraul_bar": 200.0,
    "rpm_corona": 1000.0,
    "avance_mmin": 1.5,
    "agua_iny_lmin": 50.0,
    "vibracion_rms_ms2": 5.0,
    "temp_motor_c": 70.0,
}


@pytest.fixture
def matriz() -> pd.DataFrame:
    return matriz_sintetica(frentes=2, turnos_por_frente=30)


@pytest.fixture
def registry(tmp_path: Path, matriz: pd.DataFrame) -> str:
    """Registra un modelo de ley y uno de falla en un registry temporal."""
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    # Los artefactos se anclan al directorio temporal, como hace RegistroExperimento con la
    # base: sin esto MLflow deja un `mlruns/` en la raiz del repositorio en cada corrida.
    mlflow.create_experiment(
        "servicio_de_prueba", artifact_location=(tmp_path / "mlartifacts").as_uri())
    mlflow.set_experiment("servicio_de_prueba")

    ley = ModeloLightGBM(conjunto=COMPLETO).pipeline().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO])
    # El ejemplo se arma igual que en el experimento real, incluida la conversion de tipos:
    # es lo que hace que la firma registrada sea la misma que el servicio va a satisfacer.
    ejemplo = tipos_de_servicio(matriz.loc[:, list(columnas_de_entrada(COMPLETO))].head(3))
    with mlflow.start_run(run_name="ley"):
        mlflow.sklearn.log_model(
            ley, name="modelo_ley", serialization_format="cloudpickle",
            input_example=ejemplo, registered_model_name="ley_de_prueba")
    mlflow.MlflowClient().set_registered_model_alias(
        "ley_de_prueba", domain.ALIAS_PRODUCCION, "1")
    return uri


@pytest.fixture
def predictor(registry: str) -> PredictorAurum:
    listo = PredictorAurum(uri_ley=uri_modelo("ley_de_prueba"),
                           uri_falla=uri_modelo("no_existe"),
                           uri_seguimiento=registry)
    listo.cargar()
    return listo


# -- esquema de entrada ------------------------------------------------------------------


def test_un_turno_normal_no_produce_alertas() -> None:
    assert CondicionesTurno(**TURNO_NORMAL).alertas() == []


def test_los_valores_de_alerta_se_aceptan_y_se_marcan() -> None:
    """Vibracion sobre 12 y temperatura sobre 95 son alertas, no imposibles."""
    condiciones = CondicionesTurno(
        **{**TURNO_NORMAL, "vibracion_rms_ms2": 15.0, "temp_motor_c": 99.0})
    avisos = condiciones.alertas()
    assert any("vibracion_rms_ms2" in aviso for aviso in avisos)
    assert any("temp_motor_c" in aviso for aviso in avisos)


def test_la_presion_fuera_del_rango_operacional_se_marca_por_los_dos_extremos() -> None:
    baja = CondicionesTurno(**{**TURNO_NORMAL, "pres_hidraul_bar": 100.0}).alertas()
    alta = CondicionesTurno(**{**TURNO_NORMAL, "pres_hidraul_bar": 300.0}).alertas()
    assert any("por debajo" in aviso for aviso in baja)
    assert any("por encima" in aviso for aviso in alta)


def test_un_turno_sin_lecturas_de_la_sonda_se_marca() -> None:
    avisos = CondicionesTurno(**{**TURNO_NORMAL, "lecturas_ley_turno": 0}).alertas()
    assert any("sonda XRF" in aviso for aviso in avisos)


def test_el_marco_lleva_los_nombres_internos_de_opus() -> None:
    marco = CondicionesTurno(**TURNO_NORMAL).como_marco()
    assert len(marco) == 1
    for columna in (domain.COLUMNA_FRENTE, domain.COLUMNA_TURNO, domain.COLUMNA_PRESION):
        assert columna in marco.columns


# -- servicio ----------------------------------------------------------------------------


def test_el_servicio_responde_listo_con_el_modelo_de_ley(
        predictor: PredictorAurum) -> None:
    with TestClient(crear_aplicacion(predictor)) as cliente:
        cuerpo = cliente.get("/health").json()
    assert cuerpo["estado"] == "listo"
    assert cuerpo["modelo_ley"] is not None
    assert cuerpo["modelo_falla"] is None


def test_un_turno_valido_devuelve_ley_estimada(predictor: PredictorAurum) -> None:
    with TestClient(crear_aplicacion(predictor)) as cliente:
        respuesta = cliente.post("/predict", json=TURNO_NORMAL)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["frente_id"] == "FR-0"
    assert cuerpo["ley_estimada"] > 0
    assert cuerpo["prob_falla_4h"] is None
    assert cuerpo["alertas"] == []


def test_un_turno_de_alerta_responde_200_y_no_422(predictor: PredictorAurum) -> None:
    """Es la prueba de la decision: la alerta se acepta y vuelve marcada."""
    with TestClient(crear_aplicacion(predictor)) as cliente:
        respuesta = cliente.post(
            "/predict", json={**TURNO_NORMAL, "vibracion_rms_ms2": 18.0,
                              "temp_motor_c": 101.0})
    assert respuesta.status_code == 200
    assert len(respuesta.json()["alertas"]) == 2


@pytest.mark.parametrize("campo,valor", [
    ("pres_hidraul_bar", -1.0),
    ("rpm_corona", -50.0),
    ("temp_motor_c", -300.0),
    ("ley_turno", -2.0),
    ("turno_cod", "D3"),
    ("tipo_mineral", "XX"),
])
def test_lo_fisicamente_imposible_se_rechaza_con_422(
        predictor: PredictorAurum, campo: str, valor: object) -> None:
    with TestClient(crear_aplicacion(predictor)) as cliente:
        respuesta = cliente.post("/predict", json={**TURNO_NORMAL, campo: valor})
    assert respuesta.status_code == 422


def test_un_campo_desconocido_se_rechaza(predictor: PredictorAurum) -> None:
    with TestClient(crear_aplicacion(predictor)) as cliente:
        respuesta = cliente.post("/predict", json={**TURNO_NORMAL, "inventado": 1})
    assert respuesta.status_code == 422


def test_los_rezagos_son_opcionales(predictor: PredictorAurum) -> None:
    with TestClient(crear_aplicacion(predictor)) as cliente:
        sin_rezagos = cliente.post("/predict", json=TURNO_NORMAL)
        con_rezagos = cliente.post(
            "/predict", json={**TURNO_NORMAL, "ley_rezago_1": 7.5, "ley_media_10": 7.8})
    assert sin_rezagos.status_code == con_rezagos.status_code == 200


def test_sin_modelo_el_servicio_vive_pero_no_predice(tmp_path: Path) -> None:
    """Un despliegue sin modelo publicado es un servicio incompleto, no uno caido."""
    vacio = PredictorAurum(uri_ley=uri_modelo("no_existe"),
                           uri_falla=uri_modelo("tampoco"),
                           uri_seguimiento=f"sqlite:///{tmp_path}/vacio.db")
    with TestClient(crear_aplicacion(vacio)) as cliente:
        assert cliente.get("/health").json()["estado"] == "sin_modelo"
        assert cliente.post("/predict", json=TURNO_NORMAL).status_code == 503


def test_el_predictor_sin_modelo_falla_con_excepcion_propia(tmp_path: Path) -> None:
    vacio = PredictorAurum(uri_ley=uri_modelo("no_existe"),
                           uri_seguimiento=f"sqlite:///{tmp_path}/vacio.db")
    vacio.cargar()
    with pytest.raises(ModeloNoDisponibleError, match="no_existe"):
        vacio.predecir(CondicionesTurno(**TURNO_NORMAL))
    assert vacio.listo is False


def test_las_uri_salen_del_entorno_cuando_no_se_pasan(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE_MODELO_LEY, "models:/otro_ley@produccion")
    monkeypatch.setenv(VARIABLE_MODELO_FALLA, "models:/otro_falla@produccion")
    predictor = PredictorAurum()
    assert predictor.uri_ley == "models:/otro_ley@produccion"
    assert predictor.uri_falla == "models:/otro_falla@produccion"


def test_la_probabilidad_de_falla_sale_del_clasificador(
        registry: str, matriz: pd.DataFrame) -> None:
    """El pyfunc de un clasificador devuelve la clase; el servicio pide la probabilidad."""
    from aurum_pipeline.modeling.classifiers import ClasificadorLightGBM

    mlflow.set_tracking_uri(registry)
    mlflow.set_registry_uri(registry)
    falla = ClasificadorLightGBM(conjunto=COMPLETO).pipeline().fit(
        matriz, matriz["falla_en_4h"])
    ejemplo = tipos_de_servicio(matriz.loc[:, list(columnas_de_entrada(COMPLETO))].head(3))
    with mlflow.start_run(run_name="falla"):
        mlflow.sklearn.log_model(
            falla, name="modelo_falla", serialization_format="cloudpickle",
            input_example=ejemplo, registered_model_name="falla_de_prueba")
    mlflow.MlflowClient().set_registered_model_alias(
        "falla_de_prueba", domain.ALIAS_PRODUCCION, "1")

    completo = PredictorAurum(uri_ley=uri_modelo("ley_de_prueba"),
                              uri_falla=uri_modelo("falla_de_prueba"),
                              uri_seguimiento=registry)
    completo.cargar()
    aplicacion = crear_aplicacion(completo)
    with TestClient(aplicacion) as cliente:
        cuerpo = cliente.post("/predict", json=TURNO_NORMAL).json()
    assert 0.0 <= cuerpo["prob_falla_4h"] <= 1.0
    assert cuerpo["modelo_falla"] is not None
    # Al apagarse, el ciclo de vida suelta el predictor: el servicio no deja modelos en
    # memoria despues de cerrar.
    assert getattr(aplicacion.state, CLAVE_PREDICTOR) is None


def test_un_modelo_de_falla_sin_estimador_interno_cae_a_predict(
        predictor: PredictorAurum) -> None:
    """Si MLflow cambia como envuelve el modelo, el servicio degrada en vez de reventar."""

    class ModeloPlano:
        """Envoltorio sin `_model_impl`, como el de un flavor que no expone el estimador."""

        @staticmethod
        def predict(marco: pd.DataFrame) -> list[float]:
            return [0.42] * len(marco)

    predictor.modelo_falla = ModeloPlano()
    respuesta = predictor.predecir(CondicionesTurno(**TURNO_NORMAL))
    assert respuesta.prob_falla_4h == pytest.approx(0.42)


def test_el_esquema_de_la_api_cubre_las_entradas_de_todos_los_conjuntos() -> None:
    """El contrato de `/predict` tiene que satisfacer la firma que MLflow hace cumplir.

    Es la prueba que faltaba: el `input_example` con que se registra el modelo define una
    firma, y si el esquema del servicio no la cubre, la primera peticion real falla por
    esquema aunque todas las pruebas de la API pasen.
    """
    del_esquema = set(CondicionesTurno.model_fields)
    for conjunto in CONJUNTOS:
        faltantes = set(columnas_de_entrada(conjunto)) - del_esquema
        assert not faltantes, f"{conjunto.nombre} exige campos que la API no recibe: {faltantes}"


def test_el_marco_de_la_api_satisface_la_firma_de_un_modelo_registrado(
        predictor: PredictorAurum) -> None:
    """Reproduce el defecto: un modelo con firma inferida rechazaba el marco del servicio."""
    condiciones = CondicionesTurno(**TURNO_NORMAL)
    marco = condiciones.como_marco()
    for columna in columnas_de_entrada(COMPLETO):
        assert columna in marco.columns
    # Sin rezagos, las columnas opcionales tienen que llegar como faltante numerico y no como
    # objeto: una columna de objetos no satisface una firma `double`.
    assert marco["ley_rezago_1"].dtype == "float64"
    assert marco["ley_rezago_1"].isna().all()
    assert predictor.predecir(condiciones).ley_estimada > 0


# -- resumen de actividad y por umbral ----------------------------------------------------


def test_el_resumen_de_actividad_es_opcional_y_llega_como_faltante_numerico(
        predictor: PredictorAurum) -> None:
    """Sin los campos nuevos el modelo recibe faltantes flotantes, no objetos."""
    marco = CondicionesTurno(**TURNO_NORMAL).como_marco()
    for columna in (domain.COLUMNA_MINUTOS_INACTIVO, domain.COLUMNA_TEMP_MAX,
                    domain.COLUMNA_EVENTOS_TEMP_RIESGO, domain.COLUMNA_VIB_MAX,
                    domain.COLUMNA_EVENTOS_VIB_ALERTA):
        assert marco[columna].dtype == "float64"
        assert marco[columna].isna().all()
    with TestClient(crear_aplicacion(predictor)) as cliente:
        con_actividad = cliente.post("/predict", json={
            **TURNO_NORMAL, "minutos_inactivo_al_cierre": 25.0, "temp_max_turno": 97.0,
            "eventos_temp_riesgo": 2, "vib_max_turno": 13.5, "eventos_vib_alerta": 1})
    assert con_actividad.status_code == 200


@pytest.mark.parametrize("campo,valor", [
    ("minutos_inactivo_al_cierre", -5.0),
    ("minutos_inactivo_al_cierre", 400.0),
    ("eventos_temp_riesgo", -1),
    ("temp_max_turno", -300.0),
])
def test_un_resumen_de_actividad_imposible_se_rechaza_con_422(
        predictor: PredictorAurum, campo: str, valor: object) -> None:
    with TestClient(crear_aplicacion(predictor)) as cliente:
        respuesta = cliente.post("/predict", json={**TURNO_NORMAL, campo: valor})
    assert respuesta.status_code == 422
