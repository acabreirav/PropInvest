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
estado: hecha
resuelto_por: "T-920: la ruta permitida del portal alcanza. No hizo falta invocar D-016." · agente: fuente-scout · fase: 1 · depende_de: [T-011]
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
estado: hecha_por_otra_via
resuelto_por: >
  La API de MELI devolvio 403 (ADR-003). Las microzonas salieron del propio portal: 165 barrios
  con el nombre que el portal usa, extraidos de las paginas de listado. `classified_locations`
  queda como verificacion futura, no como dependencia. · agente: geo-microzonas · fase: 1 · depende_de: [T-011]
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
estado: cancelada
razon: "/sites/MLC/search devuelve 403 (ADR-003). Reemplazada por T-920, ya hecha." · agente: colector · fase: 1 · depende_de: [T-011]
paraleliza_con: [T-014, T-021, T-022]
criterio_de_aceptacion:
  - ≥1.000 avisos de venta en las 3 comunas, con `neighborhood` asignado
  - `selftest()` verde; fixture grabada

## T-021 · Colector meli_arriendo (comparables, 3 comunas)
estado: cancelada
razon: "misma razon que T-020. El colector de T-920 trae venta y arriendo." · agente: colector · fase: 1 · depende_de: [T-011]
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
estado: hecha · modulo: src/flujocero/agg/arriendo.py · comando: `cli agregar-arriendo`
resultado: >
  Agrupa por (microzona, tipologia, rango_m2) —nunca por comuna— con mediana, p25, p75, UF/m2
  y dispersion. La conversion CLP->UF usa la UF del DIA DE CADA AVISO, no la de hoy: usar la
  de hoy mezclaria el movimiento de la UF con el del mercado, que es lo que el §3.3 manda
  separar. Sin UF de ese dia la fila se descarta y se CUENTA por motivo: una fila que no entra
  a la mediana tiene que poder explicarse.
estado_anterior: pendiente · agente: analista-arriendo · fase: 1 · depende_de: [T-021, T-022, T-013]
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
estado: hecha (con una excepcion declarada) · modulo: src/flujocero/api/ · agente: dashboard · fase: 1
adr: docs/adr/007-dashboard.md · comando: `make serve`
criterio_de_aceptacion:
  - [x] Ranking filtrable por pie, comuna, m2 y pie de flujo cero maximo
  - [x] Ficha de unidad con las SEIS columnas de procedencia del §3.1
  - [x] Simulador de pie: mover el control re-evalua sin rehacer la biseccion
  - [x] E2E Playwright verde: carga <3 s con 10.000 unidades, el filtro muerde, la ficha
        muestra la procedencia, ningun numero sin `evidence_level` EN EL DOM
  - [ ] **El mapa NO se dibuja.** `dim_microzona.geom` esta vacio en las 165 microzonas y
        los avisos no traen coordenadas. Bloqueado por T-014. El tablero lo DICE en vez de
        dibujar puntos aproximados: una microzona mal ubicada contradice la tesis del §2.4
        mientras aparenta confirmarla. `test_el_tablero_dice_por_que_no_hay_mapa` esta
        escrito para FALLAR cuando entre la geometria.
hallazgos: >
  1. La primera carga de la pagina mandaba un pie fijo del 20% y descartaba la foto que el
     servidor precalcula con el pie del perfil: **8,1 s contra 0,3 s** con 10.000 unidades.
     Lo encontro el E2E, no una revision de codigo.
  2. `escenario_id` codifica el pie (`pie20`, `pie40`), asi que meterlo en la firma de la
     cache la habria anulado entera SIN QUE NADA FALLARA: solo lenta, para siempre.
  3. El aviso de micro-unidades saltaba con el ranking vacio: "0 de las 15 primeras son de
     menos de 35 m2", una advertencia sobre unidades que no existen.
desviacion_declarada: >
  El §5 sugiere Alpine.js + MapLibre + Chart.js por CDN. No se uso ninguna: el gate E2E corre
  en un contenedor SIN internet, y un gate que no puede correr se salta en silencio. Ademas
  un tablero de decision financiera que se cae con un CDN ajeno es peor que uno que no.
  Hay dos tests que fijan la ausencia de dependencias externas. Ver ADR 007 §1.1.

## T-928 · El mapa de microzonas
estado: bloqueada · agente: dashboard · fase: 2 · depende_de: [T-014]
motivo: >
  Es el unico criterio del §7.5 que T-027 no pudo cumplir. Necesita geometria: hoy
  `dim_microzona.geom` esta vacio en las 165 microzonas y `fact_unidad_venta` no guarda
  coordenadas. Se destraba con el Censo 2024 por manzanas del INE.
criterio_de_aceptacion:
  - [ ] Geometria cargada en `dim_microzona.geom` desde el Censo
  - [ ] El mapa dibuja las microzonas coloreadas por pie de flujo cero minimo
  - [ ] `capacidades.mapa` pasa a `true` y `test_el_tablero_dice_por_que_no_hay_mapa` se
        reemplaza por uno que verifique que el mapa se dibuja
  - [ ] Evaluar vendorizar MapLibre (copiarlo al repo, NO por CDN): el gate E2E tiene que
        seguir corriendo sin internet

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
estado: hecha · modulo: src/flujocero/sources/gael_indicadores.py · agente: colector · fase: 1 · depende_de: [T-010]
adr: docs/adr/006-gael-indicadores.md
motivo: >
  La API de la CMF corta la conexion al azar (medido: la misma URL fallo y minutos despues
  devolvio 974 registros). Los reintentos con backoff lo absorben, pero un fallback a
  api.gael.cloud daria una segunda fuente. Limite duro de Gael: mas de 9 peticiones en
  10 segundos = IP baneada 1 hora.
criterio_de_aceptacion:
  - [x] Colector con el protocolo Source completo y ADR escrito
  - [x] Cupo respetado del lado del CLIENTE, con margen (6 en 10 s, no 9) y un 429 que
        NO se reintenta: reintentar un baneo lo prolonga
  - [x] El respaldo NUNCA pisa una fila de la CMF (`DO NOTHING` vs el `DO UPDATE` de la
        primaria). Una discrepancia entre fuentes se REPORTA, no se resuelve sola
  - [x] `cli ingest` cae solo a Gael cuando la CMF no responde; `--sin-fallback` lo apaga
  - [x] Registrado en `sources/registro.py` para que `make rebuild --from-raw` lo reconstruya
  - [x] Test de que el orden de reconstruccion NO cambia el resultado
pendiente: >
  `forma_verificada=false`: el egreso hacia api.gael.cloud esta bloqueado en el entorno del
  agente, asi que la forma de la respuesta viene de documentacion y no de una respuesta viva
  (misma situacion que el ADR 001 con la CMF). Una corrida de
  `cli ingest --fuente gael_indicadores` desde una maquina con internet deja el primer blob
  real y de ahi sale la fixture. El parser esta escrito para FALLAR RUIDOSAMENTE si la forma
  difiere, nunca para adivinar.

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
estado: hecha · agente: motor-financiero · fase: 1 · depende_de: []
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
estado: hecha
resuelto_por: "T-920, por la ruta que el robots.txt permite. 2.696 unidades cargadas." · agente: fuente-scout · fase: 1 · depende_de: [T-011]
criterio_de_aceptacion:
  - [ ] ADR por fuente candidata con robots + legal_tier: chilepropiedades, catastro SII, CBR
  - [x] Aprobacion humana para `html_prohibido`: **D-016, 28-ago-2026**. Cada colector de esa
        categoria debe citarla en su ADR y en fuentes.yml, o no se habilita.
  - [ ] Estimacion de cobertura por comuna de Fase 1
nota: >
  El 403 de MercadoLibre golpea mas fuerte al usado que al nuevo: la obra nueva tiene caminos
  permitidos que no pasan por portales (PlanOK, wp-json, Pabellon, Enlace); el usado vive
  disperso en los portales. Chilepropiedades permite crawling (Crawl-delay: 2). El catastro SII
  da atributos reales por rol, que para usado vale mas que para nuevo.

## T-913 · Preguntas al banco (bloquean dos decisiones)
estado: bloqueada_por_humano · agente: - · fase: 1
criterio_de_aceptacion:
  - [x] ¿FOGAES cubre viviendas USADAS? **NO, solo primera venta.** Ver D-017. Cierra T-915.
  - [~] ¿Limite de unidades por persona? Respuesta: una. **Sin fuente primaria y contra el
        texto del Decreto 180 art. 3**, asi que queda en `C`. No bloquea: el inversionista no
        declaro querer dos. Ver D-017 punto 3.
  - [x] ¿Tasa del tramo <= UF 3.000 vs general? **Plana, sin diferencia.** Cierra D-009.
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
estado: hecha · agente: motor-financiero · fase: 1 · depende_de: [T-913]
resuelto_por: "D-017 — el usuario confirmo que FOGAES cubre solo primera venta"
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

## T-916 · Auditar el codigo heredado del proyecto anterior del usuario
estado: hecha · agente: fuente-scout · fase: 1 · depende_de: []
resultado: "docs/adr/004-legado-investop.md — 6.180 HTML parseados, 5.870 unidades unicas"
criterio_de_aceptacion:
  - [x] Inventario: que scrapea cada modulo, contra que endpoint, y si sigue vivo tras el 403
  - [x] Que se puede reusar tal cual, que hay que reescribir para cumplir el contrato
        (seis columnas de procedencia, zona cruda, idempotencia, cero datos personales)
  - [x] Revision critica: que se le escapo al trabajo anterior (lo pidio el usuario explicitamente)
  - [x] Inventario de la data historica: que vale (series irreproducibles, fixtures) y que es basura
  - [ ] Purga de datos personales ANTES de que nada toque la base analitica

