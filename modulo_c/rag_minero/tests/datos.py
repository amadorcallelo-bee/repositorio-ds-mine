"""Documentos sinteticos para las pruebas del asistente RAG.

Reproducen en pequeno las tres estructuras que importan: un procedimiento con pasos y una
tabla de criterios, un informe con prosa larga y una tabla con fila TOTAL, y un manual con
especificaciones, una tabla de fallas y una advertencia. Las pruebas no dependen de los PDF
reales; los PDF solo entran en las pruebas de integracion, que se saltan si no estan.
"""

from __future__ import annotations

from pathlib import Path

from rag_minero.documentos import (
    DocumentoTecnico,
    Elemento,
    TipoDocumento,
    TipoElemento,
    renderizar_tabla,
)


def _tabla(
    seccion: str, pagina: int, orden: int, cabecera: tuple[str, ...], *filas: tuple[str, ...]
) -> Elemento:
    return Elemento(
        tipo=TipoElemento.TABLA,
        texto=renderizar_tabla(cabecera, filas),
        seccion=seccion,
        pagina=pagina,
        orden=orden,
        cabecera=cabecera,
        filas=tuple(filas),
    )


def procedimiento() -> DocumentoTecnico:
    """Un PET con dos pasos y una tabla de criterios de parada."""
    seccion_pasos = "Procedimiento de Operacion"
    seccion_parada = "Criterios de Parada Inmediata"
    return DocumentoTecnico(
        codigo="PET-TEST-001",
        tipo=TipoDocumento.PROCEDIMIENTO,
        titulo="Procedimiento de prueba",
        version="2",
        fecha="2024-01-01",
        clasificacion="INTERNO",
        ruta=Path("PET-TEST-001.pdf"),
        elementos=(
            Elemento(TipoElemento.PROSA, "Aplica a perforadoras L8 en el frente FR-S1-02.", "Encabezado", 1, 1),
            Elemento(TipoElemento.ENCABEZADO, "4. " + seccion_pasos, seccion_pasos, 1, 2, titulo=seccion_pasos),
            Elemento(
                TipoElemento.PASO,
                "Encender el motor a 800 RPM. Esperar 3 minutos antes de extender el brazo.",
                seccion_pasos,
                1,
                3,
                titulo="Paso 2 — Inicio controlado",
            ),
            Elemento(
                TipoElemento.PASO,
                "Reducir RPM a 800 antes de retirar la corona.",
                seccion_pasos,
                1,
                4,
                titulo="Paso 5 — Parada programada",
            ),
            Elemento(TipoElemento.ENCABEZADO, "5. " + seccion_parada, seccion_parada, 2, 5, titulo=seccion_parada),
            _tabla(
                seccion_parada,
                2,
                6,
                ("Código", "Condición", "Umbral", "Acción inmediata"),
                ("CP-02", "Temperatura motor crítica", ">92°C", "Detener. Reportar M-MOTOR-07."),
                ("CP-03", "Pérdida de presión hidráulica", "<140 bar", "Detener. Reportar H-HIDRA-02."),
            ),
        ),
    )


def informe() -> DocumentoTecnico:
    """Un informe con prosa larga y una tabla de ensayos con fila TOTAL."""
    resumen = "Resumen Ejecutivo"
    muestreo = "Resultados de Muestreo"
    prosa_larga = " ".join(
        f"El frente FR-S2-03 mantiene una ley de 9.21 g/t en el tramo 320-380 m, oracion {i}."
        for i in range(1, 25)
    )
    return DocumentoTecnico(
        codigo="INFORME-TEST-2024",
        tipo=TipoDocumento.INFORME,
        titulo="Informe de prueba",
        version="2024-Q3",
        fecha="2024-09-30",
        clasificacion="CONFIDENCIAL",
        ruta=Path("INFORME-TEST-2024.pdf"),
        elementos=(
            Elemento(TipoElemento.ENCABEZADO, "1. " + resumen, resumen, 1, 1, titulo=resumen),
            Elemento(TipoElemento.PROSA, prosa_larga, resumen, 1, 2),
            Elemento(TipoElemento.ENCABEZADO, "2. " + muestreo, muestreo, 1, 3, titulo=muestreo),
            _tabla(
                muestreo,
                1,
                4,
                ("Frente", "Muestras", "Ley media (g/t)"),
                ("FR-S1-02", "198", "8.52"),
                ("FR-S2-03", "231", "9.21"),
                ("TOTAL SECTOR", "429", "8.89"),
            ),
        ),
    )


def manual() -> DocumentoTecnico:
    """Un manual con especificaciones, una falla y una advertencia."""
    specs = "Especificaciones Tecnicas"
    monitoreo = "Sistema de Monitoreo"
    return DocumentoTecnico(
        codigo="MANUAL-TEST-L8",
        tipo=TipoDocumento.MANUAL,
        titulo="Manual de prueba",
        version="2",
        fecha="2024-01-10",
        clasificacion="INTERNO",
        ruta=Path("MANUAL-TEST-L8.pdf"),
        elementos=(
            Elemento(TipoElemento.ENCABEZADO, "1. " + specs, specs, 1, 1, titulo=specs),
            _tabla(
                specs,
                1,
                2,
                ("Parámetro", "Especificación", "Unidad", "Observación UMLC"),
                ("Presión hidráulica máxima", "280", "bar", "No operar >260 bar."),
                ("RPM corona — máximo", "1,500", "RPM", "No superar."),
            ),
            _tabla(
                specs,
                1,
                3,
                ("Código falla OPUS", "Síntoma en campo", "Causa probable"),
                ("H-HIDRA-05", "Presión no sube tras 5 min", "Válvula de alivio descalibrada"),
            ),
            Elemento(TipoElemento.ENCABEZADO, "3. " + monitoreo, monitoreo, 2, 4, titulo=monitoreo),
            Elemento(
                TipoElemento.ADVERTENCIA,
                "IMPORTANTE — Sonda XRF (SX-01): el sistema registra ley_au_gpT = -1 como valor "
                "centinela. Registrar falla_cod = E-ELEC-04 si persiste.",
                monitoreo,
                2,
                5,
                titulo="IMPORTANTE — Sonda XRF (SX-01)",
            ),
        ),
    )


def corpus() -> list[DocumentoTecnico]:
    """Los tres documentos sinteticos."""
    return [procedimiento(), informe(), manual()]
