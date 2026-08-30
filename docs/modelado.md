# Modelado del Ejercicio A-2

Decisiones de modelado de la regresión de ley y de la clasificación de falla, con la medición
que sostiene cada una. Está escrito para que se pueda leer sin ejecutar el notebook.

Las cifras salen del registro de experimentos (`mlflow.db`) y del notebook
[`modulo_a/aurum_pipeline/modeling_demo.ipynb`](../modulo_a/aurum_pipeline/modeling_demo.ipynb),
que se entrega con sus salidas ejecutadas.

---

## Resumen de resultados

Todas las cifras salen de `mlflow.db` tras ejecutar `modeling_demo.ipynb`. La ejecución
completa tarda unos 30 minutos y deja 86 corridas padre —31 de ley y 55 de falla— con sus
395 hijas, una por pliegue, repartidas en dos experimentos.
Cada corrida registra dos familias de métricas —validación y entrenamiento, esta con el sufijo
`_entrenamiento`— y la **brecha** entre ambas, que es cuánto mejor se ve el modelo sobre los
datos que memorizó. Es positiva bajo sobreajuste en los dos problemas, aunque en uno la métrica
se minimice y en el otro se maximice.

### Regresión de la ley del turno siguiente

**Fase A — conjunto de variables** (ventana expansiva, hiperparámetros por defecto, error medio
en g/t sobre los cinco pliegues):

| Modelo | Conjunto | Validación | Entrenamiento | Brecha | Desv. entre pliegues |
|---|---|---|---|---|---|
| lightgbm | MINIMO | **0.3809** | 0.3569 | 0.0240 | 0.0165 |
| xgboost | MINIMO | **0.3809** | 0.3569 | 0.0240 | 0.0165 |
| lightgbm | ACTIVIDAD | 0.4101 | 0.2916 | 0.1184 | 0.0192 |
| lightgbm | CONDICIONES | 0.4150 | 0.1557 | 0.2593 | 0.0156 |
| lightgbm | COMPLETO | 0.4177 | 0.1368 | 0.2808 | 0.0296 |
| xgboost | CONDICIONES | 0.4327 | 0.0255 | 0.4072 | 0.0128 |
| xgboost | ACTIVIDAD | 0.4596 | 0.1466 | 0.3130 | 0.0262 |
| xgboost | COMPLETO | 0.4782 | **0.0213** | **0.4569** | 0.0250 |

Con `MINIMO` los dos modelos reproducen el baseline hasta la cuarta cifra y la brecha es la del
propio baseline: con una variable de trece valores no hay nada que memorizar. Agregar variables
**empeora** la validación entre un 8% y un 26%, y la brecha dice por qué: XGBoost sobre
`COMPLETO` baja el error de entrenamiento a 0.021 g/t —memoriza las 1573 filas— y sube el de
validación a 0.478. No es que las variables no aporten; es que con hiperparámetros por defecto
el modelo las usa para ajustar ruido.

**Fase B — ventana temporal** (error medio en g/t; se muestran el mejor de cada estrategia y los
dos baselines):

| Modelo | Ventana | Validación | Brecha | Desv. | Turnos de entrenamiento |
|---|---|---|---|---|---|
| xgboost · MINIMO | deslizante 12m | **0.3803** | 0.0226 | 0.0160 | 1308 |
| lightgbm · MINIMO | deslizante 18m | 0.3805 | 0.0232 | 0.0169 | 1560 |
| baseline nivel frente | deslizante 12m | 0.3805 | 0.0227 | 0.0161 | 1308 |
| lightgbm · MINIMO | expansiva | 0.3806 | 0.0237 | 0.0171 | 1573 |
| baseline nivel frente | expansiva | 0.3809 | 0.0240 | 0.0165 | 1573 |
| lightgbm · MINIMO | deslizante 6m | 0.3815 | 0.0231 | 0.0170 | 781 |
| baseline nivel frente | deslizante 6m | 0.3820 | 0.0236 | 0.0168 | 781 |
| xgboost · MINIMO | deslizante 3m | 0.3950 | 0.0370 | 0.0293 | 419 |
| baseline nivel frente | deslizante 3m | 0.3956 | 0.0378 | 0.0309 | 419 |
| lightgbm · MINIMO | deslizante 3m | 0.4549 | 0.0639 | **0.0847** | 419 |
| baseline persistencia | cualquiera | 0.5479 | ~0.03 | 0.0444 | — |

Las cinco estrategias caben en un rango de 0.0006 g/t entre la expansiva y la deslizante de 12
meses. **La mejor deslizante supera a la expansiva por 0.0003 g/t con 0.016 de desviación entre
pliegues: es un empate, y el experimento lo trata como tal.** La expansiva es la hipótesis por
defecto y solo la desplaza una deslizante que la supere por más de la desviación entre pliegues
(§5); sin esa regla, «el máximo gana» convertía el empate en una elección y el modelo quedaba
registrado con una ventana que este mismo documento llamaba empate. Lo que sí se mide es el
otro extremo: a tres meses el baseline sube un 3.9% y LightGBM un 19.5%, con la desviación
entre pliegues multiplicada por cinco (0.0847 contra 0.0169) y la brecha casi triplicada.
Recortar la ventana no vuelve al modelo más adaptativo; lo vuelve inestable.

La persistencia da exactamente lo mismo bajo las cinco estrategias, como debe ser: no aprende
nada del histórico, así que la ventana le da igual. Es la comprobación de que la comparación
está midiendo lo que dice medir.

**Fase C — conjunto de prueba** (797 turnos, mirado una sola vez; el ganador se reajustó con los
3188 turnos del desarrollo):

| | Error medio | Error cuadrático | Error relativo | Varianza explicada |
|---|---|---|---|---|
| Ganador: lightgbm · MINIMO · expansiva | 0.3979 g/t | 0.5509 | 4.54% | 0.9753 |
| Baseline nivel del frente | **0.3975 g/t** | 0.5504 | 4.54% | 0.9753 |
| Baseline persistencia | 0.5491 g/t | 0.7429 | 6.27% | 0.9550 |

**El modelo empata con el baseline; no le gana.** La diferencia es de 0.0004 g/t a favor del
baseline, más de cuarenta veces menor que la dispersión del propio error entre pliegues
(0.017). El techo
del problema —la media del frente calculada con todo el histórico, que ningún modelo puede
usar— está en 0.9757 de varianza explicada, y el baseline causal llega a 0.9753. Ese es todo el
espacio que había, y no queda nada por ocupar.

El error por frente sobre la prueba va de 0.1657 g/t en FR-N2-09 a 0.7361 g/t en FR-C2-02, y
sigue el nivel de ley del frente: los frentes ricos tienen más varianza absoluta. En error
relativo la diferencia se achica mucho.

### Clasificación de falla en las próximas 4 horas

