"""Pruebas del lector de PDF: las reglas de normalizacion y la fusion de tablas partidas."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_minero.documentos import (
    LectorPdf,
    TipoDocumento,
    TipoElemento,
    _BloqueTabla,
    _BloqueTexto,
    _parrafos,
    normalizar_celda,
    parece_fila_de_datos,
    renderizar_tabla,
)
from rag_minero.errores import DocumentoNoReconocidoError

# --- normalizacion de celdas ---


@pytest.mark.parametrize(
    ("celda", "esperado"),
    [
        ("AC-L8-HM-472\n1", "AC-L8-HM-4721"),
        ("AC-L8-CR-ST\nD", "AC-L8-CR-STD"),
        ("Códig\no", "Código"),
        ("Especificació\nn", "Especificación"),
        ("Tiemp\no entre\nga", "Tiempo entrega"),
        ("rango operacional tras\n5 min calentamiento", "rango operacional tras 5 min calentamiento"),
        ("Nivel de aceite\nhidráulico", "Nivel de aceite hidráulico"),
        ("Circuito principal\nHP", "Circuito principal HP"),
        ("Sello principal motor\nde rotación", "Sello principal motor de rotación"),
        ("Stock\nmínimo\nUMLC", "Stock mínimo UMLC"),
        ("  espacios   dobles  ", "espacios dobles"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalizar_celda_une_fragmentos_sin_romper_palabras(celda: str | None, esperado: str) -> None:
    assert normalizar_celda(celda) == esperado


@pytest.mark.parametrize(
    ("fila", "es_dato"),
    [
        (("PT-01", "Nivel"), True),
        (("CP-06", "x"), True),
        (("R-01", "x"), True),
        (("AC-L8-HM-4721", "x"), True),
        (("Rev. 3", "x"), True),
        (("TOTAL SECTOR", "847"), True),
        (("OX (oxidado)", "0-45 m"), True),
        (("Ítem", "Parámetro"), False),
        (("Código", "Condición"), False),
        (("Frente", "Muestras"), False),
        ((), False),
    ],
)
def test_parece_fila_de_datos_distingue_cabeceras(fila: tuple[str, ...], es_dato: bool) -> None:
    assert parece_fila_de_datos(fila) is es_dato


def test_renderizar_tabla_conserva_cabecera_y_filas() -> None:
    texto = renderizar_tabla(("A", "B"), [("1", "2"), ("3", "4")])
    assert texto == "A | B\n1 | 2\n3 | 4"


def test_renderizar_tabla_sin_cabecera() -> None:
    assert renderizar_tabla((), [("1", "2")]) == "1 | 2"


# --- fusion de tablas partidas por pagina ---


def _tabla(pagina: int, top: float, bottom: float, *filas: tuple[str, ...]) -> _BloqueTabla:
    return _BloqueTabla(pagina, top, bottom, [tuple(f) for f in filas])


def test_una_tabla_al_pie_y_otra_al_inicio_se_fusionan() -> None:
    cabecera = _tabla(1, 700.0, 740.0, ("Ítem", "Parámetro"))
    filas = _tabla(2, 76.0, 300.0, ("PT-01", "Aceite"), ("PT-02", "Presión"))
    resultado = LectorPdf._fusionar_tablas_partidas([cabecera, filas])
    assert len(resultado) == 1
    tabla = resultado[0]
    assert isinstance(tabla, _BloqueTabla)
    assert tabla.filas == [("Ítem", "Parámetro"), ("PT-01", "Aceite"), ("PT-02", "Presión")]
    assert tabla.bottom == 300.0


def test_no_se_fusionan_si_hay_prosa_entre_medio() -> None:
    cabecera = _tabla(1, 700.0, 740.0, ("Ítem", "Parámetro"))
    prosa = _BloqueTexto(2, 76.0, ("Texto entre tablas",))
    filas = _tabla(2, 200.0, 300.0, ("PT-01", "Aceite"))
    assert len(LectorPdf._fusionar_tablas_partidas([cabecera, prosa, filas])) == 3


def test_no_se_fusionan_si_cambia_el_numero_de_columnas() -> None:
    a = _tabla(1, 700.0, 740.0, ("A", "B"))
    b = _tabla(2, 76.0, 300.0, ("1", "2", "3"))
    assert len(LectorPdf._fusionar_tablas_partidas([a, b])) == 2


def test_no_se_fusionan_si_la_segunda_no_empieza_en_el_margen_superior() -> None:
    a = _tabla(1, 700.0, 740.0, ("A", "B"))
    b = _tabla(2, 400.0, 500.0, ("1", "2"))
    assert len(LectorPdf._fusionar_tablas_partidas([a, b])) == 2


def test_una_tabla_que_cruza_tres_paginas_se_fusiona_en_cadena() -> None:
    bloques = [
        _tabla(1, 700.0, 740.0, ("A", "B")),
        _tabla(2, 76.0, 740.0, ("1", "2")),
        _tabla(3, 76.0, 200.0, ("3", "4")),
    ]
    resultado = LectorPdf._fusionar_tablas_partidas(bloques)
    assert len(resultado) == 1
    assert isinstance(resultado[0], _BloqueTabla)
    assert len(resultado[0].filas) == 3


# --- parrafos: encabezados, pasos, advertencias y prosa ---


def test_parrafos_separan_encabezado_paso_y_prosa() -> None:
    lineas = (
        "4. Procedimiento de Operación",
        "Paso 1 — Posicionamiento del equipo",
        "Posicionar la perforadora.",
        "Activar frenos.",
        "Paso 2 — Inicio controlado",
        "Encender el motor.",
    )
    resultado = list(_parrafos(lineas))
    assert [r[0] for r in resultado] == [TipoElemento.ENCABEZADO, TipoElemento.PASO, TipoElemento.PASO]
    assert resultado[0][1] == "Procedimiento de Operación"
    assert resultado[1][1] == "Paso 1 — Posicionamiento del equipo"
    assert resultado[1][2] == ("Posicionar la perforadora.", "Activar frenos.")


def test_una_advertencia_abre_su_propio_elemento() -> None:
    lineas = ("Texto normal.", "IMPORTANTE — Sonda XRF: el valor -1 es centinela.", "No es ley cero.")
    resultado = list(_parrafos(lineas))
    assert [r[0] for r in resultado] == [TipoElemento.PROSA, TipoElemento.ADVERTENCIA]
    assert resultado[1][1] == "IMPORTANTE — Sonda XRF"
    assert len(resultado[1][2]) == 2


def test_una_advertencia_dentro_de_un_paso_no_lo_parte() -> None:
    lineas = ("Paso 4 — Operación normal", "Registrar cada 30 minutos.", "ATENCIÓN: si la sonda no responde.")
    resultado = list(_parrafos(lineas))
    assert len(resultado) == 1
    assert resultado[0][0] is TipoElemento.PASO


def test_lineas_vacias_no_producen_elementos() -> None:
    assert list(_parrafos(())) == []


# --- reconocimiento del genero ---


def test_un_pdf_sin_codigo_conocido_falla_con_mensaje_descriptivo(tmp_path: Path) -> None:
    pdfplumber = pytest.importorskip("pdfplumber")
    del pdfplumber
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    ruta = tmp_path / "SIN-GENERO.pdf"
    lienzo = reportlab.Canvas(str(ruta))
    lienzo.drawString(72, 720, "Documento sin codigo reconocible")
    lienzo.save()
    with pytest.raises(DocumentoNoReconocidoError, match="SIN-GENERO"):
        LectorPdf().leer(ruta)


# --- integracion sobre los PDF reales ---


@pytest.mark.integracion
def test_inventario_de_los_tres_pdf_reales(directorio_pdf: Path) -> None:
    lector = LectorPdf()
    pet = lector.leer(directorio_pdf / "PET-PERF-007.pdf")
    informe = lector.leer(directorio_pdf / "INFORME-GEO-VETA-SUR-2024.pdf")
    manual = lector.leer(directorio_pdf / "MANUAL-ATLAS-COPCO-L8.pdf")

    assert (pet.tipo, pet.version, pet.clasificacion) == (TipoDocumento.PROCEDIMIENTO, "4", "INTERNO")
    assert [len(t.filas) for t in pet.tablas] == [4, 6, 6, 4]
    assert [e.titulo for e in pet.de_tipo(TipoElemento.PASO)][:2] == [
        "Paso 1 — Posicionamiento del equipo",
        "Paso 2 — Inicio controlado",
    ]

    assert (informe.tipo, informe.clasificacion) == (TipoDocumento.INFORME, "CONFIDENCIAL")
    assert [len(t.filas) for t in informe.tablas] == [5, 4, 4, 4]
    assert informe.tablas[0].filas[-1][0] == "TOTAL SECTOR"

    assert (manual.tipo, manual.version) == (TipoDocumento.MANUAL, "2")
    assert [len(t.filas) for t in manual.tablas] == [16, 3, 7, 5, 6]
    assert manual.tablas[-1].filas[0][0] == "AC-L8-HM-4721"
    assert manual.tablas[-1].filas[-1][0] == "AC-L8-CR-STD"
    assert len(manual.de_tipo(TipoElemento.ADVERTENCIA)) == 1