## T-917 · `exigir_dfl2` vaciaria el ranking contra datos de portal
estado: hecha · agente: motor-financiero · fase: 1 · depende_de: []
criterio_de_aceptacion:
  - [ ] `acogida_dfl2` admite tres estados: si / no / **por_verificar**, no un booleano
  - [ ] `exigir_dfl2` excluye solo los `no`; los `por_verificar` compiten y se marcan en la UI
  - [ ] La ficha de unidad dice como verificarlo (escritura o certificado municipal)
  - [ ] Caso de oro: un universo entero de `por_verificar` no produce ranking vacio
hallazgo: >
  Medido sobre los 5.870 avisos del legado: **16 mencionan DFL2. El 0,3%.** Con exigir_dfl2
  como exclusion dura booleana, el ranking se vacia — y no porque las unidades no sean DFL2,
  sino porque el aviso no lo declara. Confirma el §2.5: el DFL2 se verifica en la escritura,
  nunca en lo que diga el vendedor. Un ND tratado como `false` es exactamente lo que el §3.2
  prohibe.

## T-918 · Ingesta del legado: HTML a la zona cruda con procedencia
estado: hecha · agente: colector · fase: 1 · depende_de: [T-916]
criterio_de_aceptacion:
  - [x] 6.180 HTML en `data/raw/portal_legado_2026_05/` con `.meta.json` y las seis columnas.
        `fetched_at` sale del NOMBRE del archivo (mayo-2026), no del reloj de hoy.
  - [x] Fuente `portal_legado_2026_05` con `historica: true` en fuentes.yml. El gate de
        frescura la exime y lo REPORTA; no la ignora. Exime la fuente declarada, no la regla.
  - [x] Anonimizacion ANTES de escribir a la zona cruda. Cero fugas sobre 600 fichas.
  - [x] 6 fixtures reales en `tests/fixtures/portal_legado/` (712 KB) y 20 tests de
        integracion. `tests/integration/` ya no esta vacio.
  - [x] 84 microzonas y 7 comunas en `dim_microzona`/`dim_comuna` -> desbloquea T-013
  - [x] 2.701 unidades de venta y 2.850 comparables de arriendo, procedencia 100%
  - [x] `rebuild --from-raw` reconstruye las 5.643 filas desde la zona cruda (§3.6 probado)
bugs_encontrados_y_corregidos:
  - a_decimal convertia "35 - 61 m2" en 3.561 m2 (rangos de proyecto). Ahora un rango es ND.
  - El gate de datos personales daba 6.443 falsos positivos: `MLC-3939132164` contiene
    `939132164`, que calza con celular chileno. Patrones anclados.
  - Un vendedor puso su celular en el TITULO del aviso y quedaba en `source_url`, que es
    columna de procedencia. Ahora la URL tambien se sanea.
  - El mismo aviso en dos fechas se contaba como duplicado. Es SCD tipo 2: version nueva
    solo si el precio cambio, y la vieja se cierra.

## T-919 · Delta de precios: cuatro meses de senal de compra
estado: en_curso · agente: colector · fase: 1 · depende_de: [T-918, T-920]
criterio_de_aceptacion:
  - [x] Re-scrapear por la ruta permitida `_Desde_` -> T-920, corrida real 29-ago-2026
  - [x] `quality/delta.py` + `cli delta`: cruza por `unidad_key` sobre las versiones SCD
  - [x] Cuatro categorias: bajaron / subieron / sin cambio / **ya no estan** / nuevas
  - [x] La clasificacion va por FECHAS (`valid_from` vs `fetched_at`), no por `source_id`:
        al confirmar una unidad su procedencia pasa a la captura de hoy, asi que clasificar
        por fuente diria que desaparecio, justo lo contrario de lo que paso.
  - [ ] Correr el cruce completo en la maquina del usuario (necesita la foto de mayo ingerida)
bloqueo: >
  Falta que el usuario ingiera la foto de mayo en SU base. Los 6.229 HTML estan en su disco,
  en la carpeta del proyecto anterior. Dos comandos:
  `uv run python -m flujocero.cli ingerir-legado --origen <ruta>\data\raw\portal_inmobiliario\listings`
  `uv run python -m flujocero.cli delta`

## T-921 · `fact_unidad_venta` no tenia microzona (corregido)
estado: hecha · agente: colector · fase: 1
hallazgo: >
  Aparecio al escribir la consulta del delta: la tabla de unidades en venta no tenia
  `microzona_id`. Sin ella no hay yield — el arriendo comparable esta indexado por microzona
  y no habia por donde cruzarlos. Se llegaba a la comuna via `dim_proyecto`, que solo existe
  para obra nueva; un usado de portal no tiene proyecto. Corregido en el esquema con migracion
  idempotente y en el cargador. Verificado: 2.607 de 2.701 ventas con microzona, 83 distintas,
  y el cruce venta x arriendo por microzona ya devuelve filas.

## T-920 · Colector Portal Inmobiliario por la ruta PERMITIDA
estado: hecha · agente: colector · fase: 1 · depende_de: [T-916]
criterio_de_aceptacion:
  - [x] Solo rutas `_Desde_`. La pagina 1 tambien se pide con `_Desde_1`, porque servida sin
        sufijo no calza con `/*_Desde_` y quedaria fuera de lo permitido.
  - [x] `robots_check` corre ANTES de recolectar, contra una URL `_Desde_` real y no contra
        la raiz del sitio: lo que importa es si la RUTA esta permitida.
  - [x] El constructor RECHAZA cualquier User-Agent con "Mozilla". Sin sesion, sin Playwright,
        sin banderas de evasion. Un 403 levanta `Bloqueado` y detiene: no se reintenta disfrazado.
  - [x] Separa unidad de proyecto. El proyecto va con `evidence_level` E y sus rangos en ND.
  - [x] Seis columnas de procedencia, zona cruda anonimizada, SCD tipo 2, detector de parser roto
  - [x] `Decimal` en todo monto; `datetime` con tzinfo=UTC
  - [x] Sin UF hardcodeada: el parser no convierte monedas (§11). Guarda monto + moneda.
  - [x] Verificado contra las 130 paginas reales: 6.076 tarjetas, microzona 99,8%, m2 99,3%
  - [x] ADR escrito: `docs/adr/005-portal-busqueda.md`
  - [x] **Primera corrida real, 29-ago-2026**: 12 paginas, 571 avisos, 552 filas.
        selftest verde: precio 100%, m2 99,8%, dormitorios 99,1%, comuna y microzona 100%.
medido: >
  Las dos incognitas quedaron resueltas y las dos a favor:
  (a) NO necesita JavaScript. httpx a secas trae el listado completo. Playwright no se
      justifica y no se agrega (§5).
  (b) El portal acepta un cliente ANONIMO y honesto: HTTP 200 sin sesion, sin UA de navegador
      y sin banderas de evasion. Todo el disfraz del scraper anterior era innecesario para
      esta ruta, y arriesgaba la cuenta del usuario a cambio de nada.

## T-922 · El catalizador de Metro esta doble-contado con la microzona
estado: pendiente · agente: geo-microzonas · fase: 1 · depende_de: [T-023, T-014]
origen: "observacion del usuario, 29-ago-2026"
hallazgo: >
  La distancia al Metro es escalar, pero el valor es direccional. Ejemplo del usuario:
  desde Metro Chile Espana, dos cuadras al este esta Plaza Ñuñoa (caro) y dos al oeste
  Exequiel Fernandez (mas barato). Misma distancia, mercados distintos.
  Pero la microzona YA es esa variable bidimensional, y mejor que (distancia, rumbo): un
  poligono contiene lo que un vector no. Medido en los datos propios: Metro Irarrazaval
  0,372 UF/m2 contra Estadio Nacional 0,326 — 14% de brecha, misma comuna, ambas junto al Metro.
  => Para una estacion QUE YA OPERA, `catalizador` (10% del score) cuenta dos veces lo mismo:
  su valor ya esta dentro de la mediana del barrio. Y premia a un barrio caro por ser caro.
criterio_de_aceptacion:
  - [ ] Medir con el modelo hedonico (efectos fijos por microzona) si la distancia a Metro
        explica algo UNA VEZ controlada la microzona
  - [ ] Si no explica: el peso del catalizador se redistribuye, con la evidencia escrita
  - [ ] Si explica: separar `metro_operativo` (ya en el precio) de `metro_en_construccion`
        (lo que todavia NO esta en el precio, que es donde vive el valor real)
  - [ ] Evaluar distancias a POLOS (Plaza Ñuñoa, parques, universidades) en vez de rumbo:
        el angulo no tiene relacion monotona con el precio y exigiria datos que no hay
nota: >
  El codigo heredado (`investop/src/modelo/regresion.py`) ya trae el OLS hedonico con
  agrupacion de microzonas: es el instrumento para esta pregunta, no hay que inventarlo.

## T-029 · El eslabon que falta: cruzar venta x arriendo y rankear
estado: hecha · modulo: src/flujocero/agg/oportunidades.py · comando: `cli oportunidades` · agente: motor-financiero · fase: 1 · depende_de: [T-023]
PRIORIDAD: la mas alta. Es lo unico entre el estado actual y un ranking mirable.
hallazgo: >
  Estan las dos puntas y no esta el puente. `fact_unidad_venta` tiene 2.696 unidades con
  precio, m2, tipologia y microzona. `agg_arriendo_microzona` tiene la mediana de arriendo por
  (microzona, tipologia, rango_m2). El motor financiero calcula todo. **Pero ningun comando
  toma una unidad, le pega el arriendo de su celda y corre el motor.** `demo` corre sobre
  unidades inventadas; no hay `score` sobre datos reales.
