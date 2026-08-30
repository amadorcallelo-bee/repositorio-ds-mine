# repositorio-ds-mine

Prueba técnica **DS-MINE-2025-v2** — Científico de Datos Senior, minería de oro.
Trabajo sobre el extracto `OP_AURUM_extract.csv` del sistema de telemetría OPUS-MINE de la
Unidad Minera La Cornisa.

El uso de IA generativa está declarado en `ia_usage.md`, con la transcripción literal de la
conversación. Las decisiones propias y su justificación están en `diario_decisiones.md`.

## Estado de los módulos

| Módulo | Estado |
|---|---|
| Análisis exploratorio del extracto | completo — `modulo_a/exploration/eda_opus.ipynb` |
| A-1 · Los cuatro transformadores | completo, con pruebas |
| A-1 · `pipeline_demo.ipynb` | completo |
| A-2 · Regresión de ley, clasificación de falla, MLflow y SHAP | completo, con pruebas |
| A-2 · API FastAPI sobre el Model Registry | completo, con pruebas |
| A-2 · `modeling_demo.ipynb` | completo |
| A-2 · Error de entrenamiento, brecha y diagnóstico de sobreajuste | completo, registrado en MLflow |
| Módulo B · Lakehouse y MLOps | pendiente |
| C-1 · Arquitectura de plataforma | completo — `modulo_c/decisiones_arquitectura.md` |
| C-2 · RAG sobre documentación técnica | completo — `modulo_c/rag_minero/README.md`, demo ejecutada |

## Resultado del Ejercicio A-2

En una línea cada uno, con el detalle en [`docs/modelado.md`](docs/modelado.md):

- **La ley del turno siguiente no es predecible más allá del nivel del frente.** El modelo
  ganador da 0.3979 g/t de error medio sobre la prueba y el baseline del nivel del frente
  0.3975: un empate en la cuarta cifra decimal, resuelto a favor del baseline.
  El techo del problema —la media del frente calculada con todo el histórico, que ningún modelo
  puede usar— explica el 97.57% de la varianza y el baseline causal llega al 97.53%.
- **Agregar variables empeora la regresión** entre un 8% y un 26%, y la brecha entre
  entrenamiento y validación dice por qué: con hiperparámetros por defecto XGBoost baja el error
  de entrenamiento a 0.02 g/t y sube el de validación a 0.48. SHAP lo confirma sobre un modelo
  con todas las variables: el nivel del frente se lleva el 81% de la atribución y el sensor
  mejor ubicado —la vibración RMS— llega al 0.83%. Tiene sentido geológico: la ley es una
  propiedad de la veta, no de cómo se perfora.
- **La etiqueta de falla a 4 horas mide continuidad operativa, no estado mecánico.** Su tasa
  reproduce la de eventos independientes al 3.3% cada uno en todos los tramos de actividad, sin
  agrupamiento ni precedencia. El conjunto `ACTIVIDAD` —cuatro variables— gana a `COMPLETO`
  —27— y el techo del problema es el oráculo que conoce cuántos eventos tendrá la ventana:
  0.2984 de precisión media sobre la prueba. El modelo da 0.2817 contra 0.2271 de base
  —levante 1.24— y 0.2642 de un baseline que es una tabla de cinco tasas por tramo de minutos
  de inactividad; su exhaustividad al 50% de precisión es del 1.1%. Sirve para programar, no
  para mantener.
- **El sobreajuste está medido, no supuesto.** Cada corrida registra validación, entrenamiento
  y brecha; con hiperparámetros por defecto los clasificadores con más de cuatro variables dan
  precisión media 1.0000 en entrenamiento y 0.25 en validación, y la búsqueda la baja a
  0.07–0.20. El peso de clase se comparó con y sin, y sin peso ganó: la probabilidad por frente
  sigue a la tasa real sin capa de calibración.
