# Tabla de resultado del pipeline AURUM

Documenta columna por columna el marco que entrega el pipeline del Ejercicio A-1 sobre
`OP_AURUM_extract.csv`: **50 000 filas × 30 columnas**, las 18 originales sin alterar más 12
agregadas. Es la referencia para leer cualquier salida del pipeline sin volver a deducir qué
significa cada campo.

La tabla se produce encadenando los tres transformadores en este orden:

```python
imputador = AurumImputer()
imputado  = imputador.fit_transform(crudo)
codificado = AurumShiftEncoder().fit_transform(imputado, imputador.objetivo_medido(imputado))
final = AurumFeatureBuilder().fit_transform(codificado)
```

La demostración ejecutable está en [`../modulo_a/aurum_pipeline/pipeline_demo.ipynb`](../modulo_a/aurum_pipeline/pipeline_demo.ipynb)
y la evidencia de cada decisión, en [`../modulo_a/exploration/eda_opus.ipynb`](../modulo_a/exploration/eda_opus.ipynb).

**Convenciones.** Los rangos son los observados en el extracto completo, no los declarados en el
diccionario. Cuando ambos difieren, se indica. `NaN` significa faltante genuino; ninguna columna
usa valores centinela después del pipeline. Las advertencias marcadas con `[A#]` se desarrollan
al final.

---

## Columnas originales

Se conservan con su nomenclatura interna OPUS, sin renombrar ni reordenar, por restricción del
enunciado.

| Columna | Tipo | Unidad | Definición e interpretación | Rango observado | Nulos |
|---|---|---|---|---|---|
| `ts_opus_utc` | datetime | UTC | Instante del evento. Define el orden de todo el extracto y es el origen del turno y de la fecha local. Único por registro. `[A1]` | 2023-07-01 a 2025-10-28 | 0 |
| `frente_id` | texto | — | Frente de extracción, formato `FR-{zona}{n}-{nn}`. Es la variable de ubicación más fina y la que más separa la ley. | 13 categorías | 0 |
| `turno_cod` | texto | — | Turno operacional: D1, D2, N1, N2. No es información independiente: se deriva de la hora con un desfase de cinco horas. `[A2]` | 4 categorías | 0 |
| `ley_au_gpT` | float | g/t (gramos de oro por tonelada) | Ley de oro medida con sonda XRF. **Objetivo de regresión.** Después del pipeline ya no contiene el centinela: 2315 valores son reconstruidos y 495 quedan en `NaN`. `[A3]` | 0.87 a 25.76 · mediana 7.32 | 495 |
| `ton_rom_acum` | float | t (toneladas) | Tonelaje de mineral ROM. Pese al nombre **no es un acumulado del turno**: es el tonelaje del evento individual. `[A4]` | 24.61 a 419.99 · mediana 221.85 | 0 |
| `pres_hidraul_bar` | float | bar | Presión hidráulica de la perforadora. Rango normal del diccionario 180–240; el 9.5% de los registros sale de esa banda. | 140.0 a 270.0 · mediana 210.0 | 0 |
| `rpm_corona` | entero | rev/min | Revoluciones de la corona de perforación. Rango operacional del diccionario 800–1400; ningún registro sale de él. `[A5]` | 820 a 1379 · mediana 1101 | 0 |
| `avance_mmin` | float | m/min | Velocidad de penetración. Sin rango publicado en el diccionario. | 0.30 a 3.42 · mediana 1.80 | 0 |
| `agua_iny_lmin` | float | L/min | Caudal de agua de inyección para barrido. Sin rango publicado. | 8.0 a 90.0 · mediana 44.98 | 0 |
| `vibracion_rms_ms2` | float | m/s² | Vibración RMS del cuerpo de la máquina. Alerta operacional del diccionario sobre 12 m/s². | 0.50 a 19.62 · mediana 3.20 | 0 |
| `temp_motor_c` | float | °C | Temperatura del motor. Apagado automático declarado sobre 95 °C, pero el riesgo real empieza en 88 °C. `[A6]` | 38.0 a 108.49 · mediana 72.0 | 0 |
| `op_id` | texto | — | Operador anonimizado, formato `OP-{hash4}`. **No admite lectura causal.** `[A7]` | 18 categorías | 0 |
| `equipo_id` | texto | — | Equipo de perforación. **No admite lectura causal.** `[A7]` | 10 categorías | 0 |
| `falla_cod` | texto / nulo | — | Código OPUS de falla; nulo significa operación normal. **Origen del objetivo de clasificación.** Ocho códigos de cinco subsistemas. | 8 categorías · 3.32% de los registros | 48 341 |
| `prod_estimada_oz` | float | oz (onzas troy) | Producción estimada por OPUS. **Calculada, no medida**: es función determinista de la ley, el tonelaje y el tipo de mineral. `[A8]` | 0.24 a 265.50 · mediana 40.05 | 2 810 |
| `tipo_mineral` | texto | — | Clasificación geológica: OX, SUL, MIX, EST. No discrimina la ley; determina el factor de recuperación metalúrgica. | 4 categorías | 0 |
| `sector_geol` | texto | — | Sector geológico. Misma jerarquía que `frente_id`, más gruesa: cada frente pertenece a un único sector. | 4 categorías | 0 |
| `flag_mant_prev` | entero | 0/1 | Registro dentro de una ventana de mantenimiento preventivo programado. Sin poder discriminante. `[A9]` | 2.43% en 1 | 0 |

