# Fabric y orquestación (Ejercicio B-2) — diseño documentado

La cuenta del trial no otorga capacidad de Fabric (se intentó varias veces: cuenta nueva,
sin trial de capacidad disponible), así que el B-2 se entrega como **diseño completo y
verificable**, no como despliegue: cada decisión está tomada, el diagrama está en
`modulo_b/fabric_b2.png` y la demostración de RLS se sustituye por un protocolo con las
cifras esperadas calculadas del extracto real. Nada de lo que sigue es un pendiente
disfrazado: es lo que se construiría, en orden, el día que exista una capacidad F.

Las cifras de este documento salen de ejecutar las clases ya probadas del B-1 sobre el
extracto, en Spark local y sin costo de nube:

```python
crudo = EsquemaOpus.leer_csv(spark, ruta_extracto, EsquemaOpus.EXTRACTO)
bronze = IngestorBronze(spark, Catalogo.local()).enriquecer(crudo, F.lit("extracto"), F.current_timestamp())
silver = LimpiadorSilver().separar(LimpiadorSilver().enriquecer(bronze)).validas
gold = ConstructorKpiTurno().construir(silver)   # 4019 celdas, las mismas de la nube
```

## 1. Servicios y flujos, de un vistazo

Cada paso con su servicio concreto, qué fluye y a qué ritmo; es el mismo orden del
diagrama `modulo_b/fabric_b2.png`:

| # | De → a | Servicio concreto | Qué fluye | Cadencia |
|---|---|---|---|---|
| 1 | Jobs B-1/B-3 → `lakehouse_umlc.gold` | Databricks Workflows (serverless) | KPI por turno en Delta | cada 30 min |
| 2 | Gold (Unity Catalog) → OneLake | **Mirroring**: Mirrored Azure Databricks Catalog | metadatos Delta; los datos no se copian | continua |
| 3 | OneLake → Lakehouse de Fabric | shortcut interno del espejo | las tablas de gold, legibles como propias | — |
| 4 | Lakehouse → modelo semántico | **Direct Lake** (Power BI) | columnas a memoria bajo demanda (framing) | tras cada escritura |
| 5 | Entra ID → roles RLS | grupos de seguridad `sec-fabric-<sector>` | membresía de los cuatro roles | al cambiar el grupo |
| 6 | Orquestación | **Data pipeline** (Data Factory en Fabric) | frescura del espejo, framing, chequeo del KPI | cada 30 min |
| 7 | Modelo → alerta | **Activator** (Real-Time Intelligence) | regla: tasa de fallas del último turno cerrado > 5 % con ≥ 20 eventos | al evaluarse |
| 8 | Activator → operaciones | Teams y correo | la alerta con el turno y la cifra | al disparar |
| 9 | Modelo → consumidores | **Informe Power BI** | visuales; el jefe de Veta-Sur con RLS, la gerencia sin rol | — |

## 2. Réplica de Gold: espejo, no copia

