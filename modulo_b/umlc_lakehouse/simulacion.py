"""Simulacion de la llegada incremental y de las correcciones del laboratorio.

El enunciado pide ingerir el CSV "simulando llegada incremental" y "3 lotes donde registros
pasados son corregidos". Esta clase produce los archivos, en local y de forma determinista,
para que el lakehouse los reciba como recibiria los de OPUS y del laboratorio: por el
volumen de landing, sin que los notebooks sepan que son sinteticos.

Se usa pandas y no Spark porque corre una vez en la maquina del analista sobre 6 MB, y se
lee todo como texto para que cada lote conserve los bytes del extracto: el pipeline debe
enfrentarse al formato real, no a uno reescrito por el simulador.

Los tres lotes de correccion se disenan para cubrir lo que el `MERGE` tiene que resolver:
actualizaciones reales, reenvios que ya se aplicaron, claves que no existen y tipos fuera
de dominio.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from umlc_lakehouse import dominio
from umlc_lakehouse.errores import ParametroInvalidoError


@dataclass(frozen=True)
class ArchivoLote:
    """Un archivo producido por el simulador."""

    nombre: str
    ruta: Path
    filas: int


@dataclass(frozen=True)
class PlanCorreccion:
    """Como se construye un lote de reclasificacion."""

    nombre: str
    mes: str
    de: str
    a: str
    n: int
    n_repetidas: int = 0
    n_inexistentes: int = 0
    n_invalidas: int = 0


class SimuladorLotes:
    """Parte el extracto en lotes de llegada y genera las correcciones del laboratorio."""

    #: Cortes de la simulacion: un historico y tres meses incrementales. Los meses son los
    #: ultimos del extracto para que el incremental sea lo mas reciente, como en produccion.
    MESES_INCREMENTALES: Final[tuple[str, ...]] = ("2025-08", "2025-09", "2025-10")
    LABORATORIO: Final[str] = "ALS Geoquimica Lima"
    TIPO_INVALIDO: Final[str] = "XX"
    PLANES: Final[tuple[PlanCorreccion, ...]] = (
        PlanCorreccion("01_reclasificacion_2025-08", "2025-08", "MIX", "OX", n=40),
        PlanCorreccion("02_reclasificacion_2025-09", "2025-09", "EST", "SUL", n=40,
                       n_repetidas=10),
        PlanCorreccion("03_reclasificacion_2025-07", "2025-07", "SUL", "MIX", n=40,
                       n_inexistentes=5, n_invalidas=5),
    )

    def __init__(self, ruta_csv: Path, salida: Path, semilla: int = 20250506) -> None:
        if not ruta_csv.is_file():
            raise ParametroInvalidoError(f"No existe el extracto {ruta_csv}")
        self.ruta_csv = ruta_csv
        self.salida = salida
        self.semilla = semilla
        self._extracto: pd.DataFrame | None = None

    @property
    def extracto(self) -> pd.DataFrame:
        """El extracto como texto, columna por columna, sin conversion alguna."""
        if self._extracto is None:
            self._extracto = pd.read_csv(self.ruta_csv, dtype=str, keep_default_na=False)
            faltantes = set(dominio.COLUMNAS_EXTRACTO) - set(self._extracto.columns)
            if faltantes:
                raise ParametroInvalidoError(f"Al extracto le faltan columnas: {faltantes}")
        return self._extracto

    def _mes(self) -> pd.Series:
        return self.extracto[dominio.COLUMNA_TIEMPO].str.slice(0, 7)

    def partir_extracto(self) -> list[ArchivoLote]:
        """Un archivo historico mas uno por mes incremental, en `opus/`."""
        carpeta = self.salida / "opus"
        carpeta.mkdir(parents=True, exist_ok=True)
        mes = self._mes()
        primero = self.MESES_INCREMENTALES[0]
        historico = self.extracto[mes < primero]
        ultimo_historico = str(mes[mes < primero].max())
        primer_mes = str(mes.min())
        lotes = [(f"00_historico_{primer_mes}_{ultimo_historico}", historico)]
        lotes += [
            (f"{i:02d}_{m}", self.extracto[mes == m])
            for i, m in enumerate(self.MESES_INCREMENTALES, start=1)
        ]
        archivos: list[ArchivoLote] = []
        for nombre, marco in lotes:
            if marco.empty:
                raise ParametroInvalidoError(f"El lote {nombre} quedo vacio")
            ruta = carpeta / f"{nombre}.csv"
            marco.to_csv(ruta, index=False, lineterminator="\n")
            archivos.append(ArchivoLote(nombre, ruta, len(marco)))
        return archivos

    def _muestra(self, mes: str, tipo: str, n: int, rng: random.Random) -> pd.DataFrame:
        candidatos = self.extracto[
            (self._mes() == mes) & (self.extracto[dominio.COLUMNA_TIPO_MINERAL] == tipo)
        ]
        if len(candidatos) < n:
            raise ParametroInvalidoError(
                f"Solo hay {len(candidatos)} eventos {tipo} en {mes}; se pidieron {n}"
            )
        indices = sorted(rng.sample(sorted(candidatos.index.tolist()), n))
        return candidatos.loc[indices, list(dominio.CLAVE_EVENTO)].reset_index(drop=True)

    def generar_reclasificaciones(self) -> list[ArchivoLote]:
        """Los tres lotes del laboratorio, en `reclasificacion/`."""
        carpeta = self.salida / "reclasificacion"
        carpeta.mkdir(parents=True, exist_ok=True)
        rng = random.Random(self.semilla)
        archivos: list[ArchivoLote] = []
        anterior: pd.DataFrame | None = None
        contador = 0
        for plan in self.PLANES:
            base = self._muestra(plan.mes, plan.de, plan.n, rng)
            base[dominio.COLUMNA_TIPO_LAB] = plan.a
            partes = [base]
            if plan.n_repetidas:
                if anterior is None:
                    raise ParametroInvalidoError("No hay lote anterior del que repetir")
                partes.append(anterior.head(plan.n_repetidas).copy())
            if plan.n_inexistentes:
                falsas = base.head(plan.n_inexistentes).copy()
                falsas[dominio.COLUMNA_TIEMPO] = (
                    falsas[dominio.COLUMNA_TIEMPO].str.slice(0, 17) + "30"
                )
                partes.append(falsas)
            if plan.n_invalidas:
                invalidas = base.tail(plan.n_invalidas).copy()
                invalidas[dominio.COLUMNA_TIPO_LAB] = self.TIPO_INVALIDO
                partes.append(invalidas)
            lote = pd.concat(partes, ignore_index=True)
            lote[dominio.COLUMNA_FECHA_ANALISIS] = f"{plan.mes}-28"
            lote[dominio.COLUMNA_LABORATORIO] = self.LABORATORIO
            lote[dominio.COLUMNA_MUESTRA] = [
                f"LAB-{plan.mes[:4]}-{contador + i + 1:06d}" for i in range(len(lote))
            ]
            contador += len(lote)
            ruta = carpeta / f"{plan.nombre}.csv"
            lote.to_csv(ruta, index=False, lineterminator="\n")
            archivos.append(ArchivoLote(plan.nombre, ruta, len(lote)))
            anterior = base
        return archivos


def main(argumentos: list[str] | None = None) -> int:
    """Punto de entrada: `python -m umlc_lakehouse.simulacion --csv ... --salida ...`."""
    parser = argparse.ArgumentParser(description="Genera los lotes de llegada y de correccion")
    parser.add_argument("--csv", required=True, type=Path, help="ruta del extracto OPUS")
    parser.add_argument("--salida", required=True, type=Path, help="directorio de salida")
    parser.add_argument("--semilla", type=int, default=20250506)
    args = parser.parse_args(argumentos)
    simulador = SimuladorLotes(args.csv, args.salida, args.semilla)
    for archivo in simulador.partir_extracto() + simulador.generar_reclasificaciones():
        print(f"{archivo.ruta}: {archivo.filas} filas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
