# Diario de decisiones

Bitácora de las decisiones que tomé **yo, Amador Calle**, durante el desarrollo de la prueba
DS-MINE-2025-v2. Está escrita en primera persona y el sujeto soy siempre yo: aquí no se
registran decisiones de la herramienta de IA. Cuando una opción la planteó Claude, se dice
explícitamente y lo que queda registrado es mi resolución sobre esa propuesta. Lo que la
herramienta ejecutó vive en `ia_usage.md`, que es el otro archivo y no se mezcla con este.

Formato: consideré X pero elegí Y porque Z. Orden cronológico.

## 2026-08-29 — Arranque del repositorio

- **Arquitectura del proyecto.** Consideré aplicar Clean Architecture, que es mi estándar
  en los proyectos de mi empresa (capas de dominio, casos de uso y adaptadores), pero elegí
  una estructura plana de paquetes Python porque esto es un entregable de prueba técnica de
  alcance acotado: la indirección de puertos y adaptadores sobre un pipeline de pandas y
  cuatro transformadores agrega archivos sin agregar capacidad de cambio real, y quien
  evalúa el código tiene que poder leerlo completo en pocos minutos. La complejidad
  estructural se justifica cuando hay más de un consumidor o más de una implementación de
  cada frontera, y aquí no los hay.

- **Ubicación de `tests/` y `pipeline_demo.ipynb`.** Al pedirle a Claude la estructura de
  directorios me señaló que el enunciado se contradice: el árbol general de la Sección 1 los
  cuelga de `modulo_a/`, mientras que el Ejercicio A-1 los pone dentro de `aurum_pipeline/`.
  Consideré seguir el árbol general por ser el "mínimo obligatorio", pero elegí la estructura
  del A-1 porque es la especificación más específica y más cercana al ejercicio que se está
  evaluando; ante dos instrucciones en conflicto, la particular manda sobre la general. Dejo
  constancia aquí para que la diferencia frente al árbol de la Sección 1 se lea como una
  decisión y no como un descuido.

- **Versionado del dataset.** Consideré copiar `OP_AURUM_extract.csv` (6.3 MB) dentro del
  repositorio para que el evaluador clone y ejecute sin fricción, pero elegí dejarlo fuera
  y leerlo desde su ubicación original porque un extracto de telemetría operacional de una
  unidad minera es dato de negocio, no código: no pertenece a la historia de git, donde
  además es permanente. La consecuencia es que la ruta no puede quedar escrita en el código;
  se resuelve con la variable de entorno `AURUM_CSV_PATH`, documentada en el README.

- **Gestión de dependencias.** Consideré `pyproject.toml` con Poetry o uv, que es lo que uso
  cuando un paquete se publica o se instala como dependencia de otro, pero elegí `venv` más
  `requirements.txt` porque aquí nadie instala este código como librería: solo hay que
  reproducir un entorno en una máquina limpia, y `python -m venv` está en la biblioteca
  estándar, sin obligar al evaluador a instalar una herramienta previa para poder correr
  los tests.

- **Formato de `ia_usage.md`.** Consideré redactar un resumen curado de en qué me apoyé en
  Claude, que es lo que suele entregarse, pero elegí la transcripción literal y completa de
  la conversación, sin edición ni juicio, porque el enunciado premia explicar cómo se validó
  el output y un resumen escrito después es justamente donde se pierde la evidencia. El
  costo es un archivo largo; la ganancia es que la defensa técnica de 30 minutos se puede
  contrastar contra lo que realmente pasó.

- **Declaración de IA en la historia de git.** Claude me advirtió que el commit de arranque
  había quedado sin el trailer `Co-Authored-By`. Consideré dejar los commits sin marca y
  concentrar la declaración en `ia_usage.md`, pero elegí que el trailer vaya en cada commit
  donde haya intervenido la herramienta porque así la trazabilidad queda en el mismo lugar
  donde vive el código y no depende de que alguien abra un archivo aparte. Declarar de más
  no me quita puntos; declarar de menos, sí.

- **Modelo de ramas.** Consideré trabajar todo directo sobre `main` por ser un proyecto de
  un solo autor y 48 horas, pero elegí ramas cortas de feature integradas con merge commit
  porque la historia del repositorio también se evalúa: quiero que cada módulo entre como
  una unidad revisable y que se vea el orden en que se construyó. La excepción es el commit
  de arranque, que va directo a `main` por ser el bootstrap del repositorio, cuando todavía
  no hay nada de qué ramificarse.

## 2026-08-29 — Documentación y exploración del dataset

- **Diccionario de variables en el repositorio.** Consideré trabajar con el diccionario en
  el `.docx` del enunciado, que es donde vive el original, pero elegí transcribirlo a
  `docs/diccionario_variables.md` porque un `.docx` no se consulta desde un notebook ni se
  diferencia entre commits: quiero que la definición de cada columna esté a un `grep` de
  distancia y que el análisis conceptual quede versionado junto al código que lo usa. La
  transcripción separa lo que dice el enunciado de lo que es interpretación propia, para que
  el evaluador sepa cuál es cuál.

- **Explorar antes de escribir el pipeline.** Consideré arrancar directo por los
  transformadores del Ejercicio A-1, que es lo que puntúa, pero elegí hacer primero el EDA
  en `modulo_a/exploration/` porque el enunciado dice que la ley "puede contener valores
  especiales — explóralos" y esconde al menos una trampa que solo se ve mirando los datos.
  Escribir el imputador sin saber que el centinela es `-1.0` y que se concentra en el turno
  N2 habría producido código correcto sobre un supuesto equivocado.

- **Auditar `prod_estimada_oz` en lugar de asumir.** El enunciado la marca como calculada y
  pide justificar por qué no usarla. Consideré responder con el argumento conceptual, que ya
  es suficiente para el punto, pero elegí pedirle a Claude que recuperara la fórmula exacta a
  partir de los datos porque una afirmación con `R2 = 0.999999999972` y error máximo de
  6.45e-4 oz no se discute en la defensa técnica, y porque solo así aparece el matiz que hace
  la respuesta completa: la variable no es inutilizable en absoluto, es inutilizable
  **contemporánea al objetivo**; como lag de turnos ya cerrados es legítima.

- **Notebook ejecutado y versionado con sus salidas.** Consideré versionar el notebook
  limpio, que es la práctica habitual para no ensuciar los diffs, pero elegí guardarlo con
  las salidas y las figuras porque el evaluador tiene 30 minutos y no necesariamente el CSV
  a mano: quiero que abra el archivo y vea los resultados sin ejecutar nada. El costo es un
  diff ilegible en ese archivo; lo asumo porque el notebook es un entregable de lectura, no
  un módulo que vaya a evolucionar línea a línea.