**Mirrored Azure Databricks Catalog**: Fabric monta `lakehouse_umlc.gold` desde Unity
Catalog en OneLake, sin mover datos y con los cambios visibles al ritmo en que los jobs del
B-1 escriben. Es la misma costura que el C-1 dejó como regla ("una sola copia física; solo
cruza Gold", `decisiones_arquitectura.md` §2.2): el espejo es la implementación nativa de
esa regla en este stack.

Alternativas descartadas:

- **Shortcut S3 directo**: exige una credencial de solo lectura sobre el bucket, y el
  *Default Storage* del trial no expone su almacenamiento gestionado. En una cuenta con
  ADLS propio (la arquitectura del C-1) sería equivalente.
- **Copia programada (pipeline copy)**: dos verdades que reconciliar, doble almacenamiento
  y un desfase que alguien tiene que vigilar. Es el anti-patrón que el C-1 ya rechazó.

## 3. Modelo semántico en Direct Lake

Sobre el espejo, un modelo en modo **Direct Lake** (ni import, que copia, ni DirectQuery,
que traduce cada visual a SQL): lee el Delta de OneLake directamente y el framing lo deja
al día tras cada escritura. Tabla de hechos: `aurum_kpi_turno` (grano frente × fecha local
× turno); dimensiones delgadas: fechas (generada) y sector/frente (derivada del hecho).

Las tres medidas que exige el enunciado, en DAX y con su decisión:

```dax
Ley Ponderada g/t =
DIVIDE (
    SUMX ( aurum_kpi_turno, aurum_kpi_turno[ley_ponderada_gpt] * aurum_kpi_turno[ton_total] ),
    SUM ( aurum_kpi_turno[ton_total] )
)
-- Re-agrega el promedio ponderado sobre cualquier filtro. Aproximación declarada: el
-- denominador exacto por celda es el tonelaje de las filas con ley válida, y la tabla
-- publica el total; el sesgo es el 5% de centinelas y se elimina agregando las columnas
-- de soporte _num/_den a gold (cambio de una línea en ConstructorKpiTurno, si se exige
-- exactitud contable).

Produccion oz = SUM ( aurum_kpi_turno[prod_oz_recalculada] )
Ranking Frente = RANKX ( ALL ( aurum_kpi_turno[frente_id] ), [Produccion oz] )

Fallas Semana = SUM ( fallas_equipo_semana[fallas] )
-- sobre la tabla gold adicional de la sección 3.
```

Valores esperados sobre el extracto completo: ley ponderada global **7.9623 g/t**; ranking
encabezado por **FR-C2-02 (Veta-Principal, 311 341 oz)**, seguido de FR-C1-05
(Cuerpo-Central, 295 741) y FR-C2-07 (Veta-Principal, 288 812); el último de los trece es
FR-N2-09 (Rampa-Norte, 61 258).

**Hallazgo que el B-2 le devuelve al B-1**: la tendencia semanal de fallas **por equipo**
no se puede servir desde `aurum_kpi_turno`, cuyo grano es el frente (solo conserva
`equipos_distintos`). Falta una tabla gold, especificada aquí y no construida:

| `gold.fallas_equipo_semana` | tipo | regla |
|---|---|---|
| `semana` | date | lunes ISO de `fecha_local` (`date_trunc('week', ...)`) |
| `equipo_id` | string | del evento de silver |
| `fallas` | bigint | eventos con `falla_cod` no nulo |
| `eventos` | bigint | denominador, para tasa por equipo |

Muestra real (semana del 2025-10-20): EQ-BOAR-05 con 4 fallas, EQ-BOAR-06 y EQ-SAND-09 con
2, EQ-ATLAS-04, EQ-SAND-08 y EQ-SAND-11 con 1; 1 659 fallas en los 18 meses del extracto.

## 4. Pipeline cada 30 minutos: orquestar, no copiar

Con el espejo, la réplica no necesita pipeline. El pipeline de Fabric (cadencia 30 min,
alineada con la llegada de lotes del B-1) queda en tres actividades:

1. **Frescura**: verificar que el espejo refleja la última versión Delta de gold; si el
   desfase supera un umbral, fallar con ruido (un tablero al día de ayer sin aviso es peor
   que uno caído).
2. **Framing** del modelo Direct Lake, para que los visuales lean la versión nueva.
3. **Chequeo de alerta**: la evaluación del umbral del 5 %.

**La alerta, con una corrección al enunciado que los datos exigen.** "Tasa de fallas > 5 %
en el último turno" sobre un turno con pocos eventos es ruido con apariencia de incidente:
el último turno del extracto (N2 del 2025-10-28, **en curso** al momento del corte) tiene 8
eventos y 1 falla — 12.5 %, dispararía por una sola falla. La regla diseñada: evaluar el
último turno **cerrado**, exigir un mínimo de 20 eventos, y disparar por **Activator**
(nativo, sin código, escucha el KPI del modelo) hacia Teams y correo. La alternativa
—actividad de pipeline con notificación— queda para capacidades sin Activator.

## 5. Row-Level Security

- **Rol** `Jefe Sector Veta-Sur`, filtro DAX sobre el hecho: `[sector_geol] = "Veta-Sur"`
  (y el mismo filtro en `fallas_equipo_semana` vía la relación con los frentes del sector).
- **Membresía por grupo de Entra ID** (`sec-fabric-veta-sur`), nunca usuarios nominales: es
  la regla de identidad única que fijó el C-1 (§6.1); dar de baja a alguien es sacarlo del
  grupo.
- Un rol por sector (cuatro), y la gerencia sin rol (vista completa). El RLS del modelo no
  sustituye los permisos de Unity Catalog: gobierna lo que el visual muestra, no quién
  puede leer la tabla.

**Protocolo de demostración, con las cifras esperadas del extracto real.** Sin capacidad no
hay "View as role", así que la demostración queda especificada como verificación con
resultados conocidos de antemano; cuando exista capacidad, es una lista de chequeo:

1. `Ver como rol` `Jefe Sector Veta-Sur` y ejecutar `EVALUATE VALUES(aurum_kpi_turno[frente_id])`:
   debe devolver **exactamente 4 frentes** — FR-S1-02, FR-S1-06, FR-S2-03, FR-S2-08 — y
   `COUNTROWS(aurum_kpi_turno)` debe dar **1 176** celdas.
2. Sin rol: 13 frentes y **4 019** celdas (Rampa-Norte 1 566, Veta-Sur 1 176,
   Cuerpo-Central 657, Veta-Principal 620).
3. Con el rol activo, el ranking debe encabezarlo **FR-S2-08 (174 100 oz)** y no FR-C2-02:
   si el frente de Veta-Principal aparece, el filtro no está aplicado.
4. La prueba negativa: un usuario del grupo de Veta-Sur consultando por DAX directo
   (XMLA), no solo por el visual — el RLS aplica en el modelo, y esta consulta lo confirma.

## 6. Costos y límites

- La capacidad y su costo ya están dimensionados en el C-1: **F8** para 25–40 visores, con
  la tarifa verificada contra la API de precios de Azure (`modulo_c/costos.py`). Este
  diseño no agrega costo propio: el espejo no duplica almacenamiento y Direct Lake no paga
  cómputo de import.
- **No ejecutado por falta de capacidad**: el espejo, el modelo, los roles y el Activator
  están especificados pero no desplegados; la cuenta del trial no otorga Fabric. Es la
  única pieza de la prueba en esa condición y queda dicho sin rodeos.
- El espejo de catálogos de Databricks requiere que el workspace exponga su almacenamiento;
  en Default Storage la variante es el espejo (que lo gestiona Fabric) y en la arquitectura
  del C-1 (ADLS propio) también funcionaría el shortcut.
