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
| A-2 · Modelado, MLflow, SHAP y API | pendiente |
| Módulo B · Lakehouse y MLOps | pendiente |
| C-1 · Arquitectura de plataforma | completo — `modulo_c/decisiones_arquitectura.md` |
| C-2 · RAG sobre documentación técnica | completo — `modulo_c/rag_minero/README.md`, demo ejecutada |

## Próximo paso: Ejercicio A-2

El A-1 está cerrado. Lo que sigue es el modelado, y el EDA ya dejó medido lo que lo condiciona;
conviene leer esto antes de escribir la primera línea:

- **Regresión de `ley_au_gpT`.** La ley es el nivel del frente más ruido blanco: la media
  histórica del frente predice la ley del turno siguiente con R² de 0.9752 y el turno anterior
  con 0.9505. El baseline naive tiene que ser la media del frente, no el último valor, y ninguna
  feature de historia aporta información más allá de ese nivel.
- **Clasificación de falla a 4 horas.** El objetivo tal como lo define el enunciado no es
  predecible en este extracto: ninguna condición observable mueve la tasa base de 3.05%. La
  detección contemporánea sí funciona (22.7% de falla sobre 88 °C contra 3.3% de base). La
  discusión de métrica tiene que partir de ahí.
- **Validación temporal, no aleatoria**, y la codificación por objetivo se ajusta solo con datos
  de entrenamiento.
- **`prod_estimada_oz` no entra como feature**, y el enunciado exige un bloque de respuesta
  explícito sobre por qué; sin él, el A-2 recibe cero puntos.
- Faltan por crear `modulo_b/` y `modulo_c/`, que el enunciado lista en la estructura mínima.

## Ejecutar en un entorno limpio

Requiere **Python 3.12** y el archivo `OP_AURUM_extract.csv`, que no se versiona.

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

## Correr las verificaciones

Los tres comandos se ejecutan desde la raíz del repositorio y no necesitan el dataset: las
pruebas trabajan sobre datos sintéticos deterministas.

```bash
pytest          # pruebas y cobertura, con umbral mínimo del 80%
mypy            # tipado estático en modo estricto
ruff check .    # linter, incluido el código de los notebooks
```

## Abrir el análisis exploratorio

```bash
jupyter lab modulo_a/exploration/eda_opus.ipynb
```

El notebook está versionado **con sus salidas ejecutadas**: se puede leer completo, con sus
35 figuras, sin ejecutarlo y sin tener el dataset a mano. Empieza con una tabla de síntesis
enlazada a la sección de cada variable.

Para regenerarlo desde cero:

```bash
jupyter nbconvert --to notebook --execute --inplace modulo_a/exploration/eda_opus.ipynb
```

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
│   └── tabla_resultado.md        las 30 columnas de salida: unidades, lectura y advertencias
└── modulo_a/
    ├── exploration/
    │   └── eda_opus.ipynb        análisis exploratorio, una sección por variable
    └── aurum_pipeline/
        ├── domain.py             constantes del dominio operacional
        ├── errors.py             excepciones propias
        ├── transformers/
        │   ├── base.py           AurumTransformer (clase abstracta)
        │   ├── imputer.py        AurumImputer
        │   ├── encoder.py        AurumShiftEncoder
        │   └── features.py       AurumFeatureBuilder
        ├── tests/                pruebas con pytest, sin dependencia del dataset
        └── pipeline_demo.ipynb   demo end-to-end (pendiente)
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
        └── tests/                  155 pruebas sobre documentos sintéticos
```

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
- **Los nombres de columna no se cambian**, por restricción del enunciado. Las columnas
  nuevas se agregan; las originales se conservan tal cual.
