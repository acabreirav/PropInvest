# Backlog — Flujo Cero
Tablero del harness. Estados: `pendiente` · `en_curso` · `bloqueada` · `hecha`.
Regla: nada se marca `hecha` sin `make gates` verde.

---

# FASE 0 · Cimientos (sin red)

## T-001 · Esqueleto del repo y toolchain
estado: hecha · agente: colector · fase: 0 · depende_de: []
paraleliza_con: [T-002]
criterio_de_aceptacion:
  - `uv sync` instala; `make setup` deja Playwright chromium listo
  - `ruff` y `mypy --strict src/flujocero/finance` corren en limpio
  - `make test` corre aunque no haya tests todavía

## T-005 · Cargar y validar el perfil del inversionista
estado: hecha · agente: motor-financiero · fase: 0 · depende_de: [T-002]
criterio_de_aceptacion:
  - `config/inversionista.yml` cargado y validado; falla si falta `renta_liquida_mensual_clp`
  - `ticket_max_uf` calculado = min(6000, capacidad por dividendo <=25% renta y carga total <=45%)
  - `exigir_dfl2: true` aplicado como exclusión dura (m2_utiles <= 140 y flag DFL2 presente)
  - escenario base = `con_subsidio` (el inversionista no tiene propiedades ⇒ D-001 resuelta)
  - el informe reporta por separado el subconjunto <= UF 3.000 (tramo especial, ver D-009)

## T-002 · Esquema DuckDB + carga de params
estado: hecha · agente: colector · fase: 0 · depende_de: []
paraleliza_con: [T-001]
criterio_de_aceptacion:
  - `schema/schema.sql` se aplica sin error sobre una base vacía
  - loader de `config/params.yml` valida con pydantic y **falla si un valor `E` no trae `rango`**
  - `make rebuild` reconstruye desde cero

## T-003 · Motor financiero
estado: hecha · agente: motor-financiero · fase: 0 · depende_de: [T-002]
paraleliza_con: []   # NUNCA en paralelo
criterio_de_aceptacion:
  - Todas las fórmulas de `docs/02-modelo-financiero.md` implementadas
  - `mypy --strict` limpio en `src/flujocero/finance/`
  - Los 7 casos de oro de CLAUDE.md §7.2 verdes, incluida la doble implementación del dividendo
  - Invariantes con `hypothesis` sobre 10.000 casos

## T-004 · Motor de escenarios y score
estado: hecha · agente: motor-financiero · fase: 0 · depende_de: [T-003]
criterio_de_aceptacion:
  - Producto cartesiano `{con,sin subsidio} × {pie 10/15/20/equilibrio} × {DFL2} × {vacancia}`
  - Score con pesos leídos de `config/params.yml`, con `score_desglose` en JSON auditable
  - Las exclusiones duras excluyen (no restan puntos) y registran `motivo_exclusion`

---

# FASE 1 · Un extremo a otro sobre 3 comunas (San Miguel, La Florida, Ñuñoa)

## T-010 · Colector CMF + Gael (UF, UTM, IPC, TMC)
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-011, T-012]
criterio_de_aceptacion:
  - Serie de UF completa 2024–2026 en `dim_tiempo_financiero`
  - Fallback a Gael respetando su límite duro (>9 req/10 s = ban de 1 h)

## T-011 · OAuth MercadoLibre + verificación de categorías
estado: pendiente · agente: fuente-scout · fase: 1 · depende_de: []
paraleliza_con: [T-010, T-012]
criterio_de_aceptacion:
  - App registrada, flujo OAuth funcionando, refresh token persistido
  - **Resueltas las brechas 1–4 de `docs/01-fuentes.md §G`**: ID real de categoría inmuebles/departamentos
    en `MLC`, si `/sites/MLC/search` exige Bearer, tope real de resultados, rate limit medido
  - ADR con las mediciones

## T-012 · Colector CMF tasas hipotecarias por banco
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-010, T-011]
criterio_de_aceptacion:
  - `dim_tasa_banco` poblada; brecha 13 de §G resuelta o marcada `ND` con evidencia del intento

## T-013 · dim_microzona desde MELI classified_locations
estado: pendiente · agente: geo-microzonas · fase: 1 · depende_de: [T-011]
criterio_de_aceptacion:
  - Cascada CL → states → cities → neighborhoods materializada con coordenadas
  - Microzonas de las 3 comunas de fase 1 presentes, con `saturada` desde `config/zonas.yml`

## T-014 · Manzanas Censo 2024 + join espacial
estado: pendiente · agente: geo-microzonas · fase: 1 · depende_de: [T-013]
paraleliza_con: [T-020]
criterio_de_aceptacion:
  - GeoParquet descargado, join espacial con `dim_microzona`, regla de asignación **documentada**
  - Distancia a Metro operativo y en construcción, con año de apertura

## T-020 · Colector meli_venta (proyectos nuevos, 3 comunas)
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-011]
paraleliza_con: [T-014, T-021, T-022]
criterio_de_aceptacion:
  - ≥1.000 avisos de venta en las 3 comunas, con `neighborhood` asignado
  - `selftest()` verde; fixture grabada

## T-021 · Colector meli_arriendo (comparables, 3 comunas)
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-011]
paraleliza_con: [T-020, T-022]
criterio_de_aceptacion:
  - ≥1.500 avisos de arriendo con microzona y tipología normalizada

