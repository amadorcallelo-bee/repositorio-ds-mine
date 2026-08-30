"""Pruebas del registro en MLflow y del explicador SHAP.

Todas corren contra una base SQLite temporal: el registro tiene que poder probarse sin tocar
el `mlflow.db` del repositorio y sin depender de que exista una corrida previa.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import mlflow
import pandas as pd
import pytest

from aurum_pipeline import domain
from aurum_pipeline.errors import InvalidParameterError
from aurum_pipeline.modeling.baselines import BaselineNivelFrente
from aurum_pipeline.modeling.evaluacion import evaluar_por_pliegues
from aurum_pipeline.modeling.explain import ExplicadorLey
from aurum_pipeline.modeling.features import MINIMO
from aurum_pipeline.modeling.models import ModeloLightGBM
from aurum_pipeline.modeling.splitter import ventana_desde_matriz
from aurum_pipeline.modeling.tracking import (
    ARCHIVO_SEGUIMIENTO,
    VARIABLE_URI,
    RegistroExperimento,
    huella_de_datos,
    raiz_del_repositorio,
    resolver_uri,
    uri_por_defecto,
)
from aurum_pipeline.tests.datos_modelado import matriz_sintetica


@pytest.fixture
def matriz() -> pd.DataFrame:
    return matriz_sintetica()


@pytest.fixture
def registro(tmp_path: Path) -> RegistroExperimento:
    """Registro contra una base temporal, con el experimento aislado por prueba."""
    return RegistroExperimento(uri=f"sqlite:///{tmp_path}/mlflow.db",
                               experimento="prueba_aurum")


# -- resolucion del backend --------------------------------------------------------------


def test_el_uri_sale_del_entorno_o_del_valor_por_defecto(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VARIABLE_URI, raising=False)
    assert resolver_uri() == uri_por_defecto()
    monkeypatch.setenv(VARIABLE_URI, "sqlite:///otro.db")
    assert resolver_uri() == "sqlite:///otro.db"


def test_el_uri_por_defecto_es_absoluto_y_apunta_a_la_raiz() -> None:
    """Un URI relativo pondria la base donde este el directorio de trabajo.

    El notebook corre con `nbconvert` desde su propio directorio: con una ruta relativa la
    base terminaria dentro del paquete y no en la raiz que documenta el README.
    """
    uri = uri_por_defecto()
    assert uri.startswith("sqlite:////")
    assert uri.endswith(ARCHIVO_SEGUIMIENTO)
    assert raiz_del_repositorio() == Path(uri.removeprefix("sqlite:///")).parent


def test_la_raiz_se_encuentra_subiendo_desde_cualquier_subdirectorio() -> None:
    raiz = raiz_del_repositorio()
    assert raiz_del_repositorio(raiz / "modulo_a" / "aurum_pipeline") == raiz


def test_sin_marca_de_raiz_se_usa_el_directorio_de_partida(tmp_path: Path) -> None:
    assert raiz_del_repositorio(tmp_path) == tmp_path.resolve()


def test_la_huella_cambia_cuando_cambia_la_matriz(matriz: pd.DataFrame) -> None:
    original = huella_de_datos(matriz)
    assert original == huella_de_datos(matriz.copy())
    alterada = matriz.copy()
    alterada.loc[0, domain.COLUMNA_OBJETIVO] = 999.0
    assert huella_de_datos(alterada) != original


# -- registro de evaluaciones ------------------------------------------------------------


def test_una_evaluacion_deja_una_corrida_padre_y_una_hija_por_pliegue(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    identificador = registro.registrar_evaluacion(
        resultado, parametros={"modelo": "nivel", "meses_ventana": None},
        fase="fase_de_prueba")

    todas = cast(pd.DataFrame, mlflow.search_runs(
        experiment_names=["prueba_aurum"]))
    assert len(todas) == 3
    padre = todas[todas["run_id"] == identificador].iloc[0]
    assert padre["tags.fase"] == "fase_de_prueba"
    assert padre["params.modelo"] == "nivel"
    # Un parametro nulo se registra como cadena vacia y no revienta el registro.
    assert padre["params.meses_ventana"] == ""
    assert padre["metrics.error_medio_g_por_tonelada"] > 0


def test_la_tabla_de_corridas_excluye_las_hijas(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    registro.registrar_evaluacion(resultado, parametros={}, fase="fase_de_prueba")
    tabla = registro.tabla_de_corridas(fase="fase_de_prueba")
    assert len(tabla) == 1


def test_la_tabla_de_corridas_vacia_no_revienta(registro: RegistroExperimento) -> None:
    assert registro.tabla_de_corridas(fase="fase_inexistente").empty


def test_los_artefactos_quedan_guardados_como_csv(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    identificador = registro.registrar_evaluacion(
        resultado, parametros={}, fase="con_artefactos",
        artefactos={"tabla_de_prueba": pd.DataFrame({"a": [1, 2]})})
    archivos = [a.path for a in mlflow.MlflowClient().list_artifacts(identificador)]
    assert "tabla_de_prueba.csv" in archivos


# -- registro de modelos -----------------------------------------------------------------


def test_el_modelo_se_registra_con_alias_y_se_puede_cargar(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO])
    version = registro.registrar_modelo(
        pipeline, "corrida_de_prueba",
        parametros={"modelo": "lightgbm", "modelo__num_leaves": 15},
        metricas={"error_medio_g_por_tonelada": 0.4},
        ejemplo=matriz.head(2), fase="fase_de_prueba",
        registrar_como="modelo_de_prueba", alias=domain.ALIAS_PRODUCCION)

    assert version is not None
    cargado = mlflow.pyfunc.load_model(
        f"models:/modelo_de_prueba@{domain.ALIAS_PRODUCCION}")
    assert len(cargado.predict(matriz.head(2))) == 2


def test_un_modelo_sin_nombre_de_registro_no_publica_version(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO])
    version = registro.registrar_modelo(
        pipeline, "sin_registrar", parametros={}, metricas={"error": 1.0},
        ejemplo=matriz.head(2), fase="fase_de_prueba")
    assert version is None


def test_los_hiperparametros_pierden_el_prefijo_del_pipeline(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    """`modelo__num_leaves` es ruido de scikit-learn en un panel de operaciones."""
    pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO])
    registro.registrar_modelo(
        pipeline, "nombres_legibles", parametros={"modelo__num_leaves": 15},
        metricas={"error": 1.0}, ejemplo=matriz.head(2), fase="nombres")
    tabla = registro.tabla_de_corridas(fase="nombres")
    assert "params.num_leaves" in tabla.columns
    assert "params.modelo__num_leaves" not in tabla.columns


def test_el_commit_de_git_queda_como_etiqueta(registro: RegistroExperimento) -> None:
    assert "commit_git" in registro.etiquetas_comunes
    assert registro.etiquetas_comunes["semilla"] == str(domain.SEMILLA)


# -- explicador SHAP ---------------------------------------------------------------------


def test_el_explicador_atribuye_sobre_las_columnas_que_vio_el_modelo(
        matriz: pd.DataFrame) -> None:
    pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO])
    explicador = ExplicadorLey(pipeline)
    valores = explicador.valores(matriz.head(20))
    assert list(valores.columns) == list(MINIMO.columnas)
    assert len(valores) == 20


def test_la_importancia_suma_cien_por_ciento(matriz: pd.DataFrame) -> None:
    pipeline = ModeloLightGBM().pipeline().fit(matriz, matriz[domain.COLUMNA_OBJETIVO])
    tabla = ExplicadorLey(pipeline).importancia(matriz.head(30))
    assert tabla["contribucion_pct"].sum() == pytest.approx(100.0)
    assert tabla["contribucion_media_g_por_tonelada"].is_monotonic_decreasing


def test_la_figura_de_shap_se_guarda(matriz: pd.DataFrame, tmp_path: Path) -> None:
    pipeline = ModeloLightGBM(conjunto=MINIMO).pipeline().fit(
        matriz, matriz[domain.COLUMNA_OBJETIVO])
    ruta = ExplicadorLey(pipeline).figura_resumen(
        matriz.head(20), tmp_path / "figuras" / "shap.png")
    assert ruta.exists()
    assert ruta.stat().st_size > 0


def test_un_pipeline_de_un_paso_no_se_puede_explicar() -> None:
    from sklearn.pipeline import Pipeline

    from aurum_pipeline.modeling.features import CodificadorNivelFrente

    with pytest.raises(InvalidParameterError, match="al menos un transformador"):
        ExplicadorLey(Pipeline([("nivel", CodificadorNivelFrente())]))


def test_el_registro_usa_el_uri_del_entorno_si_no_se_le_pasa_uno(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE_URI, f"sqlite:///{tmp_path}/desde_entorno.db")
    registro = RegistroExperimento(experimento="desde_entorno")
    assert registro.uri.endswith("desde_entorno.db")
    assert os.environ[VARIABLE_URI] == registro.uri


def test_sin_git_el_commit_queda_como_desconocido(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """El experimento tiene que poder correr fuera de un repositorio."""
    import subprocess

    from aurum_pipeline.modeling import tracking

    def sin_git(*_: object, **__: object) -> None:
        raise OSError("git no esta disponible")

    monkeypatch.setattr(subprocess, "run", sin_git)
    assert tracking._commit_actual() == "desconocido"


def test_la_tabla_sin_filtro_de_fase_descarta_las_hijas(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    registro.registrar_evaluacion(resultado, parametros={}, fase="sin_filtro")
    todas = registro.tabla_de_corridas()
    assert len(todas) == 1


def test_el_registro_puede_cambiar_de_experimento(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    """Un mismo objeto de seguimiento sirve a los dos problemas del A-2."""
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    registro.registrar_evaluacion(resultado, parametros={}, fase="en_el_primero")

    registro.usar_experimento("segundo_experimento")
    assert registro.experimento == "segundo_experimento"
    registro.registrar_evaluacion(resultado, parametros={}, fase="en_el_segundo")
    assert len(registro.tabla_de_corridas()) == 1

    registro.usar_experimento("prueba_aurum")
    assert len(registro.tabla_de_corridas()) == 1


# -- entrenamiento, brecha y ubicacion de artefactos ---------------------------------------


def test_padre_e_hijas_registran_entrenamiento_y_brecha(
        registro: RegistroExperimento, matriz: pd.DataFrame) -> None:
    ventana = ventana_desde_matriz(matriz, pliegues=2)
    resultado = evaluar_por_pliegues(BaselineNivelFrente(), matriz, ventana, "nivel")
    identificador = registro.registrar_evaluacion(
        resultado, parametros={}, fase="con_brecha")

    todas = cast(pd.DataFrame, mlflow.search_runs(experiment_names=["prueba_aurum"]))
    padre = todas[todas["run_id"] == identificador].iloc[0]
    hijas = todas[todas["tags.mlflow.parentRunId"] == identificador]
    assert len(hijas) == 2
    assert padre["metrics.error_medio_g_por_tonelada_entrenamiento"] == pytest.approx(
        resultado.valor_principal_entrenamiento)
    assert padre["metrics.brecha_entrenamiento_validacion"] == pytest.approx(
        resultado.brecha_entrenamiento_validacion)
    assert hijas["metrics.brecha_entrenamiento_validacion"].notna().all()
    assert hijas["metrics.error_medio_g_por_tonelada_entrenamiento"].notna().all()


def test_los_artefactos_quedan_junto_a_la_base_sqlite(tmp_path: Path) -> None:
    """Reproduce el defecto: `mlruns/` quedaba en el directorio de trabajo.

    Ese directorio era el del notebook o el de las pruebas, y no el que el README decia.
    """
    RegistroExperimento(uri=f"sqlite:///{tmp_path}/mlflow.db", experimento="anclado")
    experimento = mlflow.get_experiment_by_name("anclado")
    assert experimento is not None
    esperado = (tmp_path.resolve() / "mlartifacts" / "anclado").as_uri()
    assert experimento.artifact_location == esperado


def test_un_experimento_que_ya_existe_conserva_su_ubicacion(tmp_path: Path) -> None:
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    mlflow.set_tracking_uri(uri)
    mlflow.create_experiment("previo", artifact_location=(tmp_path / "otro").as_uri())
    RegistroExperimento(uri=uri, experimento="previo")
    experimento = mlflow.get_experiment_by_name("previo")
    assert experimento is not None
    assert experimento.artifact_location == (tmp_path / "otro").as_uri()


def test_con_otro_backend_la_ubicacion_de_artefactos_la_decide_el_servidor(
        registro: RegistroExperimento, monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo con SQLite se anclan los artefactos; con un servidor remoto no se toca nada."""
    def no_debe_llamarse(*args: object, **kwargs: object) -> None:
        raise AssertionError("no se debe crear el experimento con ubicacion propia")

    monkeypatch.setattr(mlflow, "create_experiment", no_debe_llamarse)
    registro.uri = "http://servidor-remoto:5000"
    registro._asegurar_experimento("experimento_remoto_inexistente")