**Antes que el modelo, la etiqueta.** La etiqueta es cero por construcción cuando el frente no
registra eventos en la ventana (el 16.5% de las celdas). Si las fallas de cada evento fueran
independientes con la tasa de evento del extracto (3.32%), la tasa de una ventana con `n`
eventos sería `1 − (1 − p)^n`. Sobre el desarrollo:

| Eventos del frente en la ventana | Turnos | Eventos medios | Tasa observada | Si fueran independientes |
|---|---|---|---|---|
| 0 | 536 | 0.00 | 0.000 | 0.000 |
| 1–3 | 100 | 1.96 | 0.050 | 0.064 |
| 4–6 | 82 | 4.77 | 0.122 | 0.149 |
| 7–9 | 959 | 8.78 | 0.243 | 0.257 |
| 10–12 | 1510 | 10.34 | 0.289 | 0.294 |

La tasa observada reproduce la de eventos independientes en cada tramo. El EDA ya había medido
que no hay agrupamiento ni precedencia: P(falla en el evento siguiente | falla ahora) es igual a
la tasa base, y la temperatura del evento anterior no mueve la tasa del actual (0.0336 contra
0.0331). **Dada la actividad, la falla es una moneda de 3.3% por evento.** Anticipar la falla
es, en este extracto, anticipar si el frente sigue operando, y el techo del problema es el
oráculo que conoce cuántos eventos tendrá la ventana: precisión media de 0.2795 sobre el
desarrollo (tasa base 0.2149) y de **0.2984 sobre la prueba** (tasa base 0.2271). El oráculo
binario —«hubo registros o no»— da 0.2678 sobre la prueba.

La variante por `equipo_id`, la que pide la letra del enunciado, reparte los mismos eventos
independientes entre diez etiquetas: la tasa cae a 2.85%, solo el 63.9% de las ventanas tiene
registros del equipo y la tabla de independencia se reproduce igual (1–3 eventos: 0.045
observado contra 0.049). La falla se vuelve más rara, no más anticipable.

**Fase A — conjunto de variables y peso de clase** (precisión media; más es mejor; tasa base
0.2146, promedio de los cinco pliegues):

| Modelo | Conjunto | Peso | Validación | Entrenamiento | Brecha | Desv. |
|---|---|---|---|---|---|---|
| lightgbm | ACTIVIDAD | sin | **0.2618** | 0.8256 | 0.5638 | 0.0247 |
| lightgbm | CONDICIONES | sin | 0.2607 | 1.0000 | 0.7393 | 0.0370 |
| lightgbm | ACTIVIDAD | 3.65 | 0.2586 | 0.8073 | 0.5487 | 0.0262 |
| xgboost | ACTIVIDAD | 3.65 | 0.2574 | 0.9346 | 0.6772 | 0.0231 |
| lightgbm | COMPLETO | sin | 0.2571 | 1.0000 | 0.7429 | 0.0294 |
| lightgbm | COMPLETO | 3.65 | 0.2566 | 1.0000 | 0.7434 | 0.0210 |
| lightgbm | CONDICIONES | 3.65 | 0.2564 | 1.0000 | 0.7436 | 0.0344 |
| xgboost | COMPLETO | 3.65 | 0.2562 | 1.0000 | 0.7438 | 0.0276 |
| xgboost | CONDICIONES | sin | 0.2536 | 1.0000 | 0.7464 | 0.0304 |
| xgboost | ACTIVIDAD | sin | 0.2530 | 0.9141 | 0.6611 | 0.0199 |
| xgboost | COMPLETO | sin | 0.2516 | 1.0000 | 0.7484 | 0.0146 |
| xgboost | CONDICIONES | 3.65 | 0.2501 | 1.0000 | 0.7499 | 0.0300 |
| lightgbm, xgboost | MINIMO | sin y 3.65 | 0.2209 | 0.2517 | 0.0308 | 0.0215 |

Tres lecturas. **`ACTIVIDAD` gana con cuatro variables** —nivel del frente, turno, eventos del
turno y minutos de inactividad al cierre— sobre `COMPLETO` con 27: la tesis de la etiqueta
quedó probada dentro del experimento. **El peso de clase no compra ordenamiento**: en la misma
combinación, sin peso 0.2618 y con peso 0.2586. Y **con hiperparámetros por defecto todo
modelo con más de cuatro variables memoriza**: precisión media de 1.0000 sobre el
entrenamiento y 0.25 sobre la validación. `MINIMO` reproduce al baseline de la tasa del frente
(0.2209), seis milésimas sobre el azar (0.2146) y con la brecha de un baseline: la identidad del
frente no dice nada sobre la falla.

**Fase B — ventana temporal** (conjunto `ACTIVIDAD`, sin peso, búsqueda de hiperparámetros
anidada; se muestran los modelos y el mejor de cada baseline):

| Modelo | Ventana | Validación | Entrenamiento | Brecha | Desv. |
|---|---|---|---|---|---|
| lightgbm | deslizante 18m | **0.2821** | 0.4795 | 0.1974 | 0.0302 |
| xgboost | deslizante 18m | 0.2797 | 0.3492 | 0.0695 | 0.0221 |
| xgboost | deslizante 6m | 0.2796 | 0.3648 | 0.0852 | 0.0262 |
| xgboost | expansiva | 0.2792 | 0.3487 | 0.0695 | 0.0219 |
| lightgbm | deslizante 6m | 0.2786 | 0.3806 | 0.1020 | 0.0218 |
| xgboost | deslizante 12m | 0.2781 | 0.3525 | 0.0743 | 0.0236 |
| xgboost | deslizante 3m | 0.2768 | 0.4334 | 0.1566 | 0.0204 |
| lightgbm | expansiva | 0.2766 | 0.3882 | 0.1115 | 0.0176 |
| lightgbm | deslizante 12m | 0.2756 | 0.4769 | 0.2013 | 0.0238 |
| lightgbm | deslizante 3m | 0.2746 | 0.4209 | 0.1462 | 0.0225 |
| baseline actividad | cualquiera | 0.2544 | 0.2500 | −0.0044 | 0.0190 |
| lightgbm · MINIMO | deslizante 12m | 0.2256 | 0.2518 | 0.0262 | 0.0230 |
| baseline tasa frente | deslizante 12m | 0.2237 | 0.2524 | 0.0287 | 0.0253 |
| baseline prevalencia | cualquiera | 0.2146 | 0.2159 | 0.0013 | 0.0143 |

La búsqueda de hiperparámetros baja la brecha de 0.56–0.75 a 0.07–0.20: la regularización
funciona, y XGBoost la lleva más lejos que LightGBM con la misma validación. El baseline de
actividad —una tabla de cinco tasas por tramo de minutos— no memoriza (brecha −0.004) y queda a
0.025 del mejor modelo. **La mejor deslizante supera a la expansiva por 0.0029 con 0.022 de
desviación entre pliegues: empate, y se conserva la expansiva**, igual que en la regresión. El
ganador que pasa a la prueba es XGBoost · ACTIVIDAD · expansiva.

