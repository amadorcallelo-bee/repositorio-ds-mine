# MLOps del Módulo B (Ejercicio B-3)

Monitor de deriva, trigger de re-entrenamiento y promoción con rollback, sobre el modelo
real del A-2. Las cifras salen de la corrida del job `lakehouse_umlc_mlops`
(run `488960626879075`, 2026-08-30, serverless, 11 min 33 s) y de las pruebas locales.

## 1. Monitor de deriva (PSI)

- **Variables**: `ley_au_gpT` (solo lecturas con `ley_valida`: el centinela de la sonda ya es
  nulo en silver, y dejarlo entrar haría que una sonda caída parezca deriva geológica) y
  `vibracion_rms_ms2`, como nombra el enunciado.
- **Ventanas**: "los últimos 30 días como referencia" se lee como referencia = los 30 días
  anteriores a una ventana de evaluación de 7. Se vigila el proceso, no al modelo: anclar la
  referencia al entrenamiento respondería otra pregunta. En la corrida: referencia
  2025-09-22 a 2025-10-21, evaluación 2025-10-22 a 2025-10-28.
- **Método**: bins por deciles de la referencia, proporciones acotadas con un épsilon antes
  del logaritmo, cálculo exacto en numpy (miles de filas, no millones) y umbrales de la
  convención que usa el propio enunciado: < 0.1 estable, 0.1–0.2 moderado, > 0.2 crítico.
  El PSI de dos bins está reproducido a mano en las pruebas.
- **Persistencia**: `dq_reports.monitor_deriva`, una fila por variable y ámbito con las
  ventanas, los conteos y el detalle de bins en JSON.

**Resultado real: la ley sí deriva al final del extracto.**

| Variable | Ámbito | PSI | Veredicto | n ref | n actual |
|---|---|---|---|---|---|
| ley_au_gpT | global | 0.9875 | crítico | 1 684 | 333 |
| ley_au_gpT | Veta-Principal | 8.9246 | crítico | 355 | 3 |
| ley_au_gpT | Veta-Sur | 1.6780 | crítico | 686 | 100 |
| ley_au_gpT | Rampa-Norte | 0.8269 | crítico | 524 | 230 |
| vibracion_rms_ms2 | global | 0.0355 | estable | 1 772 | 361 |

El desglose por sector —que existe exactamente para esto— muestra que el PSI global de la
ley no es deriva del proceso de medición sino **mezcla de frentes**: en la última semana
Veta-Principal casi se apaga (3 lecturas contra 355 de referencia) y Rampa-Norte concentra la
actividad. La vibración, que sí es un sensor del equipo, está estable. Es la lectura que un
monitor sin desglose no permitiría hacer, y por eso el desglose es informativo y el trigger
solo escucha al PSI global de cada variable.

## 2. Trigger de re-entrenamiento

`DecisorReentrenamiento`: dispara si el PSI global de cualquier variable crítica supera 0.2,
o si el error medio actual supera en más del 15 % al baseline. El baseline es
`error_medio_g_por_tonelada` —el mismo nombre de operación del A-2— del run que entrenó al
modelo que porta el alias `@produccion`; el error actual se mide sobre la ventana de
evaluación con la verdad ya observada (la ley del turno siguiente). La decisión queda como
run de MLflow con las razones, se dispare o no.

En la corrida real disparó por el PSI de la ley (0.9875 > 0.2), con el baseline en
0.2645 g/t y el error actual igual (el bootstrap acababa de entrenar con la misma historia).

## 3. El modelo es el del A-2, portado, no imitado

