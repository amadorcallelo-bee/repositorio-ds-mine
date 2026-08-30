"""Excepciones del asistente RAG.

Existen por la misma razon que las del pipeline AURUM: que un uso incorrecto falle donde se
comete y con un mensaje que nombre la causa. Un PDF que no se reconoce, una variable de
entorno ausente o un presupuesto de tokens agotado son condiciones distintas y quien
integre el asistente debe poder capturarlas por separado.
"""

from __future__ import annotations

from collections.abc import Iterable


class RagError(Exception):
    """Raiz de los errores propios del asistente RAG."""


class DocumentoNoReconocidoError(RagError):
    """El PDF no declara un codigo que permita saber de que genero de documento se trata."""

    def __init__(self, ruta: str, pistas: Iterable[str]) -> None:
        vistas = ", ".join(pistas) or "ninguna"
        super().__init__(
            f"No se reconoce el genero del documento {ruta}: se esperaba un codigo PET-, "
            f"IGE-/INFORME- o MAN-/MANUAL- y se encontro: {vistas}."
        )


class PdfIlegibleError(RagError):
    """El PDF no tiene texto extraible: probablemente es un escaneo sin OCR."""

    def __init__(self, ruta: str) -> None:
        super().__init__(
            f"El documento {ruta} no contiene texto extraible; si es un escaneo, requiere OCR "
            "antes de indexarse."
        )


class ConfiguracionError(RagError):
    """Falta una variable de entorno requerida o su valor es invalido."""

    def __init__(self, variable: str, detalle: str) -> None:
        super().__init__(f"Configuracion invalida en {variable}: {detalle}")


class PresupuestoExcedidoError(RagError):
    """La evaluacion se detuvo antes de superar el tope de tokens autorizado."""

    def __init__(self, consumidos: int, maximo: int) -> None:
        super().__init__(
            f"Presupuesto de tokens agotado: {consumidos:,} consumidos de {maximo:,} "
            "autorizados. La evaluacion se detuvo antes de la siguiente llamada."
        )


class IndiceVacioError(RagError):
    """Se intento consultar un almacen vectorial que todavia no tiene chunks."""

    def __init__(self, nombre: str) -> None:
        super().__init__(f"El almacen {nombre} no tiene chunks indexados: llama a indexar() antes.")
