# Diccionario de variables — OP_AURUM_extract.csv

Fuente: OPUS-MINE, plataforma de telemetría operacional de la Unidad Minera La Cornisa
(UMLC). El archivo es un extracto plano de eventos de perforación. Los nombres de columna
son la nomenclatura interna de sensores y no se renombran (restricción del enunciado,
Sección 6).

Definiciones transcritas del enunciado DS-MINE-2025-v2, Sección 2. Las columnas
"Naturaleza" y "Notas" son análisis propio, contrastado contra los datos.

## Tabla de referencia

| Columna | Tipo / Unidad | Descripción (enunciado) | Naturaleza |
|---|---|---|---|
| `ts_opus_utc` | datetime (UTC) | Timestamp del evento en OPUS-MINE. | Eje temporal |
| `frente_id` | string (FK) | Frente de extracción activo. Formato `FR-{zona}-{num}`. | Identificador de lugar |
| `turno_cod` | string categórico | Turno: D1, D2, N1, N2. | Contexto organizacional |
| `ley_au_gpT` | float (g/t) | Ley de oro. Sonda XRF in situ. Puede contener valores especiales. | Variable geológica — objetivo de regresión |
| `ton_rom_acum` | float (t) | Toneladas ROM acumuladas en el turno. | Variable de producción |
| `pres_hidraul_bar` | float (bar) | Presión hidráulica de la perforadora. Rango normal 180-240. | Sensor de máquina |
| `rpm_corona` | int | RPM de corona. Rango operacional 800-1400. | Sensor de máquina |
| `avance_mmin` | float (m/min) | Velocidad de avance de perforación. | Sensor de desempeño |
| `agua_iny_lmin` | float (L/min) | Flujo de agua de inyección. | Sensor de proceso |
| `vibracion_rms_ms2` | float (m/s2) | Vibración RMS del cuerpo. Alerta operacional >12. | Sensor de salud mecánica |
| `temp_motor_c` | float (C) | Temperatura del motor. Apagado automático >95. | Sensor de salud mecánica |
| `op_id` | string (FK) | Operador anonimizado. Formato `OP-{hash4}`. | Etiqueta sin contenido en este extracto (ver sección 1) |
| `equipo_id` | string (FK) | Equipo de perforación. | Etiqueta sin contenido en este extracto (ver sección 1) |
| `falla_cod` | string / null | Código OPUS de falla. Null = operación normal. | Evento — objetivo de clasificación |
| `prod_estimada_oz` | float (oz) | Producción estimada por OPUS (calculada, no medida). | Variable derivada — no es medición |
| `tipo_mineral` | string categórico | Clasificación geológica: OX, SUL, MIX, EST. | Atributo geológico |
| `sector_geol` | string | Sector geológico UMLC. | Atributo geológico de agregación |
| `flag_mant_prev` | bool (0/1) | Equipo en ventana de mantenimiento preventivo. | Estado programado — sin poder discriminante (ver sección 4) |

## Análisis conceptual

El extracto mezcla cuatro familias de variables que tienen orígenes, latencias y grados de
confiabilidad distintos. Tratarlas como una tabla homogénea de features es el primer error
que hay que evitar.

### 1. Contexto: dónde, cuándo, quién

`ts_opus_utc`, `frente_id`, `turno_cod`, `op_id`, `equipo_id`.

`frente_id` y `sector_geol` no son independientes: cada frente pertenece a un único sector
y el prefijo de zona del código (`FR-C1-05` es Cuerpo-Central, `FR-N…` Rampa-Norte,
`FR-S…` Veta-Sur, `FR-C2-…` Veta-Principal) ya codifica esa jerarquía. Son la misma
información a dos granularidades: el sector agrupa, el frente discrimina.

`turno_cod` es una partición determinista de la hora del reloj, no una variable
independiente. En este extracto la hora UTC determina el turno sin excepción, con una
frontera en 05:00, 11:00, 17:00 y 23:00 UTC; leído en hora local de Perú (UTC-5) eso da
turnos de seis horas que arrancan a las 00:00, 06:00, 12:00 y 18:00, lo que corresponde a
la operación real. Es la evidencia de que la conversión a hora local del Módulo B tiene que
ser UTC-5 y de que el turno debe recalcularse, no copiarse.