---

## Columnas agregadas por el pipeline

### `AurumImputer`

| Columna | Tipo | Unidad | Definición e interpretación | Cobertura |
|---|---|---|---|---|
| `flag_imputed` | booleano | — | **`True` marca lo que NO se pudo imputar.** Sigue la letra del enunciado: la fila tenía el centinela de ley y su ventana de siete días del mismo frente y tipo de mineral no llegó a cinco lecturas válidas, así que la ley quedó en `NaN` en lugar de reconstruirse. `[A3]` | 495 filas (0.99%) |

### `AurumShiftEncoder`

| Columna | Tipo | Unidad | Definición e interpretación | Rango observado |
|---|---|---|---|---|
| `frente_id_target_enc` | float | g/t | Ley media del frente, calculada dejando fuera la propia fila (leave-one-out) y suavizada hacia la media global con `smoothing=10`. Es el predictor más fuerte del extracto: correlaciona 0.92 con la ley. `[A10]` | 2.91 a 15.28 |
| `equipo_id_target_enc` | float | g/t | Lo mismo para el equipo. Se codifica porque el enunciado lo pide; el resultado se mueve en un rango de 0.15 g/t alrededor de la media global y correlaciona 0.00 con la ley. `[A7]` | 7.91 a 8.06 |

### `AurumFeatureBuilder`

| Columna | Tipo | Unidad | Definición e interpretación | Rango observado | Nulos |
|---|---|---|---|---|---|
| `ley_ventana` | float | g/t | **Media** de la ley del mismo frente en los siete días anteriores, sin incluir la propia fila. Estimador causal del nivel del frente, que es la única señal disponible para la regresión: correlaciona 0.91 con la ley, prácticamente el techo teórico. `[A11]` | 1.19 a 22.21 | 456 |
| `ley_n_ventana` | float | conteo | Cuántas lecturas respaldan a `ley_ventana`. Cero significa ventana vacía, no dato faltante. **Cuenta lecturas disponibles, no necesariamente medidas.** `[A12]` | 0 a 366 · mediana 68 | 0 |
| `ley_lag_1` | float | g/t | Última ley válida observada en el frente. Son las "condiciones actuales" del enunciado y la única información cuando la ventana está vacía. Correlaciona 0.84 con la ley. | 0.87 a 25.76 | 14 |
| `dias_desde_evento_previo` | float | días | Tiempo desde el evento anterior del mismo frente. Mide qué tan frescas están las tres features anteriores. La distribución es bimodal: mediana de 25 minutos, máximo de 115 días. `[A13]` | 0.0104 (15 min) a 115.47 | 13 |
| `flag_temp_riesgo` | booleano | — | Temperatura sobre **88 °C**, el punto de quiebre medido en el extracto. Tasa de falla del 22.7% contra 3.3% de base; captura el 49% de todas las fallas. `[A6]` | 3 602 filas (7.20%) | 0 |
| `flag_temp_apagado` | booleano | — | Temperatura sobre **95 °C**, el umbral de apagado automático del diccionario. Misma tasa de falla (22.0%) pero captura solo el 12% de las fallas. | 922 filas (1.84%) | 0 |
| `flag_vib_alerta` | booleano | — | Vibración sobre **12 m/s²**, la alerta operacional del diccionario. Tasa de falla del 17.1%. Solo el 19% de estos registros supera también el umbral térmico: no es información repetida. | 140 filas (0.28%) | 0 |
| `energia_especifica_proxy` | float | bar·rev/m ≡ 10⁵ N/m³ | `pres_hidraul_bar × rpm_corona / avance_mmin`. Aproximación al esfuerzo por metro perforado, que en una operación real seguiría a la dureza de la roca. **No es energía específica en J/m³**; se convierte multiplicando por una constante de geometría de la máquina con unidades de longitud. `[A14]` | 49 404 a 979 704 · mediana 128 293 | 0 |
| `sobretemperatura_por_rpm` | float | °C·min/rev | `(temp_motor_c − 38) / rpm_corona`. Grados por encima de la referencia ambiente por cada revolución por minuto: separa el motor caliente porque trabaja del caliente sin razón. Se mide sobre el **incremento** y no sobre la temperatura absoluta. `[A15]` | 0.0 a 0.0805 · mediana 0.0309 | 0 |

