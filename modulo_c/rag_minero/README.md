# Asistente RAG sobre documentación técnica minera (Ejercicio C-2)

Respuestas a las cinco preguntas del enunciado, con la medición que sostiene cada una. Las
cifras salen de [`rag_demo.ipynb`](rag_demo.ipynb), que se entrega ejecutado, y de
[`resultados/resultados.json`](resultados/resultados.json), que el notebook escribe al cerrar.

```
rag_minero/
├── documentos.py         lector de PDF: elementos tipados, tablas partidas fusionadas, códigos unidos
├── chunking.py           tres estrategias por género + dos de control para la ablación
├── guardrails.py         puerta de dominio calibrada + verificador determinista de hechos
├── indice.py             Databricks Vector Search (destino) y Chroma + BM25 (local), ambos híbridos
├── asistente.py          cadena LangChain: recuperación, generación con citas, verificación, presupuesto
├── evaluacion.py         golden set, ablación sin modelo y RAGAS
├── flujo.py              orquestación de la demo: lo gratis primero, lo que cuesta al final
├── golden_set.json       10 preguntas con respuesta esperada y pasajes de referencia, validadas
├── preguntas_control.json 10 fuera de dominio + 3 del dominio sin respaldo documental
├── flujo_usuario.png     diagrama del camino de una pregunta
├── roles_y_acceso.png    diagrama de roles, documentos y clasificación
├── rag_demo.ipynb        demo ejecutada
├── resultados/           salida de la demo en JSON
└── tests/                pruebas sobre documentos sintéticos; integración sobre los PDF reales
```

## Cómo ejecutar

Entorno propio, separado del Módulo A mientras el A-2 corre en paralelo:

```bash
python3.12 -m venv .venv-rag && source .venv-rag/bin/activate
pip install -r modulo_c/rag_minero/requirements.txt
export RAG_PDF_DIR=/ruta/a/los/tres/pdf        # PET-PERF-007, INFORME-GEO-VETA-SUR-2024, MANUAL-ATLAS-COPCO-L8
```

Pruebas, tipos y linter, sin red ni credenciales:

```bash
python -m pytest modulo_c/rag_minero -o addopts="" --cov=rag_minero --cov-fail-under=80
python -m mypy modulo_c/rag_minero
python -m ruff check modulo_c/rag_minero
```

Con `RAG_PDF_DIR` definido, las pruebas marcadas `integracion` leen los PDF reales y fijan el
inventario de cada documento (por ejemplo, que el manual tiene cinco tablas de 16, 3, 7, 5 y 6
filas); sin la variable se saltan.

La demo necesita un workspace de Databricks autenticado con la CLI (`databricks auth login`)
y estas variables:

| Variable | Uso |
|---|---|
| `DATABRICKS_CONFIG_PROFILE` | perfil de la CLI |
| `RAG_ALMACEN` | `databricks` (Vector Search) o `local` (Chroma + BM25 con los mismos embeddings) |
| `RAG_CATALOG`, `RAG_SCHEMA`, `RAG_WAREHOUSE_ID`, `RAG_VS_ENDPOINT` | dónde vive la tabla de chunks y el índice |
| `RAG_MODELO_GENERADOR`, `RAG_MODELO_JUEZ`, `RAG_MODELO_EMBEDDINGS` | endpoints de Foundation Model APIs |
| `RAG_TOKENS_MAXIMOS` | tope de tokens de la sesión; el asistente se niega a llamar si lo superaría |

```bash
cd modulo_c/rag_minero && jupyter nbconvert --to notebook --execute --inplace rag_demo.ipynb
```

## 1. Chunking justificado por tipo de documento

**El género decide qué elementos existen; el tipo de elemento decide la unidad de
recuperación.** Un extractor de texto plano no ve ni lo uno ni lo otro, así que el lector
devuelve elementos tipados —encabezado, prosa, paso, tabla, advertencia— y resuelve antes dos
defectos de los PDF reales: la mayoría de las tablas cruzan una página (cabecera en una, filas
en la siguiente) y se fusionan por continuidad, y los códigos partidos dentro de la celda
(`AC-L8-HM-472` / `1`) se unen con una regla declarada y probada.

| Documento | Cómo está construido | Cómo pregunta quien lo usa | Unidad de chunk |
|---|---|---|---|
| PET-PERF-007 | pasos numerados y tablas con código de fila (PT-01..06, CP-01..06) | «¿qué hago si...?» | un paso, o una fila con su código, rendida como frase con la sección delante |
| INFORME-GEO-VETA-SUR-2024 | prosa larga, tabla de ensayos con fila TOTAL, referencias cruzadas entre secciones | compara y cruza | prosa por sección con solapamiento; la tabla entera; cada chunk etiquetado con los frentes que menciona |
| MANUAL-ATLAS-COPCO-L8 | specs, tabla de fallas, sensores, repuestos, una advertencia | un hecho por código | una fila por chunk («Presión hidráulica máxima — Especificación: 280; Unidad: bar; ...»); la advertencia indivisible y con prioridad |