# -- el clasificador tambien se explica ----------------------------------------------------


def test_el_explicador_de_falla_atribuye_sobre_la_clase_positiva(matriz: pd.DataFrame) -> None:
    from aurum_pipeline.modeling.classifiers import ClasificadorLightGBM, ClasificadorXGBoost
    from aurum_pipeline.modeling.explain import ExplicadorFalla
    from aurum_pipeline.modeling.features import ACTIVIDAD

    for fabrica in (ClasificadorLightGBM, ClasificadorXGBoost):
        pipeline = fabrica(conjunto=ACTIVIDAD).pipeline().fit(matriz, matriz["falla_en_4h"])
        explicador = ExplicadorFalla(pipeline)
        valores = explicador.valores(matriz)
        assert valores.shape == (len(matriz), len(ACTIVIDAD.columnas))
        importancia = explicador.importancia(matriz)
        assert set(importancia["variable"]) == set(ACTIVIDAD.columnas)
        assert importancia["contribucion_pct"].sum() == pytest.approx(100.0)


def eventos_de_sonda(semilla: int = 3) -> pd.DataFrame:
    """Eventos sinteticos donde la falla ocurre exactamente cuando el motor pasa de 88 C.

    La temperatura de cada evento es independiente de la del anterior, como en el extracto,
    de modo que la falla del evento siguiente no se puede anticipar desde el actual.
    """
    import numpy as np

    generador = np.random.default_rng(semilla)
    filas = []
    for frente in ("FR-A", "FR-B"):
        inicio = pd.Timestamp("2025-01-01 00:00:00")
        for k in range(400):
            temperatura = 72.0 + generador.normal(0, 9)
            filas.append({
                domain.COLUMNA_FRENTE: frente,
                domain.COLUMNA_INICIO_TURNO: inicio + pd.Timedelta(minutes=25 * k),
                domain.COLUMNA_FALLA: "M-MOTOR-01" if temperatura > 88.0 else None,
                domain.COLUMNA_TEMPERATURA: temperatura,
                domain.COLUMNA_PRESION: 200.0 + generador.normal(0, 8),
                domain.COLUMNA_RPM: 1000.0 + generador.normal(0, 60),
                domain.COLUMNA_AVANCE: 1.5 + generador.normal(0, 0.1),
                domain.COLUMNA_AGUA: 50.0 + generador.normal(0, 3),
                domain.COLUMNA_VIBRACION: 5.0 + generador.normal(0, 1),
                domain.COLUMNA_TONELAJE: 100.0 + generador.normal(0, 5),
            })
    return pd.DataFrame(filas)