---

## Notas y advertencias

**[A1] El archivo es un flujo estrictamente serial.** No hay un solo evento simultáneo: cero
timestamps repetidos, nunca dos registros en el mismo minuto, jamás dos frentes o dos equipos a
la vez, y la cadencia global es uniforme entre 15 y 34 minutos con todos los segundos en 00. Es
incompatible con diez perforadoras operando en paralelo. Se adopta el supuesto de que el extracto
es sintético y de que las etiquetas se repartieron sobre un flujo único. El orden temporal del
archivo es orden de emisión, no secuencia de operación concurrente.

**[A2] `turno_cod` no aporta información independiente.** Cada hora UTC pertenece a un único
turno, con fronteras en 05:00, 11:00, 17:00 y 23:00 UTC. El desfase implícito del archivo es de
cinco horas; que corresponda a la zona horaria de la operación es la interpretación natural, pero
el archivo no declara zona horaria en ninguna parte.

**[A3] La ley después del pipeline mezcla medición y reconstrucción.** De los 2810 centinelas
originales, 2315 se reemplazaron por la mediana de sus vecinas y 495 quedaron en `NaN`. La
columna ya no es homogénea: quien la use como objetivo debería excluir las reconstruidas con
`AurumImputer.objetivo_medido(...)`, que las devuelve como faltantes. **Cuidado con el nombre de
`flag_imputed`**: marca lo que *no* se imputó, siguiendo la letra del enunciado, que es lo
contrario de lo que el nombre sugiere. Las filas efectivamente reconstruidas quedan en
`AurumImputer.filas_imputadas_`, como estado del transformador y no como columna.

**[A4] `ton_rom_acum` no es un acumulado.** Dentro de un mismo frente, fecha y turno la serie es
creciente en apenas el 4% de los grupos; en un turno aislado del extracto el valor baja en 8 de
17 transiciones. Cualquier KPI que tome el máximo del turno como acumulado final estará
equivocado: hay que **sumar**. En el turno de ejemplo, 4201 t sumando contra 414 t maximizando.

**[A5] `rpm_corona` nunca sale de su rango.** Una bandera de excedencia sobre esta variable sería
una columna constante, así que no se construye pese a que el diccionario publica el rango.

**[A6] El umbral térmico real es 88 °C, no los 95 °C del diccionario.** La relación con la falla
es un escalón: hasta 87 °C la tasa ronda el 2%, entre 88 y 89 salta al 22% y de ahí en adelante
se mantiene plana. Por encima del umbral la magnitud del exceso no discrimina (correlación
+0.02), razón por la cual se codifica como bandera y no como variable continua. Tiene lectura
operacional directa: entre 88 y 95 °C el equipo opera con el riesgo ya multiplicado por diez y
sin que el apagado automático intervenga.

**[A7] `equipo_id` y `op_id` son etiquetas sin contenido.** Cada equipo aparece en los trece
frentes, cada operador pasa por los diez equipos, y tanto la ley media como la tasa de falla son
planas entre unos y otros, dentro de la banda que se espera solo por muestreo. No soportan
ninguna afirmación sobre el desempeño de máquinas ni de cuadrillas. Se codifican porque el
enunciado lo pide; cualquier señal que apareciera en ellas sería ruido codificado.