`op_id` y `equipo_id` son identificadores que en una operación real llevarían señal
(habilidad del operador, estado del activo). **En este extracto no la llevan**, y el EDA
documenta por qué: el archivo es un flujo estrictamente serial — ningún par de registros
comparte instante ni siquiera minuto, la cadencia global es uniforme entre 15 y 34 minutos y
todos los segundos son 00 — lo que es incompatible con diez perforadoras trabajando en
paralelo. Se adopta el supuesto de que el extracto es sintético y de que `op_id` y `equipo_id`
son etiquetas repartidas al azar sobre un flujo único: cada equipo aparece en los trece
frentes, cada operador en los diez equipos, y las leyes medias y las tasas de falla son planas
entre unos y otros.

La consecuencia es que ninguna de las dos columnas admite lectura causal ni es candidata útil
a target encoding: cualquier señal que apareciera sería ruido codificado. La exigencia de
leave-one-out sigue vigente donde sí hay señal, que es `frente_id`.

### 2. Geología: lo que la mina tiene, no lo que la máquina hace

`ley_au_gpT`, `tipo_mineral`, `sector_geol`.

La ley de oro es una propiedad del macizo rocoso, no del proceso de perforación. Esto tiene
una consecuencia directa sobre el modelado: los sensores de la perforadora describen cómo
se está perforando, no cuánto oro hay. La expectativa razonable a priori es que la señal
predictiva de la ley venga de la ubicación (frente y sector), de la historia reciente de ley
en ese mismo frente y del tipo de mineral, mientras que presión, RPM, agua y vibración
aporten poco de forma directa. El EDA confirma esa hipótesis: la correlación lineal de la
ley con cada sensor de máquina es del orden de 0.005, mientras que la media de ley entre
sectores va de 4.5 g/t en Rampa-Norte a 13.4 g/t en Veta-Principal.

`ley_au_gpT` usa un valor centinela para el dato faltante: el mínimo del campo es
exactamente -1.0 y aparece en 2810 registros. Una ley negativa no existe físicamente, así
que -1 es "sin lectura válida de la sonda XRF" codificado dentro del dominio numérico. Es
el caso borde que el imputador tiene que atender. Su distribución no es aleatoria: se
concentra en el turno N2 (16.1% de sus registros, frente a ~2.1% en los otros tres), lo que
lo hace un faltante condicionado a una variable observada y no un faltante completamente
al azar. Imputar sin dejar rastro borraría esa estructura; de ahí que la marca
`flag_imputed` no sea un adorno sino parte de la información.

`tipo_mineral` es una clasificación de laboratorio, y el propio Módulo B advierte que se
corrige retroactivamente tras el análisis: es un dato que llega tarde y cambia. Usarlo como
feature en un modelo que predice el turno siguiente obliga a preguntarse si en el momento
de la predicción ya está disponible el valor definitivo o solo la clasificación provisional
de campo.

### 3. Máquina: presión, giro, agua, vibración, temperatura

`pres_hidraul_bar`, `rpm_corona`, `avance_mmin`, `agua_iny_lmin`, `vibracion_rms_ms2`,
`temp_motor_c`.

Son series de sensores con rangos operacionales publicados en el diccionario, lo que
permite construir banderas de anomalía con criterio de dominio en lugar de con percentiles
arbitrarios. Los rangos del diccionario no coinciden con los rangos observados y esa
diferencia es informativa, no un error de datos: la presión hidráulica sale de la banda
180-240 bar en cerca del 9.5% de los registros, la vibración supera el umbral de alerta de
12 m/s2 en 140 registros y la temperatura de motor supera los 95 C de apagado automático en
922. Un valor fuera de rango no es ruido a recortar; es exactamente el evento que interesa
detectar.

Las dos variables de salud mecánica se comportan distinto frente a la falla:
`temp_motor_c` separa con claridad (media de 81.4 C en registros con falla contra 71.6 C sin
falla) y `vibracion_rms_ms2` apenas (3.72 contra 3.59). La temperatura es el candidato
natural a predictor principal de falla, y sus excedencias tienen tasa de falla del 22%
contra una prevalencia base del 3.3%. La relación está medida **dentro del mismo registro**:
temperatura y código de falla vienen en la misma fila, de modo que lo observado es
coocurrencia y no precedencia. El extracto no contiene evidencia de que la temperatura
anteceda a la falla, así que hablar de "precursor" sería atribuirle al dato algo que no
demuestra.

