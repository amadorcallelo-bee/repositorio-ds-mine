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
| B-1 · Lakehouse medallion en Databricks | completo — `modulo_b/`, [`docs/lakehouse.md`](docs/lakehouse.md) |
| B-2 · Fabric y orquestación | pendiente |
| B-3 · MLOps y re-entrenamiento | pendiente |
| C-1 · Arquitectura de plataforma | completo — `modulo_c/decisiones_arquitectura.md` |
| C-2 · RAG sobre documentación técnica | pendiente |

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

## Resultado del Ejercicio B-1

En una línea cada uno, con el detalle y las cifras en [`docs/lakehouse.md`](docs/lakehouse.md):

- **Bronze ingiere con esquema explícito y llegada incremental.** Auto Loader lee los CSV del
  volumen de landing con las 18 columnas tipadas del diccionario, un archivo por microlote, y
  deja en `ingesta_log` archivo fuente, instante y conteo. Partición por `fecha_ingesta`,
  justificada por operación y no por rendimiento.
- **Silver aplica el diccionario como reglas.** Hora local `America/Lima`, turno recalculado
  desde la hora (cero discrepancias en 50 000 filas), centinela a nulo sin imputar, alertas
  que se marcan y físicamente imposibles que van a cuarentena, `MERGE` idempotente y reporte
  de calidad por lote en una tabla. Partición por `anio_mes`, porque las consultas y el CDC
  van por rango de fecha.
- **Gold materializa `aurum_kpi_turno`** por frente, fecha local y turno: ley ponderada por
  tonelaje, eficiencia de avance contra el 3.5 m/min del manual, tasa de fallas y horas
  efectivas. Sin partición, con `ZORDER BY (frente_id, fecha_local)` argumentado por las
  consultas del B-2.
- **El CDC es incremental de verdad.** Tres lotes del laboratorio actualizan 120 eventos con
  `MERGE` (los reenvíos no escriben, las claves inexistentes se reportan) y gold recalcula
  desde el Change Data Feed solo las 98 celdas afectadas de 4 019. Una segunda corrida del
  job no ingiere, no limpia y no recalcula nada.

## Ejecutar en un entorno limpio

Requiere **Python 3.12** y el archivo `OP_AURUM_extract.csv`, que no se versiona.

```bash
git clone <url-del-repositorio> && cd repositorio-ds-mine

python3.12 -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

El Módulo B prueba su lógica sobre Spark en local, y Spark necesita una JVM: en macOS
`brew install openjdk@21` (las pruebas la encuentran solas en la ruta de Homebrew); en Linux,
el `openjdk-21-jdk` del sistema o `JAVA_HOME` definido. La primera sesión descarga los jars de
Delta una sola vez.

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

Las pruebas del Módulo B levantan una sesión de Spark local y tardan unos tres minutos; el
resto corre en segundos.

## Correr el lakehouse en Databricks

Todo va por la CLI de Databricks: ningún paso exige abrir la interfaz. Requiere un perfil
configurado (`databricks configure`) con un workspace que tenga Unity Catalog y serverless.

```bash
export DATABRICKS_CONFIG_PROFILE=<perfil>
export CATALOGO=lakehouse_umlc      # creado desde la interfaz: con Default Storage la API no puede

# 1. Lotes de llegada y de corrección, generados de forma determinista desde el extracto
PYTHONPATH=modulo_b python -m umlc_lakehouse.simulacion --csv data/OP_AURUM_extract.csv --salida data/lotes

# 2. Esquemas y volumen de landing (llamadas a la API, sin cómputo)
for e in bronze silver gold dq_reports; do databricks schemas create $e $CATALOGO; done
databricks volumes create $CATALOGO bronze landing MANAGED
databricks fs cp -r data/lotes/opus dbfs:/Volumes/$CATALOGO/bronze/landing/opus
databricks fs cp -r data/lotes/reclasificacion dbfs:/Volumes/$CATALOGO/bronze/landing/reclasificacion

# 3. Despliegue y ejecución del job de cinco tareas en serverless
cd modulo_b
databricks bundle deploy --var="catalogo=$CATALOGO"
databricks bundle run lakehouse_umlc_b1 --var="catalogo=$CATALOGO"
```

`bundle run` imprime el resumen JSON con que termina cada notebook: filas por lote, versiones
Delta, reporte de calidad, correcciones aplicadas y celdas de gold recalculadas. Una segunda
ejecución no ingiere ni recalcula nada: es la prueba de idempotencia.

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
│   ├── tabla_resultado.md        las 30 columnas de salida: unidades, lectura y advertencias
│   └── lakehouse.md              decisiones del B-1 y las cifras de la corrida que las sostienen
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
├── modulo_b/
│   ├── databricks.yml            Asset Bundle: tres notebooks y el job serverless de cinco tareas
│   ├── 01_bronze.py              Auto Loader con esquema explícito, metadata e ingesta_log
│   ├── 02_silver.py              limpieza por diccionario, reporte DQ por lote y CDC del laboratorio
│   ├── 03_gold.py                aurum_kpi_turno, Z-ORDER e incremental por Change Data Feed
│   ├── lakehouse_umlc.png        diagrama del lakehouse (fuente: lakehouse_umlc.eraser)
│   └── umlc_lakehouse/           la lógica, probada en local sobre Spark
│       ├── dominio.py            reglas del dominio y nombres del lakehouse
│       ├── catalogo.py           catálogo, esquemas y tablas calificados
│       ├── esquema.py            esquema explícito del extracto y lector de CSV sin inferencia
│       ├── ingesta.py            IngestorBronze: metadata, log de ingesta y libros de control
│       ├── limpieza.py           LimpiadorSilver y TablaSilver: reglas, hora local y MERGE
│       ├── calidad.py            ReglaCalidad y ReporteCalidad: el reporte por lote
│       ├── kpi.py                ConstructorKpiTurno: las fórmulas de gold
│       ├── gold.py               ActualizadorGold: carga completa, Z-ORDER e incremental
│       ├── cdc.py                AplicadorReclasificacion: el MERGE de las correcciones
│       ├── simulacion.py         lotes de llegada y de corrección desde el extracto
│       └── tests/                pruebas sobre Spark local con datos sintéticos
└── modulo_c/
    ├── decisiones_arquitectura.md  plataforma, gobernanza, costos y riesgos del C-1
    ├── arquitectura.png            diagrama de fuentes a consumo
    ├── ingesta_edge.png            camino del dato bajo conectividad intermitente
    ├── costos.py                   modelo de costos, solo biblioteca estándar
    ├── tests/                      fija las cifras que publica el documento
    └── rag_minero/                 reservado para el C-2
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