criterio_de_aceptacion:
  - [ ] `cli oportunidades`: join unidad -> celda de arriendo por (microzona, tipologia, rango)
  - [ ] Una unidad sin celda con n>=8 NO se rankea y se cuenta aparte: es el gate del §7.3,
        y con los datos de hoy va a excluir a la mayoria. Hay que decirlo, no esconderlo.
  - [ ] Corre `evaluar_universo` + `puntuar` y muestra el top con su desglose de score
  - [ ] Cada fila expone: yield bruto, cap rate, costo real de tenencia, pie de equilibrio,
        y de donde salio su arriendo (microzona, n, dispersion)
  - [ ] Gate de coherencia: ninguna unidad rankeada sin `evidence_level` V en su precio (§12)

## T-923 · El pie de flujo cero se calculaba con la forma cerrada, y mentia
estado: hecha · modulo: src/flujocero/finance/modelo.py · agente: motor-financiero · fase: 1 · depende_de: [T-029]
hallazgo: >
  `pie_minimo_flujo_cero` es la forma cerrada `1 - (1-opex)*yield/factor`, que parte del yield
  **BRUTO**: ignora vacancia, incobrabilidad, la erosion intra-anual del §3.3 y los seguros que
  el banco cobra junto al dividendo. Subestima **siempre**, y de forma desigual: mas donde el
  opex y la vacancia pesan mas. Medido por biseccion sobre el modelo completo, la diferencia en
  unidades reales del ranking fue de **+24 a +30 puntos** de pie. Era la metrica insignia del
  producto (§12, 20% del score) y ordenaba el ranking por un numero sesgado.
criterio_de_aceptacion:
  - [x] `pie_flujo_cero_real()` por biseccion sobre el modelo completo, mismo modelo que produce
        el resto de la fila, para que lo mostrado sea internamente coherente
  - [x] Devuelve `None` cuando el flujo no cruza cero ni con pie 100%
  - [x] El score usa la real, no la cerrada
  - [x] `core.pie_minimo_flujo_cero` se conserva: esta anclada por el §7.2 contra la literatura
        y sirve para comparar con cifras publicadas
nota: >
  Los 43-44% medidos caen dentro del 34-47% que el §2.3 del contrato predecia para el Gran
  Santiago. Yo le habia dicho al usuario que el contrato se equivocaba, apoyado en la metrica
  sesgada. Correccion entregada.

## T-924 · El ranking premia micro-unidades y no mide su riesgo
estado: pendiente · agente: motor-financiero · fase: 2 · depende_de: [T-014]
hallazgo: >
  Un tercio del top esta bajo 35 m2 (mediana 40 m2 en el top 15). El §13.3 advierte exactamente
  de esto: los retornos de dos digitos del mercado chileno son stock usado, chico y barato.
  Una unidad de 25 m2 tiene mas rotacion, mas vacancia, gastos comunes mas altos por m2 y mucha
  menos liquidez de salida. **El ranking no mide nada de eso**: hoy solo salta un aviso cuando
  un tercio o mas del top esta bajo 35 m2.
criterio_de_aceptacion:
  - [ ] Medir con datos si la vacancia y la rotacion son peores bajo 35 m2 (no asumirlo)
  - [ ] Si lo son: entra como componente del riesgo de microzona, con su peso en params.yml
  - [ ] Si no lo son: se documenta y el aviso se retira, en vez de dejar un miedo sin evidencia
  - [ ] Los gastos comunes por m2 por tramo de superficie salen de una fuente, no de un supuesto

## T-925 · Cero unidades nuevas llegan al ranking
estado: pendiente · agente: colector · fase: 2 · depende_de: [T-920]
hallazgo: >
  De 1.048 unidades rankeadas, **0 reciben subsidio a la tasa y 0 reciben FOGAES**: todas son
  usadas y el motor se los niega con razon (§12: el subsidio es condicion del inmueble, exige
  primera venta). La maquinaria legal que da nombre al proyecto hoy no aplica a ninguna fila.
  No es un error del motor: es que el universo de avisos que sobrevive a los filtros de calidad
  es stock usado de portal.
criterio_de_aceptacion:
  - [ ] Cuantificar cuantas unidades de `fact_unidad_venta` son de proyecto nuevo y por que se
        caen: sin celda de arriendo con n>=8, sin precio por unidad, o sin microzona
  - [ ] Colector de proyectos nuevos con precio POR UNIDAD (PlanOK cotizador, T-042)
  - [ ] El comando `oportunidades` reporta la composicion nuevo/usado del universo rankeado,
        no solo del top

## T-926 · El verificador de robots SUB-BLOQUEABA: la stdlib no entiende comodines
estado: hecha · modulo: src/flujocero/sources/robots_rfc9309.py · agente: colector · fase: 1
hallazgo: >
  Lo destapo una CONTRAPRUEBA en los tests de Gael: puse un test que exigia que las rutas
  que su robots.txt prohibe salieran prohibidas, y fallo. `/admin/x` salia PERMITIDO
  teniendo un `Disallow: /admin/*` al frente.
  La causa es el `RobotFileParser` de la libreria estandar de Python: **no implementa los
  comodines del RFC 9309**. Guarda la regla como el literal `/admin/%2A` — trata el
  asterisco como un caracter mas. O sea que cualquier `Disallow` con `*` o `$` no bloqueaba
  nada. La direccion del error es la peligrosa: sobre-bloquear molesta, **sub-bloquear te
  hace pedir lo que el sitio prohibio**, y el §3.5 es una regla dura.
criterio_de_aceptacion:
  - [x] Evaluador propio del RFC 9309: comodines `*` y `$`, gana el patron mas largo,
        empate a favor de Allow, lineas malformadas ignoradas, grupo de user-agent mas
        especifico
  - [x] `_veredicto_desde_cuerpo` corre los DOS y toma la conjuncion: permitido solo si el
        RFC y la stdlib coinciden. Sobre-bloquear es el lado seguro del error
  - [x] Tests contra los robots.txt REALES, con contraprueba: lo prohibido sale prohibido
  - [x] Modulo puro, sin red ni reloj
impacto_medido: >
  Ninguna recoleccion pasada violo robots. El unico robots con comodines que habiamos
  evaluado es el de Gael (`/admin/*` etc.) y nunca pedimos esas rutas. El del portal
  —`Disallow: /propiedades/`— no usa comodines y se evaluaba bien.
  PERO hay un matiz que si conviene saber: su `Allow: /*_Desde_`, que es la justificacion
  documentada del `legal_tier: html_permitido` del colector del portal, **la stdlib nunca
  lo leyo**. El permiso venia de que ningun Disallow calzaba, no de ese Allow. Ahora si se
  lee, y el veredicto es el mismo por dos caminos en vez de uno.

## T-927 · La UF no es monotona ni lineal, y yo asumi las dos cosas
estado: hecha · agente: colector · fase: 1
hallazgo: >
  Al escribir tests contra la respuesta REAL de la CMF (T-909) puse el invariante "la UF
  nunca baja". Fallo: entre el 2026-01-10 y el 2026-02-09 cayo de 39.759,95 a 39.682,99,
  un -0,2%, porque el IPC del mes anterior fue NEGATIVO.
  Lo cambie por "se mueve en tramos lineales". Tambien fallo: dentro del mismo tramo el
  monto diario va de 13,22 a 13,35.
  Lo que si se cumple: la UF se recalcula el dia 10 de cada mes con el IPC del mes anterior
  y **compone a tasa diaria constante** hasta el 9 del siguiente. La razon entre dias
  consecutivos es constante hasta 4e-07, que es el redondeo al centavo. Ademas, con IPC
  cero la UF queda EXACTAMENTE plana un mes entero (paso en feb-2026).
consecuencia: >
  Nada en el codigo asumia monotonia (verificado por grep), asi que no hubo bug. Pero queda
  fijado por test, y es una advertencia para el motor y el dashboard: **la UF puede bajar**.
  Cualquier grafico o proyeccion que la dibuje siempre creciente esta mintiendo.

## T-935 · Diagnostico de huecos: que recolectar para desbloquear mas unidades
estado: hecha · modulo: src/flujocero/agg/faltantes.py · comando: `cli faltantes` · fase: 1
hallazgo: >
  El cuello de botella del proyecto NO son los avisos de venta. De 2.380 unidades con precio
  verificado, **2.043 (86%) se caen por `sin_comparables`**: su celda de arriendo no llega a
  los 8 comparables del §7.3. Y el desbalance esta concentrado de forma explotable —
  `san-miguel/el-llano 2D2B` tiene 108 unidades en venta y 2 comparables de arriendo, o sea
  que **seis avisos desbloquean 108 unidades**.
  Recolectar "mas arriendo" a ciegas reparte el esfuerzo entre celdas que ya sirven y celdas
  que no le importan a nadie. Este comando lo convierte en un plan.
criterio_de_aceptacion:
  - [x] Ordena las celdas por PALANCA: unidades desbloqueadas por cada aviso que falta
  - [x] El rango de m2 se calcula con la MISMA funcion que la agregacion de arriendo, o el
        diagnostico apuntaria a celdas que el emparejamiento nunca mira
  - [x] Vista por comuna, que es como recorre el colector
  - [x] NO baja el umbral de 8: la respuesta a "faltan comparables" es conseguirlos