**[A8] `prod_estimada_oz` no puede usarse como feature para predecir la ley.** Es
`ley_au_gpT × ton_rom_acum / 31.1035 × recuperacion(tipo_mineral)`, con R² de 0.999999999972 y
error máximo de 6.5e-4 oz. Usarla sería invertir una fórmula conocida y, además, en el momento de
predecir el turno siguiente ese valor todavía no existe. El pipeline nunca la usa; se conserva en
la tabla porque es parte del extracto original.

**[A9] `flag_mant_prev` no discrimina.** La tasa de falla dentro de la ventana preventiva es
2.80% contra 3.33% fuera, y la diferencia no se distingue del azar: z = −1.01, p = 0.31, con un
intervalo de confianza del 95% de 1.87% a 3.73% que contiene la tasa base. No autoriza a concluir
nada sobre el programa de mantenimiento de la unidad.

**[A10] La codificación por objetivo debe ajustarse solo con datos de entrenamiento.** El diseño
lo permite —`fit` sobre train y `transform` sobre test— pero no lo obliga. Con una partición
temporal, ajustar sobre todo el histórico filtraría información del futuro. `fit_transform` y
`transform` hacen cosas distintas a propósito: la primera aplica leave-one-out, la segunda la
media suavizada aprendida.

**[A11] La ley es el nivel del frente más ruido blanco.** Un modelo que solo usa la media del
frente explica el 83% de la varianza, y al descontarla la autocorrelación cae a −0.001. Sobre el
objetivo real —ley media del turno siguiente— la media histórica del frente predice con R² de
0.9752 y el turno anterior con 0.9505. Consecuencia: el baseline honesto es la media del frente,
no el último valor, y ninguna feature de historia de ley aporta información nueva más allá de ese
nivel. Se usa **media** y no mediana porque dentro de cada frente la ley es simétrica
(asimetría +0.03) y la contaminación ya la trató el imputador; la media gana en RMSE, MAE y R².

**[A12] `ley_n_ventana` cuenta lo disponible, no lo medido.** Si el imputador corrió antes, en la
ventana hay lecturas medidas y reconstruidas, y la feature no distingue entre unas y otras. Es una
medida de respaldo, no de calidad del dato.

**[A13] Los frentes son intermitentes.** 635 pausas de más de un día, mediana de 10.8 días y
máximo de 115; cada frente pasa entre dos y seis meses sin registros. Por eso la regla de los
cinco registros del imputador se activa en 495 filas, y por eso `dias_desde_evento_previo` importa:
una media de ventana calculada tras una pausa de cuarenta días describe otra realidad.

**[A14] `energia_especifica_proxy` no está en unidades de energía específica.** Sus unidades son
bar·rev/m, equivalentes a 10⁵ N/m³ tomando la revolución como adimensional: es un gradiente de
presión, fuerza por unidad de volumen. La energía específica de perforación de Teale es J/m³ = Pa
y su término rotacional usa **torque**, no presión hidráulica. Si el torque es proporcional a la
presión, `T = k·P`, entonces `SE = (2πk/A) × proxy`, y ese factor tiene unidades de longitud, que
es lo que convierte N/m³ en J/m³. Con las medianas del extracto el proxy vale 1.28e10 N/m³, de
modo que equivaler a una energía específica de 50 MPa exigiría un factor de 3.89 mm, una escala
geométrica plausible para una perforadora. **Conclusión**: es proporcional a la energía específica
dentro de una máquina de geometría fija, pero el factor no tiene por qué ser el mismo entre los
tres fabricantes del extracto, así que comparar el proxy entre equipos solo vale a menos de esa
constante. Su correlación medida con la ley es 0.00: se construye por criterio de dominio y su
valor real se reporta en lugar de suponerse.

**[A15] La sobretemperatura se mide sobre un cero real, y por eso no usa la temperatura
absoluta.** El grado Celsius es una escala de intervalo con cero arbitrario: el cociente
`temp / rpm` da otro orden de registros al medirlo en kelvin —la correlación de rangos entre ambas
versiones es 0.82— y con ello deja de ser una magnitud física comparable. Midiendo el incremento
sobre los 38 °C mínimos del extracto, que actúan como proxy de temperatura ambiente, el cero es
físico y además la asociación con la falla mejora: 0.144 contra 0.113. La referencia es un
parámetro configurable del transformador. Aun así, ninguna versión del ratio supera a la
temperatura sola (0.160), lo cual es coherente con que la relación sea de umbral: las banderas la
capturan mejor que cualquier cociente.
