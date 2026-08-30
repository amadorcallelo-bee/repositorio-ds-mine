"""Pruebas del simulador de lotes.

Los lotes de llegada reproducen el extracto byte a byte y las correcciones tienen la
composicion disenada para ejercitar el MERGE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError
from umlc_lakehouse.simulacion import SimuladorLotes, main

ENCABEZADO = ",".join(dominio.COLUMNAS_EXTRACTO)


def _extracto(ruta: Path, por_tipo: int = 45) -> list[str]:
    """Un extracto sintetico con `por_tipo` eventos de cada tipo en cada mes."""
    lineas: list[str] = []
    for mes in ("2025-06", "2025-07", "2025-08", "2025-09", "2025-10"):
        minuto = 0
        for tipo in dominio.TIPOS_MINERAL:
            for _ in range(por_tipo):
                dia, resto = divmod(minuto, 1440)
                hora, mm = divmod(resto, 60)
                ts = f"{mes}-{dia + 1:02d} {hora:02d}:{mm:02d}:00"
                lineas.append(
                    f"{ts},FR-S2-03,D1,8.1,100.5,210,1100,1.8,45,5,75,OP-1,EQ-1,,23.4,"
                    f"{tipo},Veta-Sur,0")
                minuto += 7
    ruta.write_text("\n".join([ENCABEZADO, *lineas]) + "\n")
    return lineas


def test_los_lotes_reparten_el_extracto_sin_perder_ni_alterar_filas(tmp_path: Path) -> None:
    lineas = _extracto(tmp_path / "extracto.csv")
    simulador = SimuladorLotes(tmp_path / "extracto.csv", tmp_path / "lotes")
    archivos = simulador.partir_extracto()
    assert [a.nombre for a in archivos] == [
        "00_historico_2025-06_2025-07", "01_2025-08", "02_2025-09", "03_2025-10"]
    reunidas: list[str] = []
    for archivo in archivos:
        contenido = archivo.ruta.read_text().splitlines()
        assert contenido[0] == ENCABEZADO
        assert len(contenido) - 1 == archivo.filas
        reunidas += contenido[1:]
    assert sorted(reunidas) == sorted(lineas)


def test_las_correcciones_tienen_la_composicion_disenada_y_son_deterministas(
        tmp_path: Path) -> None:
    _extracto(tmp_path / "extracto.csv")
    simulador = SimuladorLotes(tmp_path / "extracto.csv", tmp_path / "lotes")
    archivos = simulador.generar_reclasificaciones()
    assert [(a.nombre, a.filas) for a in archivos] == [
        ("01_reclasificacion_2025-08", 40), ("02_reclasificacion_2025-09", 50),
        ("03_reclasificacion_2025-07", 50)]
    r1 = archivos[0].ruta.read_text().splitlines()
    r2 = archivos[1].ruta.read_text().splitlines()
    r3 = archivos[2].ruta.read_text().splitlines()
    assert r1[0] == ",".join([
        dominio.COLUMNA_TIEMPO, dominio.COLUMNA_FRENTE, dominio.COLUMNA_TIPO_LAB,
        dominio.COLUMNA_FECHA_ANALISIS, dominio.COLUMNA_LABORATORIO, dominio.COLUMNA_MUESTRA])

    def claves(lineas: list[str]) -> set[tuple[str, ...]]:
        return {tuple(linea.split(",")[:3]) for linea in lineas[1:]}

    assert all(c[2] == "OX" and c[0].startswith("2025-08") for c in claves(r1))
    assert len(claves(r1) & claves(r2)) == 10
    inexistentes = [linea for linea in r3[1:] if linea.split(",")[0].endswith(":30")]
    invalidas = [linea for linea in r3[1:] if linea.split(",")[2] == "XX"]
    assert (len(inexistentes), len(invalidas)) == (5, 5)
    assert all("ALS Geoquimica Lima" in linea for linea in r3[1:])
    otra_vez = SimuladorLotes(tmp_path / "extracto.csv", tmp_path / "otra")
    otra_vez.generar_reclasificaciones()
    for archivo in archivos:
        assert archivo.ruta.read_text() == (tmp_path / "otra" / "reclasificacion"
                                            / archivo.ruta.name).read_text()


def test_el_simulador_falla_con_claridad(tmp_path: Path) -> None:
    with pytest.raises(ParametroInvalidoError, match="No existe"):
        SimuladorLotes(tmp_path / "nada.csv", tmp_path)
    _extracto(tmp_path / "pocos.csv", por_tipo=10)
    with pytest.raises(ParametroInvalidoError, match="Solo hay 10"):
        SimuladorLotes(tmp_path / "pocos.csv", tmp_path / "lotes").generar_reclasificaciones()
    (tmp_path / "sin_columnas.csv").write_text("a,b\n1,2\n")
    with pytest.raises(ParametroInvalidoError, match="faltan columnas"):
        SimuladorLotes(tmp_path / "sin_columnas.csv", tmp_path / "lotes").partir_extracto()


def test_main_escribe_los_siete_archivos(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _extracto(tmp_path / "extracto.csv")
    assert main(["--csv", str(tmp_path / "extracto.csv"), "--salida", str(tmp_path / "s")]) == 0
    assert capsys.readouterr().out.count("filas") == 7