## T-936 · Explorador de fuentes: capturar antes de parsear
estado: hecha · comando: `cli explorar` · fase: 1
motivo: >
  Un parser de HTML escrito a ciegas contra una fuente que nunca vimos es adivinanza con cara
  de codigo. Con Gael se pudo porque era JSON documentado; con Assetplan no. Este comando es
  el paso `fuente-scout` del §8 antes del paso `colector`: verifica robots, baja unos pocos
  documentos a la zona cruda con procedencia completa, y describe su FORMA —JSON-LD,
  `__NEXT_DATA__`, sitemap, montos— para escribir el parser sobre bytes reales.
criterio_de_aceptacion:
  - [x] Se niega a descargar lo que robots prohibe, y lo dice citando el §3.5
  - [x] Respeta el `Crawl-delay` declarado
  - [x] Escribe a la zona cruda con las seis columnas (§3.6)
  - [x] `--render` para paginas con JS, solo cuando el ADR de la fuente lo justifique (§5)
  - [x] Detecta JSON-LD y estado de app embebido, que evitan parsear HTML

## T-022 · Colector Assetplan (arriendo efectivo + vacancia)
estado: en_curso · agente: colector · fase: 1 · depende_de: [T-936]
PRIORIDAD ALTA, y por dos razones a la vez:
  1. Publica **arriendo EFECTIVO**, no precio pedido. Hoy el yield se calcula sobre una
     aspiracion y probablemente sea optimista.
  2. Publica **vacancia**, que es justo lo que le falta a `riesgo_microzona` — el 15% del
     score que hoy esta muerto. Destraba parte del 25% inerte SIN esperar el Censo.
legal: >
  Su robots.txt permite EXPLICITAMENTE a ClaudeBot y Claude-User. Pero trae
  `Disallow: /arriendo/departamento/*/edificio/` **con comodin**, que el verificador de la
  stdlib ignoraba: sin el arreglo de T-926 habriamos entrado a una ruta prohibida creyendo
  que estaba permitida.
siguiente_paso: >
  El usuario corre `cli explorar https://www.assetplan.cl/edificios.xml --seguir 3` desde su
  IP chilena y manda los blobs. Con esos bytes se escribe el parser y su ADR.


## T-937 · Recoleccion dirigida, y medir su rendimiento
estado: hecha · comando: `cli recolectar-portal --dirigida N` · fase: 1 · depende_de: [T-935]
hallazgo: >
  Medido sobre la base REAL del usuario el 30-ago-2026: 3.875 unidades con precio verificado,
  **2.227 rankean (57%)**, 1.648 esperan comparables. Y las 20 celdas de mayor palanca suman
  ~290 unidades esperando con solo **~35 avisos** de arriendo faltantes.
  `nunoa/estadio-nacional 3D2B 70-100` tiene **30 unidades esperando y le falta UN aviso**.
criterio_de_aceptacion:
  - [x] `--dirigida N` toma las N comunas con mas unidades esperando y recolecta SOLO arriendo
  - [x] El orden es por unidades que esperan, NO por avisos que faltan: ordenar por esfuerzo
        en vez de por resultado manda la corrida al lugar equivocado
  - [x] Al terminar corre `agregar-arriendo` y reporta **cuantas unidades desbloqueo**
  - [x] Cero desbloqueadas no se presenta como fracaso: los avisos pueden haber caido en
        celdas que aun no llegan a 8, y eso se dice
nota: >
  La URL del portal solo permite filtrar por COMUNA, no por tipologia ni rango de m2, asi que
  la direccion es a nivel de comuna. La celda exacta la resuelve la agregacion despues.
correccion: >
  Antes de tener la base del usuario yo habia medido "86% se cae por sin_comparables" sobre la
  base PARCIAL de mi contenedor. En la base real es 43%. El diagnostico de DONDE estaba el
  hueco era correcto; la gravedad no. Corregido.

## T-938 · La exclusion dura del §12 no se disparaba NUNCA sobre datos reales
estado: hecha · modulo: src/flujocero/alcance.py · agente: motor-financiero · fase: 1
hallazgo: >
  Tres agujeros que salieron de una sola corrida (`recolectar-portal --dirigida 3`):

  1. **GRAVE.** `params.yml` declara `excluir_microzonas_saturadas: true` y `modelo.py`
     implementa la regla contra `Unidad.microzona_saturada`, pero `oportunidades.emparejar()`
     —el UNICO camino de las unidades reales— nunca poblaba ese campo. Quedaba en su default
     `False` y **la exclusion no se disparaba jamas**. Solo funcionaba en `demo`, sobre
     unidades inventadas. El caso que lo destapo: `nunoa/estadio-nacional` esta marcada
     saturada en zonas.yml y es justo la microzona con MAS comparables que tenemos (n=124).
  2. `--dirigida 3` eligio Nunoa, Providencia y Macul por volumen. **Providencia esta en
     `excluidas`** ("2D2B en UF 8.921, sobre el tope"): un tercio de esa corrida se gasto
     recolectando arriendo para unidades que el motor nunca iba a rankear.
  3. El diagnostico de huecos contaba como "desbloqueable" lo que se descarta despues por
     regla dura, inflando el objetivo y desviando la recoleccion.
criterio_de_aceptacion:
  - [x] `alcance.py`: fuente unica desde `zonas.yml`, LISTA BLANCA (lo no declarado esta
        fuera), microzonas saturadas con su `microzona_id` completo
  - [x] `emparejar()` puebla `microzona_saturada` y descarta fuera de alcance, contando cada
        motivo aparte
  - [x] `diagnosticar()` no cuenta lo que no puede rankear
  - [x] `--dirigida` se detiene si el diagnostico propone una comuna fuera de alcance
  - [x] Test de que el motor EXCLUYE de verdad una unidad saturada: sin el, el arreglo
        podria poblar un campo que nadie mira
  - [x] Test que ata las comunas del fixture E2E con el alcance real
consecuencia: >
  El ranking se va a ACHICAR y eso es el arreglo funcionando. Las unidades de Las Condes,
  Providencia y `nunoa/estadio-nacional` que aparecian antes no debian estar ahi.
  Ademas explica la alerta de reconciliacion de la ultima corrida: las dos microzonas fuera
  de ±25% —las-condes +49%, providencia +29%— son justo comunas EXCLUIDAS del alcance.

## T-022 · Assetplan — CORREGIDO: no es la fuente de arriendo efectivo que creiamos
estado: bloqueada (espera una medicion) · adr: docs/adr/008-assetplan.md · fase: 1
hallazgo: >
  Se exploro con `cli explorar` desde IP chilena y se miraron los bytes. El catalogo la
  describia como "mejor proxy de arriendo efectivo y vacancia". **No entrega ninguna de las
  dos.** Esa afirmacion venia de investigacion secundaria, no de mirar una respuesta.
  Lo que SI entrega, en un `x-data="buildingPage(JSON.parse(...))"` de 35 KB (Livewire +
  Alpine; el unico JSON-LD es un BreadcrumbList inutil):
    - `latlng` — las primeras coordenadas reales del sistema
    - `nearby_transport[].distance_meters` a estacion de Metro, via Google Places
    - `min_ggcc` por tipologia — gastos comunes REALES por edificio
  Lo que NO entrega: nada por unidad (sin m2, sin precio por depto — `units_by_size` lo carga
  Livewire por AJAX), y sin vacancia. Y `min_price` es un **"desde"**: el §12 lo excluye como
  `E`, y usarlo como comparable sesgaria la mediana de arriendo hacia abajo de forma
  sistematica, justo en el numerador del yield.
decision_pendiente: >
  Una sola medicion la resuelve: `cli explorar <ficha> --render`. Si al renderizar aparecen
  unidades con m2 y precio, Assetplan pasa a ser la MEJOR fuente de comparables del catalogo
  —precio por unidad con superficie, operador profesional, robots que nos permite
  explicitamente— y eso justifica Playwright, que el §5 solo admite con justificacion en el
  ADR de la fuente. Si no aparecen, Assetplan baja de capa 4 a capa 6: fuente de CONTEXTO
  (Metro, gastos comunes, coordenadas), no de arriendo.

## T-939 · El catalizador de Metro tiene una fuente posible que no sabiamos que existia
estado: pendiente · agente: geo-microzonas · fase: 2 · depende_de: [T-022]
motivo: >
  El catalizador es el 10% del score y esta INERTE: sin fuente, reparte el mismo puntaje a
  todas las unidades y no mueve una posicion. La exploracion de Assetplan encontro
  `nearby_transport[].distance_meters` — distancia a estacion de Metro MEDIDA por Google
  Places, con nombre y tipo (`subway_station`), para 176 edificios con coordenadas.
  No resuelve el catalizador de nuestras unidades (que no tienen coordenadas), pero es la
  primera medicion real de distancia a Metro que entra al sistema y sirve de ancla.
nota: >
  Antes de subirle peso hay que resolver T-922: si la cercania al Metro YA esta en el precio
  de la microzona, el score la esta pagando dos veces.

## T-940 · Validar el supuesto de gastos comunes contra dato real
estado: pendiente · agente: auditor-datos · fase: 2 · depende_de: [T-022]
motivo: >
  `params.yml:gastos_operativos.gastos_comunes_clp_m2_mes` es un `E` de 3.000 CLP/m2/mes con
  rango [2.000, 5.000], afinado a mano por comuna. Assetplan publica `min_ggcc` REAL por
  edificio y tipologia (ej. Estudio $45.000 · 1D $60.000 · 2D $90.000). Validar un `E` contra
  dato real es exactamente lo que el §3.2 pide de un `E`.