- **Ninguna cifra sin ejecución que la respalde.** Es una regla fija de cómo trabajo y aquí
  la hice cumplir: al cerrar el EDA aparecieron dos números del texto que no coincidían con
  la salida del notebook ya ejecutado. Consideré dejarlos, porque el sentido de los párrafos
  no cambiaba, pero elegí que se corrigieran contra la ejecución porque una cifra que no
  reproduce el propio notebook del repositorio es exactamente el tipo de detalle que hunde
  una defensa técnica.

## 2026-08-29 — Reglas de trabajo y reorganización del EDA

- **Dónde viven mis reglas de trabajo.** Consideré repetirle a Claude en cada chat que sea
  conciso, que no escriba código sin mi aprobación explícita y que no avance de fase sin que yo
  se lo indique, pero elegí dejarlo escrito en un `CLAUDE.md` en la raíz del repositorio y
  duplicado en su memoria persistente, porque una regla que hay que repetir en cada sesión se
  incumple tarde o temprano y además no queda constancia de ella para quien revise el
  repositorio. El archivo va versionado: es parte del entregable, no configuración privada.

- **De quién es este diario.** Encontré en esta bitácora decisiones que en realidad tomó o
  ejecutó la herramienta, redactadas en primera persona como si fueran mías. Consideré
  simplemente corregir las entradas equivocadas, pero elegí además escribirlo como regla en el
  encabezado y en las instrucciones del repositorio, porque el error es sistemático y no
  puntual: si no queda dicho, vuelve. Este archivo registra mis decisiones; cuando la opción la
  propuso Claude se dice explícitamente y lo que queda es mi resolución sobre esa propuesta. Lo
  que ejecutó la herramienta vive en `ia_usage.md`.

- **El EDA no anticipa las fases siguientes.** El notebook había acumulado referencias a los
  transformadores del Ejercicio A-1, a las capas del Módulo B y a la estrategia de validación.
  Consideré dejarlas porque adelantan trabajo que igual hay que hacer, pero elegí sacarlas todas
  y que el notebook solo describa el dato, porque mezclar la exploración con las conclusiones de
  diseño ensucia el análisis y me confunde a mí primero: al leerlo ya no distingo qué es un
  hallazgo del extracto y qué es una decisión que todavía no tomé.

- **Una sección por variable.** Consideré organizar el notebook por temas (completitud, tiempo,
  geología, máquina), que es como estaba, pero elegí una sección por variable con el nombre de
  la columna en el título y las dieciocho columnas cubiertas, incluidas las que no dan para más
  que una descripción breve. La razón es de uso: cuando vuelva a buscar qué sé de
  `agua_iny_lmin` quiero un lugar único donde mirar, no reconstruirlo de tres secciones
  temáticas. La consecuencia es algo de repetición entre secciones y la asumo.

- **Histograma y diagrama de caja para todas.** Consideré graficar solo las variables con
  hallazgo, pero elegí que todas tengan histograma y caja — y en las categóricas, frecuencias
  más caja de la ley por categoría — porque la ausencia de estructura también es un resultado y
  se sostiene mejor mostrándola que afirmándola. El costo es un notebook más pesado; se resuelve
  con dos funciones auxiliares en lugar de repetir el código veinte veces.

- **Demostrar, no afirmar, que `ton_rom_acum` no es un acumulado.** Noté que el valor se reduce
  dentro de un mismo turno, cuando un acumulado solo puede crecer. Consideré quedarme con el
  estadístico agregado (solo el 4% de los grupos es creciente), pero elegí que además se aísle
  un turno concreto y se grafique junto al acumulado que resultaría de sumar, porque un
  porcentaje se discute y una serie que baja ocho veces en un turno no.

- **Caracterizar los eventos que desplazan la media del intervalo.** La mediana entre eventos de
  un frente es de 25 minutos y la media de 308. Consideré reportar la discrepancia y seguir,
  pero elegí que se caracterizaran los eventos responsables, y eso destapó que la distribución
  es bimodal: el 0.84% de los pares concentra el 84% del tiempo transcurrido. Sin ese desglose,
  la variable parecía tener cola larga cuando en realidad tiene dos regímenes distintos.

- **El extracto es sintético y sus etiquetas están repartidas al azar.** Al ver que no existe un
  solo evento simultáneo pregunté si el archivo describe una sola máquina. Ante las dos lecturas
  posibles — una máquina real, o un extracto sintético con `equipo_id` y `op_id` repartidos como
  etiquetas sobre un flujo único — elegí la segunda, porque es la única que explica todo a la
  vez: la cadencia uniforme entre 15 y 34 minutos, los segundos siempre en 00, la ausencia total
  de simultaneidad y el reparto perfecto de cada equipo en los trece frentes y cada operador en
  los diez equipos. La lectura de "una sola máquina" explicaría la serialización pero no lo
  demás. La consecuencia, y por eso la decisión importa: `equipo_id` y `op_id` no admiten lectura
  causal, no se afirma nada sobre el desempeño de máquinas ni de cuadrillas, y el orden del
  archivo se lee como orden de emisión y no como secuencia de operación concurrente. El supuesto
  queda enunciado como supuesto: lo demostrado es que el archivo es un flujo serial, no cuántas
  máquinas tiene la unidad minera.

## 2026-08-30 — Ejercicio A-1: primeros transformadores

- **Figuras estáticas en lugar de interactivas.** Había pedido llevar todas las figuras del
  EDA a Plotly por la interactividad, y funcionó: el hover permite leer valores exactos sin
  agregar celdas. Pero GitHub no renderiza Plotly con ningún mecanismo, y el repositorio es
  privado, así que quien me evalúe lo va a recorrer en el navegador y vería celdas de figura
  vacías. Consideré dejar Plotly y advertirlo en el README, pero elegí volver a seaborn sobre
  matplotlib porque la decisión la manda el destinatario y no la tecnología: el notebook ya
  no es una herramienta para explorar, es un documento para ser leído, y una figura que el
  lector no ve es peor que una figura que no puede interrogar. La alternativa de emitir
  ambas representaciones exige `kaleido`, que a su vez exige un Chrome instalado, y eso
  rompe la promesa de "ejecutable en entorno limpio" del README.

- **El extracto vive en `data/`, ignorado por git.** Veníamos leyendo el CSV desde un
  directorio hermano al repositorio, fuera de él. Consideré dejarlo así, pero elegí traer una
  copia a `data/` en la raíz y agregar ese directorio al `.gitignore`, porque el proyecto
  tiene que ser autocontenido para cualquiera que lo clone sin dejar de excluir el dato de la
  historia de git. El orden de búsqueda queda documentado: `AURUM_CSV_PATH`, luego `data/`,
  luego el directorio hermano.

- **Las cuatro prácticas quedan escritas, no repetidas.** OOP, testing, typing y
  documentación son criterio de evaluación explícito del enunciado y yo se las venía pidiendo
  a la herramienta en cada tarea. Elegí escribirlas como sección propia del `CLAUDE.md` con
  criterio verificable por herramienta —cobertura mínima forzada por configuración, mypy
  estricto— en vez de dejarlas como intención: una regla que depende de que alguien la
  recuerde no es una regla.

