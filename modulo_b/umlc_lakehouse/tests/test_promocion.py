"""Pruebas del trigger, el registro en MLflow y la resolucion staging contra produccion."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import mlflow
import pandas as pd
import pytest

from umlc_lakehouse import dominio
from umlc_lakehouse.deriva import ResultadoPsi, Veredicto
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.modelo import EntrenadorLey
from umlc_lakehouse.promocion import (
    DecisorReentrenamiento,
    PromotorModelos,
    RegistroMlops,
)
from umlc_lakehouse.tests.conftest import eventos_sinteticos


def _psi(psi: float, ambito: str = "global", variable: str = "ley_au_gpT") -> ResultadoPsi:
    veredicto: Veredicto = (
        "critico" if psi > 0.2 else "moderado" if psi > 0.1 else "estable")
    return ResultadoPsi(variable=variable, ambito=ambito, psi=psi, veredicto=veredicto,
                        n_referencia=100, n_actual=100, proporciones=((0.5, 0.5),))


def test_el_trigger_dispara_por_psi_global_y_no_por_sector() -> None:
    decisor = DecisorReentrenamiento()
    quieta = decisor.decidir([_psi(0.05), _psi(0.19)], None, None)
    assert not quieta.reentrenar and quieta.razones == ()
    global_critico = decisor.decidir([_psi(0.25)], None, None)
    assert global_critico.reentrenar
    assert "0.2500" in global_critico.razones[0]
    solo_sector = decisor.decidir([_psi(0.05), _psi(0.9, ambito="Veta-Sur")], None, None)
    assert not solo_sector.reentrenar


def test_el_trigger_dispara_por_degradacion_estricta_del_error() -> None:
    decisor = DecisorReentrenamiento()
    justo_en_el_umbral = decisor.decidir([], 1.15, 1.0)
    assert not justo_en_el_umbral.reentrenar
    degradado = decisor.decidir([], 1.1501, 1.0)
    assert degradado.reentrenar and "15%" in degradado.razones[0]
    sin_baseline = decisor.decidir([], 1.5, None)
    assert not sin_baseline.reentrenar
    with pytest.raises(ParametroInvalidoError):
        DecisorReentrenamiento(umbral_psi=0.0)


@pytest.fixture
def registro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RegistroMlops:
    """MLflow completo sobre SQLite temporal, con los artefactos dentro del tmp."""
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    return RegistroMlops(uri, uri, nombre_modelo="modelo_prueba_b3")


def test_bootstrap_registra_produccion_con_las_metricas_del_a2(
        registro: RegistroMlops) -> None:
    modelo = EntrenadorLey().entrenar(eventos_sinteticos(dias=21))
    version = registro.registrar_entrenamiento(modelo, dominio.ALIAS_PRODUCCION, "bootstrap")
    en_alias = registro.version_por_alias(dominio.ALIAS_PRODUCCION)
    assert en_alias is not None and en_alias.version == version.version
    assert registro.version_por_alias(dominio.ALIAS_STAGING) is None
    assert registro.error_registrado(version) == pytest.approx(
        modelo.metricas[dominio.METRICA_ERROR])
    cargado = registro.cargar(dominio.ALIAS_PRODUCCION)
    prediccion = cargado.predict(pd.DataFrame({dominio.COLUMNA_FRENTE: ["FR-A-01"]}))
    assert prediccion[0] == pytest.approx(5.0, abs=0.1)


def test_un_staging_peor_o_igual_produce_rollback_registrado(
        registro: RegistroMlops) -> None:
    modelo = EntrenadorLey().entrenar(eventos_sinteticos(dias=21))
    produccion = registro.registrar_entrenamiento(modelo, dominio.ALIAS_PRODUCCION, "bootstrap")
    candidato = registro.registrar_entrenamiento(
        replace(modelo, metricas={**modelo.metricas, dominio.METRICA_ERROR: 0.9}),
        dominio.ALIAS_STAGING, "candidato")
    promotor = PromotorModelos(registro)
    assert promotor.resolver(candidato, 0.9, 0.5, ["PSI critico"]) == "rollback"
    vigente = registro.version_por_alias(dominio.ALIAS_PRODUCCION)
    assert vigente is not None and vigente.version == produccion.version
    assert promotor.resolver(candidato, 0.5, 0.5) == "rollback"
    eventos = mlflow.search_runs(
        experiment_names=[dominio.EXPERIMENTO_MLOPS],
        filter_string="tags.evento = 'rollback'")
    assert isinstance(eventos, pd.DataFrame)
    assert len(eventos) == 2
    assert "no mejora" in eventos.iloc[0]["tags.razon"]
    assert eventos.iloc[0]["metrics.error_staging_g_por_tonelada"] in (0.9, 0.5)


def test_un_staging_estrictamente_mejor_se_promueve(registro: RegistroMlops) -> None:
    modelo = EntrenadorLey().entrenar(eventos_sinteticos(dias=21))
    registro.registrar_entrenamiento(modelo, dominio.ALIAS_PRODUCCION, "bootstrap")
    candidato = registro.registrar_entrenamiento(modelo, dominio.ALIAS_STAGING, "candidato")
    assert PromotorModelos(registro).resolver(candidato, 0.3, 0.5) == "promocion"
    vigente = registro.version_por_alias(dominio.ALIAS_PRODUCCION)
    assert vigente is not None and vigente.version == candidato.version
    eventos = mlflow.search_runs(
        experiment_names=[dominio.EXPERIMENTO_MLOPS],
        filter_string="tags.evento = 'promocion'")
    assert isinstance(eventos, pd.DataFrame)
    assert len(eventos) == 1 and "mejora" in eventos.iloc[0]["tags.razon"]