## T-941 · Una banda de m2 no es homogenea, y el sesgo cae justo en el top del ranking
estado: hecha · decision D-018 aprobada por el usuario el 30-ago-2026 · fase: 1
hallazgo: >
  Las primeras filas del ranking real son unidades de **18 a 23 m2**, todas emparejadas
  contra la celda de arriendo `0-35 m2`. Medido sobre 1D1B en esa banda:

    17-21 m2   n= 11   arriendo mediano $320.000
    22-26 m2   n= 37                    $300.000
    27-30 m2   n=145                    $334.800
    31-35 m2   n=289                    $370.000
    LA BANDA   n=482                    $350.000

  El **60% de los comparables mide 31-35 m2**, asi que la mediana de la banda describe a un
  depto grande. Acreditarsela a uno de 22-26 le regala **+17% de arriendo**, y el arriendo es
  el numerador del yield: el mismo +17% se traslada entero al yield y lo sube en el ranking.
  O sea que **las primeras filas del top pueden ser un artefacto del banding**, no una
  oportunidad.
lo_hecho:
  - [x] `agg_arriendo_microzona.m2_mediana`: la superficie tipica de cada celda
  - [x] Migracion idempotente en `db.migrar()` — `CREATE TABLE IF NOT EXISTS` no agrega
        columnas a una base que ya existe, y esto habria roto la base del usuario
  - [x] `emparejar()` mide el desvio de cada unidad contra el depto tipico de su celda
  - [x] `cli oportunidades` avisa cuando una de las 20 primeras esta 15% o mas bajo el
        tamano tipico de su celda, con el numero
  - [x] `cli bandas` mide el costo de angostar: cuantas celdas caen bajo los 8 del §7.3
lo_que_NO_se_hizo_y_por_que: >
  **No se corrige el arriendo.** Inventar un ajuste por m2 seria imputar (§3.2). Y no se
  cambian las bandas por mi cuenta: mover `ingresos.rangos_m2` cambia el ranking en mas de un
  10% de posiciones, y el §8.4 dice que eso se decide con el humano.
decision_para_el_usuario: >
  Correr `cli bandas` sobre la base real. Si angostar `0-35` en `0-25` + `25-35` no cuesta
  celdas, es gratis y se hace. Si cuesta, el cambio es: menos sesgo a cambio de menos
  unidades rankeables, y se compensa recolectando dirigido.

## T-040 · Gran Concepcion, La Serena, Antofagasta — DESBLOQUEADA
estado: en_curso · agente: colector · fase: 3 · comando: `cli probar-comunas --fase 3`
motivo: >
  Decision estrategica del 30-ago-2026, con el usuario. Llevabamos la sesion perfeccionando
  la medicion de Santiago, que segun la propia investigacion es el PEOR mercado del alcance:
  cap rate neto 2,8%, cero unidades con subsidio (todas usadas), y pies de equilibrio de
  42-51%. Fase 3 —donde el §10 dice cap rate 4,0-4,5% y **el unico mercado donde el pie de
  equilibrio baja a ~32%**— tenia CERO datos.
dos_bloqueos_que_habia_y_ya_no:
  - >
    El colector tenia `metropolitana` CLAVADO en la URL, en tres lugares. Ahora la region
    viaja por comuna desde zonas.yml. Y la extraccion de la comuna desde la URL se ancla
    contra la lista de regiones conocidas: partir por el ultimo guion daria
    `san-pedro-de-la-paz-bio` para `san-pedro-de-la-paz-bio-bio`.
  - >
    `zonas.yml` declaraba fase 3 con `ciudad`, y **una ciudad no es una comuna**. "Gran
    Concepcion" es una conurbacion de cinco. El alcance tomaba `gran-concepcion` como comuna,
    asi que la declaraba dentro y ninguna unidad podia calzar con ella jamas: fase 3 estaba
    en el alcance y era inalcanzable al mismo tiempo.
lo_que_falta_y_NO_se_adivina: >
  El `region_slug` que usa el PORTAL en su URL. `bio-bio`, `coquimbo` y `antofagasta` estan
  en zonas.yml marcados **SIN VERIFICAR**. Un slug malo **no da error**: el portal responde
  200 con cero resultados y una corrida de veinte minutos "funciona" sin traer nada.
  `cli probar-comunas --fase 3` pide UNA pagina por comuna y cuenta tarjetas: cero tarjetas
  con HTTP 200 es la senal.
criterio_de_aceptacion:
  - [x] La region viaja por comuna, desde zonas.yml
  - [x] Fase 3 se expande de ciudad a comunas
  - [x] `probar-comunas` verifica los slugs antes de gastar una corrida
  - [x] `recolectar-portal --fase 3`
  - [x] Slugs verificados contra el portal — 8/8, 48 tarjetas c/u, 31-ago-2026
  - [x] Venta de fase 3 en la base — 3.812 avisos, ~1.200 unidades nuevas
  - [ ] Arriendo de fase 3 con celdas n>=8: **hoy ninguna llega**. De las 130 celdas
        utiles, cero son de fase 3, y del top 15 solo `coquimbo/sindempart` es de region.
  - [ ] Contrastar el pie de equilibrio real contra el ~32% que predice el §10


## T-042 · El §7.1 aplicado a la tabla, no a una muestra de 5 documentos
estado: hecha
agente: auditor-datos
fase: 2
gate: make gates

`MLC-1939505225` encabezaba el ranking del 31-ago-2026 con **yield 17,58%** contra 7,90% de
la segunda, y `pie 0%` para flujo cero. Su titulo: `vendo-promesa-con-descuento-de-6-millones`.
No vende un departamento: vende su **posicion en una promesa de compraventa**. Los UF 850 son
lo que pide por la cesion; el comprador ademas hereda el saldo con la inmobiliaria.

UF 850 sobre 60 m2 = **14,2 UF/m2**, con la microzona en 59. El §7.1 declara `UF/m2 entre 20
y 200` desde el principio, pero ese rango es un **cociente** y solo se aplicaba dentro del
`selftest()` de cada fuente, o sea contra <=5 documentos vivos. El parser aplica precio y
superficie por separado y los dos pasan: UF 850 > 500, y 60 m2 esta entre 15 y 400.

**Por que importa mas de lo que su conteo sugiere (1 fila de 2.696):** un ranking por yield
ordena por precio bajo, asi que toda fila cuyo precio signifique otra cosa **flota sola hasta
el primer lugar**. No queda perdida en el medio: es el numero que el usuario mira primero.
Es el §13.3 en ropa nueva.

criterio_de_aceptacion:
  - [x] Modulo puro `quality/plausibilidad.py` con los rangos del §7.1
  - [x] Descarte propio `precio_implausible` en el emparejamiento, con la razon por unidad
  - [x] Check del §7.3 que lo reporta en `make gates`
  - [x] Contraprueba: no bota la unidad mas barata de su microzona ni las 8 promesas que SI
        publican el precio del departamento


## T-043 · `marcar_outliers` calcula y tira el resultado a la basura
estado: pendiente
agente: auditor-datos
fase: 2
depende_de: [T-042]
gate: make gates

**El sexto caso de la familia "senal que se lee bien porque no mide nada".** Y este es peor
que los otros cinco, porque imprime un numero que lo hace parecer vivo:

    • outliers: 161 unidades marcadas `sospechoso`; se conservan, no entran a medianas

`checks.marcar_outliers` lee las filas a diccionarios, muta `sospechoso` **en el diccionario**
y nadie lo escribe de vuelta. La columna `fact_unidad_venta.sospechoso` sigue en `false` para
las 161, en cada corrida, desde siempre. Un `grep sospechoso src/` da dos resultados: el que
lo escribe en memoria y el que lo lee en SQL. Ninguno lo persiste.

Y hay un segundo filo: `agg/arriendo.py:205` filtra los comparables con
`coalesce(sospechoso, FALSE) = FALSE` — pero `marcar_outliers` corre sobre **unidades de
venta**, no sobre comparables. O sea que ese WHERE es un no-op sobre una columna que nadie
llena nunca, **en la consulta que calcula la mediana de arriendo: el numerador de todo yield
del sistema**.

**Cuidado al arreglarlo, y es el punto dificil de la tarea.** Con `[p1, p99]` y n chico el
percentil cae casi sobre el extremo, asi que el minimo y el maximo de cada microzona quedan
marcados **siempre**, sean anomalos o no. Para sacarlos del calculo de una mediana eso es una
winsorizacion suave y es exactamente lo que el §7.3 pide. Para excluir del ranking seria un
desastre: descartaria automaticamente la unidad mas barata de cada barrio, que es justo la
candidata a mejor oportunidad. **`sospechoso` no debe excluir del ranking** — el §7.3 dice
"se excluye del calculo de medianas", y hay que leerlo literal.

criterio_de_aceptacion:
  - [ ] `sospechoso` se persiste a la base despues de `marcar_outliers`
  - [ ] Los comparables de ARRIENDO se marcan por su propia metrica (arriendo_uf/m2 por celda),
        que es lo que el WHERE de `agg/arriendo.py` presupone y hoy no existe
  - [ ] Test que falla si el filtro vuelve a ser un no-op: sembrar un comparable absurdo y
        verificar que la mediana NO lo incluye
  - [ ] Medir el antes/despues de las medianas de arriendo: cambia el yield de todo el
        universo, asi que va con numero, no con "quedo mejor"


## T-044 · El gate de frescura anunciaba una consecuencia que no ocurria
estado: hecha
agente: auditor-datos
fase: 2
gate: make gates

**El septimo caso de la familia, y el mas caro.** En cada corrida el gate imprimia:

    ! frescura: 2696 filas con mas de 21 dias: quedan FUERA del ranking y sirven de linea
      base historica

