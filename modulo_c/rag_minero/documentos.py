"""Lectura de los PDF tecnicos y su descomposicion en elementos con estructura.

El chunking del Ejercicio C-2 se decide por genero de documento y por tipo de elemento, y
eso exige que el lector no devuelva texto plano sino una secuencia de elementos tipados:
encabezados de seccion, prosa, pasos numerados, tablas con cabecera y filas, y advertencias.
Este modulo es el unico que conoce `pdfplumber`; todo lo demas trabaja sobre
`DocumentoTecnico`, que es una estructura de datos y no un objeto de la libreria.

Dos problemas de los PDF reales que este lector resuelve, y que un extractor de texto plano
no resuelve:

Tablas partidas por el salto de pagina. En los tres documentos la mayoria de las tablas
cruzan una pagina: la cabecera queda en una y las filas en la siguiente. Un parser pagina a
pagina produce cabeceras huerfanas y filas sin cabecera. Aqui, si una pagina termina en una
tabla y la siguiente empieza en otra con el mismo numero de columnas, se fusionan y las filas
heredan la cabecera.

Codigos partidos dentro de la celda. El PDF renderiza `AC-L8-HM-4721` como dos lineas,
`AC-L8-HM-472` y `1`, y `Codigo` como `Codig` y `o`. Si no se unen antes de indexar, la
busqueda lexica indexa `472` y nunca encuentra el repuesto. La regla de union es una
heuristica declarada y probada, no una limpieza silenciosa.

Se descarto `pypdf`, que no detecta tablas, y se dejo para produccion el parser de layout de
la plataforma (`ai_parse_document`), que ademas cubre escaneos con OCR; este lector es el
puente local sobre PDF generados digitalmente.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

import pdfplumber

from rag_minero.errores import DocumentoNoReconocidoError, PdfIlegibleError

# --- Tipos del dominio ---


class TipoDocumento(StrEnum):
    """Genero del documento, que es lo que elige la estrategia de chunking."""

    PROCEDIMIENTO = "procedimiento"
    INFORME = "informe"
    MANUAL = "manual"


class TipoElemento(StrEnum):
    """Unidad estructural dentro de un documento."""

    ENCABEZADO = "encabezado"
    PROSA = "prosa"
    PASO = "paso"
    TABLA = "tabla"
    ADVERTENCIA = "advertencia"


#: Una fila de tabla ya normalizada: una cadena por columna, sin saltos de linea.
Fila = tuple[str, ...]


@dataclass(frozen=True)
class Elemento:
    """Una unidad estructural del documento, con la seccion y la pagina de donde salio.

    `texto` es la version plana que sirve para buscar y para mostrar; para las tablas es un
    renderizado de cabecera y filas. `cabecera` y `filas` conservan la estructura para que
    cada estrategia de chunking decida si una fila es un chunk o si lo es la tabla entera.
    """

    tipo: TipoElemento
    texto: str
    seccion: str
    pagina: int
    orden: int
    titulo: str = ""
    cabecera: Fila = ()
    filas: tuple[Fila, ...] = ()

    @property
    def es_tabla(self) -> bool:
        """Verdadero si el elemento conserva filas estructuradas."""
        return self.tipo is TipoElemento.TABLA


@dataclass(frozen=True)
class DocumentoTecnico:
    """Un PDF ya leido: su identidad, su clasificacion y sus elementos en orden de lectura.

    La clasificacion se conserva desde el origen porque en produccion es un filtro de acceso
    y no una nota al pie: el informe geologico esta marcado CONFIDENCIAL en su encabezado.
    """

    codigo: str
    tipo: TipoDocumento
    titulo: str
    version: str
    fecha: str
    clasificacion: str
    ruta: Path
    elementos: tuple[Elemento, ...] = field(default_factory=tuple)

    def de_tipo(self, tipo: TipoElemento) -> list[Elemento]:
        """Elementos de un tipo dado, en orden de lectura."""
        return [e for e in self.elementos if e.tipo is tipo]

    @property
    def tablas(self) -> list[Elemento]:
        """Las tablas del documento, ya fusionadas si cruzaban paginas."""
        return self.de_tipo(TipoElemento.TABLA)


# --- Reglas de reconocimiento ---

PATRON_SECCION: Final[re.Pattern[str]] = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
PATRON_PASO: Final[re.Pattern[str]] = re.compile(r"^Paso\s+(\d+)\s*[\u2014\u2013-]\s*(.+)$")
PATRON_CODIGO_FILA: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Z]{1,4}-[A-Z0-9]{1,6}(?:-[A-Z0-9]+)*|Rev\.\s*\d+|OX|MIX|SUL|EST|TOTAL)\b"
)
PALABRAS_ADVERTENCIA: Final[tuple[str, ...]] = ("IMPORTANTE", "ATENCIÓN", "ATENCION", "PELIGRO")
PREFIJOS_TIPO: Final[dict[str, TipoDocumento]] = {
    "PET-": TipoDocumento.PROCEDIMIENTO,
    "IGE-": TipoDocumento.INFORME,
    "INFORME-": TipoDocumento.INFORME,
    "MAN-": TipoDocumento.MANUAL,
    "MANUAL-": TipoDocumento.MANUAL,
}
#: Palabras cortas que si pueden empezar una linea dentro de una celda sin ser un fragmento
#: de palabra partida: no se pegan a la linea anterior.
PALABRAS_CORTAS_LEGITIMAS: Final[frozenset[str]] = frozenset(
    {"de", "y", "a", "en", "el", "la", "al", "un", "es", "se", "si", "no"}
)
#: Distancia desde el borde superior de la pagina por debajo de la cual una tabla se
#: considera continuacion de la pagina anterior.
MARGEN_SUPERIOR: Final[float] = 120.0


# --- Bloques intermedios de una pagina ---


@dataclass(frozen=True)
class _BloqueTexto:
    pagina: int
    top: float
    lineas: tuple[str, ...]


@dataclass
class _BloqueTabla:
    pagina: int
    top: float
    bottom: float
    filas: list[Fila]
    #: Ultima pagina que abarca; cambia al fusionar continuaciones.
    ultima_pagina: int = -1

    def __post_init__(self) -> None:
        if self.ultima_pagina < 0:
            self.ultima_pagina = self.pagina


_Bloque = _BloqueTexto | _BloqueTabla


def normalizar_celda(celda: str | None) -> str:
    """Une los saltos de linea de una celda sin romper palabras ni codigos partidos.

    Un salto seguido de un fragmento de una o dos letras —`Codig`/`o`, `Especificacio`/`n`—
    se pega sin espacio, y un fragmento de uno o dos digitos se pega solo si lo anterior
    parece un codigo o termina en digito (`AC-L8-HM-472`/`1`), porque «tras»/«5 min» es un
    salto legitimo. Cualquier otro salto se convierte en espacio, y las palabras cortas del
    espanol (`de`, `y`, `en`...) nunca se pegan.
    """
    if not celda:
        return ""
    fragmentos = [f.strip() for f in celda.split("\n")]
    resultado = fragmentos[0]
    for fragmento in fragmentos[1:]:
        if not fragmento:
            continue
        primera = fragmento.split(" ", 1)[0]
        ultimo_token = resultado.rsplit(" ", 1)[-1]
        es_fragmento_de_palabra = (
            len(primera) <= 2
            and resultado[-1:].isalnum()
            and (
                (primera.isdigit() and ("-" in ultimo_token or ultimo_token[-1:].isdigit()))
                or (primera.islower() and primera not in PALABRAS_CORTAS_LEGITIMAS)
                or (primera.isupper() and "-" in ultimo_token)
            )
        )
        resultado += fragmento if es_fragmento_de_palabra else " " + fragmento
    return re.sub(r"\s+", " ", resultado).strip()


def parece_fila_de_datos(fila: Fila) -> bool:
    """Verdadero si la primera celda es un codigo o una etiqueta de dato, no una cabecera."""
    return bool(fila) and bool(PATRON_CODIGO_FILA.match(fila[0]))


def renderizar_tabla(cabecera: Fila, filas: Sequence[Fila]) -> str:
    """Texto plano de una tabla: cabecera y filas separadas por barras."""
    lineas = [" | ".join(cabecera)] if cabecera else []
    lineas.extend(" | ".join(fila) for fila in filas)
    return "\n".join(lineas)


class LectorPdf:
    """Convierte un PDF tecnico en un `DocumentoTecnico`.

    Cada pagina se recorre en orden vertical alternando regiones de prosa y tablas, que es
    el orden de lectura real. Las tablas que cruzan paginas se fusionan al cerrar la pagina.
    """

    def leer(self, ruta: Path) -> DocumentoTecnico:
        """Lee el PDF completo y devuelve sus elementos en orden de lectura.

        Raises
        ------
        PdfIlegibleError
            Si ninguna pagina tiene texto extraible.
        DocumentoNoReconocidoError
            Si el encabezado y el nombre del archivo no declaran un genero conocido.
        """
        with pdfplumber.open(str(ruta)) as pdf:
            bloques = self._fusionar_tablas_partidas(list(self._bloques(pdf.pages)))
            titulo = _titulo_por_tamano(pdf.pages[0]) if pdf.pages else ""
        if not any(isinstance(b, _BloqueTexto) and any(b.lineas) for b in bloques):
            raise PdfIlegibleError(str(ruta))
        codigo, tipo, version, fecha, clasificacion = self._encabezado(ruta, bloques)
        elementos = tuple(self._elementos(bloques))
        return DocumentoTecnico(
            codigo=codigo,
            tipo=tipo,
            titulo=titulo,
            version=version,
            fecha=fecha,
            clasificacion=clasificacion,
            ruta=ruta,
            elementos=elementos,
        )

    # --- lectura fisica ---

    def _bloques(self, paginas: Sequence[pdfplumber.page.Page]) -> Iterator[_Bloque]:
        for numero, pagina in enumerate(paginas, start=1):
            tablas = sorted(pagina.find_tables(), key=lambda t: t.bbox[1])
            cursor = 0.0
            for tabla in tablas:
                _x0, top, _x1, bottom = tabla.bbox
                yield from self._texto_en_region(pagina, numero, cursor, top)
                filas = [tuple(normalizar_celda(c) for c in fila) for fila in tabla.extract()]
                yield _BloqueTabla(numero, float(top), float(bottom), filas)
                cursor = float(bottom)
            yield from self._texto_en_region(pagina, numero, cursor, float(pagina.height))

    @staticmethod
    def _texto_en_region(
        pagina: pdfplumber.page.Page, numero: int, top: float, bottom: float
    ) -> Iterator[_BloqueTexto]:
        if bottom - top < 4:
            return
        region = pagina.crop((0, top, pagina.width, bottom))
        texto = region.extract_text() or ""
        # El glifo del recuadro de portada se extrae como una linea con una sola letra.
        lineas = tuple(
            linea.strip() for linea in texto.splitlines() if len(linea.strip()) > 1
        )
        if lineas:
            yield _BloqueTexto(numero, top, lineas)

    @staticmethod
    def _fusionar_tablas_partidas(bloques: Sequence[_Bloque]) -> list[_Bloque]:
        """Une una tabla al pie de una pagina con la que abre la siguiente.

        La condicion es triple: la pagina anterior termina en tabla, la siguiente empieza en
        tabla dentro del margen superior, y ambas tienen el mismo numero de columnas. Con
        eso las filas sin cabecera heredan la cabecera de la pagina anterior.
        """
        resultado: list[_Bloque] = []
        for bloque in bloques:
            anterior = resultado[-1] if resultado else None
            if (
                isinstance(bloque, _BloqueTabla)
                and isinstance(anterior, _BloqueTabla)
                and bloque.pagina == anterior.ultima_pagina + 1
                and bloque.top <= MARGEN_SUPERIOR
                and bloque.filas
                and anterior.filas
                and len(bloque.filas[0]) == len(anterior.filas[0])
            ):
                anterior.filas.extend(bloque.filas)
                anterior.bottom = bloque.bottom
                anterior.ultima_pagina = bloque.pagina
                continue
            resultado.append(bloque)
        return resultado

    # --- interpretacion ---

    @staticmethod
    def _encabezado(
        ruta: Path, bloques: list[_Bloque]
    ) -> tuple[str, TipoDocumento, str, str, str]:
        primer_texto = next((b for b in bloques if isinstance(b, _BloqueTexto)), None)
        lineas = list(primer_texto.lineas) if primer_texto else []
        cabecera = " ".join(lineas[:6])
        pistas = [ruta.stem, *re.findall(r"\b[A-Z]{2,7}-[A-Z0-9-]+\b", cabecera)]
        codigo = next((p for p in pistas[1:] if p.startswith(tuple(PREFIJOS_TIPO))), ruta.stem)
        tipo = next(
            (
                t
                for pista in pistas
                for prefijo, t in PREFIJOS_TIPO.items()
                if pista.startswith(prefijo)
            ),
            None,
        )
        if tipo is None:
            raise DocumentoNoReconocidoError(str(ruta), pistas)
        version = (
            _primero(r"Rev\.\s*(\d+)", cabecera)
            or _primero(r"-v(\d+)\b", cabecera)
            or _primero(r"(\d{4}-Q\d)", cabecera)
        )
        fecha = _primero(r"(\d{4}-\d{2}-\d{2})", cabecera)
        clasificacion = "CONFIDENCIAL" if "CONFIDENCIAL" in cabecera else "INTERNO"
        return codigo, tipo, version, fecha, clasificacion

    def _elementos(self, bloques: list[_Bloque]) -> Iterator[Elemento]:
        seccion = "Encabezado"
        orden = 0
        for bloque in bloques:
            if isinstance(bloque, _BloqueTabla):
                cabecera, filas = _separar_cabecera(bloque.filas)
                orden += 1
                yield Elemento(
                    tipo=TipoElemento.TABLA,
                    texto=renderizar_tabla(cabecera, filas),
                    seccion=seccion,
                    pagina=bloque.pagina,
                    orden=orden,
                    cabecera=cabecera,
                    filas=tuple(filas),
                )
                continue
            for tipo, titulo, lineas in _parrafos(bloque.lineas):
                if tipo is TipoElemento.ENCABEZADO:
                    seccion = titulo
                orden += 1
                yield Elemento(
                    tipo=tipo,
                    texto=" ".join(lineas),
                    seccion=seccion,
                    pagina=bloque.pagina,
                    orden=orden,
                    titulo=titulo,
                )


def _primero(patron: str, texto: str) -> str:
    coincidencia = re.search(patron, texto)
    return coincidencia.group(1) if coincidencia else ""


def _titulo_por_tamano(pagina: pdfplumber.page.Page) -> str:
    """El titulo son las lineas del recuadro de portada con el mismo cuerpo que la linea de codigo.

    Se usa el tamano de fuente y no una heuristica de puntuacion porque el titulo ocupa una o
    dos lineas sin punto final y la descripcion que lo sigue empieza sin ninguna marca.
    """
    lineas = pagina.crop((0, 0, pagina.width, pagina.height * 0.35)).extract_text_lines()
    inicio = next((i for i, linea in enumerate(lineas) if "|" in linea["text"]), None)
    if inicio is None:
        return ""
    cuerpo = round(lineas[inicio]["chars"][0]["size"], 1)
    titulo: list[str] = []
    for linea in lineas[inicio + 1 :]:
        if round(linea["chars"][0]["size"], 1) != cuerpo:
            break
        titulo.append(linea["text"].strip())
    return " ".join(titulo)


def _separar_cabecera(filas: list[Fila]) -> tuple[Fila, list[Fila]]:
    if filas and not parece_fila_de_datos(filas[0]):
        return filas[0], filas[1:]
    return (), list(filas)


def _parrafos(lineas: Sequence[str]) -> Iterator[tuple[TipoElemento, str, tuple[str, ...]]]:
    """Agrupa lineas en encabezados, pasos, advertencias y prosa.

    Un encabezado numerado o un `Paso N` abre un elemento nuevo; una linea que empieza con
    una palabra de advertencia abre una advertencia; el resto se acumula como prosa del
    elemento abierto. Se prefiere agrupar de mas y no de menos: partir un paso en dos
    elementos separa la condicion de la accion, que es el error que el chunking evita.
    """
    tipo = TipoElemento.PROSA
    titulo = ""
    acumulado: list[str] = []

    def cerrar() -> Iterator[tuple[TipoElemento, str, tuple[str, ...]]]:
        if acumulado:
            yield tipo, titulo, tuple(acumulado)

    for linea in lineas:
        seccion = PATRON_SECCION.match(linea)
        paso = PATRON_PASO.match(linea)
        advertencia = linea.split(" ", 1)[0].rstrip(":\u2014\u2013-") in PALABRAS_ADVERTENCIA
        if seccion:
            yield from cerrar()
            yield TipoElemento.ENCABEZADO, seccion.group(2).strip(), (linea,)
            tipo, titulo, acumulado = TipoElemento.PROSA, "", []
        elif paso:
            yield from cerrar()
            tipo, titulo, acumulado = TipoElemento.PASO, linea.strip(), []
        elif advertencia and tipo is not TipoElemento.PASO:
            yield from cerrar()
            tipo, titulo, acumulado = TipoElemento.ADVERTENCIA, linea.split(":")[0], [linea]
        else:
            acumulado.append(linea)
    yield from cerrar()