- **`flag_imputed` se implementa literal.** El enunciado dice "si n<5, marca la fila con
  `flag_imputed=True` en lugar de imputar", lo que significa que la bandera marca lo **no**
  imputado. Se me propuso agregar una segunda columna con la semántica inversa por si el
  modelado la necesitaba; consideré aceptarla, pero elegí ceñirme a la letra del enunciado y
  no crear columnas que nadie pidió todavía. Si el Ejercicio A-2 la necesita, se agrega ahí,
  con la justificación puesta en su momento.

- **scikit-learn sí, pero sin heredar de `TransformerMixin`.** Voy a usar scikit-learn en el
  modelado del A-2. Consideré que `AurumTransformer` heredara de `BaseEstimator` y
  `TransformerMixin` para componer con `Pipeline` gratis, pero elegí una clase abstracta
  propia porque el enunciado pide exactamente eso —`fit()`, `transform()` y
  `fit_transform()`— y porque atar la pieza más central del paquete a las convenciones de un
  framework obliga a conocerlas para entender qué hace `fit_transform`. La firma conserva la
  convención `fit(X, y=None)`, de modo que los objetos siguen encajando en una `Pipeline` por
  duck typing si conviene.

- **`pyproject.toml` solo para configuración.** No empaqueta ni declara dependencias: las
  dependencias siguen en `requirements.txt` con `venv`, que es lo que un evaluador puede
  reproducir sin instalar antes un gestor. El archivo existe para que pytest, mypy y ruff se
  configuren en un lugar en vez de en tres dotfiles sueltos en la raíz.

- **`AurumFeatureBuilder` se detiene hasta comparar.** Tengo mi propia tabla de features
  pensada desde el dominio. Consideré dejar que la herramienta implementara la suya y
  corregir después, pero elegí pedir primero la tabla detallada y compararla contra la mía,
  porque las features son la parte del ejercicio donde se evalúa criterio minero y no
  destreza de programación: una feature que no puedo defender en la entrevista no sirve
  aunque el código esté impecable.

- **La media, no la mediana, para resumir la ley reciente.** Consideré la mediana por
  coherencia con el imputador, que la usa por mandato del enunciado, pero elegí la media
  después de medirlo: dentro de cada frente la ley es simétrica (asimetría +0.03) y sin
  contaminación —el centinela ya lo trató el imputador aguas arriba—, y ahí la media es el
  estimador eficiente. Gana en RMSE, MAE, correlación y en R² sobre el objetivo real, 0.9695
  contra 0.9671. La robustez de la mediana protege de algo que en ese punto del pipeline ya
  no existe. El estadístico queda como parámetro configurable, por si aparece un centinela no
  declarado.

- **La vibración entra como feature.** No aparece en la matriz de correlación —su coeficiente
  con la ley es 0.004— y por eso casi la dejo fuera, pero elegí incluirla porque el criterio
  de la matriz no ve relaciones de umbral: sobre 12 m/s2 la tasa de falla es 17.1% contra
  3.3% de base, el umbral del diccionario coincide con el salto real del dato, y solo el 19%
  de esos registros supera también el umbral de temperatura, así que no es información
  repetida. Va como bandera y no como magnitud, porque con 140 casos el dato no sostiene una
  forma continua.

- **El umbral térmico de las features es 88 °C, no los 95 °C del diccionario.** Al verificar
  si la magnitud del exceso de temperatura servía, apareció que la relación es un escalón:
  hasta 87 °C la tasa de falla ronda el 2% y entre 88 y 89 salta al 22%, quedando plana de ahí
  en adelante. Consideré quedarme con el umbral publicado, que es lo que pide literalmente el
  enunciado para las banderas de anomalía, pero elegí llevar las dos: la de 95 °C porque el
  enunciado pide banderas según los rangos del diccionario, y la de 88 °C porque captura el
  49% de las fallas contra el 12% de la otra, con la misma precisión. Y descarté la feature
  continua del exceso, porque por encima del umbral la magnitud no discrimina (correlación
  +0.02).

- **El objetivo de clasificación se declara limitado antes de modelarlo.** Medí el objetivo
  literal del enunciado —falla del mismo equipo en las próximas cuatro horas— y ninguna
  condición observable mueve la tasa base de 3.05%. La detección contemporánea sí funciona
  (22.7% sobre 88 °C). Consideré no mencionarlo y dejar que el modelo del A-2 hablara por sí
  solo, pero elegí dejarlo escrito en el EDA antes de modelar, porque presentar después un
  clasificador a cuatro horas como si funcionara sería un error de lectura, y porque la
  discusión de métrica del A-2 se apoya justamente en esto.

- **La demo es verificación, no ilustración.** Consideré que `pipeline_demo.ipynb` fuera un
  recorrido narrado de los transformadores, que es lo que se suele entregar, pero elegí que
  además compruebe sobre las cincuenta mil filas reales lo que las pruebas fijan sobre datos
  sintéticos: que ningún rezago replique su propia fila, que ninguna antigüedad sea cero, que
  no sobreviva un centinela y que ninguna columna original cambie. Una fuga de información no
  se manifiesta como error sino como una métrica sospechosamente buena, así que el lugar donde
  se ejecuta con datos verdaderos es el lugar donde hay que buscarla. La tabla consolidada se
  muestra completa, con sus primeras cincuenta filas, para que el evaluador vea el resultado y
  no solo el resumen.

- **Revisión adversarial antes de pasar al A-2.** Consideré seguir con el modelado, que es lo
  que puntúa, pero elegí detenerme a revisar en contra de lo construido: contrastar el
  entregable contra la letra del enunciado y buscar los errores que las pruebas verdes no
  pueden encontrar, porque son las pruebas mismas las que se escriben con los supuestos del
  autor. La revisión encontró tres cosas para corregir y dos para decidir; queda registro de
  todas, incluidas las que se midieron y se decidió no cambiar.

- **La sobretemperatura se mide sobre un cero real.** La feature era `temp_motor_c / rpm_corona`
  y al pedir sus unidades apareció el problema: el grado Celsius es una escala de intervalo con
  cero arbitrario, así que el cociente cambia el orden de los registros si se mide en kelvin
  —la correlación de rangos entre ambas versiones es 0.82— y deja de ser una magnitud física.
  Consideré dejarla, porque el modelo igual encontraría la relación, pero elegí cambiarla por
  `(temp_motor_c − 38) / rpm_corona`, medida sobre el incremento respecto de la temperatura
  mínima observada, que actúa como proxy de ambiente. Gana en las dos cosas que importan: tiene
  sentido dimensional y su asociación con la falla sube de 0.113 a 0.144. La referencia queda
  como parámetro configurable.