- **El sensor sirve para detectar, no para anticipar, y el SHAP del clasificador lo muestra a tres
  horizontes.** A horizonte cero la temperatura domina la atribución (62.8%) con
  levante 3.9× sobre la tasa base; a un evento, unos 25 minutos, no queda señal; a cuatro horas
  pesa 3.9% y mandan los minutos de inactividad al cierre.
- **La ventana expansiva es la hipótesis por defecto y el experimento la conserva**, porque la
  mejor deslizante la supera por menos de una quinta parte de la desviación entre pliegues en
  los dos problemas.

## Ejercicio A-2: cómo se plantea el modelado

La unidad de modelado es la celda `(frente_id, fecha_local, turno_cod)` y el objetivo es la ley
del siguiente turno de ese frente. Sobre el extracto quedan 3985 pares; la prueba es el 20% más
reciente del calendario —797 turnos desde el 2025-05-06— y el desarrollo, 3188 turnos, se valida
con walk-forward de cinco pliegues y purga en la frontera.

El EDA ya dejó medido lo que condiciona el resultado, y conviene leerlo antes del código:

- **Regresión de `ley_au_gpT`.** La ley es el nivel del frente más ruido blanco: la media
  histórica del frente predice la ley del turno siguiente con R² de 0.9752 y el turno anterior
  con 0.9505. El baseline naive tiene que ser la media del frente, no el último valor, y ninguna
  feature de historia aporta información más allá de ese nivel.
- **Clasificación de falla a 4 horas.** El objetivo tal como lo define el enunciado no es
  predecible en este extracto: ninguna condición observable mueve la tasa base de 3.05%, y a
  nivel de turno la etiqueta es cero por construcción cuando el frente no registra en la
  ventana, con lo que anticipar la falla es anticipar si el frente sigue operando. La
  detección contemporánea sí funciona (22.7% de falla sobre 88 °C contra 3.3% de base). La
  discusión de métrica tiene que partir de ahí, y por eso se reporta también la precisión media
  condicionada a las ventanas con actividad.
- **Validación temporal, no aleatoria**, y la codificación por objetivo se ajusta solo con datos
  de entrenamiento. Cada pliegue se mide además contra su propio entrenamiento, y la brecha
  queda en MLflow.
- **`prod_estimada_oz` no entra como feature.** No es un sensor: es el objetivo despejado.
  Sobre el extracto, `prod_estimada_oz = ley_au_gpT × ton_rom_acum / 31.1035 × recuperación`,
  con factores de recuperación 0.10 en EST, 0.83 en MIX, 0.87 en OX y 0.91 en SUL, y
  desviación del orden de 5×10⁻⁶ en las cuatro. Como `ton_rom_acum` y `tipo_mineral` están en
  el mismo archivo, la ley se reconstruye con R² de 0.9999999998 y error máximo de
  5.3×10⁻⁴ g/t: el modelo no predeciría, invertiría una ecuación. El enunciado exige un bloque
  de respuesta explícito sobre esto en el notebook; sin él, el A-2 recibe cero puntos.
- **La ventana temporal se decide con cifras del propio experimento.** `splitter.py` implementa
  la expansiva y la deslizante bajo un mismo contrato, con bloques de validación idénticos, y las
  cinco variantes se comparan y quedan registradas en MLflow. La expansiva es la hipótesis por
  defecto y solo la desplaza una deslizante que la supere por más de la desviación entre
  pliegues; la ventana elegida gobierna también el reajuste final. El techo del problema es R²
  0.9757 y el baseline causal llega a 0.9753, así que el entregable demuestra dónde está el
  límite en lugar de fabricar una victoria del modelo.
- Falta por crear `modulo_b/`, que el enunciado lista en la estructura mínima; `modulo_c/`
  quedó completo con el C-1 y el C-2.

## Ejecutar en un entorno limpio

Requiere **Python 3.12** y el archivo `OP_AURUM_extract.csv`, que no se versiona.

