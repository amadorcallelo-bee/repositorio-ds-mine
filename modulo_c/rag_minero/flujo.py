"""Orquestacion de la demo: los pasos que el notebook ejecuta, en el orden que cuesta menos.

El orden importa por dinero. Primero todo lo que es gratis y determinista —leer los PDF,
trocear, calibrar la puerta de dominio, correr la ablacion de chunking— y solo despues lo
que llama a un modelo: responder el golden set, las preguntas de control y juzgar con RAGAS.
El endpoint de Vector Search, que cobra por hora, se crea justo antes de indexar y se
borra al final desde el propio flujo.

Este modulo no contiene logica de negocio: cada paso delega en una clase que ya tiene sus
pruebas. Existe para que el notebook sea una secuencia de llamadas legibles con sus
salidas, y no un lugar donde se esconda codigo.

La configuracion sale del entorno, como en el resto del repositorio: `RAG_PDF_DIR` para los
documentos, `RAG_ALMACEN` (`local` o `databricks`), `RAG_TOKENS_MAXIMOS` como tope de
sesion, y las variables del workspace que valida `ConfiguracionDatabricks`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from langchain_core.embeddings import Embeddings

from rag_minero.asistente import (
    SALIDA_MAXIMA,
    Asistente,
    PresupuestoTokens,
    Respuesta,
    crear_modelo_databricks,
)
from rag_minero.chunking import Trozador
from rag_minero.documentos import DocumentoTecnico, LectorPdf
from rag_minero.errores import ConfiguracionError
from rag_minero.evaluacion import (
    Ablacion,
    EvaluadorRagas,
    GoldenSet,
    MetricasCaso,
    PreguntasControl,
    ResultadoAblacion,
)
from rag_minero.guardrails import Calibracion, Calibrador, PuertaDeDominio, Vocabulario
from rag_minero.indice import (
    COSTO_ENDPOINT_USD_HORA,
    AlmacenDatabricks,
    AlmacenLocal,
    AlmacenVectorial,
    ConfiguracionDatabricks,
)

TipoAlmacen = Literal["local", "databricks"]
RAIZ: Final[Path] = Path(__file__).parent
DOCUMENTOS: Final[tuple[str, ...]] = (
    "PET-PERF-007.pdf",
    "INFORME-GEO-VETA-SUR-2024.pdf",
    "MANUAL-ATLAS-COPCO-L8.pdf",
)


@dataclass(frozen=True)
class Configuracion:
    """Parametros de la demo, leidos del entorno y validados antes de empezar.

    Los nombres de los modelos son configuracion y no codigo: el workspace de prueba tiene
    los modelos propietarios apagados con un limite de tasa cero, asi que la demo corre con
    `RAG_MODELO_GENERADOR` y `RAG_MODELO_JUEZ` abiertos y en produccion basta cambiar la
    variable para volver a Claude Sonnet 5.
    """

    directorio_pdf: Path
    almacen: TipoAlmacen = "local"
    tokens_maximos: int = 400_000
    k: int = 6
    modelo_generador: str = "databricks-claude-sonnet-5"
    modelo_juez: str = "databricks-claude-sonnet-5"
    modelo_embeddings: str = "databricks-qwen3-embedding-0-6b"
    perfil: str | None = None
    directorio_salida: Path = RAIZ / "resultados"

    @classmethod
    def desde_entorno(cls, entorno: dict[str, str] | None = None) -> Configuracion:
        """Lee `RAG_PDF_DIR` (obligatoria) y el resto con valores por defecto."""
        valores = entorno if entorno is not None else dict(os.environ)
        ruta = valores.get("RAG_PDF_DIR", "").strip()
        if not ruta:
            raise ConfiguracionError("RAG_PDF_DIR", "falta el directorio con los tres PDF")
        directorio = Path(ruta)
        faltantes = [d for d in DOCUMENTOS if not (directorio / d).is_file()]
        if faltantes:
            raise ConfiguracionError("RAG_PDF_DIR", f"no se encuentran: {', '.join(faltantes)}")
        almacen = valores.get("RAG_ALMACEN", "local").strip() or "local"
        if almacen not in ("local", "databricks"):
            raise ConfiguracionError("RAG_ALMACEN", "debe ser 'local' o 'databricks'")
        tokens = valores.get("RAG_TOKENS_MAXIMOS", "").strip()
        por_defecto = cls(directorio_pdf=directorio)
        return cls(
            directorio_pdf=directorio,
            almacen="databricks" if almacen == "databricks" else "local",
            tokens_maximos=int(tokens) if tokens else 400_000,
            modelo_generador=valores.get("RAG_MODELO_GENERADOR", "").strip()
            or por_defecto.modelo_generador,
            modelo_juez=valores.get("RAG_MODELO_JUEZ", "").strip() or por_defecto.modelo_juez,
            modelo_embeddings=valores.get("RAG_MODELO_EMBEDDINGS", "").strip()
            or por_defecto.modelo_embeddings,
            perfil=valores.get("DATABRICKS_CONFIG_PROFILE") or None,
        )


@dataclass
class Resultados:
    """Todo lo que la demo produce, serializable a JSON para el README."""

    chunks_por_variante: dict[str, int] = field(default_factory=dict)
    calibracion: dict[str, float] = field(default_factory=dict)
    ablacion: list[dict[str, Any]] = field(default_factory=list)
    ablacion_tabla: str = ""
    control: list[dict[str, Any]] = field(default_factory=list)
    ragas: list[dict[str, Any]] = field(default_factory=list)
    ragas_tabla: str = ""
    ragas_resumen: dict[str, float] = field(default_factory=dict)
    tokens_consumidos: int = 0
    llamadas_al_modelo: int = 0

    def guardar(self, directorio: Path) -> Path:
        """Escribe `resultados.json` y devuelve su ruta."""
        directorio.mkdir(parents=True, exist_ok=True)
        ruta = directorio / "resultados.json"
        ruta.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return ruta


class Flujo:
    """Los pasos de la demo, cada uno con su salida y sin gasto oculto."""

    def __init__(self, configuracion: Configuracion, embeddings: Embeddings | None = None) -> None:
        self.configuracion = configuracion
        self.presupuesto = PresupuestoTokens(maximo=configuracion.tokens_maximos)
        self.resultados = Resultados()
        self._embeddings = embeddings
        self.golden = GoldenSet.cargar(RAIZ / "golden_set.json")
        self.control = PreguntasControl.cargar(RAIZ / "preguntas_control.json")
        self.documentos: list[DocumentoTecnico] = []
        self.chunks: list[Any] = []
        self.vocabulario: Vocabulario | None = None
        self.puerta: PuertaDeDominio | None = None

    # --- pasos gratis ---

    def cargar_documentos(self) -> list[DocumentoTecnico]:
        """Lee los tres PDF con el lector de tablas partidas."""
        lector = LectorPdf()
        self.documentos = [lector.leer(self.configuracion.directorio_pdf / d) for d in DOCUMENTOS]
        return self.documentos

    def trocear(self) -> list[Any]:
        """Chunks con la estrategia por genero y elemento, y el conteo de cada variante."""
        variantes = self._variantes()
        for variante in variantes:
            self.resultados.chunks_por_variante[variante.nombre] = len(
                variante.trocear(self.documentos)
            )
        self.chunks = variantes[0].trocear(self.documentos)
        self.vocabulario = Vocabulario.desde_textos(c.page_content for c in self.chunks)
        return self.chunks

    def calibrar(self) -> Calibracion:
        """Umbral de la puerta de dominio derivado del golden set y las preguntas de control."""
        if self.vocabulario is None:
            raise RuntimeError("llama a trocear() antes de calibrar()")
        calibracion = Calibrador(self.vocabulario).calibrar(
            self.golden.preguntas, list(self.control.fuera_de_dominio)
        )
        self.puerta = PuertaDeDominio(self.vocabulario, calibracion.cobertura_minima)
        self.resultados.calibracion = {
            "cobertura_minima": calibracion.cobertura_minima,
            "aceptadas_del_dominio": calibracion.aceptadas_del_dominio,
            "total_del_dominio": calibracion.total_del_dominio,
            "rechazadas_fuera": calibracion.rechazadas_fuera,
            "total_fuera": calibracion.total_fuera,
        }
        return calibracion

    def ablacion(self) -> list[ResultadoAblacion]:
        """Precision y recall de contexto de las tres variantes de chunking, sin modelo juez."""
        ablacion = Ablacion(
            self.documentos, self.golden, self._almacen_local, k=self.configuracion.k
        )
        resultados = ablacion.ejecutar(self._variantes())
        self.resultados.ablacion = [asdict(r) for r in resultados]
        self.resultados.ablacion_tabla = Ablacion.tabla_markdown(resultados)
        return resultados

    # --- pasos que cuestan ---

    def construir_almacen(self) -> AlmacenVectorial:
        """El almacen configurado; en Databricks, crea el endpoint y avisa lo que cuesta."""
        if self.configuracion.almacen == "local":
            almacen: AlmacenVectorial = self._almacen_local()
        else:
            databricks = AlmacenDatabricks(ConfiguracionDatabricks.desde_entorno())
            print(
                f"Creando el endpoint de Vector Search: {COSTO_ENDPOINT_USD_HORA} USD por hora "
                "desde que exista un indice. Se borra al final del flujo."
            )
            databricks.crear_endpoint()
            almacen = databricks
        almacen.indexar(self.chunks)
        return almacen

    def construir_asistente(self, almacen: AlmacenVectorial) -> Asistente:
        """El asistente sobre el almacen, con el generador de Databricks y el presupuesto."""
        if self.puerta is None:
            raise RuntimeError("llama a calibrar() antes de construir_asistente()")
        modelo = crear_modelo_databricks(self.configuracion.modelo_generador, SALIDA_MAXIMA)
        return Asistente(
            almacen,
            modelo,
            self.puerta,
            k=self.configuracion.k,
            presupuesto=self.presupuesto,
            salida_maxima=SALIDA_MAXIMA,
        )

    def probar_control(self, asistente: Asistente) -> list[Respuesta]:
        """Las preguntas fuera de dominio deben rechazarse y las sin respaldo no deben inventar."""
        respuestas: list[Respuesta] = []
        for pregunta in self.control.fuera_de_dominio + self.control.sin_respaldo_documental:
            respuesta = asistente.responder(pregunta)
            respuestas.append(respuesta)
            self.resultados.control.append(
                {
                    "pregunta": pregunta,
                    "rechazada": respuesta.rechazada,
                    "bloqueada": respuesta.bloqueada,
                    "motivo": respuesta.motivo,
                    "texto": respuesta.texto,
                }
            )
        return respuestas

    def evaluar_ragas(self, asistente: Asistente) -> list[MetricasCaso]:
        """Responde el golden set y lo juzga con RAGAS sobre Foundation Model APIs."""
        host, token = self._credenciales()
        evaluador = EvaluadorRagas.con_databricks(
            asistente,
            host=host,
            token=token,
            modelo_juez=self.configuracion.modelo_juez,
            modelo_embeddings=self.configuracion.modelo_embeddings,
            presupuesto=self.presupuesto,
        )
        resultados = evaluador.evaluar(self.golden)
        self.resultados.ragas = [
            {
                "caso_id": r.caso_id,
                "documento": r.documento,
                "faithfulness": r.faithfulness,
                "answer_relevancy": r.answer_relevancy,
                "context_precision": r.context_precision,
                "estado": "respondida" if r.respuesta.exitosa else r.respuesta.motivo,
                "texto": r.respuesta.texto,
                "fuentes": list(r.respuesta.fuentes),
            }
            for r in resultados
        ]
        self.resultados.ragas_tabla = EvaluadorRagas.tabla_markdown(resultados)
        self.resultados.ragas_resumen = EvaluadorRagas.resumen(resultados)
        return resultados

    def cerrar(self, almacen: AlmacenVectorial) -> Path:
        """Registra el consumo, borra el endpoint si lo hubo y guarda los resultados."""
        self.resultados.tokens_consumidos = self.presupuesto.consumidos
        self.resultados.llamadas_al_modelo = self.presupuesto.llamadas
        if isinstance(almacen, AlmacenDatabricks):
            almacen.vaciar()
            almacen.borrar_endpoint()
            print("Endpoint de Vector Search borrado; la facturacion cesa en 24 horas.")
        return self.resultados.guardar(self.configuracion.directorio_salida)

    # --- ayudantes ---

    @staticmethod
    def _variantes() -> Sequence[Trozador]:
        return (Trozador.por_genero_y_elemento(), Trozador.solo_genero(), Trozador.tamano_fijo())

    def _almacen_local(self) -> AlmacenLocal:
        return AlmacenLocal(self._embeddings_o_databricks(), coleccion=f"rag-{os.getpid()}")

    def _embeddings_o_databricks(self) -> Embeddings:
        if self._embeddings is None:
            from databricks_langchain import DatabricksEmbeddings

            self._embeddings = DatabricksEmbeddings(endpoint=self.configuracion.modelo_embeddings)
        return self._embeddings

    def _credenciales(self) -> tuple[str, str]:
        from databricks.sdk import WorkspaceClient

        config = WorkspaceClient(profile=self.configuracion.perfil).config
        cabeceras = config.authenticate()
        token = cabeceras.get("Authorization", "").removeprefix("Bearer ").strip()
        if not config.host or not token:
            raise ConfiguracionError("DATABRICKS_CONFIG_PROFILE", "no se pudo autenticar")
        return str(config.host), token