**Fase C — conjunto de prueba** (797 turnos, tasa base 0.2271):

| | Precisión media | Levante sobre el azar | Con actividad (base 0.2678) | Error de Brier | Exhaustividad al 50% de precisión |
|---|---|---|---|---|---|
| Oráculo del conteo de eventos (techo) | 0.2984 | 1.31× | — | — | — |
| Ganador: xgboost · ACTIVIDAD · expansiva · sin peso | **0.2817** | 1.24× | 0.2879 | 0.1689 | 1.1% |
| Baseline actividad | 0.2642 | 1.16× | 0.2718 | 0.1675 | 0 |
| Baseline prevalencia (azar) | 0.2271 | 1.00× | 0.2678 | 0.1757 | 0 |
| Baseline tasa del frente | 0.2245 | 0.99× | 0.2632 | 0.1763 | 0 |

**Hay señal, es de actividad, y el modelo está cerca del techo.** Queda a 0.0167 del oráculo
que conoce cuántos eventos tendrá la ventana y 0.0175 por encima de una tabla de cinco tasas
por tramo de minutos de inactividad. Condicionado a las ventanas con registros da 0.2879 contra
0.2678 de base condicional: ese residuo es actividad dentro de la actividad —cuántos eventos
vendrán, no solo si vendrán—, no señal mecánica, y el baseline de actividad lo reproduce a
medias (0.2718). La exhaustividad al 50% de precisión es del 1.1%: si operaciones acepta que
una de cada dos alarmas sea en vano, anticipa una de cada cien fallas. Recomendarlo como
disparador de mantenimiento sería irresponsable, y no por falta de modelo.

**La probabilidad está calibrada sin capa de calibración.** Sin peso de clase, el error de
Brier queda en 0.1689 contra 0.1757 de una constante, y la media predicha por frente va de 0.16
a 0.27 con la tasa real entre 0.17 y 0.27. En la versión anterior, con peso, iba de 0.34 a 0.50
contra la misma tasa real.

**La señal es de continuidad operativa, no de estado mecánico, y así hay que decirlo.** Un
modelo que anticipa si el frente sigue perforando en las próximas cuatro horas sirve para
programar, no para mantener. Lo que sí sostiene el extracto sobre la máquina es la **detección
contemporánea**: la tasa de falla pasa de 3.3% por debajo de 88 °C a 22.7% por encima. Eso es
un umbral operacional, no un modelo, y está medido en el EDA.

### SHAP del clasificador: el mismo sensor a tres horizontes

Si la temperatura anticipara la falla, tendría que verse en la atribución del clasificador. El
clasificador registrado no lleva sensores, así que explicarlo no puede mostrarla por
construcción; por eso el notebook explica tres cosas: el registrado, un clasificador con las 28
variables y los hiperparámetros del ganador —para que los sensores compitan de verdad—, y una
sonda a nivel de evento (`SondaContemporanea`) que mide los mismos siete sensores contra la
falla del mismo evento —detección, no pronóstico— y contra la del evento siguiente del frente,
unos 25 minutos después. Todo entrenado antes del corte y evaluado sobre el periodo de prueba.

| Horizonte | Modelo | Precisión media (base) | Levante | Peso SHAP de la temperatura |
|---|---|---|---|---|
| 0, mismo evento | sonda: XGBoost sobre los siete sensores a nivel de evento, 10 225 eventos de prueba | 0.1364 (0.0348) | 3.9× | **62.8%**; el resto reparte entre 5.4% y 7.3% |
| 1 evento, unos 25 minutos | la misma sonda, falla del evento siguiente del frente, 10 212 eventos | 0.0359 (0.0349) | 1.03× | sin señal que repartir: ROC 0.497 |
| 4 h tras el cierre | XGBoost con las 28 variables y los hiperparámetros del ganador | 0.2971 (0.2271) | 1.31× | `temp_max_turno` 3.9%, `temp_motor_c` fuera de las doce primeras; `minutos_inactivo_al_cierre` 40.8% |
| 4 h, registrado | XGBoost · ACTIVIDAD | 0.2817 (0.2271) | 1.24× | no entra; `minutos_inactivo_al_cierre` 71.5%, `nivel_frente` 14.4%, `eventos_turno` 11.8% |

**La señal del sensor muere dentro de un evento.** A horizonte cero la temperatura domina la
atribución con el 62.8% y el modelo levanta 3.9× la tasa base; veinticinco minutos después la
precisión media vuelve a la base (1.03×) y el ROC a 0.50; a cuatro horas la temperatura pesa lo
mismo que el avance o las rpm, que es la firma del ruido, y lo que manda son los minutos de
inactividad. El rango útil del sensor es contemporáneo: una alarma en tiempo real, no un
pronóstico. Con las 28 variables el clasificador da 0.2971 contra 0.2817 del registrado; es una
mirada diagnóstica a la prueba y no una selección (§4).

### SHAP: ¿qué sensor predice la ley?

El modelo en producción usa una sola variable, así que atribuir sobre él respondería la
pregunta por definición: le da el 100% a `nivel_frente` porque no hay nada más. Por eso el
notebook explica **también** un modelo entrenado con `COMPLETO` sobre la misma partición, donde
los siete sensores y su resumen por umbral compiten de verdad. Contribución media absoluta sobre
el conjunto de prueba:

| Variable | g/t | % |
|---|---|---|
| `nivel_frente` | 2.7266 | **80.95** |
| `ley_media_3` | 0.1291 | 3.83 |
| `ley_media_10` | 0.0650 | 1.93 |
| `ley_rezago_1` | 0.0574 | 1.70 |
| `ley_turno` | 0.0402 | 1.19 |
| `ley_rezago_2` | 0.0372 | 1.10 |
| `ley_desv_10` | 0.0296 | 0.88 |
| **`vibracion_rms_ms2`** | 0.0279 | **0.83** |
| `minutos_inactivo_al_cierre` | 0.0246 | 0.73 |
| `pres_hidraul_bar` | 0.0230 | 0.68 |
| `temp_motor_c` | 0.0203 | 0.60 |
| `agua_iny_lmin` | 0.0202 | 0.60 |
| `rpm_corona` | 0.0169 | 0.50 |
| `temp_max_turno` | 0.0167 | 0.50 |
| `ton_rom_acum` | 0.0135 | 0.40 |
| `vib_max_turno` | 0.0128 | 0.38 |
| `avance_mmin` | 0.0125 | 0.37 |
| `eventos_temp_riesgo` | 0.0027 | 0.08 |
| `eventos_vib_alerta` | 0.0000 | 0.00 |
| … resto | < 0.02 | < 0.6 |