En macOS hace falta además la runtime de OpenMP, que LightGBM necesita y no viaja dentro del
wheel; sin ella `import lightgbm` falla con `Library not loaded: @rpath/libomp.dylib`. En
Linux la provee el sistema y no hay paso adicional.

```bash
brew install libomp                # solo macOS
```

```bash
git clone <url-del-repositorio> && cd repositorio-ds-mine

python3.12 -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### El dataset

El extracto es dato operacional de negocio, no código: no entra a la historia de git. Copiá
el archivo en `data/`, que está en el `.gitignore`:

```bash
mkdir -p data && cp /ruta/a/OP_AURUM_extract.csv data/
```

El código lo busca en este orden, sin rutas absolutas escritas en ninguna parte:

1. la variable de entorno `AURUM_CSV_PATH`, si está definida;
2. `data/OP_AURUM_extract.csv` dentro del repositorio;
3. un directorio `insumos/` hermano del repositorio.

```bash
export AURUM_CSV_PATH=/otra/ruta/OP_AURUM_extract.csv   # opcional
```

### El registro de experimentos

MLflow 3.15 dejó el backend de archivos (`./mlruns`) en modo mantenimiento y lanza excepción
al usarlo, así que el seguimiento va contra SQLite: un archivo `mlflow.db` en la raíz, con los
artefactos anclados junto a la base en `mlartifacts/<experimento>/`. Los dos están en el
`.gitignore` porque son salida de una corrida y se regeneran ejecutando el notebook de
modelado; antes de reejecutarlo conviene borrarlos, para que el registro no acumule corridas de
dos ejecuciones.

```bash
export AURUM_MLFLOW_URI=sqlite:///mlflow.db   # valor por defecto, no hace falta definirlo
mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001
```

El puerto 5001 y no el 5000 por defecto: en macOS el receptor de AirPlay escucha en el 5000 y
responde en su lugar.

## Correr las verificaciones

Los tres comandos se ejecutan desde la raíz del repositorio y no necesitan el dataset: las
pruebas trabajan sobre datos sintéticos deterministas.

```bash
pytest          # pruebas y cobertura, con umbral mínimo del 80%
mypy            # tipado estático en modo estricto
ruff check .    # linter, incluido el código de los notebooks
```

## Levantar la API de inferencia

Necesita los modelos publicados en el Model Registry, que es lo que hace `modeling_demo.ipynb`
al ejecutarse. Sin ellos el servicio arranca igual: `/health` responde `sin_modelo` y
`/predict` devuelve 503.

```bash
uvicorn aurum_pipeline.serving.app:app --app-dir modulo_a --reload
```

```bash
curl -s localhost:8000/health
curl -s -X POST localhost:8000/predict -H 'content-type: application/json' -d '{
  "frente_id": "FR-S2-03", "turno_cod": "D1", "tipo_mineral": "OX",
  "ley_turno": 9.3, "ton_rom_acum": 120.0, "pres_hidraul_bar": 210.0,
  "rpm_corona": 1100.0, "avance_mmin": 1.6, "agua_iny_lmin": 52.0,
  "vibracion_rms_ms2": 14.0, "temp_motor_c": 97.0,
  "eventos_turno": 14, "minutos_inactivo_al_cierre": 12.0}'
