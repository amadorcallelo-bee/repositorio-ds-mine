# Lakehouse medallion UMLC (Ejercicio B-1)

Decisiones del B-1 y la corrida que las sostiene. Todas las cifras salen de la ejecución del
job `lakehouse_umlc_b1` (run `353845186819195`, 2026-08-30, serverless, 4 min 14 s de
extremo a extremo, sobre el catálogo `lakehouse_umlc`) y de las pruebas locales; ninguna está escrita a mano.

## Resumen de resultados

| Capa | Objeto | Resultado de la corrida |
|---|---|---|
| Bronze | `bronze.opus_raw` | 4 lotes, 50 000 filas, partición `fecha_ingesta`, 4 archivos Delta (1 320 442 bytes), un commit `STREAMING UPDATE` por archivo |
| Bronze | `bronze.ingesta_log` | 4 renglones: archivo fuente, `ts_ingesta`, filas, versión |
| Silver | `silver.opus_clean` | 50 000 válidas, 0 en cuarentena, partición `anio_mes` (28 meses, 29 archivos, 2 190 219 bytes), Change Data Feed activo, `turno_discrepante` = 0 |
| DQ | `dq_reports.reporte_calidad` | 15 reglas × 4 lotes = 60 filas en silver, más 4 por lote de corrección |
| Gold | `gold.aurum_kpi_turno` | 4 019 celdas `(frente_id, fecha_local, turno_cod)`, 1 archivo (235 KB), `ZORDER BY (frente_id, fecha_local)` |
| CDC | 3 lotes del laboratorio | 120 filas actualizadas, 10 sin cambio, 5 sin evento, 5 inválidas; silver pasa de la versión 1 a la 4 |
| Gold incremental | desde `table_changes` | 98 celdas recalculadas de 4 019, 0 insertadas, 0 borradas |

KPI globales sobre las 4 019 celdas: ley ponderada media 7.94 g/t, eficiencia de avance
media 0.514, tasa de fallas media 3.34 %, horas efectivas medias 4.39 h de 6.

## 1. Del árbol del enunciado a Unity Catalog

El enunciado pide `lakehouse_umlc/bronze/opus_raw`, `silver/opus_clean`,
`gold/aurum_kpi_turno` y `dq_reports/`. Se traduce a un catálogo, cuatro esquemas y tablas
gestionadas Delta, sin rutas sueltas: en Unity Catalog una ruta en DBFS es deuda desde el
primer día.

| Enunciado | Objeto Delta | Partición / orden |
|---|---|---|
| `bronze/opus_raw` | `<catálogo>.bronze.opus_raw` | `fecha_ingesta` |
| — | `<catálogo>.bronze.ingesta_log` | ninguna |
| `silver/opus_clean` | `<catálogo>.silver.opus_clean` | `anio_mes`, Change Data Feed |
| — | `<catálogo>.silver.opus_cuarentena` | ninguna |
| `gold/aurum_kpi_turno` | `<catálogo>.gold.aurum_kpi_turno` | sin partición, `ZORDER BY (frente_id, fecha_local)` |
| `dq_reports/` | `<catálogo>.dq_reports.reporte_calidad` | ninguna |

Los archivos llegan al volumen `<catálogo>.bronze.landing`, con `opus/` para la telemetría y
`reclasificacion/` para el laboratorio. Los nombres están en `umlc_lakehouse/dominio.py` y
`catalogo.py` los califica; el catálogo es un parámetro del Asset Bundle (`catalogo`).