**La respuesta es que ningún sensor lo es.** El nivel histórico del frente se lleva el 81% de
la atribución; las variables que le siguen son historia de la propia ley. El sensor mejor
ubicado es la vibración RMS con un 0.83%, y los siete sensores juntos no llegan al
4%. El resumen por umbral —máximos y conteos sobre 88 °C y 12 m/s²— responde
la objeción de que la media diluía el escalón: sumados dan menos del 1%, y el conteo de alertas
de vibración exactamente cero. El reparto entre sensores es tan parejo que no distingue a
ninguno: es la firma de variables que aportan ruido.

**¿Tiene sentido operacional?** Todo. La ley es una propiedad geológica de la veta, y la
presión hidráulica o las revoluciones de la corona describen el esfuerzo sobre la roca, no su
contenido de oro. Un sensor de perforación podría, como mucho, informar sobre la dureza de la
roca, y la dureza no está correlacionada con el oro en este yacimiento. La consecuencia es
accionable: para mejorar esta predicción hace falta geología —ensayos, mapeo, sondajes de
avanzada— y no más telemetría.

---

## 1. La unidad de modelado es el turno, no el evento

El enunciado pide predecir la ley «del siguiente turno». Eso fija la unidad en la celda
`(frente_id, fecha_local, turno_cod)`: 4019 celdas con una mediana de 14 eventos cada una, de
las que 3985 forman par con un turno siguiente.

Se descartó modelar a nivel de evento. Repetiría el mismo objetivo unas catorce veces y la
validación quedaría optimista por correlación dentro del turno: el modelo vería en
entrenamiento otros eventos del mismo turno que está prediciendo.

**«El siguiente turno» es el siguiente de ese frente en orden cronológico, no el siguiente del
calendario.** Los frentes se apagan por semanas; exigir contigüidad de calendario descartaría
uno de cada seis pares. El salto no se esconde: entra al modelo como `dias_desde_turno_previo`.

**La ley del turno se promedia solo sobre lecturas medidas.** Las que el imputador del A-1
reconstruyó quedan fuera del promedio, por la misma razón por la que existe
`AurumImputer.objetivo_medido`: un objetivo construido sobre imputaciones entrena al modelo a
predecir a su propio imputador. El costo está acotado —11 celdas de 4019 quedan sin ninguna
lectura medida, y con ellas se pierden unos 22 pares de 3985.

**El turno cierra con el reloj.** El cierre del bloque horario —inicio del turno según
`turno_cod` más seis horas— viaja en la matriz como `cierre_turno_local`, porque dos
consumidores lo necesitan y no pueden calcularlo cada uno a su manera: la etiqueta de falla
cuenta su ventana desde ahí y los minutos de inactividad se miden hasta ahí. La primera versión
usaba «primer evento más seis horas», y en el extracto el primer evento llega más de una hora
tarde en el 13.6% de los turnos (percentil 95: 255 minutos): la ventana de predicción se corría
hasta seis horas y la etiqueta cambiaba en el 5.5% de las celdas.

### La ventana objetivo: ¿envejece la información con el hueco?

El 83.5% de los pares son contiguos en el calendario y el 10.5% tienen más de siete días de
hueco. Había que medir si un hueco de semanas envejece lo que se sabe del frente. Sobre el
desarrollo, con el oráculo del nivel del frente:

| Hueco hasta el turno objetivo | Residuo del oráculo (g/t) | Turnos | Solo con ≥ 10 lecturas | Turnos |
|---|---|---|---|---|
| contiguo | 0.3492 | 2650 | 0.3094 | 2320 |
| 1 a 7 días | 0.4460 | 170 | 0.2897 | 50 |
| 7 a 30 días | 0.4824 | 268 | 0.3378 | 83 |
| más de 30 días | 0.5614 | 76 | 0.3986 | 26 |

| Lecturas del turno objetivo (pares contiguos) | Residuo del oráculo (g/t) | Turnos |
|---|---|---|
| 1–3 | 1.0319 | 109 |
| 4–6 | 0.4908 | 93 |
| 7–9 | 0.3879 | 127 |
| 10–12 | 0.3196 | 471 |
| 13 o más | 0.3068 | 1849 |

El residuo sube con el hueco, pero al fijar las lecturas del turno objetivo el efecto casi
desaparece: los turnos que reabren una campaña son parciales —unas siete lecturas en vez de
trece— y la media de pocas lecturas es ruidosa. El nivel del frente no envejece (su desviación
entre trimestres es 0.14 g/t contra 3.69 g/t entre frentes), así que la ventana objetivo está
bien planteada. Lo que fija el piso del error es cuántas lecturas respaldan al turno que se
quiere predecir, y eso no lo decide el modelo: es ruido de medición de la sonda XRF.

---

## 2. Partición: entrenamiento, validación y prueba

| Conjunto | Rango | Turnos | Papel |
|---|---|---|---|
| Desarrollo | 2023-06-30 → 2025-05-06 | 3188 | entrenar y validar |
| Prueba | 2025-05-06 → 2025-10-27 | 797 | se mira una sola vez |

El corte es **por fecha y no por número de filas**. Con frentes que se apagan por semanas,
cortar por filas dejaría las mismas fechas a los dos lados y la métrica de prueba compartiría
calendario con el entrenamiento.

Dentro del desarrollo, la validación es walk-forward de cinco bloques de igual duración. El
primer tramo solo entrena; cada uno de los cinco siguientes es un bloque de validación.

```
                T0      T1      T2      T3      T4      T5    ||   PRUEBA
              |-------|-------|-------|-------|-------|-------||-----------|
  pliegue 1   ######- +++++++ ....... ....... ....... .......
  pliegue 2   ####### ######- +++++++ ....... ....... .......
  pliegue 3   ####### ####### ######- +++++++ ....... .......
  pliegue 4   ####### ####### ####### ######- +++++++ .......
  pliegue 5   ####### ####### ####### ####### ######- +++++++

  #  entrena     +  valida     .  no se usa
  -  purga: sale la celda cuyo turno objetivo cae dentro del bloque de validacion
```

Un turno de un tramo intermedio valida en su pliegue y entrena en los posteriores. Eso no es
fuga porque la dirección es siempre pasado hacia futuro, pero significa que entrenamiento y
validación son papeles que se mueven y no bloques fijos. Se descartaron tres bloques disjuntos
sin walk-forward: dejan una sola estimación de validación, sin dispersión medible, e
inutilizan el bloque intermedio para el ajuste final.

Dos debilidades que se declaran y no se corrigen: el primer pliegue entrena con 516 turnos y su
estimación es más ruidosa que la del quinto, lo que la desviación entre pliegues absorbe; y en
clasificación parte de esa desviación viene de cuántos finales de campaña caen en cada bloque,
que es estructura de la etiqueta y no de la partición.

### La purga