- **La tabla de salida se documenta en su propio archivo.** Consideré que bastara con los
  docstrings de los transformadores, que ya explican cada feature, pero elegí escribir
  `docs/tabla_resultado.md` con las treinta columnas una por una —unidad, interpretación, rango
  observado y advertencias— porque los docstrings los lee quien abre el código y esta tabla la
  va a leer quien reciba el resultado. Ahí quedan reunidas las quince advertencias que hoy
  estaban dispersas entre el notebook, el diccionario y los docstrings: que `flag_imputed` marca
  lo contrario de lo que sugiere su nombre, que `ton_rom_acum` no es un acumulado, que el umbral
  térmico real es 88 °C, que `equipo_id` y `op_id` no admiten lectura causal, y las demás.

- **La respuesta obligatoria sobre `prod_estimada_oz` es una sola, no cuatro.** Claude me
  presentó cuatro argumentos posibles: la circularidad algebraica —la variable es el objetivo
  despejado y con `ton_rom_acum` y `tipo_mineral` en el mismo archivo la ley se reconstruye con
  R² de 0.9999999998—, la fuga temporal, la fuga por el patrón de nulos y la procedencia
  —el diccionario dice "calculada, no medida directamente"—. Consideré entregar las cuatro,
  que es lo que suma en apariencia, pero elegí responder con la circularidad y la procedencia
  como una sola tesis, porque en el fondo son la misma: la variable es una salida del propio
  modelo interno de OPUS y por eso se despeja exactamente. Descarté la fuga temporal porque se
  disuelve en cuanto alguien plantee que va a usar el modelo para simular escenarios y fije las
  demás variables a mano, y descarté la del patrón de nulos porque es una observación menor que
  no sostiene la respuesta por sí sola. Prefiero un argumento que resista la defensa técnica a
  una lista que se caiga en la primera repregunta.

- **La estructura del A-2 va dentro de `aurum_pipeline`, en dos paquetes nuevos.** Claude
  propuso `modeling/` y `serving/` como hermanos de `transformers/`, y coincidía con lo que yo
  había esbozado. Consideré un paquete separado por ejercicio, que dejaría el A-2 visualmente
  aislado, pero elegí mantener un único paquete importable: el A-2 consume el A-1 por import y
  no por copia, y la configuración de pytest, mypy y ruff no cambia. La separación entre
  `modeling/` y `serving/` sí la conservo, porque es de dependencias y no de orden: entrenar no
  debe requerir FastAPI y probar la predicción no debe requerir levantar un servidor.

- **Los lags entran al modelo; el contrato de la API es otra cosa.** Claude había acotado las
  features a lo que el payload de `/predict` puede transportar, apoyándose en que el objetivo
  dice "dado el frente activo y condiciones actuales". Consideré aceptarlo, porque deja una API
  sin estado y elegante, pero elegí separar los dos contratos: el enunciado no restringe las
  features del modelo y los rezagos son causales; el A-1 los pidió explícitamente. La medición
  me dio la razón —con lags el error baja de 0.4230 a 0.4140 g/t— aunque ninguno de los dos le
  gane al baseline. La API los recibe como campos opcionales y degrada al nivel congelado del
  frente cuando no llegan.

- **La estrategia de ventana la deciden las cifras del modelo, no un tanteo previo.** Claude
  midió expansiva contra deslizante en un experimento aparte y propuso la expansiva ya decidida.
  Consideré aceptar la conclusión, que además coincidía con la mía, pero elegí que la comparación
  fuera parte del entregable: el splitter soporta las dos estrategias como parámetro y las cinco
  variantes se evalúan sobre los mismos pliegues y quedan registradas en MLflow. El enunciado
  pide justificar la ventana temporal, y una justificación que el evaluador no puede reproducir
  desde el repositorio no es justificación. De paso obligó a corregir un error: lo que Claude
  había medido primero no era una ventana deslizante sino una historia decreciente anclada al
  mismo corte.

- **Tres conjuntos, no dos.** Pedí separar entrenamiento, validación y prueba en vez de trabajar
  con desarrollo y hold-out. La prueba —el 20% más reciente del calendario, 797 turnos desde el
  2025-05-06— se toca una sola vez y no participa de ninguna decisión; la validación es la que
  elige hiperparámetros, conjunto de variables y estrategia de ventana. Descarté los tres bloques
  fijos disjuntos que Claude ofrecía como alternativa, porque dejan una sola estimación de
  validación sin dispersión medible e inutilizan el bloque intermedio para el ajuste final.

- **Grilla aleatoria y no exhaustiva, con veinte configuraciones.** Elegí búsqueda aleatoria
  sobre las distribuciones de hiperparámetros, anidada dentro de cada estrategia de ventana para
  que cada una compita en su mejor configuración. Claude propuso `n_iter=30`, que medido daba 22
  minutos de cómputo; lo bajé a 20 porque 13 minutos es un notebook que el evaluador puede correr
  y 22 empieza a ser un notebook que nadie reejecuta.

- **La API rechaza lo imposible y marca lo alarmante.** Claude advirtió que los rangos del
  diccionario mezclan dos cosas: `pres_hidraul_bar` entre 180 y 240 es un rango operacional, pero
  `vibracion > 12` y `temp > 95` son alertas, no imposibilidades físicas. Resolví que Pydantic
  rechace con 422 únicamente lo que no puede existir y que acepte los valores de alerta
  devolviéndolos marcados, porque un 422 ahí rechazaría exactamente los registros que a
  operaciones le interesa consultar.

- **El A-2 completo de una vez, no la regresión primero.** Había pedido cerrar la regresión y
  después seguir con la clasificación, y lo cambié: con la estructura y las decisiones de
  diseño ya tomadas, lo que faltaba era ver resultados, y partir el trabajo en dos entregas
  habría significado revisar dos veces la misma partición, el mismo registro y la misma API.
  Consideré el riesgo de que un lote grande escondiera un error; lo compensé pidiendo revisión
  adversarial explícita sobre lo construido en lugar de confiar en que las pruebas verdes
  bastaran.

- **La firma del modelo es el contrato de la API, no una fila de la matriz.** La revisión de
  extremo a extremo mostró que el servicio fallaba por esquema contra los modelos recién
  registrados, y que las pruebas no lo veían porque registraban sin ejemplo. Consideré relajar
  la validación de MLflow, que era el arreglo de una línea, pero elegí lo contrario: que la
  firma sea exactamente la entrada del servicio y que un solo lugar del código defina qué
  columnas y con qué tipos. La firma deja así de ser un adorno del registro y pasa a ser lo que
  impide que el contrato de la API y el del modelo se separen en silencio.