Y `oportunidades.emparejar` **no miraba `fetched_at`**. Su consulta filtraba por `valid_to`,
`precio_uf` y `evidence_level`, nada mas. Las 2.696 filas del corpus de mayo entraban al
ranking igual que las de hoy. La segunda del ranking del 31-ago-2026 —`MLC-1933353711`,
UF 1.350, la mejor oportunidad real de la corrida— tenia precio del **4 de mayo**.

El §7.3 lo pedia textual desde el principio: *"ninguna fila usada en el ranking puede tener
`fetched_at` > 21 dias"*. El check contaba las filas correctamente; lo que no existia era la
consecuencia que el mensaje afirmaba.

**Los dos lados del yield estaban igual.** `agg/arriendo.comparables_desde_duckdb` leia
`fetched_at` — pero solo para convertir CLP a UF del dia, nunca para filtrar. Una mediana de
arriendo armada con avisos de mayo le pone arriendo de mayo a una compra de hoy, y el
arriendo es el numerador. Cuatro meses viejo en las dos puntas.

**Y `faltantes` tambien**, por la misma razon por la que ya comparte `unidad_rankeable` con
el emparejamiento: una unidad que el ranking no va a tomar tampoco se "desbloquea"
recolectando arriendo. Contarla infla el objetivo y manda la recoleccion a la comuna
equivocada. Es el mismo agujero #3 de `alcance.py`, en otra columna.

criterio_de_aceptacion:
  - [x] `emparejar` filtra por frescura, con descarte propio `desactualizada`
  - [x] `comparables_desde_duckdb` tambien, con descarte `desactualizado`
  - [x] `faltantes.diagnosticar` usa el MISMO criterio
  - [x] `ahora` entra por argumento en los tres (§11: nada de reloj del sistema en la logica)
  - [x] El mensaje de "cero rankeables" nombra la causa que DOMINA, no una plausible
  - [x] Test que ata el gate con el ranking: si alguien saca el filtro, el gate sigue
        anunciando lo mismo y ese test es el que falla


## T-045 · El ancla externa quedo ciega justo donde entraron los datos nuevos
estado: hecha
agente: auditor-datos
fase: 3
gate: make gates

**Octavo caso de la familia.** Al abrir fase 3, las tres primeras del ranking del
31-ago-2026 pasaron a ser de **Antofagasta y La Serena**. El gate imprimio:

    ✓ reconciliacion_arriendo: medianas dentro de ±25%  (4 comunas comparadas)

Las cuatro comparadas: la-florida, nunoa, san-miguel, santiago. **Ninguna de ellas esta en
el podio.** `UF_M2_REFERENCIA` y `ARRIENDO_UF_M2_REFERENCIA` salen de la tabla Colliers de
`docs/00-hallazgos.md`, que cubre la RM y nada mas. Los dos checks hacian `continue` en
silencio sobre las comunas sin referencia, asi que la falta de control se leia como control
cumplido — y se leia asi con mas fuerza cuanto mas nuevo era el mercado.

**No se inventa una referencia** (§3.2). Lo que cambia es que la ausencia se nombra: los dos
checks devuelven ALERTA listando las comunas que no pudieron verificar, en vez de OK contando
solo las que si.

Y como cuando el ancla externa no llega el unico control que queda es mirar los avisos, se
agrego `cli comparables <microzona> --tipologia --rango`: lista los avisos detras de una
mediana con su URL. Las seis columnas de procedencia del §3.1 existian para esto y estaban
guardadas sin manera de leerlas.

criterio_de_aceptacion:
  - [x] `ancla_externa_uf_m2` nombra las comunas sin referencia, con ALERTA
  - [x] `reconciliacion_arriendo` idem
  - [x] Una desviacion medida sigue ganandole a la falta de ancla (FALLA > ALERTA)
  - [x] Contraprueba: con todo verificado sigue en OK, para que la alerta no sea ruido
  - [x] `cli comparables` abre la caja de una mediana


## T-046 · Gran Concepcion trajo avisos y no produjo una sola celda
estado: pendiente
agente: analista-arriendo
fase: 3
depende_de: [T-045]
gate: make gates

La corrida de arriendo de fase 3 desbloqueo **La Serena, Antofagasta y Coquimbo** —
`la-serena/avenida-del-mar 2D2B 50-70` con n=77 es hoy la celda MAS PROFUNDA del sistema.
De **Gran Concepcion no entro nada**: cero celdas utiles, cero unidades en el top 15.

Y Concepcion es la que importa: el §10 la declara *"el unico mercado del alcance donde el pie
de equilibrio baja a ~32%"*. Las otras dos entraron y dan pies de 45-50%, o sea que la parte
verificable de la tesis de fase 3 **todavia no se verifico**.

Las cinco comunas respondieron 48 tarjetas cada una en `probar-comunas`, asi que el slug
`bio-bio` esta bien y el portal tiene oferta. Las hipotesis, en orden de costo:
  1. La conurbacion reparte los avisos entre cinco comunas y muchas microzonas, y ninguna
     celda `(microzona, tipologia, rango)` junta 8. Se ve con `cli faltantes --comuna
     concepcion` y se arregla con mas paginas.
  2. Las microzonas de Concepcion no se estan asignando y los avisos caen en `sin_microzona`.
  3. El colector recolecto arriendo solo en algunas de las ocho comunas.

criterio_de_aceptacion:
  - [x] Saber CUAL de las tres es, con el conteo que lo demuestra — `cli embudo` lo responde
        con el mismo recorrido que arma el ranking, no con una consulta paralela
  - [ ] Al menos una celda de Gran Concepcion con n>=8
  - [ ] El pie de equilibrio real de Concepcion contrastado contra el ~32% del §10, con el
        numero que salga — sea el que confirma la tesis o el que la desmiente

herramienta_construida: >
  `cli embudo [--comuna X | --fase N]`. Muestra, por comuna, cuantas unidades salieron en
  cada paso hasta el ranking, y **dice explicitamente cuando una comuna tiene CERO filas en
  la base** — que es un diagnostico distinto de "se cayeron en un filtro" y lleva a una
  accion distinta: recolectar VENTA, no arriendo. Antes esa pregunta no se podia contestar
  sin escribir SQL a mano, y `faltantes --comuna concepcion` respondia "0 celdas" para
  inmediatamente listar nunoa y antofagasta, que se lee como si fueran de Concepcion.


## T-047 · Verificar la mediana de arriendo de Antofagasta
estado: pendiente
agente: analista-arriendo
fase: 3
depende_de: [T-045]

`antofagasta/la-chimba · 1D1B · 35-50 m²` da **UF 16,15/mes con n=11**: mas que un 2D2B de
La Serena (14,68) y que uno de San Miguel (12,21). En UF/m2 son **0,394 contra 0,222** de San
Miguel — 77% mas — con precios de VENTA por m2 casi iguales (41,2 vs 38-42 UF/m2).

Puede ser exactamente lo que dice la investigacion: el §10 predice cap rate neto 4,5% para
Antofagasta, el mas alto del pais, y una ciudad minera tiene arriendos altos de verdad. La
razon medida (1,77) esta cerca de la que predice el §10 (4,5/2,8 = 1,6). Pero **n=11, sin
ancla externa** (T-045), y la unidad que encabeza el ranking con eso —MLC-4427322266— da
yield 11,48% y flujo POSITIVO, que es la misma forma que tenia la cesion de promesa.

RESUELTO en parte, y el resultado NO fue el esperado. De los 11 avisos, **seis declaran
"amoblado" o "semi amoblado" en su propio titulo** y uno dice `gc incl`. Pero sacarlos NO
mueve la mediana: sigue en $660.000. Los amoblados de Antofagasta no cobran mucho mas.

**El problema es otro y es peor:** la celda solo llega a los 8 comparables del §7.3 contando
productos que no son el mismo producto. Sin los amoblados quedan **5**, y con 5 no rankea
nada. El umbral estaba satisfecho en el papel y vacio en el fondo.

Y no es local: medido sobre 2.835 comparables, la proporcion de amoblados va de **1,5% en
San Miguel a 21,6% en Las Condes**, con nunoa en 13,8% y la celda de Antofagasta en 64%. O
sea que el sesgo **no es parejo entre comunas**, y un ranking cuya gracia es comparar comunas
entre si estaba comparando mezclas distintas de dos productos.

criterio_de_aceptacion:
  - [x] Mirar los 11 avisos y descartar amoblados — `cli comparables` los marca
  - [x] Los amoblados declarados salen de la mediana (`quality/comparabilidad.py`)
  - [ ] Un ancla externa para Antofagasta y La Serena en `docs/00-hallazgos.md`, con fuente
        y fecha, o la constancia de que no existe una publicada
  - [ ] Rehacer el ranking sin amoblados y ver que queda de Antofagasta y La Serena
  - [ ] `la-serena/avenida-del-mar` (n=77, la celda mas profunda del sistema) es la avenida
        de la PLAYA: revisarla con la misma lupa antes de creerle nada


## T-048 · Cuatro de las cinco comunas de Gran Concepcion nunca se recolectaron
estado: pendiente
agente: colector
fase: 3
gate: make gates

`cli embudo --fase 3` lo dijo sin ambiguedad: **chiguayante, concepcion, hualpen y
san-pedro-de-la-paz tienen CERO filas** en `fact_unidad_venta`. No se cayeron en un filtro.
Nunca llegaron. De Gran Concepcion solo entro **talcahuano**.

Y talcahuano entro raro: de sus 232 unidades, **103 salen por `fuera_de_rango`** — o sea mas
de 140 m2 utiles — y 129 por `sin_comparables`. **Cero rankean.** Una proporcion asi de
departamentos sobre 140 m2 en Talcahuano no es creible; la URL del colector fija
`/departamento/`, asi que no son casas. Sospecha principal: en regiones la tarjeta trae
superficie TOTAL o de terreno donde en la RM trae la util, y el parser toma la que hay.