El objetivo de una celda ocurre en su futuro. Si una fila de entrenamiento predice un turno
que cae dentro del bloque de validación, el modelo ve el bloque que lo evalúa. **No produce
error: produce una métrica sospechosamente buena.** Por eso una fila entrena solo si su
`inicio_turno_siguiente` es anterior al comienzo del bloque.

| Pliegue | Entrena | Valida | Purgadas |
|---|---|---|---|
| 1 | 516 | 532 | 13 |
| 2 | 1048 | 523 | 13 |
| 3 | 1572 | 526 | 12 |
| 4 | 2097 | 534 | 13 |
| 5 | 2631 | 544 | 13 |

Doce o trece celdas por pliegue: una por frente, la que tiene el turno abierto sobre la
frontera. Que el número coincida con la cantidad de frentes es la señal de que la purga hace
lo que debe.

La misma purga cubre la ventana de falla, y hay que decir por qué: la ventana es
`(cierre, cierre + 4 h]` y el turno siguiente del frente empieza en el cierre o después, de modo
que una fila que sobrevive a la purga solo puede ver eventos de un turno que empezó antes del
bloque; un tercer turno del frente no cabe en cuatro horas.

---

## 3. Contra la fuga de información

Cuatro mecanismos, cada uno con su prueba de regresión:

1. **Purga en la frontera de los pliegues**, descrita arriba.
2. **La codificación del frente vive dentro del `Pipeline`.** La codificación por objetivo de
   `frente_id` es literalmente el baseline: la media de la ley del frente. Calculada una vez
   sobre toda la matriz, cada bloque de validación quedaría evaluado con una media que lo
   incluye. Al ser el primer paso del pipeline, se reajusta con las filas de entrenamiento de
   cada pliegue, y `RandomizedSearchCV` la reajusta también en cada configuración que prueba.
3. **El leave-one-out del A-1 no se reutiliza.** Resuelve el mismo problema en un contexto sin
   orden temporal, donde basta excluir la propia fila. Aquí hay orden, y excluir solo la propia
   fila seguiría dejando entrar el futuro del frente.
4. **Ningún conjunto de variables puede declarar una columna del futuro.** El objetivo, el
   instante del objetivo, la etiqueta de falla, la marca de ventana observada y el conteo de
   eventos de la ventana viven en la matriz porque el particionador y las métricas los
   necesitan; un `ConjuntoVariables` que los incluya falla al construirse, no en la primera
   petición real.

---

## 4. Conjuntos de variables

Cuatro hipótesis con nombre, cada una contenida en la siguiente, comparadas sobre los mismos
pliegues:

| Conjunto | Contenido | Hipótesis |
|---|---|---|
| `MINIMO` | solo el nivel del frente | la identidad del frente lo es todo |
| `ACTIVIDAD` | + turno, eventos del turno, minutos de inactividad al cierre | lo que se predice es continuidad operativa |
| `CONDICIONES` | + ley del turno, tipo de mineral, lecturas, fallas y mantenimiento del turno, tonelaje, siete sensores promediados, y el resumen por umbral: máximo de temperatura, lecturas sobre 88 °C, máximo de vibración, lecturas sobre 12 m/s² | las condiciones actuales aportan |
| `COMPLETO` | + historia del frente: rezagos 1 y 2, medias y desviaciones móviles de 3 y 10 turnos, días desde el turno previo, turnos previos | la historia aporta |

Los rezagos son causales y el enunciado no acota las variables del modelo. El contrato de la
API es otra cosa y se resuelve en el servicio, no recortando el modelo.

**Una debilidad del protocolo que se declara.** La fase A elige el conjunto con hiperparámetros
por defecto, y los defaults castigan a los conjuntos anchos porque memorizan: en clasificación,
`CONDICIONES` y `COMPLETO` dan precisión media 1.0000 sobre el entrenamiento. Un clasificador con
las 28 variables y los hiperparámetros del ganador da 0.2971 sobre la prueba contra
0.2817 del registrado. Es una mirada diagnóstica a la prueba y no una selección —el
modelo registrado no cambia por esto—; la comparación legítima sería correr la fase B con todos
los conjuntos, y no se hizo por tiempo. La atribución dice lo mismo con cualquiera de los dos:
minutos de inactividad primero, temperatura al nivel del ruido.

**Qué hereda esto del A-1 y qué no.** El `AurumFeatureBuilder` del A-1 trabaja a nivel de
evento; el A-2 cambia la unidad a turno y por eso no consume esas columnas: las recalcula en
la granularidad nueva. La correspondencia es esta: `ley_ventana` y `ley_lag_1` del A-1 son
`ley_media_10` y `ley_rezago_1` por turno; `dias_desde_evento_previo` es
`dias_desde_turno_previo`; las banderas `flag_temp_riesgo` y `flag_vib_alerta` son, sumadas por
turno, `eventos_temp_riesgo` y `eventos_vib_alerta`. Los dos ratios —`energia_especifica_proxy`
y `sobretemperatura_por_rpm`— no entran al A-2: medidos por turno sobre la prueba dan una
precisión media entre 0.21 y 0.26 frente a una base de 0.23, y con la ley correlacionan 0.003.
Se dejan fuera con la medición hecha, no por descuido.

---

## 5. Ventana temporal de entrenamiento

El enunciado pide justificar la ventana. La justificación no es un argumento previo: es una
salida del pipeline. `splitter.py` implementa la expansiva y la deslizante bajo un mismo
contrato, **con bloques de validación idénticos**, y las cinco variantes se evalúan y quedan
registradas en MLflow.

**La expansiva es la hipótesis por defecto y solo la desplaza una deslizante que la supere por
más de la desviación entre pliegues de la expansiva.** No es una regla sobre hiperparámetros
—esos se eligen por el máximo y la brecha registrada dice cuánto cuesta— sino sobre una
decisión de diseño con hipótesis declarada: no se abandona por una diferencia que no se
distingue del ruido. En los dos problemas la mejor deslizante ganó por menos de una quinta parte
de la desviación (0.0003 g/t contra 0.016; 0.0029 contra 0.022) y la expansiva se conservó.

**La ventana elegida gobierna también el reajuste final.** Los pliegues de la búsqueda la
usaban desde el principio, pero la fase C reajustaba el modelo con todo el desarrollo fuera cual
fuera la ventana, de modo que un modelo registrado como deslizante habría entrenado con toda la
historia. Ahora, si gana una deslizante, el reajuste usa solo los meses de la ventana contados
desde el comienzo de la prueba, y el número de turnos con que entrenó queda registrado como
parámetro.

Dos mediciones sostienen que la expansiva sea la hipótesis por defecto:

- **No hay deriva que olvidar.** La desviación temporal del nivel de un frente entre trimestres
  es 0.1387 g/t, contra 3.6861 g/t de desviación entre frentes: veintisiete veces menor. La
  ventana deslizante existe para descartar régimen viejo cuando el proceso deriva; aquí paga el
  costo de tirar datos sin cobrar el beneficio de olvidar.
- **Recortar la ventana no ayuda y perjudica más al modelo que al baseline.** El baseline solo
  estima trece medias y con pocos turnos por frente ya las estima bien; el modelo tiene que
  estimar esas trece medias *más* la forma funcional de las variables que son ruido, y con poca
  historia ajusta el ruido: a tres meses la brecha de LightGBM casi se triplica.

**Caveat que hay que declarar:** el periodo de desarrollo son 22 meses, de modo que una ventana
deslizante de 18 cubre casi todo y da prácticamente idéntico a la expansiva. El contraste
informativo está en 12, 6 y 3 meses.

---

## 6. Hiperparámetros

Búsqueda aleatoria de 20 configuraciones, con semilla fija y la tabla completa de
configuraciones muestreadas registrada como artefacto —sin ella, una búsqueda aleatoria obliga
a reejecutar para saber qué se probó. La tabla trae el puntaje de validación, el de
entrenamiento y la brecha de cada configuración: la curva entre capacidad y brecha sale de la
búsqueda que ya se corre, sin un experimento aparte.

**La búsqueda usa los mismos pliegues purgados.** `VentanaTemporal` implementa `split` y
`get_n_splits` con la firma de scikit-learn para que `RandomizedSearchCV` la consuma
directamente. Sin eso, la búsqueda armaría por dentro una partición aleatoria y echaría a
perder toda la estructura temporal montada afuera.

**La búsqueda se anida dentro de cada estrategia de ventana.** Fijar los hiperparámetros con la
expansiva y después comparar estrategias sesgaría la comparación a favor de la que los eligió.

**Elegir el máximo de veinte números ruidosos selecciona suerte.** Las mejores configuraciones
de la búsqueda de falla caben en unas centésimas de precisión media con una desviación entre
pliegues del mismo orden, así que parte de la caída entre validación y prueba es maldición del
ganador y no memorización. Se deja la regla del máximo —una regla 1-SE sería una decisión más
que defender— y se registra la brecha, que es lo que permite distinguir las dos cosas.

Se descartó la rejilla exhaustiva —con siete hiperparámetros y unos 1500 turnos de
entrenamiento es gastar cómputo explorando ruido— y la optimización bayesiana, que agrega una
dependencia para una ganancia que aquí no existe: el techo del problema está a cinco
diezmilésimas del baseline.

---

## 7. Métricas

### Regresión

**Error absoluto medio en gramos por tonelada**, como métrica principal. No es una elección
estética: g/t es la unidad con la que la mina decide mezcla y ley de corte, de modo que el
error se traduce directo a una decisión de planta. Se reportan al lado el error cuadrático
—castiga los turnos raros—, la varianza explicada —permite comparar contra el techo— y el
**error por frente**, porque en operación la pregunta no es «cuánto se equivoca el modelo» sino
«en cuál de mis trece frentes no puedo confiar».

### Clasificación

**Precisión media** (área bajo la curva de precisión y exhaustividad). El área bajo la curva
ROC se descarta: con 78% de negativos se ve bien sin serlo, porque basta ordenar bien los
negativos entre sí.

**Por qué esa métrica en operación minera.** Los dos errores no cuestan lo mismo. Un falso
negativo es una perforadora que se detiene sin plan, con el frente parado y una cuadrilla
esperando; un falso positivo es una inspección preventiva que no hacía falta. El costo
asimétrico empuja a privilegiar la exhaustividad, pero no sin límite: una alarma que se
equivoca la mayoría de las veces deja de mirarse a la semana, y entonces la exhaustividad real
cae a cero. Por eso se reporta además la **exhaustividad al 50% de precisión**, que responde la
pregunta que un jefe de mantenimiento hace de verdad: si acepto que una de cada dos alarmas sea
en vano, cuántas fallas alcanzo a anticipar.

**Precisión media con actividad.** Se calcula solo sobre las ventanas en que el frente siguió
registrando, con su propia tasa base al lado. Es el detector de señal mecánica: la etiqueta es
cero por construcción cuando el frente se apagó, así que un modelo que solo anticipe la
continuidad operativa se luce en la métrica global y vuelve a la tasa base en esta.

Se reporta siempre la **tasa base** al lado, porque sin ella ninguna métrica es interpretable:
una precisión media de 0.22 es exactamente el azar cuando el 22% de los turnos falla.

### Entrenamiento y brecha, en los dos problemas

Cada pliegue se mide contra su bloque de validación y contra sus propias filas de
entrenamiento. La familia de entrenamiento lleva el sufijo `_entrenamiento`, y la
`brecha_entrenamiento_validacion` es cuánto mejor se ve el modelo sobre lo que memorizó:
entrenamiento menos validación en precisión media, validación menos entrenamiento en error
medio. Positiva bajo sobreajuste en los dos casos, y es la métrica que un panel puede ordenar.

---

## 8. Desbalance de clases

A nivel de evento la tasa de falla es 3.3%. Pero la unidad de decisión no es el evento sino el
turno —la pregunta operacional es si conviene intervenir un frente antes del próximo relevo—, y
a nivel de celda la tasa de falla en las cuatro horas siguientes al cierre del turno es 21.7%.

Con ese balance **no se remuestrea**: SMOTE o el submuestreo del negativo introducen más
varianza de la que corrigen y distorsionan las probabilidades. **Tampoco se pesa la pérdida por
defecto**, y la razón está medida y no supuesta: el peso de clase distorsiona las
probabilidades igual que el remuestreo —en la versión anterior de este entregable el
clasificador con peso daba un error de Brier de 0.213 sobre la prueba, peor que el 0.172 de una
constante— y la métrica principal es insensible al umbral, así que el peso no compra
ordenamiento. La fase A corre cada combinación con y sin peso y se queda con la que valida
mejor; ganó sin peso (0.2618 contra 0.2586), y la probabilidad por frente sobre la prueba sigue
a la tasa real sin capa de calibración. El mecanismo queda disponible como parámetro para el
caso severo —a nivel de evento, con 3.3%— donde sí haría falta.

### La etiqueta

La ventana empieza **al cierre del bloque horario del turno**, no al abrirlo ni al primer
evento más seis horas: el momento de la predicción es cuando están disponibles todas las
lecturas del turno, y ese momento es el del reloj. Contar desde el inicio significaría
etiquetar con horas que ya ocurrieron; contar desde el primer evento corría la ventana hasta
seis horas en los turnos que empiezan tarde (§1).

Una ventana sin ningún registro del frente —se apagó— se etiqueta como cero, se marca en
`ventana_con_registros` y deja su conteo en `eventos_en_ventana`. No es lo mismo «no falló» que
«no había nadie perforando», y ese conteo es el que fija el techo del problema.

