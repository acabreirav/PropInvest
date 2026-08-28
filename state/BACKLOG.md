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
estado: hecha · agente: colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-011, T-012]
criterio_de_aceptacion:
  - [x] Modulo `sources/cmf_indicadores.py` con el contrato Source del §7.1
  - [x] `dim_tiempo_financiero` con las seis columnas de procedencia (requirio cambio de esquema)
  - [x] Carga idempotente por clave natural `(fecha, serie)`
  - [x] ADR escrito: `docs/adr/001-cmf-indicadores.md`
  - [x] **Serie completa cargada** — 1.037 filas el 28-ago-2026 desde la maquina del usuario:
        uf 974 (2024-01-01 -> 2026-08-31), utm 32, ipc_var_m 31
  - [x] **`selftest()` contra muestra viva: `forma_verificada: true`.** La estructura deducida
        de la documentacion resulto ser la real, ahora confirmada contra la API.
  - [ ] Fallback a Gael respetando su limite duro (>9 req/10 s = ban de 1 h) -> T-908
deuda_pendiente: >
  La fixture de tests sigue siendo la derivada de documentacion. Ahora existe la respuesta
  real en `data/raw/cmf_indicadores/2026/08/28/` de la maquina del usuario; reemplazarla
  cierra el ultimo cabo. Ver T-909.

## T-011 · OAuth MercadoLibre + verificación de categorías
estado: en_curso · agente: fuente-scout · fase: 1 · depende_de: []
paraleliza_con: [T-010, T-012]
criterio_de_aceptacion:
  - [x] App registrada, flujo OAuth funcionando, refresh token persistido (28-ago-2026)
  - [x] Modulo `sources/meli.py` con renovacion de token que **persiste el nuevo ANTES de
        usarlo** — el refresh token de MELI es de un solo uso
  - [x] `cli medir-meli` implementado: mide las brechas contra la API real
  - [x] **G1 medida**: MLC1459 es la RAIZ Inmuebles; departamentos es **MLC1472**.
        `fuentes.yml` corregido con las dos, ya no como supuesto.
  - [x] **G4 medida** [D]: 12 peticiones en 3,3 s sin 429; la API no publica cabeceras
        `X-RateLimit-*`, asi que es cota inferior, no limite.
  - [x] ADR escrito: `docs/adr/003-meli.md`
  - [ ] **G2 y G3 siguen ND**: `/sites/MLC/search` devolvio **HTTP 403 con token y sin token**
  - [ ] **G5 medida** — brecha nueva: ¿queda alguna ruta oficial a los avisos?
hallazgo: >
  /sites/MLC/search dio 403 desde IP residencial chilena, con token valido. El MISMO token
  leyo /sites/MLC/categories en la misma corrida, asi que no es la app, ni el token, ni la IP:
  es ese recurso. `meli_venta` y `meli_arriendo` quedan enabled:false. `meli_locations` NO
  esta afectada (otro recurso), asi que T-013 sigue viva.
bloqueo: >
  Necesita una corrida mas en la maquina del usuario, ya con G5 y con el cuerpo del rechazo
  capturado (antes se registraba solo el codigo HTTP, que no distingue "recurso cerrado" de
  "falta un scope"):
  `uv run python -m flujocero.cli medir-meli`
  OJO: ese comando reescribe MELI_REFRESH_TOKEN en el .env, porque el canje mata el anterior.

## T-910 · Decidir la fuente de oferta y arriendo si MELI quedo cerrada
estado: bloqueada · agente: fuente-scout · fase: 1 · depende_de: [T-011]
criterio_de_aceptacion:
  - [ ] G5 ejecutada y su salida pegada en el ADR-003
  - [ ] Si no queda ruta: D-014 escrita en docs/05-decisiones.md y aprobada por el usuario
  - [ ] Prioridad de T-022 (Assetplan) y de las fuentes de capa 3 recalculada
nota: >
  NO se resuelve scrapeando Portal Inmobiliario. Que la puerta oficial se cierre no vuelve
  permitido lo que su robots.txt prohibe (§3.5, §13.6).

## T-012 · Colector CMF tasas hipotecarias por banco
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-002]
paraleliza_con: [T-010, T-011]
estado_real: en_curso
criterio_de_aceptacion:
  - [x] Parser escrito contra la estructura REAL del archivo (117 filas, 17 bancos, 3 montos)
  - [x] Localizacion por etiqueta y no por indice de fila (se comprobo que los indices se corren)
  - [x] Deteccion de obsolescencia dentro del parser
  - [x] `n/o` se trata como ND y no como cero (§3.2)
  - [ ] **`dim_tasa_banco` poblada con datos vigentes** — imposible con la fuente actual