Trocear una fila del PET separa la condición de la acción; trocear la tabla del informe por
filas mata la pregunta comparativa; trocear la advertencia del manual separa «-1 es
centinela» de «no es ley cero». Cada estrategia evita exactamente el error de su género.

**La decisión se midió, no se argumentó.** La ablación corre el golden set contra tres
variantes —la propuesta, una que solo respeta el género cortando por sección, y la línea base
de tamaño fijo con solapamiento— y mide, sin ningún modelo juez, si los pasajes de referencia
aparecen entre los seis chunks recuperados (precisión de contexto con la fórmula sin LLM de
RAGAS, y recall de referencias). Embeddings reales de `qwen3-embedding-0-6b`:

{{ABLACION}}

Chunks por variante: {{CHUNKS}}.

La propuesta gana donde la unidad es la fila (PET, manual) y empata o gana por poco donde la
unidad es la sección (informe). La línea base pierde recall en el PET porque parte una fila de
criterio de parada en dos chunks.

## 2. Vector store: Databricks Vector Search, con Chroma como respaldo local

| Criterio | Chroma | Qdrant (local) | Azure AI Search | Databricks Vector Search |
|---|---|---|---|---|
| Corre sin workspace | sí | sí | no | no |
| Híbrido léxico + denso | no nativo; BM25 al lado | sí, vectores dispersos | sí | sí, fusión recíproca de rangos en el motor |
| Filtros por metadatos | sí | sí | sí | por cualquier columna de la tabla Delta |
| Paridad con la producción del C-1 | ninguna | ninguna | es el servicio de Fabric | es la plataforma elegida |
| Embeddings | externos | externos | externos o integrados | gestionados por el índice Delta Sync |
| Gobierno | ninguno | ninguno | RBAC de Azure | Unity Catalog: la tabla de chunks hereda la clasificación del documento |

El C-1 eligió Databricks como plataforma de datos y modelos, y el asistente debe vivir donde
viven los documentos y el catálogo que gobierna su clasificación; Azure AI Search sería la
respuesta si el C-1 hubiera elegido Fabric puro. Lo portable entre almacenes no es el índice
sino **la tabla de chunks con sus metadatos**: en Databricks es una tabla Delta con Change
Data Feed sobre la que el índice Delta Sync calcula los embeddings; en local la misma lista
alimenta a Chroma y a BM25, fusionados con el mismo algoritmo de rangos recíprocos que usa
Databricks. Cambiar de almacén es cambiar un adaptador de cuarenta líneas; los dos implementan
`AlmacenVectorial` y las pruebas corren sobre el local.

Por qué híbrido y no solo denso: en mina se pregunta por código —`H-HIDRA-02`,
`AC-L8-BP-2241`, `FR-S2-03`— y los embeddings densos son malos con alfanuméricos. BM25 los
encuentra exactos; la fusión hace que la consulta «H-HIDRA-05» traiga la fila de diagnóstico
primero y la pregunta en lenguaje natural traiga la fila de especificación.

Costo: el endpoint de Vector Search se factura por hora (0.28 USD, unidad estándar) desde que
existe un índice, por eso `AlmacenDatabricks` no lo crea por su cuenta: `crear_endpoint` y
`borrar_endpoint` son llamadas explícitas y el flujo las ejecuta dentro de la misma sesión.

## 3. Evaluación RAGAS

Golden set de diez preguntas con respuesta esperada y pasajes literales de referencia,
validadas una por una: tres por documento y una cruzada entre el PET y el manual (el
centinela `ley_au_gpT = -1`, donde los dos documentos discrepan en el umbral: «2 turnos» contra
«2 registros consecutivos», y la respuesta esperada lo dice). Métricas de RAGAS 0.4:
`faithfulness` (la respuesta se sostiene en los pasajes), `answer_relevancy` (atiende la
pregunta) y `context_precision` con referencia (los pasajes recuperados son los que la
respuesta esperada necesita).

{{RAGAS_TABLA}}

Medias: {{RAGAS_RESUMEN}}.

**Modelos de esta corrida.** El workspace de prueba mantiene los modelos propietarios
(Claude, GPT, Gemini) apagados con un límite de tasa cero, restricción de nivel de cuenta que
no se corrige desde la configuración del endpoint. La corrida usa `{{GENERADOR}}` como
generador y `{{JUEZ}}` como juez. Tiene una consecuencia favorable: generador y juez son de
familias distintas, así que no hay sesgo de autoevaluación. Volver a Claude Sonnet 5, que era
la elección original, es cambiar dos variables de entorno.

