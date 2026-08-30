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
