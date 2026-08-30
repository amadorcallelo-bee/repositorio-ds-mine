# Reglas de trabajo — repositorio-ds-mine

Prevalecen sobre las instrucciones globales de `~/.claude/CLAUDE.md` en lo que
las contradigan.

## 1. Respuestas

Concisión estricta. Entrega el resultado, no el camino. Sin preámbulos, sin
resumir lo que vas a hacer ni recapitular lo hecho. Si el código se explica
solo, no lo narres. Extenderte solo se justifica en un diagnóstico de causa
raíz o en un riesgo que debo conocer.

## 2. Aprobación y ritmo

- Es muy importante que para hacer ajustes o escrituras de código debes tener
  mi aprobación explícita.
- No avances de fase sin que yo te lo indique.
- Ante una tarea nueva: primero la propuesta de lo que crearás, luego esperas
  aprobación, y solo entonces implementas.
- Trabaja únicamente sobre el módulo que yo haya habilitado. No toques los
  demás módulos aunque el enunciado los mencione.

## 3. Contexto de la prueba

Prueba técnica de científico de datos senior para una empresa minera
(DS-MINE-2025-v2). El uso de IA está permitido y debe quedar declarado.

- Enunciado e insumos: `../insumos/`, instrucciones en
  `prueba_candidato_DS_MINE_2025.docx`.
- Repositorio en GitHub bajo la cuenta `amadorcallelo@beeanalytics.com.co`:
  `amadorcallelo-bee/repositorio-ds-mine`.
- El dataset no se versiona; la ruta se resuelve por `AURUM_CSV_PATH`.

## 4. Arquitectura

Sin Clean Architecture. Estructura plana de paquetes Python. Nada de
sobreingeniería: es un entregable acotado que el evaluador debe leer completo
en pocos minutos. Aplican las prácticas de la skill `repositorios` para ramas,
commits y PR.

## 5. Archivos de trazabilidad (raíz)

- `diario_decisiones.md`: **las decisiones de Amador, no las tuyas.** Se escribe
  en primera persona con Amador como sujeto, en formato "consideré X pero elegí
  Y porque Z", en orden cronológico. Nunca registres ahí una decisión tuya como
  si fuera suya, ni redactes en primera persona acciones que ejecutaste tú.
  Cuando la opción la propusiste tú, dilo explícitamente y registra la
  resolución de Amador sobre esa propuesta. Si algo que hiciste no corresponde
  a una decisión que él tomó o ratificó, no va en este archivo: va en
  `ia_usage.md`, o se lo consultas.
- `ia_usage.md`: transcripción literal de la conversación con la herramienta,
  sin edición ni resumen, indicando entre paréntesis las acciones que ejecutaste.
  Es el único lugar donde queda constancia de lo que hizo la herramienta.

Ambos se actualizan a medida que avanza el trabajo, no al final, sin preguntar:
es documentación, no un cambio de código.