def test_la_sonda_ve_la_temperatura_a_horizonte_cero_y_nada_a_un_evento() -> None:
    from aurum_pipeline.modeling.explain import (
        HORIZONTE_EVENTO_SIGUIENTE,
        HORIZONTE_MISMO_EVENTO,
        SondaContemporanea,
    )

    eventos = eventos_de_sonda()
    corte = pd.Timestamp(eventos[domain.COLUMNA_INICIO_TURNO].quantile(0.7))
    sonda = SondaContemporanea().ajustar(eventos, corte=corte)
    por_horizonte = {fila["horizonte"]: fila for fila in sonda.resultados_.to_dict("records")}
    assert por_horizonte[HORIZONTE_MISMO_EVENTO]["precision_media"] > 0.9
    # A un evento no queda senal: la precision media vuelve a la tasa base, con margen.
    siguiente = por_horizonte[HORIZONTE_EVENTO_SIGUIENTE]
    assert siguiente["precision_media"] < 2.0 * siguiente["tasa_base_falla"]
    assert sonda.importancia_.iloc[0]["variable"] == domain.COLUMNA_TEMPERATURA
    assert sonda.importancia_.iloc[0]["contribucion_pct"] > 50.0
    assert sonda.importancia_["contribucion_pct"].sum() == pytest.approx(100.0)


def test_la_sonda_valida_sus_precondiciones() -> None:
    from aurum_pipeline.errors import EmptyPartitionError, MissingColumnsError
    from aurum_pipeline.modeling.explain import SondaContemporanea

    eventos = eventos_de_sonda()
    with pytest.raises(InvalidParameterError, match="al menos un sensor"):
        SondaContemporanea(sensores=())
    with pytest.raises(MissingColumnsError, match=domain.COLUMNA_TEMPERATURA):
        SondaContemporanea().ajustar(eventos.drop(columns=[domain.COLUMNA_TEMPERATURA]),
                                     corte=pd.Timestamp(eventos[domain.COLUMNA_INICIO_TURNO].median()))
    with pytest.raises(EmptyPartitionError, match="para evaluar"):
        SondaContemporanea().ajustar(
            eventos, corte=eventos[domain.COLUMNA_INICIO_TURNO].max() + pd.Timedelta(days=1))