## T-022 · Colector Assetplan (arriendo efectivo + vacancia)
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-020, T-021]
criterio_de_aceptacion:
  - 175 edificios desde `edificios.xml`, unidades por tipología (requiere JS render — justificarlo)
  - Ingesta incremental por `lastmod`

## T-023 · Agregación de arriendo por microzona × tipología
estado: pendiente · agente: analista-arriendo · fase: 1 · depende_de: [T-021, T-022, T-013]
criterio_de_aceptacion:
  - `agg_arriendo_microzona` con p25/mediana/p75 y `n`; **`n<8` ⇒ `ND`, sin imputar**
  - Reconciliación contra `docs/00-hallazgos.md §2` dentro de ±25%, o alerta explicada

## T-024 · Colector PlanOK cotizador (precio por unidad)
estado: pendiente · agente: fuente-scout → colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-025]
criterio_de_aceptacion:
  - Brecha 7 de §G resuelta: método y payload de `datos.php`, universo de valores `key`
  - ≥300 unidades con precio real por unidad en las 3 comunas

## T-025 · Colector wp-json de inmobiliarias
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-024]
criterio_de_aceptacion:
  - Procedimiento B.2 aplicado a los 6 dominios verificados + los 9 por verificar
  - Socovesa parseando precios en `CLF` desde JSON-LD

## T-026 · Gates de calidad de datos
estado: pendiente · agente: auditor-datos · fase: 1 · depende_de: [T-020, T-023]
criterio_de_aceptacion:
  - Los 10 checks de CLAUDE.md §7.3 implementados y corriendo en `make gates`
  - Check de datos personales por **regex sobre valores**, no solo nombre de columna

## T-027 · API + dashboard v1
estado: pendiente · agente: dashboard · fase: 1 · depende_de: [T-004, T-026]
criterio_de_aceptacion:
  - Ranking, ficha, mapa y simulador funcionando
  - E2E Playwright verde; ningún número sin `evidence_level`

## T-028 · Cerrar el vacío #2: arriendo UF/m² de Cerrillos, Recoleta, Independencia, Macul
estado: pendiente · agente: analista-arriendo · fase: 1 · depende_de: [T-023]
criterio_de_aceptacion:
  - Mediana con n≥8 por tipología en las 4 comunas, calculada desde comparables propios
  - Documentado en `docs/00-hallazgos.md` como `[D]` con la metodología

---

# FASE 2 · Expansión RM

## T-030 · Ampliar a las 8 comunas de fase 2
estado: pendiente · agente: colector · fase: 2 · depende_de: [T-026]
criterio_de_aceptacion: ["≥2.000 unidades con precio real en las 11 comunas"]

## T-031 · Parser de listas de precios en PDF
estado: pendiente · agente: parser-pdf · fase: 2 · depende_de: [T-002]
paraleliza_con: [T-030, T-032]
criterio_de_aceptacion: ["≥90% de acierto sobre `tests/fixtures/pdf/`", "reconstrucción de total desde cuotas"]

## T-032 · Pipeline de outreach
estado: pendiente · agente: outreach · fase: 2 · depende_de: [T-031]
paraleliza_con: [T-030]
criterio_de_aceptacion:
  - Cola + aprobación humana + opt-out + tope de 40/día implementados
  - Ingesta automática de adjuntos a `data/raw/email/`
  - **Cero datos personales en la base analítica** (verificado por el auditor)

## T-033 · Transacciones reales y calibración lista→cierre
estado: bloqueada · agente: fuente-scout · fase: 2 · depende_de: []
bloqueo: "requiere decisión de presupuesto — ver docs/05-decisiones.md D-005"

## T-034 · Colectores Pabellón y Enlace Inmobiliario
estado: pendiente · agente: colector · fase: 2 · depende_de: [T-002]
paraleliza_con: [T-030, T-031]

---

# FASE 3 · Regiones y automatización

## T-040 · Gran Concepción, La Serena, Antofagasta
estado: pendiente · fase: 3
nota: "El único tramo del alcance donde el pie de equilibrio baja a ~32%. Alta prioridad de negocio."

## T-041 · Corrida diaria + alertas de bajada de precio y entradas al top 20
estado: pendiente · fase: 3

## T-042 · Backtest del score
estado: pendiente · fase: 3
criterio_de_aceptacion: ["¿Las unidades del top 20 de hace N semanas se vendieron antes que el resto?"]

---

# VIGILANCIA PERMANENTE (no cierran nunca)

## T-900 · Monitorear la publicación del reglamento del tramo UF 4.000–6.000
Revisar LeyChile y el Diario Oficial semanalmente. **Es la pregunta abierta #1**: define si el
inversionista con propiedad previa califica.

## T-901 · Monitorear consumo de cupos del subsidio
34.917 formalizados de 80.000 al 21-ago-2026. Agotamiento estimado hacia fines de 2027.

## T-902 · Monitorear la exención de IVA
Aprobada por el Congreso el 04-ago-2026; publicación en Diario Oficial sin confirmar.
Vale ~800 UF en un departamento de UF 5.000.

## T-904 · Resolver D-009: condiciones del tramo especial <= UF 3.000
Depende de la respuesta del banco. Si el tramo especial exige solo primera vivienda (y no DS1/DS19)
y su tasa es mejor, **reenfocar el ticket objetivo a <= UF 3.000**: domina en yield y en costo de
fondos a la vez para este perfil.

## T-903 · Vigilar parsers rotos
El gate de caída >30% dispara esta tarea automáticamente.