Las dos cosas se investigan juntas porque las dos apuntan al colector, no al modelo.

DIAGNOSTICO. El colector **si** recolecto las ocho: la segunda corrida reporto 3.812 avisos,
que son 8 comunas x 5 paginas x 2 operaciones x 48. La perdida es en la CARGA.

`cargar_avisos` tenia una rama que tiraba las ventas publicadas EN PESOS:

    elif a.operacion == "venta":
        omitidas.append(a.portal_id)   # y un logging.info que nadie ve

No habia columna donde ponerlas —`precio_uf` es la unica de precio— y el §11 prohibe que la
capa de carga convierta, porque la UF del dia vive en otra tabla. Medido sobre el corpus de
mayo, en la RM eso son **143 unidades, el 6,1% de las ventas**, y muy desparejo entre comunas:
0,2% en Las Condes contra 11,9% en Santiago. La proporcion sube donde el stock es mas barato,
que es exactamente el stock que este inversionista puede comprar.

**El costo real no era el 6,1%: era que una comuna entera podia esfumarse sin que nadie se
enterara.** En regiones la publicacion en pesos es mucho mas comun que en la RM.

ARREGLADO: se guarda `precio_clp` como viene y la conversion pasa al emparejamiento, con la
UF del dia del aviso — que es exactamente como el arriendo ya funcionaba. El valor convertido
es `D` (§3.2), no `V`; el §12 excluye los `E` del ranking, no los `D`, asi que compite.

criterio_de_aceptacion:
  - [x] Saber por que faltaban, con la evidencia: no era el colector, era la carga
  - [x] Las ventas en pesos dejan de tirarse; `precio_clp` en el esquema y en `migrar()`
  - [x] Conversion con la UF del dia del aviso, no con la de hoy; sin ella se descarta y se
        cuenta (`sin_uf_del_dia`), no se convierte con la de otro dia
  - [ ] Confirmar sobre la base del usuario que las cuatro comunas aparecen
  - [ ] Explicar los 103 `fuera_de_rango` de talcahuano mirando avisos concretos
  - [ ] Si el m2 de regiones es superficie total, el parser lo distingue o lo deja `ND`
        (§3.2: no se imputa) — nunca lo mezcla con m2 utiles


## T-049 · El portal servia la MISMA pagina a cinco comunas distintas
estado: hecha
agente: colector
fase: 3
gate: make gates

`cli autopsia venta_concepcion` y `cli autopsia venta_talcahuano` devolvieron salidas
**identicas byte a byte**: mismos 513/512/514/512/524 KB, mismas 47/48/47/47/48 tarjetas,
mismo reparto UF/CLP, mismo todo.

Los blobs tienen nombres distintos y **el mismo contenido**. El portal ignoro el filtro de
comuna y sirvio la misma pagina a las cinco comunas del Gran Concepcion. Al cargarlas todas
traen los mismos `MLC-`: la primera se lleva las filas y las otras cuatro quedan en CERO —
no por falta de datos, sino porque son los mismos datos. Y **cual gana depende del orden de
carga**, que es exactamente por que talcahuano "existia" antes del rebuild y chiguayante
despues. No hubo intercambio de etiquetas: hubo una sola comuna contada cinco veces.

Tambien explica la mediana de 136 m2 de "chiguayante": no son departamentos de Chiguayante,
es lo que el portal sirve cuando no aplica el filtro.

**El noveno check vacio, y es el que autorizo toda la corrida.** `probar-comunas` dijo
*"8/8, 48 tarjetas cada una"*. Contaba el numero correcto sobre el documento equivocado.
Contar resultados nunca podia detectar esto.

criterio_de_aceptacion:
  - [x] `probar-comunas` compara los `MLC-` entre comunas, no solo los cuenta
  - [x] `cli crudo` detecta blobs con el mismo `sha_contenido` bajo busquedas distintas — el
        sha estaba en cada `.meta.json` desde siempre y nadie lo miraba
  - [x] Funcion pura `busquedas_que_devuelven_lo_mismo`, con el caso real como test
  - [x] Contraprueba: un aviso mal geolocalizado no dispara el check
  - [ ] Encontrar el `region_slug` que el portal SI respeta para Bio-Bio, o registrar que no
        existe y sacar Gran Concepcion del alcance hasta tener otra fuente


## T-050 · Auditoria de codigo: tres cosas que el orden o el denominador arruinaban
estado: hecha
agente: auditor-datos
fase: 2
gate: make gates

Recorrido buscando el patron que este proyecto ya pago nueve veces: **el check que no mide**.
Tres hallazgos, y uno mio propio durante la misma auditoria.

**1. El selftest corria DESPUES de cargar.** En `recolectar-portal`:

    corrida.filas_insertadas = pb.cargar_en_duckdb(con, tarjetas)   # carga
    rep = col.selftest(docs, filas_corrida_anterior=anterior)       # despues verifica

El §7.1 pone el selftest para que un colector roto **no contamine**. Su detector de parser
roto —"el conteo no cayo >30% vs la ultima corrida exitosa"— se enteraba con los datos ya
adentro: el gate era un informe de danos. Ahora corre antes y, en rojo, no se carga nada.
Los blobs quedan en `data/raw/`, asi que si el arreglo es del parser se recuperan con
`rebuild --from-raw` sin volver a pedirle nada al portal.

**2. `cobertura["precio"]` era una tautologia.** Valia `1.0 if tarjetas else 0.0`. Toda
`Tarjeta` que llega al final tiene precio **por construccion** —el parser descarta antes la
que no lo tiene—, asi que ese 100% no podia bajar nunca, ni cuando el portal cambiara el
selector de precio y se perdiera la mitad del lote. Ahora el denominador son las tarjetas
que hay en el HTML (`contar_tarjetas_en_html`). Medido sobre el corpus de mayo: **98,7%**.

**3. El colector no detectaba por si mismo lo de T-049.** `probar-comunas` ya compara los
avisos entre comunas, pero eso es un comando aparte que hay que acordarse de correr.
`recolectar-portal` ahora hace la misma comparacion sobre lo que acaba de bajar y se detiene
antes de cargar.

**Y un error mio, corregido dentro de la auditoria.** Midiendo el punto 2 obtuve "cobertura
real 49,4%" y estuve a punto de reportar que el parser perdia la mitad de los avisos. Estaba
forzando `operacion="venta"` sobre blobs de arriendo, asi que `plausible()` descartaba los
arriendos por caer fuera del rango de precio de venta. Con la operacion sacada de la URL real
da 98,7%. La medicion mal hecha se parecia mucho a un hallazgo.


## T-051 · El ancla externa de VENTA nunca corrio, y comparaba dos productos
estado: hecha
agente: auditor-datos
fase: 2
gate: make gates

**El decimo caso de la familia**, y este ni siquiera se ejecutaba. El §7.3 declara:

> **Ancla externa**: el UF/m2 mediano de cada comuna se compara contra la tabla de referencia
> Colliers. Desviacion >20% ⇒ **falla el gate**.

`checks.correr()` acepta `mediana_uf_m2_por_comuna` desde siempre y **`cli gates` nunca se lo
pasaba**. El gate mas fuerte del contrato del lado de la venta —el unico que contrasta nuestro
pipeline contra un tercero— no se evaluo jamas. Lo mismo con `comparables_suficientes`.

**Y conectarlo tal cual habria sido peor que no tenerlo.** `UF_M2_REFERENCIA` es explicitamente
*"UF/m2 de venta de departamento NUEVO"* y hoy el **100%** de `fact_unidad_venta` es usado.
Medido sobre el corpus, el usado esta sistematicamente por debajo:

    nunoa       -1%        macul       -13%       las-condes  -16%
    san-miguel -17%        santiago    -28%

Santiago habria fallado el gate por una razon **real y explicable** —su stock es mas antiguo—,
no por un error del pipeline. Un gate que falla por algo estructural entrena a ignorarlo, que
es lo peor que le puede pasar a un gate.

Es el error del amoblado (T-047) del lado de la venta: **dos productos distintos bajo un solo
numero.** Alla eran arriendo pelado y amoblado; aca, departamento nuevo y usado.

Asi que se conecta comparando lo comparable: el ancla mira el stock **nuevo**, y el descuento
del usado va aparte como **medicion informativa** (`MARCA`), que informa sin aprobar ni
reprobar. Un numero que no puede fallar no debe presentarse como un gate que paso.

Efecto inmediato: el ancla dice *"ninguna comuna tiene referencia con que comparar"*, porque
no hay una sola unidad nueva. **Es la respuesta correcta y vuelve a poner T-925 al frente.**

criterio_de_aceptacion:
  - [x] `cli gates` pasa las medianas por comuna; el ancla del §7.3 se evalua
  - [x] Compara stock nuevo contra referencia de stock nuevo
  - [x] `descuento_stock_usado`: medicion aparte, MARCA, no aprueba ni reprueba
  - [ ] Cerrar el ancla de verdad requiere stock nuevo en la base (T-925)
  - [ ] `comparables_suficientes` sigue sin conectarse a `cli gates`


## T-053 · El gasto comun de `params.yml` esta 30-40% alto, y casi no importa
estado: pendiente
agente: analista-arriendo
fase: 2
depende_de: [T-022]

Assetplan entrega `min_ggcc` real por tipologia. Contra los m2 medianos de nuestros propios
avisos, el supuesto `E` de Estacion Central (2.200 CLP/m2/mes) esta **30-40% por encima**:
el edificio Alto Conde da 1.286-1.714.