```

Los valores de vibración y temperatura del ejemplo están **fuera del rango operacional del
diccionario y aun así responden 200**, con las alertas marcadas en la respuesta. Es
deliberado: esos rangos son alertas, no imposibles, y rechazarlos con 422 dejaría a la API
rechazando justo los turnos por los que alguien llama a preguntar. Solo lo físicamente
imposible —una presión negativa, una corona girando hacia atrás, más minutos de inactividad
que los que dura un turno— produce un 422.

Los rezagos de la ley y el resumen de actividad del turno —`minutos_inactivo_al_cierre`,
`temp_max_turno`, `eventos_temp_riesgo`, `vib_max_turno`, `eventos_vib_alerta`— son
opcionales. Sin los minutos de inactividad el clasificador de falla pierde su variable
principal; conviene enviarlos.

La documentación interactiva queda en `localhost:8000/docs`.

## Abrir los notebooks

```bash
jupyter lab modulo_a/exploration/eda_opus.ipynb          # análisis exploratorio
jupyter lab modulo_a/aurum_pipeline/pipeline_demo.ipynb  # A-1, el pipeline
jupyter lab modulo_a/aurum_pipeline/modeling_demo.ipynb  # A-2, el modelado
```

Los tres están versionados **con sus salidas ejecutadas**: se pueden leer completos, sin
ejecutarlos y sin tener el dataset a mano. El del EDA empieza con una tabla de síntesis
enlazada a la sección de cada variable; el del modelado empieza con la respuesta obligatoria
sobre `prod_estimada_oz`.

Para regenerarlos desde cero:

```bash
jupyter nbconvert --to notebook --execute --inplace modulo_a/exploration/eda_opus.ipynb
jupyter nbconvert --to notebook --execute --inplace modulo_a/aurum_pipeline/modeling_demo.ipynb
```

`modeling_demo.ipynb` entrena todo el experimento: cuatro conjuntos de variables por dos
modelos —y en clasificación con y sin peso de clase— en la fase A, y cinco estrategias de
ventana por dos modelos por dos problemas en la fase B, con búsqueda aleatoria de veinte
configuraciones anidada en cada una. Tarda **unos 30 minutos** medidos en un Mac con
M-series, y deja 86 corridas padre con sus 395 hijas repartidas en dos experimentos de `mlflow.db`.

## Estructura

```
repositorio-ds-mine/
├── README.md
├── diario_decisiones.md          decisiones propias: consideré X pero elegí Y porque Z
├── ia_usage.md                   transcripción literal del uso de IA
├── CLAUDE.md                     reglas de trabajo del repositorio
├── pyproject.toml                configuración de pytest, mypy y ruff (no empaqueta)
├── requirements.txt
├── data/                         el extracto, ignorado por git
├── docs/
│   ├── diccionario_variables.md  diccionario transcrito y análisis conceptual
│   ├── tabla_resultado.md        las 30 columnas de salida: unidades, lectura y advertencias
│   └── modelado.md               decisiones del A-2 y la medición que las sostiene
├── modulo_a/
    ├── exploration/
    │   └── eda_opus.ipynb        análisis exploratorio, una sección por variable
    └── aurum_pipeline/
        ├── domain.py             constantes del dominio operacional
        ├── errors.py             excepciones propias
        ├── transformers/         A-1: los cuatro transformadores
        │   ├── base.py           AurumTransformer (clase abstracta)
        │   ├── imputer.py        AurumImputer
        │   ├── encoder.py        AurumShiftEncoder
        │   └── features.py       AurumFeatureBuilder
        ├── modeling/             A-2: modelado
        │   ├── dataset.py        matriz supervisada por turno y su objetivo
        │   ├── falla.py          etiqueta de falla en las próximas 4 horas
        │   ├── splitter.py       partición temporal, purga y las dos ventanas
        │   ├── features.py       conjuntos de variables y codificación del frente
        │   ├── baselines.py      los cinco baselines: dos de ley, tres de falla
        │   ├── models.py         LightGBM y XGBoost bajo un contrato común
        │   ├── classifiers.py    los mismos, para la falla, con el peso de clase medido
        │   ├── metrics.py        métricas de ambos problemas y su lectura
        │   ├── evaluacion.py     evaluación por pliegues, brecha y búsqueda aleatoria
        │   ├── tracking.py       MLflow: corridas, artefactos y registry
        │   ├── explain.py        valores SHAP del modelo de ley
        │   └── experimento.py    las tres fases, para los dos problemas
        ├── serving/              A-2: la API de inferencia
        │   ├── schemas.py        contratos Pydantic con los rangos del diccionario
        │   ├── predictor.py      carga desde el registry, sin HTTP adentro
        │   └── app.py            FastAPI: /predict y /health
        ├── tests/                pruebas con pytest, sin dependencia del dataset
        ├── pipeline_demo.ipynb   A-1: demo end-to-end
        └── modeling_demo.ipynb   A-2: modelado, con la respuesta obligatoria
