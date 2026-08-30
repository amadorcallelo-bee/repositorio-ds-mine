"""Configuracion de las pruebas del asistente RAG.

Las pruebas de este directorio necesitan las librerias del entorno `.venv-rag`. Si se
ejecutan desde el entorno del Modulo A, que no las tiene, se omiten en lugar de romper la
coleccion: los dos entornos conviven mientras el A-2 corre en paralelo y se consolidan al
integrar. Este archivo no importa ninguna de esas librerias para poder decidirlo.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

DEPENDENCIAS = ("pdfplumber", "langchain_core", "langchain_text_splitters")
FALTANTES = [d for d in DEPENDENCIAS if importlib.util.find_spec(d) is None]

collect_ignore_glob = ["test_*.py"] if FALTANTES else []


@pytest.fixture
def directorio_pdf() -> Path:
    """Directorio con los tres PDF reales, resuelto por `RAG_PDF_DIR`; si no existe, se salta."""
    ruta = os.environ.get("RAG_PDF_DIR")
    if not ruta or not Path(ruta).is_dir():
        pytest.skip("RAG_PDF_DIR no apunta a un directorio con los PDF del enunciado")
    return Path(ruta)