**Y medirlo antes de alarmarse era lo correcto.** Sobre `MLC-4420580204` (30 m2), bajar el
supuesto de 2.200 a 1.500 mueve el pie de flujo cero de **29,8% a 29,1%**: siete decimas.
La razon esta en el §14 del contrato — **los gastos comunes los paga el arrendatario, salvo
en vacancia**—, asi que el modelo solo los carga el 8% del tiempo. El parametro es casi
inerte para este inversionista y el modelo ya lo trataba bien.

No se cambia sobre un edificio: `min_ggcc` es un **minimo** ("desde") y un multifamily
profesional no representa a un edificio antiguo de administracion individual.

criterio_de_aceptacion:
  - [ ] `min_ggcc` de los 176 edificios del sitemap, no de uno
  - [ ] Contrastado por comuna contra `params.yml`, con n por comuna
  - [ ] Si se cambia el supuesto, la sensibilidad va en el mismo commit — un `E` que se
        mueve sin medir cuanto mueve el ranking viola el §8.4


## T-054 · Los dos supuestos de seguro estan altos, y este si mueve la aguja
estado: pendiente
agente: motor-financiero
fase: 2

El usuario simulo en Santander la unidad real (UF 880 sobre UF 1.100, 30 anios, tasa fija
4,65%, CAE 5,28%). El simulador da **UF 4,8776** de dividendo. Descompuesto:

    anualidad francesa pura, UF 880 a 4,65%      UF 4,5376   $185.457
    seguros implicitos de Santander              UF 0,3400   $ 13.896
    seguros de nuestros supuestos E              UF 0,6160   $ 25.177

**Nuestros dos `E` juntos cobran 81% mas que la cotizacion real**, y son $11.281 al mes —
cerca de la mitad del deficit mensual de esta unidad. El efecto sobre la metrica insignia:

    seguros                                   dividendo   pie 0
    params.yml hoy (0,00035 + 0,00028)         $210.634   32,5%
    piso del rango declarado (0,0002+0,0002)   $201.642   29,2%
    lo que cotiza Santander                    $199.353      —

**Ni siquiera el PISO del rango declarado llega a la cotizacion real.** O sea que el rango
del §3.2 esta mal calibrado, no solo el valor central. Y el error va contra el usuario: el
modelo muestra cada oportunidad PEOR de lo que es.

**No se cambia sobre una cotizacion.** Es un banco, un perfil y una propiedad, y no sabemos
como se reparte entre desgravamen e incendio — que dependen de cosas distintas (edad del
deudor y saldo insoluto el primero, tasacion el segundo).

### Ampliado con 13 cotizaciones (compara.cl, 31-ago-2026)

El usuario trajo el mismo credito cotizado en 13 productos. Descompuesto contra la anualidad
francesa pura, 10 de ellos incluyen seguros en el dividendo:

    rango observado    0,2264 - 0,3666 UF/mes
    mediana            0,3190 UF/mes  = $13.038
    simulador Santander 0,3400 UF/mes

    mi supuesto        0,6160 UF = $25.177   -> +93% sobre la mediana
    piso de mi rango   0,3960 UF = $16.185   -> SIGUE arriba del maximo observado

Once puntos independientes, todos por debajo del piso del rango declarado. **El rango esta mal
calibrado, no solo el valor.** Valores que reproducen la mediana manteniendo la proporcion:

    seguro_desgravamen_pct_mensual_saldo:       0,00035 -> 0,000181
    seguro_incendio_sismo_pct_mensual_tasacion: 0,00028 -> 0,000145

**Dos cotizaciones (BancoEstado y Scotiabank Universal) dan carga de seguro ~0.** No es que
no cobren: es que ese dividendo los muestra aparte. Se excluyeron de la mediana por eso, y
haberlas promediado habria bajado el supuesto de mas.

criterio_de_aceptacion:
  - [ ] El desglose de "Ver seguros asociados y gastos operacionales" del simulador, que da
        la separacion desgravamen / incendio con cifras
  - [x] Al menos una segunda cotizacion — hay 13
  - [ ] Si se cambian, la sensibilidad sobre el ranking completo va en el mismo commit (§8.4):
        baja el dividendo de TODAS las unidades, asi que mueve todo el ranking a la vez
  - [ ] Revisar tambien el rango, no solo el valor: un rango que no contiene el dato real es
        un rango mal declarado

## T-055 · El primer dividendo no esta en el modelo
estado: pendiente
agente: motor-financiero
fase: 3

Santander cotiza dividendo $199.365 y **primer dividendo $310.743** — un 56% mas. Es normal
(intereses devengados desde el desembolso hasta el primer vencimiento, mas seguros del
periodo), pero el modelo no lo tiene: asume 360 cuotas iguales.

Impacto real: son ~$111.000 una sola vez. No mueve la TIR de forma apreciable, pero **si
mueve la plata sobre la mesa el primer mes**, que es justo cuando el comprador esta mas
apretado. Va en la ficha de la unidad, no en el score.


## T-056 · compara.cl no coincide con el simulador del propio banco
estado: pendiente
agente: fuente-scout
fase: 3

Mismo credito, mismo dia, mismo banco, dos cifras:

    Santander en compara.cl        4,10%
    Santander en su propio simulador 4,65%     55 pb de diferencia
    BancoEstado en compara.cl      4,54%
    BancoEstado medido en agosto   4,29%       25 pb de diferencia

**compara.cl es una herramienta de tamizaje, no una cotizacion.** Sirve para armar una lista
corta; no para poner un numero en `params.yml`. El §13.1 ya dice lo mismo de los yields
publicados: recalcular siempre desde el dato, nunca copiar la cifra que alguien publica.

Y trae una inconsistencia aritmetica propia: Consorcio se lista a 25 anios con un dividendo
que corresponde a 30. Descomponerlo da carga de seguro NEGATIVA, que no existe.

criterio_de_aceptacion:
  - [ ] `docs/01-fuentes.md` registra compara.cl como tamizaje, con la discrepancia medida
  - [ ] Ninguna tasa de `params.yml` sale de compara: solo de simuladores del banco o de la
        CMF, con fecha y captura
## T-014b · Puente manzana → microzona
estado: pendiente
agente: geo-microzonas
fase: 2
depende_de: [T-014]
criterio_de_aceptacion:
  - cada microzona del alcance queda mapeada a un conjunto de manzanas (map_microzona_manzana)
  - riesgo_microzona se calcula desde dim_manzana (desocupacion censal, % arriendo, densidad depto) y deja de estar inerte
  - el metodo del puente queda en un ADR: las microzonas NO tienen poligono; opciones — poligonos de barrios MELI, geocodificar avisos y usar sus manzanas, o dibujar a mano las del alcance
gate: make gates

## T-922b · Estaciones EN CONSTRUCCION ausentes de la cosecha OSM
estado: pendiente
agente: colector
fase: 2
depende_de: [T-922]
criterio_de_aceptacion:
  - la corrida real trajo 130 estaciones y CERO en construccion: los nodos de L7 y de la
    extension L6 no calzan con los tags de la consulta actual (railway=construction/proposed
    + station=subway). Investigar el tagging real en OSM (pueden ser ways/relations o
    construction=station) y ampliar la consulta
  - mientras tanto el factor_en_construccion esta ocioso y Recoleta/Cerrillos no reciben
    su catalizador — el sesgo es de SUBmedicion, no de invento
gate: make gates

## T-922c · 126 estaciones operativas vs ~143 reales del Metro
estado: pendiente
agente: colector
fase: 2
depende_de: [T-922]
criterio_de_aceptacion:
  - identificar las ~17 faltantes (probablemente mapeadas como way/relation y no como node)
  - la consulta las trae o el ADR documenta por que no
gate: make gates

## T-925 · Colector de proyectos NUEVOS via cotizador PlanOK
estado: reencuadrada  # la cotizacion exige datos personales: masivo descartado (ADR 010 adenda)
agente: colector
fase: 2
depende_de: []
criterio_de_aceptacion:
  - hoy el ranking es 100% usado: el subsidio de la Ley 21.748 (6,7 puntos de pie) jamas se
    ha aplicado a una unidad real — es la brecha estrategica del producto
  - paso 1 (probar-planok): capturar respuestas reales del cotizador a la zona cruda desde
    la maquina del inversionista, resolver el payload de datos.php (unico ❓ del docs/01 B.1)
  - paso 2: ADR con robots + legal_tier, parser con selftest, >=300 unidades con precio
    por unidad en la RM
gate: make gates

## T-925c · Precios de proyectos nuevos via wp-json / JSON-LD de inmobiliarias
estado: en_curso  # colector construido (ADR 011); falta la corrida viva local y sumar dominios
agente: colector
fase: 2
depende_de: []
criterio_de_aceptacion:
  - sonda contra 2-3 inmobiliarias reales (Socovesa primero) — HECHO: 4 corridas de
    probar-wpjson fijaron la ruta sitemap → REST wp/v2/proyecto/<id> → HTML del proyecto
  - robots verificado por dominio; raw primero; parser con selftest — HECHO (ADR 011,
    sources/wpjson_inmobiliarias.py, fixture del 03-sep-2026)
  - hallazgo que reencuadra el criterio: Socovesa publica "Precio desde" POR MODELO, no
    precio por unidad → filas con precio_es_desde=TRUE, EXCLUIDAS del ranking (B1).
    Aportan censo de oferta nueva + señal de baja de precio, no unidades rankeables.
  - pendiente: `recolectar-wpjson` en vivo desde la maquina local (selftest de muestra
    viva) y sumar dominios WP hasta cubrir oferta nueva RM relevante
gate: make gates