`EntrenadorLey` no reimplementa nada: la matriz por turno es `ConstructorMatrizTurno`, el
pipeline es `ModeloLightGBM` con el conjunto `MINIMO` —codificación del frente dentro del
pipeline, como exige la no-fuga del A-2— y las métricas registran validación, entrenamiento
y brecha con los nombres de operación del A-2. Para eso el Asset Bundle sincroniza
`modulo_a/aurum_pipeline` junto a `modulo_b` (sin tests, serving ni notebooks) y el notebook
instala LightGBM en serverless con `%pip`. Sin búsqueda de hiperparámetros: el A-2 midió que
en `MINIMO` la configuración por defecto reproduce al baseline (docs/modelado.md, fases A y
B). La partición aquí es un corte temporal simple —historia contra la ventana del monitor—
porque el walk-forward de cinco pliegues es el protocolo del A-2 y se cita, no se duplica.

Registry de Unity Catalog (`databricks-uc`): `lakehouse_umlc.modelos.aurum_ley_turno_siguiente`,
esquema `modelos` propio para no mezclar modelos con KPI, aliases `produccion` y `staging`.
Serialización con cloudpickle, como el A-2: el pipeline lleva transformadores propios y el
formato por defecto de MLflow los rechaza.

## 4. Promoción y rollback

`PromotorModelos` compara staging contra producción **sobre la misma ventana**: solo un
staging estrictamente mejor mueve el alias; peor **o igual** es rollback, para no mover
producción por ruido en ventanas cortas. El evento queda en MLflow (`evento=promocion` o
`evento=rollback`) con la razón y las dos métricas; el alias es el mecanismo de despliegue y
ninguna versión se borra.

- **En los datos reales**: el trigger disparó, el candidato se entrenó con la misma historia
  que producción y empató (0.2645 ≥ 0.2645): **rollback**, exactamente lo que la regla debe
  hacer cuando reentrenar no aporta.
- **Demo determinista de las dos ramas**, en memoria y sobre un modelo `_demo` (silver y
  gold no reciben datos falsos; el modelo real no se toca): deriva sintética de vibración
  (PSI 0.3851, crítico), producción entrenada con historia contaminada (+3 g/t, error 3.0354),
  candidato peor (+6 g/t, error 6.0234) → **rollback**; candidato con la historia limpia
  (error 0.2645) → **promoción**, y el alias `@produccion` del demo queda en la versión 3.

## 5. Orquestación y costos

Job aparte `lakehouse_umlc_mlops` —la referencia de Databricks (MLOps Stacks) separa el
monitoreo del pipeline de datos— con cadencia diaria declarada y **pausada**: encenderla es
una decisión de operación, no un costo que la prueba deba correr sola. La corrida tomó
11 min 33 s de serverless (la mitad instalando LightGBM), entre 0.02 y 0.27 USD según el
consumo de DBU; MLflow y el registry del workspace no cobran aparte.

## 6. Límites declarados

- El PSI de la ley mezcla geología con actividad de frentes; el desglose por sector lo
  expone pero el umbral global no lo corrige. En producción, el trigger fino sería por
  sector con mínimos de muestra.
- Con `n_actual` pequeño (Veta-Principal: 3 lecturas) el PSI por sector es ruido con
  apariencia de señal; se reporta el conteo al lado del índice por esa razón.
- El bootstrap deja baseline = error actual por construcción; la regla del 15 % empieza a
  discriminar desde la segunda corrida.
- La demo usa un modelo `_demo` en el mismo esquema; borrar sus versiones es una línea si
  estorba, y se dejó porque es la evidencia de las dos ramas.

## 7. Cómo reproducir

```bash
# Local: pruebas del PSI, el trigger, el registro y el rollback (MLflow sobre SQLite temporal)
pytest modulo_b/umlc_lakehouse/tests/test_deriva.py modulo_b/umlc_lakehouse/tests/test_modelo.py \
       modulo_b/umlc_lakehouse/tests/test_promocion.py

# Nube: el job del B-3 (requiere el B-1 corrido: silver poblada)
cd modulo_b
databricks bundle deploy --var="catalogo=lakehouse_umlc"
databricks bundle run lakehouse_umlc_mlops --var="catalogo=lakehouse_umlc"
```