**Se agrupa por `frente_id` y no por `equipo_id`**, aunque la letra del enunciado hable de
equipos. El EDA demostró que el extracto es un flujo estrictamente serial, incompatible con
diez perforadoras trabajando en paralelo, y bajo ese supuesto `equipo_id` es una etiqueta
repartida sobre un flujo único que no admite lectura causal. La variante por equipo se
construye cambiando un parámetro del constructor y el notebook la reporta: tasa del 2.85%, el
63.9% de las ventanas con registros del equipo, y la misma tabla de independencia.

---

## 9. MLflow y el registro de modelos

- **Backend SQLite** (`sqlite:///mlflow.db`, redirigible con `AURUM_MLFLOW_URI`). MLflow 3.15
  dejó el almacén de archivos en modo mantenimiento y lanza excepción al usarlo. Los artefactos
  se anclan junto a la base, en `mlartifacts/<experimento>/`: sin ese anclaje MLflow los deja en
  `./mlruns` relativo al directorio de trabajo, que era el del notebook o el de las pruebas.
- **Una corrida padre por combinación y una hija por pliegue.** Sin las hijas, la tabla de
  ventanas mostraría promedios sin forma de ver que una estrategia no es solo peor sino también
  más inestable. Padre e hijas registran validación, entrenamiento y brecha.
- **Nombres en lenguaje de operación**, como pide el enunciado:
  `error_medio_g_por_tonelada`, `error_relativo_pct`, `varianza_explicada`,
  `desviacion_entre_pliegues`, `turnos_entrenamiento`, `precision_media`,
  `precision_media_con_actividad`, `exhaustividad_al_50_pct_precision`, `tasa_base_falla`,
  `levante_sobre_azar`, `brecha_entrenamiento_validacion`; y como parámetros
  `peso_clase_positiva` y `turnos_entrenamiento_final`.
- **Etiquetas de reproducibilidad**: commit de git, huella del insumo y semilla.
- **Artefactos**: tabla comparativa, error por frente, configuraciones muestreadas —con puntaje
  de entrenamiento y brecha por configuración— y figura SHAP.
- **Serialización con cloudpickle**, porque el formato por defecto de MLflow 3.15 es skops y
  rechaza clases propias. La consecuencia a tener presente es que `aurum_pipeline` debe ser
  importable donde se cargue el modelo.
- **Registry con alias**: `aurum_ley_turno_siguiente@produccion` y `aurum_falla_4h@produccion`.
  Alias y no stage, que MLflow 3 los deprecó. Promover una versión nueva es mover el alias, sin
  volver a desplegar el servicio.

---

## 10. El servicio de inferencia

`POST /predict` recibe el frente activo y las condiciones del turno que cierra, y devuelve
`ley_estimada`, `prob_falla_4h` y las alertas del diccionario que ese turno no cumple.

**Los rangos del diccionario no son todos validaciones.** El diccionario publica dos cosas
distintas bajo la misma forma: `pres_hidraul_bar` entre 180 y 240 bar es un rango
**operacional**, mientras que `vibracion_rms_ms2` sobre 12 o `temp_motor_c` sobre 95 son
**alertas**. Ninguno describe lo imposible. Si Pydantic rechazara con 422 todo lo que sale del
rango publicado, la API rechazaría exactamente los turnos por los que alguien llama a
preguntar.

La regla es entonces: se rechaza lo que no puede existir —presión negativa, corona girando
hacia atrás, temperatura bajo el cero absoluto— y se acepta marcando lo que está fuera de rango
operacional.

**Los rezagos y el resumen de actividad son opcionales.** Sin los rezagos el pipeline de ley cae
al nivel del frente, que sobre el conjunto de prueba cuesta 0.0003 g/t frente a la media viva.
Exigirlos habría obligado al servicio a mantener un almacén de estado por una diferencia que no
se mide. `minutos_inactivo_al_cierre`, `temp_max_turno`, `eventos_temp_riesgo`,
`vib_max_turno` y `eventos_vib_alerta` son opcionales por la misma razón, con límites físicos
—los minutos no pueden superar la duración del turno— y los árboles tratan el faltante de forma
nativa; sin los minutos de inactividad, el clasificador de falla pierde su variable principal y
responde con lo que le queda.

---

## 11. La matriz por turno, columna por columna

Salida de `ConstructorMatrizTurno.construir()` más la etiqueta de
`ConstructorEtiquetaFalla.agregar()`. Son 38 columnas: las claves e instantes de la
celda, el resumen del turno, la historia causal del frente y los objetivos con sus marcas.

### Claves e instantes

| Columna | Unidad | Lectura |
|---|---|---|
| `frente_id` | categórica | Frente de extracción. Es la variable con toda la señal del problema de ley. |
| `fecha_local` | fecha | Jornada local del turno. Ningún turno se parte en dos: N2 va de 00:00 a 05:59. |
| `turno_cod` | categórica | D1, D2, N1 o N2. Se codifica con el orden cronológico del día, no alfabético. |
| `inicio_turno_local` | instante | Primer evento del turno, en hora local (UTC−5). |
| `cierre_turno_local` | instante | Fin del bloque horario del turno según el reloj. Desde aquí se cuenta la ventana de falla y hasta aquí la inactividad. |
| `inicio_turno_siguiente` | instante | Cuándo ocurre el objetivo. **No es información para el modelo**: es lo que el particionador usa para purgar la frontera entre pliegues. |

### Resumen del turno

| Columna | Unidad | Lectura |
|---|---|---|
| `ley_turno` | g/t | Media de las lecturas **medidas** del turno. Las reconstruidas por el imputador quedan fuera. |
| `lecturas_ley_turno` | conteo | Cuántas lecturas medidas respaldan la anterior. Cero significa turno sin sonda válida. |
| `eventos_turno` | conteo | Registros OPUS del turno. Mediana 14, mínimo 1, máximo 18. |
| `minutos_inactivo_al_cierre` | minutos | Entre el último registro del frente y el cierre del bloque. Mediana 15, percentil 90 en 125; el último turno de una campaña lleva unos 167 minutos callado contra 15 el resto. Es la variable principal del clasificador de falla. |
| `fallas_turno` | conteo | Códigos de falla registrados **dentro** del turno. No es el objetivo de clasificación. |
| `mantenimiento_turno` | proporción | Fracción de eventos en ventana de mantenimiento preventivo. |
| `tipo_mineral` | categórica | Moda del turno. OX, SUL, MIX o EST. No persiste de un turno al siguiente (31%), como una etiqueta al azar. |
| `equipo_id` | categórica | Moda del turno. **No admite lectura causal**, por el supuesto de extracto serial del EDA. |
| `sector_geol` | categórica | Sector del frente. Constante por frente en este extracto. |
| `ton_rom_acum` | t | Media del turno. Pese al nombre, no es un acumulado: el EDA lo midió. |
| `pres_hidraul_bar`, `rpm_corona`, `avance_mmin`, `agua_iny_lmin`, `vibracion_rms_ms2`, `temp_motor_c` | según el diccionario | Media del turno de cada sensor. Ninguno aporta señal medible sobre la ley. |
| `temp_max_turno`, `eventos_temp_riesgo` | °C, conteo | Máximo del turno y lecturas por encima de 88 °C, el escalón que la media diluye. |
| `vib_max_turno`, `eventos_vib_alerta` | m/s², conteo | Máximo del turno y lecturas por encima de la alerta de 12 m/s². |

