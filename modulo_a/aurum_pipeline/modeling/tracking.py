"""Registro de experimentos en MLflow, con nombres que un operador de mina pueda leer.

El enunciado pide explicitamente que los parametros, metricas y artefactos tengan nombres
comprensibles para operaciones. No es cosmetica: `mae=0.3975` no le dice nada a un jefe de
turno y `error_medio_g_por_tonelada=0.3975` si, porque g/t es la unidad con la que decide
mezcla y ley de corte. La traduccion vive aqui y en `metrics.py`, en un solo lugar.

**Backend SQLite y no el almacen de archivos.** MLflow 3.15 dejo `./mlruns` en modo
mantenimiento y lanza excepcion al usarlo. El seguimiento va contra `sqlite:///mlflow.db`,
resoluble por la variable de entorno `AURUM_MLFLOW_URI` igual que el CSV se resuelve por
`AURUM_CSV_PATH`: ninguna ruta absoluta escrita en el codigo.

**Una corrida padre por combinacion y una hija por pliegue.** Sin las hijas, la tabla
comparativa de ventanas mostraria promedios sin forma de ver que la deslizante de tres meses
no es solo peor sino tambien mas inestable. La dispersion entre pliegues es la mitad del
argumento y tiene que quedar inspeccionable, no resumida. Padre e hijas registran las dos
familias de metricas -validacion y entrenamiento, esta con sufijo- y la brecha entre ambas,
que es lo que un panel puede ordenar para ver sobreajuste sin abrir cada corrida.

**Los modelos se serializan con cloudpickle.** El formato por defecto de MLflow 3.15 es skops,
que rechaza clases propias, y el pipeline lleva dos transformadores de este paquete. La
consecuencia a tener presente es que `aurum_pipeline` debe ser importable donde se cargue el
modelo, que es justamente lo que hace el servicio de inferencia de este mismo repositorio.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

import mlflow
import pandas as pd
from mlflow.entities.model_registry import ModelVersion

from aurum_pipeline import domain
from aurum_pipeline.modeling.evaluacion import ResultadoEvaluacion

logger = logging.getLogger(__name__)

#: Variable de entorno con que se redirige el seguimiento sin tocar el codigo.
VARIABLE_URI: str = "AURUM_MLFLOW_URI"

#: Nombre del archivo SQLite del seguimiento, siempre en la raiz del repositorio.
ARCHIVO_SEGUIMIENTO: str = "mlflow.db"

#: Directorio de artefactos, hermano de la base: `mlartifacts/<experimento>/`.
DIRECTORIO_ARTEFACTOS: str = "mlartifacts"

#: Prefijo de un URI SQLite; solo con ese backend se decide aqui donde van los artefactos.
PREFIJO_SQLITE: str = "sqlite:///"

#: Marca con que se reconoce la raiz del repositorio al subir por el arbol de directorios.
MARCA_RAIZ: str = "modulo_a"


def raiz_del_repositorio(desde: Path | None = None) -> Path:
    """Directorio raiz del repositorio, subiendo hasta encontrar `modulo_a`.

    Existe porque el URI por defecto no puede ser relativo. Un notebook ejecutado con
    `nbconvert` corre con el directorio del propio notebook como directorio de trabajo, de
    modo que `sqlite:///mlflow.db` crearia la base dentro del paquete en lugar de la raiz, y
    el servicio de inferencia levantado desde otro directorio no la encontraria. Anclar la
    ruta a la raiz hace que las tres formas de usar el proyecto -notebook, pruebas y API-
    apunten al mismo backend.
    """
    inicio = (desde or Path.cwd()).resolve()
    for candidato in (inicio, *inicio.parents):
        if (candidato / MARCA_RAIZ).is_dir():
            return candidato
    return inicio


def uri_por_defecto() -> str:
    """URI SQLite absoluta, anclada a la raiz del repositorio."""
    return f"sqlite:///{raiz_del_repositorio() / ARCHIVO_SEGUIMIENTO}"


def resolver_uri() -> str:
    """URI de seguimiento, de la variable de entorno o el valor por defecto."""
    return os.environ.get(VARIABLE_URI, uri_por_defecto())


def _commit_actual() -> str:
    """Commit de git en que corre el experimento, o `desconocido` fuera de un repositorio."""
    try:
        salida = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return "desconocido"
    return salida.stdout.strip()


def huella_de_datos(matriz: pd.DataFrame) -> str:
    """Huella corta del contenido de la matriz, para saber si dos corridas la comparten.

    Se calcula sobre la forma y los instantes extremos y no sobre el contenido completo,
    porque el proposito es detectar que se cambio el insumo, no certificarlo.
    """
    firma = (
        f"{matriz.shape}|"
        f"{matriz[domain.COLUMNA_INICIO_TURNO].min()}|"
        f"{matriz[domain.COLUMNA_INICIO_TURNO].max()}|"
        f"{float(matriz[domain.COLUMNA_OBJETIVO].sum()):.6f}"
    )
    return hashlib.sha256(firma.encode("utf-8")).hexdigest()[:12]


class RegistroExperimento:
    """Envoltura de MLflow con la jerarquia de corridas y los nombres del experimento.

    Se instancia una vez por notebook y se le pasan resultados ya calculados: no entrena ni
    evalua nada. Esa separacion es lo que permite probar la evaluacion sin MLflow y probar el
    registro sin entrenar un modelo.
    """

    def __init__(
        self,
        uri: str | None = None,
        experimento: str = domain.EXPERIMENTO_LEY,
    ) -> None:
        self.uri = uri or resolver_uri()
        mlflow.set_tracking_uri(self.uri)
        mlflow.set_registry_uri(self.uri)
        self.experimento = experimento
        self._asegurar_experimento(experimento)
        mlflow.set_experiment(experimento)
        self.etiquetas_comunes: dict[str, str] = {
            "commit_git": _commit_actual(),
            "semilla": str(domain.SEMILLA),
        }
        logger.info("Seguimiento en %s, experimento %s", self.uri, experimento)

    def usar_experimento(self, nombre: str) -> None:
        """Apunta las corridas siguientes a otro experimento del mismo backend.

        Existe para que un mismo objeto de seguimiento sirva a los dos problemas del A-2 sin
        que las corridas de falla terminen dentro del experimento de la ley.
        """
        self.experimento = nombre
        self._asegurar_experimento(nombre)
        mlflow.set_experiment(nombre)
        logger.info("Seguimiento apuntado al experimento %s", nombre)

    def _asegurar_experimento(self, nombre: str) -> None:
        """Crea el experimento con sus artefactos junto a la base, si todavia no existe.

        MLflow crea los experimentos nuevos con los artefactos en `./mlruns`, relativo al
        directorio de trabajo: el notebook los dejaba dentro del paquete y las pruebas, en la
        raiz del repositorio, mientras el README describia otro lugar. Anclarlos al directorio
        de la base SQLite hace que la base y sus artefactos viajen juntos, como el URI de la
        base ya viaja anclado a la raiz. Con otro backend -un servidor remoto- la ubicacion la
        decide el servidor y no se toca.
        """
        if mlflow.get_experiment_by_name(nombre) is not None:
            return
        if not self.uri.startswith(PREFIJO_SQLITE):
            return
        base = Path(self.uri.removeprefix(PREFIJO_SQLITE)).resolve()
        destino = base.parent / DIRECTORIO_ARTEFACTOS / nombre
        mlflow.create_experiment(nombre, artifact_location=destino.as_uri())
        logger.info("Experimento %s creado con artefactos en %s", nombre, destino)

    # -- registro de evaluaciones -------------------------------------------------------

    def registrar_evaluacion(
        self,
        resultado: ResultadoEvaluacion,
        parametros: dict[str, Any],
        fase: str,
        artefactos: dict[str, pd.DataFrame] | None = None,
    ) -> str:
        """Registra una combinacion como corrida padre con una hija por pliegue.

        Devuelve el identificador de la corrida padre, que es con el que despues se arma la
        tabla comparativa.
        """
        with mlflow.start_run(run_name=resultado.nombre) as corrida:
            mlflow.set_tags({**self.etiquetas_comunes, "fase": fase})
            mlflow.log_params(self._parametros_legibles(parametros))
            mlflow.log_metrics(resultado.como_diccionario())
            for pliegue in resultado.pliegues:
                with mlflow.start_run(run_name=f"pliegue_{pliegue.numero}", nested=True):
                    mlflow.log_params({
                        "turnos_entrenamiento": pliegue.turnos_entrenamiento,
                        "turnos_validacion": pliegue.turnos_validacion,
                        "frentes_entrenamiento": pliegue.frentes_entrenamiento,
                    })
                    mlflow.log_metrics(pliegue.como_diccionario())
            self._registrar_artefactos(artefactos)
            return str(corrida.info.run_id)

    def registrar_modelo(
        self,
        pipeline: Any,
        nombre_corrida: str,
        parametros: dict[str, Any],
        metricas: dict[str, float],
        ejemplo: pd.DataFrame,
        fase: str,
        artefactos: dict[str, pd.DataFrame] | None = None,
        registrar_como: str | None = None,
        alias: str | None = None,
        nombre_artefacto: str = "modelo",
    ) -> ModelVersion | None:
        """Registra el modelo final y, si se pide, lo publica en el Model Registry.

        El `input_example` no es adorno: de el sale la firma que despues valida las entradas
        del servicio de inferencia, de modo que el contrato de la API no se mantiene a mano
        en dos lugares.
        """
        with mlflow.start_run(run_name=nombre_corrida):
            mlflow.set_tags({**self.etiquetas_comunes, "fase": fase})
            mlflow.log_params(self._parametros_legibles(parametros))
            mlflow.log_metrics(metricas)
            self._registrar_artefactos(artefactos)
            info = mlflow.sklearn.log_model(
                pipeline,
                name=nombre_artefacto,
                input_example=ejemplo,
                serialization_format="cloudpickle",
                registered_model_name=registrar_como,
            )

        if registrar_como is None:
            return None
        version = self._ultima_version(registrar_como)
        if alias is not None:
            mlflow.MlflowClient().set_registered_model_alias(
                registrar_como, alias, version.version)
            logger.info("Modelo %s version %s publicado con alias %s",
                        registrar_como, version.version, alias)
        logger.debug("Modelo registrado en %s", info.model_uri)
        return version

    # -- lectura ------------------------------------------------------------------------

    def tabla_de_corridas(self, fase: str | None = None) -> pd.DataFrame:
        """Corridas padre del experimento, como tabla comparativa.

        Las tablas del notebook y de la documentacion salen de aqui y no de un CSV mantenido
        aparte: si un numero aparece en el entregable, salio del registro de experimentos.
        """
        filtro = "attributes.run_name != ''"
        if fase is not None:
            filtro = f"tags.fase = '{fase}'"
        # `search_runs` declara devolver una lista o un marco segun `output_format`; con el
        # valor por defecto siempre es un marco, y el `cast` lo deja dicho una sola vez.
        corridas = cast(pd.DataFrame, mlflow.search_runs(
            experiment_names=[self.experimento], filter_string=filtro))
        if corridas.empty:
            return corridas
        # Las corridas hija comparten nombre entre combinaciones y no aportan a la tabla
        # comparativa; se identifican por tener padre.
        columna_padre = "tags.mlflow.parentRunId"
        if columna_padre in corridas.columns:
            corridas = corridas[corridas[columna_padre].isna()]
        return corridas.reset_index(drop=True)

    # -- interno ------------------------------------------------------------------------

    @staticmethod
    def _parametros_legibles(parametros: dict[str, Any]) -> dict[str, str]:
        """Convierte a texto y quita el prefijo del paso del pipeline de los hiperparametros.

        `modelo__num_leaves` es ruido de scikit-learn dentro de un panel que va a mirar
        alguien que no lo usa.
        """
        return {
            clave.split("__")[-1]: ("" if valor is None else str(valor))
            for clave, valor in parametros.items()
        }

    @staticmethod
    def _registrar_artefactos(artefactos: dict[str, pd.DataFrame] | None) -> None:
        """Guarda cada tabla como CSV dentro de la corrida activa."""
        if not artefactos:
            return
        with tempfile.TemporaryDirectory() as carpeta:
            for nombre, tabla in artefactos.items():
                ruta = Path(carpeta) / f"{nombre}.csv"
                tabla.to_csv(ruta, index=False)
                mlflow.log_artifact(str(ruta))

    @staticmethod
    def _ultima_version(nombre: str) -> ModelVersion:
        """Version mas reciente de un modelo registrado."""
        cliente = mlflow.MlflowClient()
        versiones = cliente.search_model_versions(f"name = '{nombre}'")
        return max(versiones, key=lambda version: int(version.version))
