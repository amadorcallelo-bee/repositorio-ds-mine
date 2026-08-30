# Diario de decisiones

Bitácora de las decisiones que tomé durante el desarrollo de la prueba DS-MINE-2025-v2.
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

- **Ubicación de `tests/` y `pipeline_demo.ipynb`.** El enunciado se contradice: el árbol
  general de la Sección 1 los cuelga de `modulo_a/`, mientras que el Ejercicio A-1 los pone
  dentro de `aurum_pipeline/`. Consideré seguir el árbol general por ser el "mínimo
  obligatorio", pero elegí la estructura del A-1 porque es la especificación más específica
  y más cercana al ejercicio que se está evaluando; ante dos instrucciones en conflicto, la
  particular manda sobre la general. Dejo constancia aquí para que la diferencia frente al
  árbol de la Sección 1 se lea como una decisión y no como un descuido.

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

- **Declaración de IA en la historia de git.** Consideré dejar los commits sin marca y
  concentrar la declaración en `ia_usage.md`, pero elegí agregar el trailer
  `Co-Authored-By` en cada commit donde haya intervenido Claude porque así la trazabilidad
  queda en el mismo lugar donde vive el código y no depende de que alguien abra un archivo
  aparte. Declarar de más no me quita puntos; declarar de menos, sí.

- **Modelo de ramas.** Consideré trabajar todo directo sobre `main` por ser un proyecto de
  un solo autor y 48 horas, pero elegí ramas cortas de feature integradas con merge commit
  porque la historia del repositorio también se evalúa: quiero que cada módulo entre como
  una unidad revisable y que se vea el orden en que se construyó. La excepción es este
  commit de arranque, que va directo a `main` por ser el bootstrap del repositorio, cuando
  todavía no hay nada de qué ramificarse.