- **Falta registrar el error de entrenamiento, y lo dejo como pendiente explícito.** Al revisar
  las corridas en MLflow noté que solo tenemos la métrica de validación: sin la de
  entrenamiento no hay brecha que mirar, y sin brecha no se puede diagnosticar sobreajuste
  desde el registro. Es una buena práctica que se nos quedó fuera. Vi además indicios de que el
  clasificador de falla sobreajusta. Consideré parar y corregirlo antes de seguir, pero elegí
  dejarlo anotado como pendiente y cerrar aquí: el cambio toca la evaluación, el registro y las
  tablas comparativas de las dos fases, y prefiero abordarlo con la cabeza fresca antes que
  meterlo al final de una sesión larga. Queda detallado en `docs/modelado.md`, con lo que hay
  que implementar y las tres señales que me hicieron sospechar.

## 2026-08-30 — Cierre del A-2: sobreajuste, feature engineering y la etiqueta de falla

- **Pensar antes que entrenar.** El tiempo para iterar entrenamientos es limitado, así que en
  vez de pedir más corridas pedí una propuesta para robustecer los modelos con revisión
  adversarial incluida, y con énfasis en el feature engineering porque mi propia lista pudo
  dejar cosas fuera. Consideré retomar directo el pendiente del error de entrenamiento, que
  era lo único anotado, pero elegí que primero se releyeran el diccionario, la definición de
  los modelos y el objetivo del A-2 contra los resultados ya medidos, porque un pendiente
  puntual no garantiza que el resto del entregable resista la defensa.

- **La etiqueta de falla mide continuidad operativa, y así hay que decirlo.** Claude midió
  sobre el extracto que la tasa de `falla_en_4h` reproduce la de eventos independientes al
  3.3% por evento en todos los tramos de actividad, que no hay agrupamiento ni precedencia, y
  que el levante del clasificador coincide con lo que da una sola variable: cuánto llevaba el
  frente sin registrar al cierre. Propuso reformular la lectura del resultado y el
  experimento —etiqueta contada desde el cierre del bloque horario, columnas de actividad y de
  resumen por umbral, un conjunto `ACTIVIDAD`, un baseline de actividad, la precisión media
  condicionada a las ventanas con registros, el peso de clase medido en lugar de supuesto y los
  campos nuevos opcionales en la API—. Consideré dejar la conclusión anterior, «hay señal pero
  no alcanza para operar», que es cierta y ya estaba escrita, pero aprobé la reformulación
  completa porque decir «hay señal» cuando la señal es «sigue perforando» es un error de
  interpretación que un evaluador minero detectaría en la defensa, y porque la tesis se prueba
  dentro del experimento y no en un párrafo.

- **El pendiente del error de entrenamiento se implementa como estaba especificado**, con el
  paso adicional que propuso Claude de pedirle el puntaje de entrenamiento a la propia
  búsqueda de hiperparámetros, para que la curva entre capacidad y brecha salga de la corrida
  que ya se hace y no de un experimento aparte.

- **La ventana temporal de la regresión se valida antes de tocarla.** Claude propuso no
  cambiar nada en la regresión. Consideré aceptarlo, porque el modelo empata con el techo del
  problema, pero pedí que se validara primero si la ventana temporal es la adecuada, igual que
  se cuestionó la ventana de la etiqueta en la clasificación: una decisión que no se revisó con
  el mismo rigor que su vecina no está cerrada.

- **Lo que queda fuera.** Acepté dejar fuera la regla 1-SE o la selección por media menos
  desviación para mitigar la maldición del ganador, la capa de calibración, el modelo por
  equipo, la búsqueda bayesiana y SMOTE, con el argumento de Claude que hice mío: con la brecha
  registrada basta para diagnosticar, y cada una de esas piezas es una decisión más que
  defender por una ganancia que el dato no sostiene.

- **Revisión adversarial sobre lo construido, no solo sobre lo propuesto.** Lo recordé a mitad
  del trabajo: la propuesta ya la había recibido con su revisión, pero la implementación tiene
  que pasar por la misma prueba antes de darse por terminada.

- **La ventana de entrenamiento, con hipótesis por defecto y reajuste que la honra.** La
  validación que pedí mostró dos cosas: la ventana objetivo está bien planteada —el residuo sube
  con el hueco solo porque los turnos que reabren una campaña son parciales—, y la fase B había
  elegido una deslizante de doce meses por 0.0003 g/t con 0.016 de desviación entre pliegues,
  mientras la fase C reajustaba el modelo con todo el desarrollo y la documentación defendía la
  expansiva. Claude propuso dos salidas: conservar la expansiva salvo que una deslizante la
  supere por más de la desviación entre pliegues y que el reajuste final honre la ventana
  elegida, o dejar la selección como estaba, honrar la ventana y reescribir la documentación
  como empate. Consideré la segunda, que no agrega reglas, pero elegí la primera porque deja en
  producción un modelo entrenado con toda la historia por una decisión declarada y no por un
  empate resuelto a favor del que tocó primero, y porque la regla no es sobre hiperparámetros
  —esos siguen eligiéndose por el máximo, con la brecha al lado— sino sobre una hipótesis de
  diseño que ya estaba escrita.

- **El sensor se explica a tres horizontes, y la debilidad del protocolo se declara.** Pregunté
  si nuestros resultados reflejaban que «el rango útil está en el sensor, no en el modelo»,
  porque debía verse en el SHAP del clasificador. Claude midió que no se podía ver: el
  clasificador registrado no lleva sensores, y el A-2 nunca había explicado al clasificador.
  Propuso dos cosas —explicar el clasificador con todas las variables y una sonda a nivel de
  evento que mide el mismo sensor contra la falla del mismo evento y contra la del siguiente, y
  declarar que la fase A elige el conjunto con hiperparámetros por defecto y eso castiga a los
  conjuntos anchos— y una tercera opcional, correr la fase B con `COMPLETO`. Elegí agregar las
  dos primeras y dejar la tercera fuera, por la misma restricción de tiempo con que abrí la
  sesión: la debilidad queda declarada con su número y la atribución dice lo mismo con
  cualquiera de los dos modelos.

- **El módulo A se cierra consolidando el repositorio desde esta sesión.** Trabajo en paralelo
  en otras dos terminales sobre el mismo proyecto, cada una en su rama y su worktree. Pedí que
  la consolidación se hiciera con cuidado: commits por nombre de archivo en la rama del A-2,
  integración a `main` con merge commit y sin tocar los worktrees de las otras ramas.

## 2026-08-30 — Módulo C, Ejercicio C-1

- **Abrir el Módulo C en paralelo al A-2, en un worktree aparte.** Estoy trabajando el A-2 en
  otra terminal, con el notebook escribiéndose en sitio y MLflow abierto sobre `mlflow.db`.
  Consideré simplemente crear la rama en el mismo directorio, pero eso obligaba a un
  `git checkout` que le cambia el árbol de trabajo al notebook en ejecución, así que elegí un
  worktree separado sobre rama nueva desde `main`. Le di además tres restricciones explícitas
  a la herramienta: no instalar ni desinstalar nada en la venv compartida, no escribir en
  `mlflow.db`, y no cambiar de rama en el directorio principal.