`ton_rom_acum` se documenta como tonelaje acumulado del turno, pero dentro de un mismo
frente, turno y fecha la serie es monótona creciente en apenas el 4.0% de los grupos. O el
campo no es acumulado en el sentido estricto, o los eventos de un turno no vienen de un
único contador. Cualquier KPI que lo trate como acumulador (por ejemplo tomando el máximo
del turno) descansa en un supuesto que los datos no respaldan, y conviene sumar en lugar de
maximizar, dejando el supuesto declarado.

### 4. Salidas del propio sistema OPUS

`falla_cod`, `prod_estimada_oz`, `flag_mant_prev`.

`falla_cod` es nulo en operación normal: la ausencia es información, no un dato perdido, y
convertirlo a binario da una prevalencia de 3.3% (1659 de 50000 registros). Ese desbalance
es el que hay que argumentar en el Ejercicio A-2. Los ocho códigos se reparten en cinco
familias por prefijo (H- hidráulica, M- motor, E- eléctrica, B- bomba, S- sello), con
frecuencias muy parejas entre 192 y 227 eventos cada uno, y ese prefijo es una agrupación de
subsistema aprovechable si el modelo multiclase se vuelve necesario.

`flag_mant_prev` marca ventanas de mantenimiento programado: cubre el 2.4% de los registros
y su tasa de falla es 2.80% contra 3.33% fuera de ventana. La diferencia **no se distingue
del azar**: con 1213 registros dentro de ventana, la prueba de dos proporciones da z = -1.01 y
p = 0.31, y el intervalo de confianza del 95% para la tasa dentro de ventana (1.87% a 3.73%)
contiene la tasa base. La columna no separa ningún subconjunto del extracto. Bajo el supuesto
de la sección 1 tampoco autoriza a concluir nada sobre el programa preventivo de la unidad
minera: es una etiqueta más repartida sobre el flujo.

**`prod_estimada_oz` merece su propio párrafo, porque es la trampa del ejercicio.** El
enunciado la describe como "calculada, no medida directamente", y los datos permiten
recuperar la fórmula exacta:

```
prod_estimada_oz = ley_au_gpT * ton_rom_acum / 31.1035 * recuperacion(tipo_mineral)
```

donde 31.1035 es la onza troy en gramos y la recuperación metalúrgica depende del tipo de
mineral: OX 0.87, SUL 0.91, MIX 0.83, EST 0.10. La reconstrucción ajusta con R2 de
0.999999999972 y error absoluto máximo de 6.5e-4 oz, atribuible al redondeo a cuatro
decimales del archivo. La confirmación adicional es que `prod_estimada_oz` es nula
exactamente en los 2810 registros donde la ley vale -1: no hay producción estimada porque no
hubo ley que multiplicar.

De ahí que usar `prod_estimada_oz` para predecir `ley_au_gpT` sea una circularidad, no un
hallazgo: el modelo aprendería a invertir una fórmula que ya conocemos, exhibiría un ajuste
casi perfecto en validación y fracasaría en producción, donde la producción estimada del
turno que se quiere predecir todavía no existe porque se calcula a partir de la ley que
falta. La variable no aporta información sobre el yacimiento; aporta información sobre la
respuesta. Esta es la respuesta al bloque obligatorio del Ejercicio A-2, y por eso se
documenta aquí con la evidencia numérica que la sostiene.

## Discrepancias del extracto frente al enunciado

Se registran para no confundirlas con errores de lectura:

- El enunciado describe un extracto de 18 meses; el archivo cubre del 2023-07-01 al
  2025-10-28, es decir 27.9 meses, en 50000 registros.
- Los rangos "normales" del diccionario para presión y RPM no son los rangos observados. En
  RPM ningún registro sale de 800-1400; en presión, el 9.5% sí sale de 180-240.
- El diccionario declara `falla_cod` con ejemplos de códigos de fallas hidráulicas; el
  archivo contiene ocho códigos de cinco subsistemas distintos.
- El extracto no contiene un solo evento simultáneo: cero timestamps repetidos, nunca dos
  registros en el mismo minuto y jamás dos frentes o dos equipos a la vez, con una cadencia
  global uniforme entre 15 y 34 minutos. Es incompatible con diez equipos operando en
  paralelo y sostiene el supuesto de extracto sintético descrito arriba.