### Historia causal del frente

Todas se calculan con desplazamiento o con ventanas que **terminan en el turno actual**. Al
predecir el turno `t+1` se conoce todo hasta `t` inclusive, así que incluir el turno actual no
es fuga.

| Columna | Unidad | Lectura |
|---|---|---|
| `ley_rezago_1`, `ley_rezago_2` | g/t | Ley de los dos turnos anteriores del frente. Faltan en los primeros turnos de cada frente. |
| `ley_media_3`, `ley_media_10` | g/t | Media móvil de la ley en 3 y 10 turnos del frente. `ley_media_10` es el mejor estimador causal del nivel del frente. |
| `ley_desv_3`, `ley_desv_10` | g/t | Desviación móvil en las mismas ventanas. Falta con un solo turno de historia. |
| `dias_desde_turno_previo` | días | Hueco desde el turno anterior del frente. El extracto es bimodal: o el frente opera seguido o desaparece por semanas. Falta en el primer turno. |
| `turnos_previos_frente` | conteo | Cuántos turnos del frente preceden a este. Mide cuánta historia respalda a las anteriores. |

### Objetivos y sus marcas

| Columna | Unidad | Lectura |
|---|---|---|
| `ley_turno_siguiente` | g/t | **Objetivo de regresión.** Ley del siguiente turno de ese frente en orden cronológico. |
| `falla_en_4h` | 0/1 | **Objetivo de clasificación.** Hubo falla del frente en `(cierre del turno, cierre + 4 h]`. Tasa base del 21.7%. |
| `eventos_en_ventana` | conteo | Registros del frente en esa ventana. Fija el techo del problema y **describe el futuro**: no puede ser variable. |
| `ventana_con_registros` | 0/1 | Si el conteo anterior es mayor que cero. Distingue «no falló» de «no había nadie perforando», y es la marca con que se calcula la precisión media con actividad. |

### Advertencias

1. **`inicio_turno_siguiente`, `eventos_en_ventana` y `ventana_con_registros` no son variables
   del modelo.** Están en la matriz porque el particionador y las métricas los necesitan; un
   conjunto que los declare falla al construirse.
2. **`ley_turno` es el rezago cero respecto del objetivo**, no el objetivo. Confundirlos
   produce un modelo perfecto y sin sentido.
3. **`fallas_turno` no es `falla_en_4h`.** El primero cuenta lo que ya pasó dentro del turno;
   el segundo es lo que se quiere anticipar.
4. **`equipo_id` y `op_id` no admiten lectura causal** en este extracto, y por eso la etiqueta
   de falla se agrupa por frente. La variante por equipo se construye con un parámetro y se
   reporta en el notebook.
5. **Las columnas de historia faltan en los primeros turnos de cada frente.** LightGBM y
   XGBoost tratan el faltante de forma nativa; no se imputan, porque imputar «no hay historia»
   con un número inventa una historia que no existe.
6. **`cierre_turno_local` no es «primer evento más seis horas».** Es el fin del bloque horario;
   un código de turno fuera del dominio no tiene bloque y hace fallar la construcción.

---

## 12. Sobreajuste: lo que muestra la brecha

Esta sección reemplaza al pendiente de la versión anterior, que decía que el error de
entrenamiento no se registraba y que había indicios de sobreajuste en el clasificador. Los
indicios eran correctos y ahora están medidos.

**Con hiperparámetros por defecto, memorizan.** En la fase A, XGBoost sobre `COMPLETO` deja el
error de entrenamiento en 0.021 g/t contra 0.478 de validación; en clasificación, LightGBM y
XGBoost sobre `CONDICIONES` y `COMPLETO` alcanzan precisión media 1.0000 sobre el entrenamiento
y 0.25 sobre la validación. `MINIMO` da la brecha de un baseline (0.024 g/t; 0.031 de
precisión media): con una sola variable no hay nada que memorizar.

**La búsqueda de hiperparámetros regulariza, y no del todo.** En la fase B de clasificación la
brecha baja a 0.07–0.20 para el mismo conjunto, y las configuraciones que la búsqueda prefiere
son las más rasas del espacio. La brecha residual no se corrige con más regularización, porque
dada la actividad la etiqueta es ruido Bernoulli: el techo es 0.30, no 1.0.

**Los defaults deciden la fase A, y eso favorece a los conjuntos chicos.** El conjunto se elige
antes de buscar hiperparámetros, con la configuración por defecto de cada librería, y esa
configuración memoriza los conjuntos anchos. Con los hiperparámetros del ganador, `COMPLETO` da
0.2971 sobre la prueba contra 0.2817 del registrado (§4). Queda declarado como
límite del protocolo; corregirlo es anidar la búsqueda también en la fase A, al doble de costo.

**La caída entre validación y prueba no es solo memorización.** Elegir el máximo entre veinte
configuraciones y diez combinaciones de modelo y ventana, con desviaciones entre pliegues de
0.02–0.03, selecciona suerte además de calidad. Con la brecha registrada se puede distinguir
cuánto es cada cosa, que es lo que antes no se podía.

---

## 13. Qué haría falta para mejorar

**Para la ley: geología.** El techo del problema es el nivel del frente, y ese nivel es una
propiedad de la veta. Ensayos, mapeo y sondajes de avanzada moverían la aguja; más telemetría
de perforación no. Y sobre la medición: el residuo del oráculo va de 1.03 g/t cuando el turno
objetivo tiene tres lecturas o menos a 0.31 con trece; el piso del error lo pone la sonda XRF.

**Para la falla: telemetría con persistencia real.** En este extracto la correlación de
`temp_motor_c` con su propio valor anterior en el mismo equipo es 0.004 y la de vibración
−0.011, y las fallas de eventos consecutivos son independientes. Eso es incompatible con un
motor que se calienta progresivamente: sin memoria en la señal no hay degradación que
anticipar, y lo que un modelo aprende de este extracto es si el frente sigue perforando. Con
sensores que sí tengan memoria, el mismo pipeline —etiqueta, purga, métricas condicionadas a
la actividad y baseline de actividad— serviría sin cambios estructurales, y la precisión media
con actividad sería la primera métrica que se movería.
