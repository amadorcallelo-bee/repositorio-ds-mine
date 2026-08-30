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