- **Plataforma: híbrido Databricks más Fabric.** Claude planteó tres opciones con una tabla
  comparativa y recomendó el híbrido. Consideré seriamente Fabric puro, que para un equipo de
  4 personas es el más barato de operar y no es un argumento menor, pero elegí el híbrido
  porque el Módulo B ya pide medallion en Databricks, capa Gold en Fabric con RLS y MLflow:
  responder Fabric puro en el C-1 dejaría al Módulo B incoherente conmigo mismo, y eso se cae
  en la defensa de 30 minutos. Acepté que el documento declare el umbral en que la decisión se
  revierte: si el equipo baja de 4 personas o desaparece el ciclo de ML, la respuesta correcta
  pasa a ser Fabric puro.

- **Estructura literal del enunciado, no la mía.** Yo había pedido `arquitectura_plataforma_umlc/`
  y `rag/` como subdirectorios, con solo un `.md` adentro. Claude me señaló que el enunciado
  lista como estructura mínima `modulo_c/arquitectura.(png|pdf)`, `decisiones_arquitectura.md`
  y `rag_minero/`, y que un evaluador que revise estructura contra esa lista lo marca sin leer
  el contenido. Consideré conservar mi organización, pero elegí la estructura literal: la
  claridad interna no vale un punto perdido por forma.

- **Verificar la normativa peruana antes de nombrarla.** Consideré describir el requisito
  regulatorio de forma genérica, que es más rápido y no arriesga un error factual, pero elegí
  que se verificara: nombrar mal una norma peruana en la defensa técnica cuesta más que no
  nombrarla. De ahí salieron ESTAMIN, la Declaración Anual Consolidada del artículo 50 del TUO
  de la Ley General de Minería, y el reporte geotécnico semestral de relaves ante OSINERGMIN,
  con sus plazos y multas.

- **Dos diagramas, en archivos de Eraser separados y privados.** Claude propuso uno solo o
  hasta tres, y agrupar ambos en un mismo archivo. Elegí dos —la arquitectura completa y el
  camino del dato bajo conectividad intermitente— porque el segundo es el que demuestra
  dominio minero, y pedí que fueran archivos distintos y privados, no un solo archivo
  compartido.

- **Tarifas de East US con la variación declarada.** Consideré cotizar en Brazil South, que es
  la región que la UMLC usaría de verdad, pero elegí East US porque es la lista base y
  cualquiera la verifica en un minuto contra la API oficial de precios de Azure; el documento
  declara que una región sudamericana encarece y que ese sobrecosto no está incorporado.

- **Escenario de consumo F8 con 25 a 40 visores.** Es el tamaño coherente con jefaturas de
  sector, planeamiento, geología y gerencia sobre 3 minas, 1 planta y 2 relaveras. Descarté
  F16 con 80 visores por inflar el total y F4 con 15 por quedarse corto frente al escenario
  del enunciado.

- **Nombrar productos concretos en el borde.** Consideré dejar el patrón sin marca, que
  envejece mejor como documento de arquitectura, pero elegí nombrar Azure IoT Edge y Event
  Hubs porque en una defensa técnica lo concreto se puede sustentar con precios y límites
  reales y el patrón abstracto no.

- **El costo de tokens del asistente se resuelve ahora; DR y staging quedan pendientes.**
  Claude propuso dejar tres cosas como pendientes para el C-2. Saqué el costo de tokens de esa
  lista y pedí que se calculara ya, y quedaron como pendientes declarados solo la continuidad
  y recuperación ante desastre y el ambiente de staging de la capacidad Fabric.

- **El modelo de costos es un archivo de código con prueba, no un anexo del documento.**
  Claude propuso embeber el script en un anexo del `.md` para no agregar archivos fuera de la
  estructura del enunciado. Elegí `modulo_c/costos.py` con su `tests/test_costos.py`, porque
  la prueba no verifica que Python sepa multiplicar sino que las cifras publicadas en el
  documento sean las que produce el modelo: si mañana cambia una tarifa y alguien no actualiza
  el texto, falla la prueba. Es la regla de hacer cumplir por máquina lo que no quiero dejar
  encomendado a la memoria.

## 2026-08-30 — Módulo C, Ejercicio C-2

- **Género y patrón de consulta no compiten: operan en niveles distintos.** Yo sostenía que el
  género del documento tiene un papel importante en el chunking; Claude proponía decidir por
  cómo pregunta el usuario. Elegí unir las dos posturas en dos niveles —el género elige la
  estrategia porque decide qué elementos existen, y el tipo de elemento fija la unidad de
  recuperación porque es lo que decide cómo se pregunta— y exigí que la discusión se cerrara
  con una ablación medida y no con un argumento: tres variantes de chunking contra el golden
  set, precisión y recall de contexto, sin modelo juez.

- **Una estrategia fuerte para las tablas partidas por página.** Noté que muchas tablas de los
  PDF están partidas por el salto de página y pedí que eso tuviera una solución robusta y no
  un parche. Quedó como fusión por continuidad —la página anterior termina en tabla, la
  siguiente empieza en tabla en el margen superior, mismo número de columnas— con una prueba
  de integración que fija el inventario de filas de cada documento.

- **BM25 para los códigos.** Ya lo había pensado antes de que Claude lo propusiera: en mina se
  pregunta por código y los embeddings densos no los encuentran. Recuperación híbrida en los
  dos almacenes, con la misma fusión de rangos recíprocos que usa Databricks.

- **Databricks, no Azure, por practicidad.** Azure AI Search es más completo para agentes, pero
  la plataforma del C-1 es Databricks y ahí es donde despega este asistente. Vector store:
  Mosaic AI Vector Search de Databricks, con Chroma más BM25 como respaldo local para las
  pruebas y para quien no tenga workspace. Claude señaló que el enunciado lista almacenes
  reproducibles en local y que Vector Search exige workspace; acepté las dos implementaciones
  detrás del mismo contrato.

- **LangChain como orquestación** y **credencial única vía Databricks** (modelo, embeddings e
  índice con el mismo perfil de la CLI), por practicidad. Sonnet 5 como generador y juez, con
  las corridas de prueba a la mitad; luego Haiku genera y Sonnet juzga, para quitar el sesgo
  de autoevaluación.

- **Dos diagramas en Eraser, uno por situación:** el flujo de una pregunta y la relación entre
  los roles de la mina, el asistente, los documentos y su clasificación. PDF por variable de
  entorno, como el CSV. Golden set redactado por Claude y validado por mí caso por caso: en
  pet-01 mi validación trajo la intervención de primer nivel del manual, y la respuesta
  esperada quedó cruzando el PET con el manual.