hallazgo: >
  La URL que este mismo archivo declaraba como fuente sirve una planilla de MAYO DE 2006.
  Lo dice su celda "Fecha de la consulta", la firma la SBIF (disuelta en 2019) y lista
  bancos que ya no existen. La fuente queda `enabled: false` con la razon registrada,
  segun manda el §7.1. El dato viejo no se borra: se conserva como fixture de estructura.

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
estado: en_curso · agente: auditor-datos · fase: 1 · depende_de: [T-020, T-023]
criterio_de_aceptacion:
  - [x] Los 10 checks de CLAUDE.md §7.3 implementados en `quality/checks.py`
  - [x] Corriendo dentro de `make gates`
  - [x] Check de datos personales por **regex sobre valores**, no solo nombre de columna
  - [x] Ancla externa contra la tabla Colliers de `docs/00-hallazgos.md §3`
  - [ ] **Ejercitados contra datos reales** — hoy solo contra fixtures sinteticas
nota: >
  Se adelanto a sus dependencias porque es logica pura y no necesita red. Los checks estan
  escritos y probados con 28 casos, pero nunca han visto una fila real: hasta que T-020 y
  T-023 carguen datos, no se puede afirmar que los umbrales estan bien calibrados.
  Tres severidades: FALLA detiene el ranking, ALERTA lo marca `parcial`, MARCA solo etiqueta.
  Ningun check borra ni imputa: el §7.3 y el §3.2 lo prohiben.

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

## T-907 · Encontrar la fuente VIGENTE de tasas hipotecarias por banco
estado: pendiente · agente: fuente-scout · fase: 1 · depende_de: []
prioridad: alta
motivo: >
  `articles-46417_recurso_1.xls` sirve datos de 2006 (ver T-012). El parser ya existe y
  funciona; lo que falta es una fuente con datos de este ciclo.
pistas_a_revisar:
  - articles-46416_recurso_1.xls — el archivo hermano, puede estar vigente
  - cmfchile.cl/portal/estadisticas/617/w3-propertyvalue-29487.html — indice de "Tasas de Interes"
  - BCCh serie F022.VIV.TIP.MA03.UF.Z.M, que `params.yml` ya cita como fuente de la tasa base
  - las cotizaciones formales con CAE que el inversionista pida en los tres bancos (PASO 9)
criterio_de_aceptacion:
  - Fuente con `Fecha de la consulta` de menos de 12 meses
  - `selftest()` verde incluido el check de frescura
nota: >
  Mientras tanto `params.yml` sigue usando sus cuatro tasas fijas con fuente citada
  (BCCh jul-2026, licitacion FOGAES, Santander/Bco de Chile e Itau ago-2026). No es ideal
  pero esta fechado y es de este ciclo, a diferencia de la planilla.

## T-908 · Fallback a Gael Cloud para indicadores
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-010]
prioridad: baja
motivo: >
  La API de la CMF corta la conexion al azar (medido: la misma URL fallo y minutos despues
  devolvio 974 registros). Los reintentos con backoff lo absorben, pero un fallback a
  api.gael.cloud daria una segunda fuente. Limite duro de Gael: mas de 9 peticiones en
  10 segundos = IP baneada 1 hora.

## T-909 · Reemplazar la fixture derivada de documentacion por la respuesta grabada
estado: pendiente · agente: colector · fase: 1 · depende_de: [T-010]
prioridad: media
motivo: >
  `tests/fixtures/cmf/` contiene una fixture construida a partir de la documentacion, con
  valores sinteticos. La corrida real del 28-ago-2026 dejo la respuesta autentica en
  `data/raw/cmf_indicadores/2026/08/28/` de la maquina del usuario. Los tests deben correr
  contra bytes reales, no contra una reconstruccion — aunque esta haya resultado correcta.
criterio_de_aceptacion:
  - fixture reemplazada por la respuesta grabada, con su `.meta.json`
  - `PROCEDENCIA.md` actualizado: deja de decir que los valores son sinteticos

## T-903 · Vigilar parsers rotos
El gate de caída >30% dispara esta tarea automáticamente.

## T-911 · DFL2 en vivienda usada: la ventana de contribuciones puede estar consumida
estado: pendiente · agente: motor-financiero · fase: 1 · depende_de: []
criterio_de_aceptacion:
  - [ ] Verificar con fuente citada desde cuando corre la rebaja de 50% de contribuciones
        (recepcion municipal) y su duracion segun m2
  - [ ] `Unidad` gana `anio_recepcion` y la rebaja se aplica solo si la ventana sigue abierta
  - [ ] Caso de oro: un usado con ventana vencida paga contribuciones completas
  - [ ] La exencion de renta del DFL2 se verifica aparte: sigue a la propiedad, no a la ventana