**El catálogo `lakehouse_umlc` se creó desde la interfaz, no por CLI.** El workspace del
trial usa *Default Storage*, y en ese modo la API y la CLI rechazan crear catálogos ("Please
use the UI to create a catalog with Default Storage"); es el único paso del B-1 que no fue por
línea de comandos. La primera corrida de validación se hizo sobre el catálogo `workspace` con
los mismos esquemas, y una vez creado `lakehouse_umlc` bastó redesplegar con
`--var catalogo=lakehouse_umlc`: el catálogo es un parámetro, no una cadena en el código.

## 2. Bronze: fidelidad al origen con metadata de ingesta

- **Auto Loader con esquema explícito.** `cloudFiles` lee los CSV del volumen con
  `EsquemaOpus.EXTRACTO` (18 columnas tipadas según el diccionario) y
  `schemaEvolutionMode = rescue`: nada se infiere y lo que no encaja queda en
  `_rescued_data`, que silver manda a cuarentena. `EsquemaOpus.verificar` compara nombre y
  tipo de cada columna y falla con el detalle; "no inferencia" se hace cumplir por máquina.
- **Llegada incremental.** `maxFilesPerTrigger = 1` convierte cada archivo en un microlote y
  un commit propio: la historia de bronze muestra cuatro `STREAMING UPDATE` con 44 786,
  1 827, 1 774 y 1 613 filas. El checkpoint de Auto Loader garantiza que un archivo ya leído
  no vuelve a entrar aunque el job se relance.
- **Metadata que exige el enunciado.** Cada fila lleva `archivo_fuente`
  (`_metadata.file_path`), `ts_ingesta`, `fecha_ingesta` y `lote_id`, que es el nombre del
  archivo sin extensión: es lo único que sobrevive igual en Auto Loader, en `dbutils.fs.ls`
  y en el log. Al cerrar el stream, `IngestorBronze.registrar_pendientes` escribe en
  `ingesta_log` un renglón por archivo con su conteo y la versión Delta vigente.
- **Bronze no deduplica ni corrige.** Reenviar un archivo lo anexa otra vez: la fidelidad
  al origen es su razón de ser y la deduplicación es de silver.

**Partición por `fecha_ingesta`.** La prescribe el enunciado, y es la partición correcta de
esta capa por razones operativas, no de lectura: reprocesar un día es borrar una partición,
la retención se expresa en días, y una ingesta cada 30 minutos nunca reescribe una partición
pasada y deja como mucho 48 archivos por día antes de `OPTIMIZE`. A la escala de este
lakehouse —50 000 filas pesan 1.3 MB en Delta; cuatro años serían unos 10 MB— Databricks
recomienda no particionar (menos de 1 TB) y exige al menos 1 GB por partición; la partición
se justifica por la operación y se declara que no compra rendimiento.

## 3. Silver: el diccionario hecho reglas

`LimpiadorSilver.enriquecer` agrega las columnas derivadas y los motivos de rechazo sin
quitar filas; sobre ese marco se evalúa el reporte de calidad y `separar` lo parte en
válidas y cuarentena. Que el reporte y la separación vean el mismo marco es lo que garantiza
que las cifras del reporte coincidan con lo que quedó en cada tabla.

- **Hora local.** `from_utc_timestamp(ts_opus_utc, 'America/Lima')`, con la zona IANA y no un
  desfase fijo: hoy Perú no tiene horario de verano, pero eso es una decisión del país y no
  del pipeline. De ahí salen `ts_local`, `fecha_local` y `anio_mes`.
- **Turno recalculado.** `turno_cod` se asigna desde la hora local con los bloques 00, 06,
  12 y 18 (`N2`, `D1`, `D2`, `N1`) y el valor recibido queda en `turno_cod_opus`. En las
  50 000 filas `turno_discrepante` es cero: la conversión y los bloques son los correctos, y
  es la misma comprobación que el EDA del Módulo A había anticipado.
- **Centinela.** `ley_au_gpT = -1` es la pérdida de comunicación de la sonda XRF (manual del
  equipo, sección 3; código `E-ELEC-04`). Pasa a nulo con `ley_valida = false` y no se
  imputa: reconstruir un valor es una decisión de modelado (Módulo A), y una ley imputada en
  silver contaminaría el KPI ponderado de gold. `prod_estimada_oz` viene nula exactamente en
  esas filas (2 810 en el extracto), lo que confirma que OPUS tampoco la calcula sin ley.
- **Alertas contra rechazos.** Un valor fuera del rango operacional del diccionario
  (presión 180–240 bar, 800–1 400 RPM, vibración > 12, temperatura > 95) es una alerta que
  se marca y se conserva; un valor físicamente imposible (presión negativa, temperatura bajo
  el cero absoluto), un dominio inválido (`tipo_mineral`, `sector_geol`), un timestamp nulo
  o una fila rescatada van a `opus_cuarentena` con su lista de motivos. Es la misma distinción
  que usa la API del A-2: rechazar las alertas dejaría fuera justo lo que operaciones quiere
  mirar. Los límites exactos están probados (180.0 no alerta, 179.9 sí).
- **Deduplicación e idempotencia.** Dentro del lote gana la copia con `ts_ingesta` más
  reciente; entre lotes, la escritura es un `MERGE` con solo `WHEN NOT MATCHED INSERT` sobre
  `(ts_opus_utc, frente_id)`: reingerir un archivo no duplica eventos. La clave es única en
  el extracto (ningún par comparte instante) y el frente la hace robusta a un sistema con
  varias perforadoras.
- **Change Data Feed** activo desde la creación, para que gold lea cambios y no tablas.

**Partición por `anio_mes`.** El enunciado pide una partición justificada. Los patrones de
consulta sobre silver son por rango de fecha: gold recalcula celdas por fecha, el monitor de
drift del B-3 lee los últimos 30 días y las correcciones del laboratorio caen sobre meses
concretos. El `MERGE` de una corrección poda a los meses tocados (en la corrida, un lote de
40 correcciones reescribió 1 archivo de 29). Se descartaron: `fecha_local` diaria, que
produce 1 460 particiones de ~100 filas en cuatro años; `sector_geol`, cuyos cuatro valores los
resuelve mejor el filtro de fila del RLS del B-2 y la estadística por archivo; y
`tipo_mineral`, que es justamente la columna que el CDC reescribe, y una partición por ella
convierte cada corrección en un borrado más una inserción entre particiones. Se declara el
límite: a 2.19 MB en 29 archivos, cada partición pesa unos 75 KB frente al mínimo de 1 GB que
publica Databricks, y a escala de telemetría real (30 segundos por equipo) la respuesta sería
liquid clustering por `(fecha_local, frente_id)` en lugar de partición.

### Reporte de calidad por lote

`ReporteCalidad` evalúa las reglas en una sola pasada agrupando por `lote_id` y deja una fila
por regla, capa y lote en `dq_reports.reporte_calidad`: filas evaluadas, filas en falla,
porcentaje, severidad y un detalle libre. Es tabla y no archivo porque el B-2 la consume desde
Fabric, y porque además hace de libro de control: un lote de bronze está procesado por
silver cuando tiene sus filas de reporte, así que `TablaSilver.lotes_pendientes` no depende de
que un lote haya dejado filas en silver (uno rechazado por completo no las dejaría y se
reprocesaría por siempre).

| Regla (severidad) | Histórico 2023-07 a 2025-07 | 2025-08 | 2025-09 | 2025-10 |
|---|---|---|---|---|
| `alerta_presion` (marca) | 9.51 % | 9.41 % | 9.41 % | 9.30 % |
| `alerta_temperatura` (marca) | 1.83 % | 2.19 % | 1.69 % | 1.92 % |
| `alerta_vibracion` (marca) | 0.28 % | 0.16 % | 0.28 % | 0.43 % |
| `ley_centinela` (marca) | 5.68 % | 4.65 % | 4.96 % | 5.77 % |
| `prod_estimada_nula` (informa) | 5.68 % | 4.65 % | 4.96 % | 5.77 % |
| las diez restantes | 0 | 0 | 0 | 0 |

El extracto no trae filas imposibles ni dominios inválidos; la cuarentena queda vacía y su
comportamiento está cubierto por las pruebas (`test_limpieza.py`).

## 4. Gold: `aurum_kpi_turno`

Grano `(frente_id, fecha_local, turno_cod)`, el mismo del modelado del A-2. Las cuatro
métricas del enunciado y la decisión que cada una encarna:

| KPI | Definición | Decisión |
|---|---|---|
| `ley_ponderada_gpt` | `sum(ley × ton_rom_acum) / sum(ton_rom_acum)` sobre filas con `ley_valida` | el peso es el tonelaje del evento y no el máximo del turno, porque el EDA mostró que `ton_rom_acum` no es acumulativo; el centinela sale del numerador y del denominador |
| `eficiencia_avance` | `avg(avance_mmin) / 3.5` | 3.5 m/min es el tope del rango normal del sensor LVDT LV-01 en el manual del equipo; el manual no publica avance nominal. Se descartó el percentil 95 histórico del frente por no tener fuente externa |
| `tasa_fallas` | eventos con `falla_cod` / eventos del turno | misma base que la alerta del 5 % que pide el B-2 |
| `horas_efectivas` | lapso entre primer y último evento del turno, acotado a 6 h, menos el tiempo de los eventos con falla o `flag_mant_prev` | el tiempo de un evento es el que transcurre hasta el siguiente del mismo turno; el último no aporta, así que la medida subestima en una cadencia |

Columnas de soporte: conteos de eventos, de ley válida, de fallas, de mantenimiento y de
alertas por sensor, tonelaje total, `prod_estimada_oz_total` (la de OPUS) y
`prod_oz_recalculada` (la fórmula de OPUS con el tipo de mineral vigente y los factores de
recuperación despejados en el A-2: EST 0.10, MIX 0.83, OX 0.87, SUL 0.91), equipos distintos,
`n_reclasificados`, primer y último evento y `ts_calculo`.

**Sin partición, con Z-ORDER.** Gold tiene 4 019 filas en un archivo de 235 KB; a cuatro años
serían unas 10 000. Particionarla produciría archivos de kilobytes. Se ordena con
`OPTIMIZE ... ZORDER BY (frente_id, fecha_local)` porque las consultas del B-2 —ranking de
frentes por producción, tendencia semanal, un frente en un rango de fechas— filtran por las
dos dimensiones a la vez, y una partición solo sirve a una. El Z-ORDER agrupa en los mismos
archivos los valores cercanos de ambas columnas, de modo que el salto de archivos por
estadísticas mín/máx funciona con cualquiera de los dos filtros. A esta escala el beneficio
es nulo y se dice así: con un solo archivo el primer `OPTIMIZE` ni siquiera escribió versión
(no había nada que compactar); tras el `MERGE` incremental sí compactó dos archivos en uno
(versión 5 de gold). En Unity Catalog el Z-ORDER y liquid clustering son excluyentes; a escala
real la elección sería liquid clustering por las mismas dos columnas, que además no exige
programar `OPTIMIZE`.

## 5. CDC: reclasificaciones del laboratorio

El laboratorio reclasifica `tipo_mineral` de eventos pasados. El simulador
(`umlc_lakehouse/simulacion.py`) genera tres lotes deterministas diseñados para ejercitar
cada rama del `MERGE`:

| Lote | Contenido | Actualizadas | Sin cambio | Sin evento | Inválidas | Versión silver |
|---|---|---|---|---|---|---|
| `01_reclasificacion_2025-08` | 40 eventos MIX → OX | 40 | 0 | 0 | 0 | 2 |
| `02_reclasificacion_2025-09` | 40 EST → SUL + 10 reenvíos del lote 1 | 40 | 10 | 0 | 0 | 3 |
| `03_reclasificacion_2025-07` | 40 SUL → MIX + 5 claves inexistentes + 5 tipos `XX` | 40 | 0 | 5 | 5 | 4 |

- `MERGE INTO silver.opus_clean` por `(ts_opus_utc, frente_id)`, con
  `WHEN MATCHED AND t.tipo_mineral <> s.tipo_mineral_lab`: solo se escribe lo que cambia, y
  un reenvío ya aplicado no produce versión (los 10 reenvíos del lote 2 quedan como "sin
  cambio"). No hay `WHEN NOT MATCHED INSERT`: corregir un evento que no existe es un error
  del laboratorio o de la clave, y las cinco claves quedan listadas en el `detalle` del
  reporte de calidad (`2025-07-01 07:31:30|FR-C2-07`, ...). Los tipos fuera de dominio se
  cuentan como inválidos.
- La fila corregida conserva su historia: `fuente_tipo_mineral = LAB`, `fecha_correccion` y
  `lote_correccion`. Bronze no se toca, y `VERSION AS OF` muestra el antes y el después: la
  clave `2025-08-01 10:24:00|FR-N2-04` pasa de MIX (versión 1) a OX (versión 2) y el lote 2 la
  encuentra ya en OX.
- `prod_estimada_oz` no se reescribe: es un cálculo de OPUS con el factor del tipo viejo.
  Gold la conserva y agrega `prod_oz_recalculada`; en la celda `FR-C1-01 · 2025-07-01 · D1`,
  con un evento reclasificado, la producción pasa de 640.54 oz (OPUS) a 633.84 oz.
- **Gold incremental.** `ActualizadorGold` guarda en una propiedad de la tabla la última
  versión de silver incorporada, lee `table_changes` entre esa versión y la vigente,
  identifica las celdas tocadas, las recalcula desde la silver actual y las funde con un
  `MERGE` que actualiza, inserta o borra (si una celda se quedó sin eventos). En la corrida:
  de la versión 1 a la 4 de silver, 98 celdas recalculadas de 4 019, con `numTargetRowsCopied
  = 0`. Eso es lo que hace incremental al CDC: una corrección de 120 eventos no reconstruye
  la tabla.
- **Idempotencia probada en la nube.** Una segunda ejecución del job sobre el mismo
  catálogo (corrida de validación en `workspace`, 12:14 del mismo día) terminó en éxito sin
  trabajo: bronze `lotes_nuevos = []`, silver `lotes_pendientes = []` y
  `archivos_pendientes = []`, y las dos tareas de gold en modo `sin_cambios` con la versión 4
  de silver ya incorporada.

Un hallazgo que sale del cruce con los PDF: el informe geológico publica recuperaciones OX
87–92 %, MIX 78–85 % y SUL 74–81 %, y los factores implícitos en `prod_estimada_oz` dan SUL
0.91 por encima de OX 0.87. El recalculo usa los factores de OPUS porque debe reproducir su
fórmula con el tipo nuevo; la discrepancia con el laboratorio es un hallazgo para operaciones,
no un parámetro que el pipeline pueda resolver.

## 6. Costos

Estimación previa: entre 1.6 y 7.9 USD (notebooks serverless 0.75 USD/DBU, jobs 0.35, SQL
0.70; los tres confirmados en `system.billing.list_prices` antes de gastar). La corrida
completa del job —cinco tareas en serverless— tardó 4 min 14 s de reloj y se ejecutó tres
veces (validación en `workspace`, idempotencia y la definitiva en `lakehouse_umlc`); el
desarrollo no usó notebooks interactivos ni el warehouse, salvo tres consultas de un minuto
para confirmar precios y leer el consumo. Estimación de lo gastado en la sesión: entre 0.5 y
0.7 USD. El consumo facturado se lee de `system.billing.usage`, que se
publica con horas de rezago.

## 7. Límites y decisiones que quedan abiertas

- **El catálogo se crea a mano.** Ver la sección 1: es la única acción del B-1 fuera de la
  CLI, impuesta por el modo Default Storage del trial.
- **Una versión por corrida en `ingesta_log`.** Auto Loader escribe un commit por archivo,
  pero el log registra la versión vigente al cerrar el stream (la 4 para los cuatro lotes).
  La versión por archivo está en `DESCRIBE HISTORY`; recuperarla en el log exigiría cruzar
  la historia y no aporta nada que la historia no tenga.
- **Sin `foreachBatch`.** La primera versión de los notebooks usaba `foreachBatch` para
  procesar cada microlote con el paquete; se retiró porque en serverless el notebook corre
  bajo Spark Connect, la función se ejecuta en el servidor y el estado del cliente no llega
  a ella. El stream escribe directo a bronze y el log se completa en batch; silver y las
  correcciones se procesan en batch con sus libros de control (`reporte_calidad` e
  `ingesta_log`).
- **Reproceso parcial.** Si silver escribe y el reporte falla antes de escribirse, el lote se
  reprocesa: el `MERGE` es idempotente, pero la cuarentena se anexaría dos veces. Es un caso
  conocido y no cubierto; la solución es escribir cuarentena también por `MERGE`. En las
  correcciones el orden ya lo contempla: el archivo se registra en `ingesta_log` después de
  aplicarse, y un reintento vuelve a pasar por un `MERGE` que no reescribe lo aplicado.
- **`OPTIMIZE` en cada actualización.** A esta escala es gratis; en producción se programaría
  aparte, o se reemplazaría por liquid clustering.
- **`archivo_fuente` con esquema `dbfs:/`.** Auto Loader y `dbutils.fs.ls` no escriben el mismo
  prefijo; el log compara por nombre de archivo, que es único dentro del volumen.

## 8. Cómo reproducir

En local, sin Databricks: las pruebas ejercitan todo el paquete sobre Spark local con datos
sintéticos (`pytest modulo_b/umlc_lakehouse/tests`, unos 3 minutos; requiere un JDK).

```bash
# Lotes de llegada y de corrección, deterministas, desde el extracto (data/ está ignorado)
PYTHONPATH=modulo_b python -m umlc_lakehouse.simulacion --csv data/OP_AURUM_extract.csv --salida data/lotes

# Objetos de Unity Catalog, sin cómputo
export DATABRICKS_CONFIG_PROFILE=<perfil>
for e in bronze silver gold dq_reports; do databricks schemas create $e <catalogo>; done
databricks volumes create <catalogo> bronze landing MANAGED
databricks fs cp -r data/lotes/opus dbfs:/Volumes/<catalogo>/bronze/landing/opus
databricks fs cp -r data/lotes/reclasificacion dbfs:/Volumes/<catalogo>/bronze/landing/reclasificacion

# Despliegue y ejecución del job (serverless)
cd modulo_b
databricks bundle validate --var="catalogo=<catalogo>"
databricks bundle deploy   --var="catalogo=<catalogo>"
databricks bundle run lakehouse_umlc_b1 --var="catalogo=<catalogo>"
```

Cada notebook termina con `dbutils.notebook.exit(json)` y `bundle run` imprime esos
resúmenes: no hace falta abrir la interfaz ni un warehouse para verificar la corrida.