- **Costos antes de cada recurso, con tope de 40 USD.** Pedí evaluar el costo antes de
  cualquier modificación. Aprobé una sesión estimada en 9.59 USD, dominada por el endpoint de
  Vector Search por hora y no por los tokens, y bajé el auto-stop del warehouse a un minuto
  para que la consulta de facturación costara 0.28 USD y no 1.54.

- **Modelos abiertos cuando el workspace apagó a Claude.** El workspace de prueba devolvió
  «rate limit of 0» para todos los modelos propietarios, incluso después de pasar a plan
  pagado, porque la cuenta sigue en el nivel de confianza de prueba. Consideré esperar la
  reclasificación o usar la API de Anthropic directa con clave propia, pero elegí correr con
  Qwen3-Next 80B como generador y Llama 3.3 70B como juez —los dos probados— porque no
  bloquea la entrega y el modelo es una variable de configuración; si Claude se habilita
  antes de entregar, se repite solo la corrida final.

- **Cierre del C-2 con la corrida sobre Vector Search.** Cuatro corridas del notebook: las tres
  primeras fallaron por el ciclo de vida del índice en Databricks —token OAuth vencido durante
  la media hora que tarda en crearse, pipeline ocupado que rechaza sincronizar, y `asyncio.run`
  dentro del kernel de Jupyter—, cada una con corrección y prueba de regresión. La cuarta cerró
  completa: faithfulness 0.97, answer_relevancy 0.70, context_precision 0.80, diez de diez
  respondidas, trece preguntas de control correctas, y el endpoint borrado por el propio
  flujo. Acepté que el README leyera las métricas bajas donde lo son (pet-01, geo-02, man-01)
  en vez de maquillarlas.

- **DeepSeek V4 Flash como generador, en lugar de Haiku.** Pedí un modelo más potente que los
  que corrieron. Claude probó todos los endpoints habilitados y me mostró que los propietarios
  y varios abiertos grandes (Kimi K3, DeepSeek V4 Pro, GLM) comparten el bloqueo de la cuenta.
  Entre los que responden, DeepSeek V4 Flash fue el único que detectó la contradicción entre
  el PET y el manual, y las comparativas públicas lo ubican al nivel de Haiku 4.5 y por debajo
  de Sonnet. Quise quedarme con Haiku, pero no existe como servicio en el workspace, así que
  elegí DeepSeek V4 Flash como su equivalente, con Llama 3.3 70B de juez. La corrida final con
  ese generador queda pendiente para la próxima sesión.

- **Despliegue del asistente, después y como ítem aparte.** Pregunté qué haría falta para
  desplegar el agente en Databricks sin sobreingeniería. Claude comparó cuatro vías y
  recomendó una Databricks App que reutiliza el código tal cual; acepté dejarlo como opcional
  fuera del enunciado, porque exige mantener vivo el endpoint de Vector Search.

- **La corrida final con DeepSeek V4 Flash, con revisión adversarial y respuestas claras.**
  De los cuatro pendientes que quedaron escritos al cierre de la sesión anterior, autoricé solo
  el primero, la corrida final con DeepSeek V4 Flash como generador, y pedí que pasara por
  revisión adversarial antes de darse por terminada, con una exigencia adicional: que las
  respuestas del C-2 —las del asistente y las del README a las cinco preguntas del enunciado—
  fueran muy claras. El merge a `main`, la lectura de la factura y la Databricks App siguen
  esperando mi indicación.

- **El C-2 se integra a `main` y la App queda descartada.** Con el A-2 ya integrado autoricé
  el merge de `feature/c2-rag` a `main` con merge commit, la lectura de la factura real en
  `system.billing.usage`, y descarté el despliegue opcional como Databricks App: está fuera
  del enunciado y exige mantener vivo el endpoint de Vector Search. Pedí además una revisión
  adversarial de cobertura: verificar contra el enunciado que el C-2 responde todo lo que se
  pregunta. La factura solo refleja por ahora 0.73 USD (warehouse SQL); el serving y el
  Vector Search de la sesión de la mañana siguen sin aparecer por el rezago de horas, así que
  la cifra completa se anota cuando el sistema la publique.

- **El Módulo C queda integrado también en el remoto.** Con el C-2 mergeado en `main` local,
  pedí ajustar repositorio y documentación para que todo el Módulo C quedara integrado:
  publicar `main` en GitHub, borrar la rama y el worktree del C-2 ya integrados, y corregir la
  última línea del README que todavía decía que `modulo_c/` faltaba por crear. El Módulo B
  sigue en sus ramas y su worktree, intacto.
## 2026-08-30 — Módulo B, Ejercicio B-1

- **El Módulo B en una tercera terminal, con límites explícitos.** Con el A-2 cerrándose en
  una terminal y el C-2 en otra, abrí el B-1 en una tercera sesión. Consideré esperar a que
  alguno terminara, pero elegí avanzar en paralelo y le fijé a la herramienta sus límites
  antes de que escribiera nada: el árbol principal, su `.venv`, `pyproject.toml`,
  `requirements.txt` y los archivos de trazabilidad son del A-2; `../repositorio-ds-mine-c1`
  y `.venv-rag` son del C-2; el B-1 vive en un worktree propio con rama desde `main` y su
  propio venv, y los conflictos de los archivos compartidos se resuelven en el PR. En
  Databricks, no tocar `workspace.rag_minero` ni la configuración del warehouse.

- **Diagrama en Eraser, en el directorio del módulo y con su fuente.** Pedí que el diagrama
  del lakehouse fuera como el de la documentación de medallion de Databricks pero con nuestro
  caso, y que viviera en `modulo_b/`. Claude lo escribió a mano en el DSL de Eraser porque la
  generación por IA había agotado su cuota; acepté que la fuente `.eraser` se versione junto
  al PNG, para que el diagrama se pueda regenerar y no sea una imagen huérfana.

- **Sin tabla `bronze.lab_reclasificacion`.** Claude propuso guardar las correcciones del
  laboratorio crudas en una tabla de bronze antes de aplicarlas a silver, por fidelidad al
  origen. Consideré aceptarlo, pero elegí quitarla: el archivo del laboratorio queda en el
  volumen de landing y `ingesta_log` lo registra, así que la tabla duplicaba el registro
  crudo sin agregar nada. Menos objetos que explicar en la defensa.

- **Silver particionada por `anio_mes`.** Pregunté de dónde salía, porque no lo recordaba del
  enunciado, y Claude aclaró que el enunciado solo pide "partición justificada" y que
  `anio_mes` era su recomendación. Consideré las otras dos que planteó —sin partición con
  liquid clustering, que es lo que Databricks recomienda por debajo de 1 TB, y
  `sector_geol`, que se alinea con el RLS del B-2— pero elegí `anio_mes` porque los
  patrones de consulta reales son por rango de fecha: el `MERGE` de las correcciones poda a
  los meses tocados, el monitor de drift del B-3 lee 30 días y gold se recalcula por celdas
  de fecha. Acepto que a 10 MB ninguna partición cumple el mínimo de 1 GB que publica
  Databricks, y que la justificación es de poda de escritura, no de rendimiento de lectura.