nota: >
  Hoy el modelo aplica la rebaja DFL2 a cualquier unidad acogida, sin mirar antiguedad. Para
  obra nueva era inocuo. Con usado en el ranking (D-015) es un supuesto optimista sobre lo que
  el §2.5 declara como el beneficio de mayor valor presente. Cerrar ANTES de rankear usado
  con datos reales.

## T-912 · De donde salen los avisos de vivienda usada
estado: pendiente · agente: fuente-scout · fase: 1 · depende_de: [T-011]
criterio_de_aceptacion:
  - [ ] ADR por fuente candidata con robots + legal_tier: chilepropiedades, catastro SII, CBR
  - [ ] Ninguna fuente `html_prohibido` sin aprobacion humana explicita
  - [ ] Estimacion de cobertura por comuna de Fase 1
nota: >
  El 403 de MercadoLibre golpea mas fuerte al usado que al nuevo: la obra nueva tiene caminos
  permitidos que no pasan por portales (PlanOK, wp-json, Pabellon, Enlace); el usado vive
  disperso en los portales. Chilepropiedades permite crawling (Crawl-delay: 2). El catastro SII
  da atributos reales por rol, que para usado vale mas que para nuevo.

## T-913 · Preguntas al banco (bloquean dos decisiones)
estado: bloqueada_por_humano · agente: - · fase: 1
criterio_de_aceptacion:
  - [ ] ¿FOGAES cubre viviendas USADAS o solo primera venta? (D-015 — la que mas mueve la aguja)
  - [ ] ¿El subsidio a la tasa tiene limite de unidades por persona? (params: null, evidence C)
  - [ ] ¿Tasa del tramo <= UF 3.000 vs tramo general? (D-009)
  - [ ] ¿Acepta conyuge como codeudora solidaria SIN copropiedad? (D-011 pregunta 4)

## T-914 · Las tasas de params.yml no aislan el efecto del subsidio
estado: hecha · agente: - · fase: 1 · depende_de: []
criterio_de_aceptacion:
  - [x] Obtener, del mismo banco y la misma fecha, la tasa CON y SIN subsidio
        -> el usuario las midio en los simuladores el 28-ago-2026, mismas condiciones
        (depto nuevo UF 3.999, pie 10%, 30 anos):
        BancoEstado 3,30% / 4,29% = 99 pb · Santander 3,32% / 4,78% (CAE 5,35) = 146 pb
  - [x] Explicar por que la brecha supera los 60 pb del Decreto 180
        -> CONFIRMA el §2.1: 60 pb son el subsidio y el resto es el efecto FOGAES sobre el
        spread del banco. Son dos beneficios sumados.
  - [x] params.yml queda con un par comparable: se usa el de BancoEstado por conservador
nota: >
  Hoy conviven tasa_mejor_caso_fogaes 3,30% y tasa_mejor_sin_subsidio 3,39%: 9 pb, cuando el
  subsidio son 60. Y tasa_anual_sin_subsidio 3,97% es un promedio de otra fuente. Vienen de
  bancos y fechas distintas, asi que ninguna resta entre ellas mide el subsidio. Lo destapo la
  revision adversarial de D-015, porque de ese par depende si el stock usado gana o pierde.

## T-915 · El motor no distingue FOGAES de subsidio a la tasa
estado: pendiente · agente: motor-financiero · fase: 1 · depende_de: [T-913]
criterio_de_aceptacion:
  - [ ] `Escenario` gana `con_fogaes` separado de `con_subsidio`
  - [ ] El pie minimo del escenario sale del LTV que corresponde (0,90 con FOGAES / 0,80 sin)
  - [ ] Un escenario con pie 10% y sin FOGAES se marca inviable, no se calcula en silencio
  - [ ] Caso de oro: perder solo el subsidio y perder ambos dan resultados distintos
nota: >
  Hoy `con_subsidio` arrastra implicitamente el 90% de LTV, y `ltv_sin_fogaes: 0.80` estaba en
  params.yml sin que nadie lo usara. Los datos del usuario mostraron que son dos beneficios
  separables: 60 pb del Decreto 180 mas el efecto FOGAES sobre el spread. Bloqueada hasta
  saber si FOGAES cubre usadas (T-913): la respuesta define si el usado va a 90% o a 80%.