**Lectura de las métricas.** `faithfulness` alto es lo esperable de un asistente que solo
responde con pasajes y que además pasa por un verificador de hechos: una cifra sin respaldo no
llega a evaluarse, se bloquea antes. `answer_relevancy` es la métrica más baja: RAGAS la mide
generando preguntas a partir de la respuesta y comparándolas por embedding con la original, y
penaliza respuestas que contestan más de lo preguntado, como la de pet-01, que junta el
criterio del PET con la intervención del manual porque así se validó la respuesta esperada.
`context_precision` baja donde la pregunta se responde con una nota al pie (geo-02) y el
recuperador trae antes la tabla de ensayos que la nota.

## 4. Guardrails: dos mecanismos deterministas

Ninguno llama a un modelo, por dos razones: un guardrail que depende de un LLM no se puede
probar con una prueba unitaria ni calibrar sin gastar tokens, y el mecanismo que impide
inventar una especificación no puede ser del mismo tipo que el componente que la inventa.

**Puerta de dominio.** Fracción de los términos de contenido de la pregunta que existe en el
corpus indexado. El umbral no se fija a mano: se deriva del golden set y de diez preguntas
fuera de dominio, y se reporta cuántas de cada lado quedan del lado correcto. Sobre los PDF
reales: umbral {{UMBRAL}}, {{DOMINIO}} del golden set aceptadas y {{FUERA}} fuera de dominio
rechazadas. Un segundo criterio, el score del mejor chunk recuperado, protege contra preguntas
con vocabulario minero que no tienen pasaje.

**Verificador de hechos.** Toda cifra con unidad y todo código alfanumérico de la respuesta
debe existir en los pasajes recuperados; si no, la respuesta se bloquea, se conserva el
borrador para auditoría y se nombra el hecho sin respaldo. Es el «no inventa especificaciones
técnicas» convertido en una regla que una prueba reproduce: la pregunta por la presión máxima
de la Sandvik DL432, que el manual no cubre, produce una negativa honesta o una respuesta
bloqueada, nunca una cifra plausible.

Resultado de las trece preguntas de control en la corrida:

{{CONTROL}}

El verificador encontró además un defecto propio durante la corrida de prueba: leía el `022`
de una cita `[PET-PERF-007#procedimiento#022]` como una cifra sin respaldo y bloqueaba las
diez respuestas. Quedó corregido con una prueba que lo reproduce.

## 5. Escalar a los 800+ documentos reales

Lo que cambia en la indexación, en orden de importancia:

1. **La clasificación de género se automatiza.** Hoy el género sale del código del documento
   (`PET-`, `IGE-`, `MAN-`). Con 800 documentos hace falta un enrutador por primera página
   —código, título, tamaño de fuente del recuadro— con una estrategia de respaldo (la de
   sección) para lo que no reconozca, y una alerta cuando el respaldo supere una fracción del
   lote.
2. **La vigencia es un filtro por defecto.** El PET Rev. 4 sustituye a la Rev. 3; un
   procedimiento obsoleto recuperado es un riesgo de seguridad, no un error de precisión. Cada
   chunk lleva `version` y `vigente`; al ingerir una revisión nueva, la anterior queda
   `vigente=false` y solo se consulta a propósito.
3. **OCR.** El propio PET dice que los formularios físicos se escanean al repositorio
   documental. Con 800 documentos el lector local de `pdfplumber` se reemplaza por
   `ai_parse_document` de Databricks, que devuelve tablas con estructura y cubre escaneos.
4. **Ingesta incremental sobre Delta.** La tabla de chunks pasa a alimentarse por lotes con
   hash del documento, y el índice Delta Sync se sincroniza solo con lo que cambió. Indexar
   los 800 documentos completos cuesta alrededor de un dólar de embeddings (calculado en el
   C-1); lo que cuesta es el endpoint por hora y las horas humanas del golden set.
5. **Clasificación ligada al catálogo.** El informe CONFIDENCIAL ya viaja como metadato de cada
   chunk; en producción ese metadato es una fila de Unity Catalog y el filtro de recuperación
   lo impone la identidad del usuario, no el prompt. Es el enlace con la sección 6 del C-1.
6. **El golden set se vuelve regresión.** Estratificado por género, con casos nuevos por cada
   tipo de documento que entra, y ejecutado en cada reindexado; la ablación de chunking corre
   con él porque no cuesta tokens.

## Consumo de la corrida

{{TOKENS}}

## Límites que se declaran

- `answer_relevancy` depende de embeddings y de un juez que genera preguntas en español; con
  un modelo abierto es más ruidosa que con el juez previsto.
- El verificador compara cifras y códigos, no afirmaciones cualitativas: una respuesta que
  invierta una causa y un efecto sin cambiar ninguna cifra pasa el filtro y solo la detecta
  `faithfulness`.
- La puerta de dominio es léxica: una pregunta minera en inglés tendría cobertura baja y se
  rechazaría. El corpus es en español y el asistente también.