└── modulo_c/
    ├── decisiones_arquitectura.md  plataforma, gobernanza, costos y riesgos del C-1
    ├── arquitectura.png            diagrama de fuentes a consumo
    ├── ingesta_edge.png            camino del dato bajo conectividad intermitente
    ├── costos.py                   modelo de costos, solo biblioteca estándar
    ├── tests/                      fija las cifras que publica el documento
    └── rag_minero/                 asistente RAG del C-2
        ├── README.md               respuestas a las cinco preguntas, con las métricas
        ├── documentos.py, chunking.py, guardrails.py, indice.py, asistente.py, evaluacion.py, flujo.py
        ├── golden_set.json, preguntas_control.json
        ├── rag_demo.ipynb          demo ejecutada contra Databricks Vector Search
        └── tests/                  168 pruebas sobre documentos sintéticos
```

`modeling/` y `serving/` son paquetes separados por una razón de dependencias, no de orden:
la lógica de predicción tiene que poder probarse sin levantar un servidor HTTP, y el paquete
de modelado no debe arrastrar FastAPI para entrenar. La frontera es `predictor.py`, que no
conoce a FastAPI, contra `app.py`, que no conoce a LightGBM.

## Decisiones que conviene conocer antes de leer el código

- **Sin Clean Architecture.** Estructura plana de paquetes. Es un entregable acotado y quien
  lo evalúa tiene que poder leerlo completo; la indirección de puertos y adaptadores sobre
  cuatro transformadores agregaría archivos sin agregar capacidad de cambio.
- **El extracto es sintético.** El EDA demuestra que el archivo es un flujo estrictamente
  serial —ningún par de registros comparte instante, la cadencia global es uniforme entre 15
  y 34 minutos— lo que es incompatible con diez perforadoras trabajando en paralelo. Se
  adopta el supuesto de que `equipo_id` y `op_id` son etiquetas repartidas sobre un flujo
  único y no admiten lectura causal. Está documentado en la sección 2 del notebook.
- **La salida del pipeline está documentada columna por columna** en
  [`docs/tabla_resultado.md`](docs/tabla_resultado.md): unidad, interpretación, rango observado
  y las quince advertencias que hay que conocer antes de usar cualquiera de los 30 campos.
- **`flag_imputed` marca lo que NO se pudo imputar.** Sigue la letra del enunciado: es `True`
  en las filas cuyo centinela de ley no se pudo reconstruir porque la ventana de siete días del
  mismo frente y tipo de mineral tenía menos de cinco lecturas, y esas filas quedan con la ley
  en `NaN`. Las filas que sí se reconstruyeron no llevan columna propia: quedan en
  `AurumImputer.filas_imputadas_`.
- **pandas queda en la serie 2.x.** MLflow 3.15 declara `pandas<3` y es la única restricción
  dura del entorno; el proyecto venía en pandas 3.0.5 y bajó a 2.3.3. El A-1 se reverificó
  bajo el pin nuevo: 61 pruebas, cobertura 100%, mypy y ruff limpios, y los dos notebooks se
  ejecutan sin errores. numpy queda en 2.4.6 y no en 2.5, porque la combinación con pandas
  2.3.3 emite miles de avisos de deprecación sobre unidades de `timedelta`.
- **Los nombres de columna no se cambian**, por restricción del enunciado. Las columnas
  nuevas se agregan; las originales se conservan tal cual.