- **Eficiencia de avance contra el 3.5 m/min del manual, no contra un percentil.** Claude
  había propuesto el percentil 95 histórico del frente; pregunté qué era y pedí que releyera
  los PDF. El manual del equipo no trae avance nominal pero sí el rango normal del sensor
  LVDT, 0.3 a 3.5 m/min. Elegí `avg(avance_mmin) / 3.5`: tiene fuente documental y un
  operador de mina lo lee como fracción del avance máximo especificado. Descarté el p95 por
  no tener fuente externa y el promedio a secas por no ser una eficiencia.

- **Horas efectivas, producción recalculada, reporte DQ como tabla y Auto Loader.** Acepté las
  cuatro recomendaciones: horas efectivas como el lapso entre primer y último evento del
  turno, acotado a seis horas, menos el tiempo de los eventos con falla o en mantenimiento;
  `prod_oz_recalculada` en gold con la fórmula de OPUS y el tipo vigente, conservando
  `prod_estimada_oz` intacta; el reporte de calidad como tabla Delta y no como archivos, para
  que Fabric lo consuma en el B-2; y Auto Loader para la ingesta, después de preguntar qué
  era y entender que el checkpoint es lo que hace idempotente la llegada de archivos.

- **JDK por Homebrew.** Pregunté si el JDK era necesario y qué alternativas había. Lo es:
  Spark corre en una JVM y `pyspark` es solo el cliente. Consideré el JDK dentro del venv con
  `install-jdk`, que no toca el sistema, y Databricks Connect, que ejecuta las pruebas en
  serverless con costo por sesión. Elegí `brew install openjdk@21` porque es lo que el README
  le va a decir al evaluador, y porque Java no lo usan las otras dos sesiones.

- **Precios confirmados antes de gastar.** Mantengo la regla de estimar el costo antes de
  cualquier acción en nube. Pedí confirmar los precios de lista en lugar de fiarme de la
  memoria: `system.billing.list_prices` dio 0.35 USD/DBU para jobs serverless, 0.75 para
  notebooks y 0.70 para SQL, exactamente los supuestos, y la consulta costó el mínimo de un
  minuto del warehouse. El rango del B-1 quedó en 1.6 a 7.9 USD de los 40 del trial.

- **Revisión adversarial y verificación contra el enunciado, siempre.** Al aprobar la
  implementación reiteré las dos condiciones: que la herramienta revise en contra de lo que
  construye y que compruebe, punto por punto, que respondemos lo que el enunciado pregunta y
  no lo que nos resultó cómodo construir.

- **El catálogo `lakehouse_umlc` lo creé yo desde la interfaz.** La CLI y la API del trial
  rechazan crear catálogos con Default Storage, y Claude corrió la validación sobre el catálogo
  `workspace` para no bloquearse. Consideré dejarlo ahí, documentado como limitación, pero
  elegí crear `lakehouse_umlc` a mano, de tipo Normal, porque el árbol del enunciado empieza
  por ese nombre y un evaluador que lo busque debe encontrarlo. Es el único paso del B-1 que
  no fue por línea de comandos; el redespliegue fue un parámetro y los esquemas de prueba de
  `workspace` se borraron.

- **Sin commit todavía.** Prefiero consolidar primero el A-2 en su terminal y commitear el B-1
  después, para resolver los conflictos de README, `pyproject.toml`, `requirements.txt` y los
  archivos de trazabilidad una sola vez y con la cabeza puesta en ello.

- **Ratifico el diseño sin `foreachBatch` y las pruebas dentro del paquete.** Claude tomó
  ambas decisiones durante la implementación y me las expuso dos veces. Consideré pedir que
  se conservara `foreachBatch`, que es el patrón canónico de Auto Loader, pero elegí el
  diseño en batch porque en serverless la función corre en el servidor bajo Spark Connect y
  el estado del cliente no llega a ella: prefiero un libro de control explícito
  (`reporte_calidad` para silver, `ingesta_log` para las correcciones) a un patrón que solo
  se puede verificar pagando corridas fallidas. Y las pruebas van dentro del paquete, como
  en el A-1, porque dos paquetes llamados `tests` en el `pythonpath` se pisan. Era justo lo
  que estaba pensando.

## 2026-08-30 — Módulo B, Ejercicio B-3

- **Las ventanas del PSI son las del monitoreo, no las del entrenamiento.** El enunciado dice
  "los últimos 30 días como referencia" y es ambiguo. Claude me planteó las dos lecturas y
  elegí la recomendada: la referencia son los 30 días anteriores a una ventana de evaluación
  de 7, porque lo que se vigila es el proceso y no al modelo; anclar la referencia al momento
  del entrenamiento respondería otra pregunta.

- **Se porta el LightGBM del A-2, no un sustituto.** Claude recomendó registrar en Unity
  Catalog un modelo de media por frente citando la conclusión del A-2, que es autocontenido y
  más rápido. Elegí lo contrario: portar el modelo real, con `aurum_pipeline` sincronizado en
  el bundle y LightGBM instalado en serverless, porque en la defensa quiero mostrar el mismo
  pipeline del A-2 —codificación del frente adentro, conjunto `MINIMO`, métricas en lenguaje
  de operación— viviendo el ciclo completo de MLOps, no una imitación.

- **El registry va en un esquema nuevo `modelos`.** Justo como lo quería: los modelos no son
  KPI y no se mezclan con `gold`.

- **La demo de deriva es en memoria.** Elegí no ingerir lotes sintéticos de deriva por el
  pipeline real: contaminar silver y gold para demostrar un mecanismo es más caro que
  fabricar el escenario en memoria sobre un modelo `_demo`, y deja los KPI limpios para el
  evaluador.

- **B-1 se integra ya y el B-3 va en rama nueva.** Pedí commitear el B-1 e integrarlo a
  `main` resolviendo los conflictos con el A-2 consolidado, y abrir `feature/b3-mlops` desde
  ahí. La integración a `main` quedó en pausa porque la terminal del C-2 está en pleno merge
  sobre el árbol principal; el B-3 avanza sobre la rama del B-1 verificada (395 pruebas,
  99.56% de cobertura tras la fusión con el A-2).

- **El MLOps es un job aparte, no una cola del job de datos.** Dudé entre las dos opciones y
  pregunté qué se usa en Databricks; la referencia de la casa (MLOps Stacks) separa el
  monitoreo y el reentrenamiento en jobs con su propio schedule, y así queda: job
  `lakehouse_umlc_mlops` con cadencia diaria declarada y pausada, porque encenderla es una
  decisión de operación y no un costo que la prueba deba correr sola.
