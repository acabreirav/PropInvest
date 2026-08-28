# CLAUDE.md — Flujo Cero

> Contrato operativo para agentes que trabajan en este repositorio.
> Léelo completo antes de tocar código. Si algo aquí contradice tu intuición, gana este archivo.
> Última calibración de datos: **28-ago-2026**.

---

## 1. Qué es este proyecto

**Flujo Cero** es un sistema de inteligencia de inversión inmobiliaria residencial en Chile.
Su trabajo es responder, con evidencia y no con opinión, una sola pregunta:

> **¿Qué departamentos NUEVOS a la venta hoy en Chile, financiados con el subsidio a la tasa
> (Ley 21.748 ampliada) y garantía FOGAES, producen el mejor retorno ajustado por riesgo —
> y cuáles de ellos llegan a flujo de caja no negativo con el pie que el inversionista puede poner?**

Tres bases de datos y un motor:

| Componente | Qué produce |
|---|---|
| **B1 · Oferta de venta** | Universo de unidades de proyectos nuevos con precio real por unidad (no "desde"), tipología, m², piso, orientación, estacionamiento, bodega, fecha de entrega. |
| **B2 · Comparables de arriendo** | Mediana de arriendo por **microzona × tipología × rango de m²**, con conteo de avisos activos (proxy de saturación) y vacancia. |
| **B3 · Contexto** | UF, tasas por banco, contribuciones, gastos comunes, transacciones reales (CBR), demografía censal por manzana, distancia a Metro. |
| **Motor financiero** | Dividendo, NOI, cap rate, DSCR, CoC, TIR real apalancada, VAN, arriendo de equilibrio, **pie mínimo para flujo ≥ 0**, y un score de oportunidad. |

Entregable final: **DuckDB + API FastAPI + dashboard web** (ranking, filtros, ficha de unidad, mapa),
más export XLSX/PDF.

---

## 2. Los cinco hallazgos que definen el producto

Estos salieron de la investigación previa (ver `docs/00-hallazgos.md`). **No los re-descubras: úsalos.**

1. **El tope subió a UF 6.000.** La ampliación de la Ley 21.748 se promulgó el **26-ago-2026**:
   tope UF 4.000 → **UF 6.000**, cupos 50.000 → **80.000**, vigencia hasta **31-may-2028**.
   El subsidio son **60 puntos base** sobre la tasa (Decreto 180 exento, art. 1), no "1 punto".
   El resto de la rebaja que cita la prensa viene del efecto FOGAES sobre el spread del banco.

2. **La disputa sobre "primera vivienda" no afecta a este inversionista — y le abre una puerta.**
   El Decreto 180 art. 3 (tramo general) exige *"primera **venta** de la vivienda"* — condición del
   **inmueble**. Hacienda y la guía Ley Fácil de BCN dicen "primera vivienda", condición del
   **comprador**. **Nuestro inversionista no tiene propiedades: califica bajo ambas lecturas.**
   El escenario base pasa a ser `con_subsidio` (ver `config/inversionista.yml`).
   → **Consecuencia estratégica:** el art. 4 reserva **6.000 cupos a viviendas ≤ UF 3.000 exigiendo
   primera vivienda del solicitante**. Es un tramo del que la mayoría de los inversionistas queda
   fuera y él no. **Verificar con el banco si su tasa es mejor** (ver `docs/05-decisiones.md` D-009):
   si lo es, apuntar a tickets ≤ UF 3.000 domina en las dos dimensiones — mejor yield y menor costo
   de fondos. `sin_subsidio` se sigue calculando como contraste, no como caso base.

3. **El mandato original "pie 10–20% + flujo no negativo" es aritméticamente imposible en el
   Gran Santiago hoy.** Con yields brutos reales de 3,5–4,3% en stock nuevo y dividendo a 30 años,
   el **pie de equilibrio está en 34%–47%**. El producto no debe fingir lo contrario.
   Lo que el producto hace es: (a) reportar el **pie mínimo para flujo cero** de cada unidad como
   métrica de primera clase, (b) rankear por **déficit mensual mínimo en UF** cuando el pie está fijo
   en 10–20%, y (c) señalar los mercados donde el pie de equilibrio sí baja (Concepción, La Serena,
   Antofagasta: cap rate neto 4,0–4,5% vs 2,8% de Santiago).

4. **La comuna es la unidad de análisis equivocada.** Dentro de Estación Central, el mismo producto
   renta ~$300.000 en Santa Isabel y ~$350.000 a pocas cuadras: **17% de brecha intracomunal**,
   más que toda la diferencia entre comunas. En Viña del Mar el p75 de UF/m² vale 83% más que el p25.
   → La clave primaria de todo comparable es `(microzona, tipologia, rango_m2)`, **nunca `comuna`**.

5. **DFL2 vale más que el subsidio en valor presente, y es el objetivo declarado.**
   Depto ≤140 m² acogido a DFL2: arriendo **exento de impuesto a la renta**, 50% de rebaja de
   contribuciones por 10–20 años, exento de IVA de arriendo, exento de impuesto de herencias.
   Límite: **2 por persona natural**; la persona jurídica **no accede**.
   El inversionista tiene **0 de sus 2 cupos usados**. Cuántos quiere usar **no está
   definido** (corregido el 28-ago-2026: dos es el tope legal, no su objetivo).
   → `exigir_dfl2: true` en `config/inversionista.yml`: **solo se rankean unidades acogidas a DFL2
   con ≤140 m² útiles**; el resto queda excluido por regla dura, no por puntaje. Y el DFL2 se
   verifica en la escritura o el certificado municipal, nunca en lo que diga el vendedor.

---

## 3. No negociables

Estas reglas son gates de merge. Un PR que las viole se rechaza aunque los tests pasen.

### 3.1 Procedencia o no existe
Toda fila de dato de mercado lleva, sin excepción:
`source_id`, `source_url`, `fetched_at` (UTC ISO-8601), `parser_version`, `raw_blob_path`, `robots_snapshot_sha`.
Si no puedes poblar esas seis columnas, **no insertes la fila**.

### 3.2 Nunca inventes una cifra
Ningún número de mercado puede nacer de un LLM. Solo de: (a) una fuente citada, (b) un cálculo
determinístico sobre datos (a). Todo valor derivado se marca en la columna `evidence_level`:

| Valor | Significado |
|---|---|
| `V` | Verificado — vino de una fuente, con URL y fecha |
| `D` | Derivado — cálculo explícito sobre valores `V` (la fórmula queda en el código, no en un prompt) |
| `E` | Estimado — supuesto de modelo, **debe** estar declarado en `config/params.yml` con rango de sensibilidad |
| `ND` | No disponible — NULL explícito. **Prohibido imputar en silencio.** |

Un `E` sin entrada en `params.yml` es un bug. Un `ND` rellenado con una media es un bug grave.

### 3.3 Todo en UF, siempre
El crédito es en UF; el arriendo se pacta en pesos y se reajusta una vez al año por IPC.
Modelamos **en UF, términos reales**. Y aplicamos la erosión intra-anual que casi todos omiten:

```
arriendo_uf_promedio_anual = arriendo_uf_inicial / (1 + π/2)     # π=0,03 → factor 0,985
```

Si tu modelo asume arriendo constante en UF, **sobreestima el flujo ~1,5% anual, para siempre**.
Corolario que debe estar en la UI: **con crédito en UF, la inflación no licúa la deuda.** El hedge
es del activo, no del pasivo. Es la falacia más repetida del rubro chileno; no la reproduzcas.

### 3.4 Cero datos personales
Persiste: precio, m², dormitorios, baños, piso, orientación, comuna, microzona, coordenadas,
nombre del proyecto, nombre de la inmobiliaria (persona jurídica).
**No persistas:** nombre de corredor, email, teléfono, RUT de persona natural.
La **Ley 21.719** entra en plena vigencia el **01-dic-2026** con multas de hasta 20.000 UTM y
2–4% de ingresos anuales, y **el hecho de que un dato sea público no lo saca de su ámbito**.
Los emails de contacto para outreach viven **solo** en `state/outreach/contacts.json`, fuera de la
base analítica, cifrados en reposo, con opt-out registrado.

### 3.5 API oficial antes que scraping. Siempre.
Orden de preferencia obligatorio para cualquier fuente nueva:
`API oficial con auth` → `endpoint JSON público (wp-json, sitemap, cotizador)` → `HTML permitido por robots`
→ `HTML prohibido por robots` (**requiere aprobación humana explícita en `docs/05-decisiones.md`**).
Antes de escribir un scraper, `python -m flujocero.sources.robots_check <url>` debe pasar.
Un scraper que necesita proxies residenciales para funcionar es una señal de que estás en la
categoría equivocada: replantea o compra el dato.

### 3.6 Idempotencia y reproducibilidad
Todo colector escribe primero a la **zona cruda** (`data/raw/{source_id}/{yyyy}/{mm}/{dd}/*.json.gz`)
y solo después parsea. Re-ejecutar un colector sobre el mismo día no debe duplicar filas
(clave natural + `ON CONFLICT DO UPDATE`). Cualquier tabla analítica debe poder reconstruirse
desde la zona cruda con `make rebuild`.

### 3.7 Español para el dominio, inglés para el código
Nombres de columnas, entidades y documentación en **español** (`precio_uf`, `dormitorios`, `microzona`).
Nombres de funciones, clases y variables internas en **inglés**. Comentarios en español.
No traduzcas términos con significado legal: `DFL2`, `FOGAES`, `UF`, `rol SII`, `pie`, `dividendo`.

---

## 4. Arquitectura de datos — seis capas

```
CAPA 1 · ANCLA DETERMINÍSTICA        (riesgo legal nulo — empieza aquí)
  SII catastro masivo (BRORGA2441N / BRORGA2441NL_NAC, TAB, sin headers)
      → rol, avalúo fiscal, m² terreno, m² construidos por línea, año, material, calidad
  INE Censo 2024 manzanas (GeoParquet, 189 variables socioeconómicas)
  → dim_predio, dim_manzana

CAPA 2 · MICROZONA                   (el puente comercial ↔ oficial)
  MercadoLibre classified_locations/countries/CL → cascada country→state→city→neighborhood
      = el diccionario de barrios que efectivamente usan los listings
  ⋈ espacial con manzanas INE
  + SII "área homogénea" (valor m² oficial por zona, vía BaseAPI)
  → dim_microzona, map_microzona_manzana

CAPA 3 · OFERTA DE VENTA             (precio de lista, por unidad)
  api.mercadolibre.com site MLC       → stock, geo-bbox, search_type=scan para >1000
  cotizador.saladeventasdigital.com   → PlanOK: precio POR UNIDAD, estacionamiento, bodega
  /wp-json/wp/v2/proyecto + JSON-LD   → inmobiliarias (Socovesa publica priceCurrency "CLF" = UF)
  Pabellón, Enlace Inmobiliario       → cobertura de proyectos nuevos, sin anti-bot
  PDFs de lista de precios            → parser dedicado (ver §7.4)
  → fact_unidad_venta

CAPA 4 · ARRIENDO REAL               (el numerador del yield)
  Assetplan edificios.xml (175 edificios, lastmod diario, robots PERMITE ClaudeBot)
  MELI MLC arriendo                   → comps de mercado abierto
  Chilepropiedades (Crawl-delay: 2)   → relleno
  → fact_arriendo_comp, agg_arriendo_microzona

CAPA 5 · TRANSACCIÓN REAL            (calibración lista → cierre)
  Data Inmobiliaria (tier gratuito: 346 comunas, export Excel)
  DataBAM (CBR, 20+ comunas RM, con precio y coordenadas — de pago)
  → fact_transaccion, factor_gap_lista_cierre

CAPA 6 · FINANCIERO
  CMF api-sbifv3 (UF, UTM, IPC, TMC) + Gael Cloud como fallback (máx 9 req/10 s)
  CMF tasas hipotecarias XLS (articles-46417_recurso_1.xls)
  SII contribuciones: 0,893% hasta $220.398.431 · 1,042% sobre el excedente
  → dim_tiempo_financiero
```

**La métrica objetivo** se calcula siempre así:

```
yield_bruto = (arriendo_mediano_microzona_tipologia × 12) / precio_venta_corregido
```

donde el arriendo viene de **Capa 4** (arriendo efectivo, no precio pedido) y el precio de
**Capa 3 corregido por el gap lista→cierre de Capa 5**.

---

## 5. Stack

| Capa | Elección | Por qué |
|---|---|---|
| Lenguaje | Python 3.11+, gestionado con `uv` | ecosistema de datos y scraping |
| HTTP | `httpx` (async) + `tenacity` | backoff exponencial con jitter |
| HTML | `selectolax` (rápido) / `beautifulsoup4` (tolerante) | |
| JS rendering | `playwright` chromium — **solo cuando esté justificado en el ADR de la fuente** | |
| PDF | `pdfplumber` + `camelot` para tablas; OCR con `ocrmypdf` solo si el PDF es imagen | |
| Almacén | **DuckDB** (`data/flujocero.duckdb`) sobre lago Parquet | analítico, un archivo, cero servidor |
| Validación | `pydantic` v2 (esquemas de entrada) + checks propios en `src/flujocero/quality/` | |
| Geo | `geopandas`, `shapely`, `duckdb spatial` | |
| API | `FastAPI` + `uvicorn` | |
| Frontend | HTML único + `Alpine.js` + `MapLibre GL` + `Chart.js`, servido por FastAPI | testeable con Playwright, sin build step |
| Tests | `pytest`, `pytest-asyncio`, `playwright` para E2E | |
| Orquestación | `Makefile` + `prefect` opcional en fase 3 | |
| Lint | `ruff` + `mypy --strict` en `src/flujocero/finance/` | el motor financiero va tipado estricto |

Comandos canónicos (definidos en el `Makefile`):

```
make setup        # uv sync + playwright install chromium
make ingest       # corre todos los colectores habilitados en config/fuentes.yml
make build        # raw → parquet → duckdb, con validaciones
make score        # motor financiero sobre todo el universo
make test         # pytest -q  (unit + golden + integration marcados)
make gates        # TODOS los gates del §7. Es lo que decide si el loop avanza.
make serve        # API + dashboard en localhost:8000
make report       # export XLSX + PDF del ranking actual
make rebuild      # reconstruye todo desde data/raw/
```

---

## 6. Layout del repositorio

```
flujo-cero/
├── CLAUDE.md                     ← este archivo
├── docs/
│   ├── PRD.md                    ← requisitos completos, criterios de aceptación
│   ├── 00-hallazgos.md           ← digest de la investigación de mercado, con fuentes
│   ├── 01-fuentes.md             ← catálogo de fuentes con endpoints verificados
│   ├── 02-modelo-financiero.md   ← fórmulas explícitas
│   ├── 03-microzonificacion.md
│   ├── 04-legal.md               ← robots, T&C, Ley 21.719, jurisprudencia
│   ├── 05-decisiones.md          ← ADRs. Toda decisión no obvia se registra aquí.
│   └── adr/NNN-titulo.md
├── config/
│   ├── params.yml                ← TODOS los supuestos numéricos del modelo. Fuente única.
│   ├── zonas.yml                 ← comunas y microzonas del alcance, por fase
│   └── fuentes.yml               ← registro de fuentes: estado, robots, cadencia, riesgo
├── schema/schema.sql             ← DDL DuckDB
├── src/flujocero/
│   ├── sources/                  ← un módulo por fuente. Interfaz común (§7.1)
│   ├── geo/                      ← microzonificación, joins espaciales, distancia a Metro
│   ├── finance/                  ← motor. mypy --strict. Sin I/O. Puro y testeable.
│   ├── quality/                  ← reglas de calidad y reconciliación
│   ├── api/                      ← FastAPI + static/
│   └── cli.py
├── tests/
│   ├── golden/                   ← casos de oro del motor financiero (§7.2)
│   ├── unit/
│   └── integration/              ← contra fixtures HTTP grabadas, nunca contra la red viva
├── state/
│   ├── BACKLOG.md                ← el tablero del harness (§8)
│   ├── RUNLOG.md                 ← append-only: qué corrió, qué encontró, qué falló
│   └── outreach/                 ← contactos y bitácora de emails. FUERA de la base analítica.
└── data/                         ← gitignored
    ├── raw/                      ← zona cruda inmutable
    ├── parquet/
    └── flujocero.duckdb
```

---

## 7. Cómo se valida el trabajo — los gates

`make gates` corre todo lo siguiente. **El harness solo avanza a la siguiente tarea si pasa.**
Si un gate falla, la tarea vuelve al backlog con el error pegado, no se marca como hecha.

### 7.1 Gate de fuente (`quality/source_contract.py`)
Todo módulo en `sources/` implementa:

```python
class Source(Protocol):
    id: str                      # slug estable, ej. "meli_mlc_venta"
    legal_tier: Literal["api_oficial","json_publico","html_permitido","html_prohibido"]
    def robots_ok(self) -> RobotsVerdict: ...
    def collect(self, scope: Scope) -> Iterator[RawDoc]: ...     # escribe a data/raw/
    def parse(self, doc: RawDoc) -> list[BaseModel]: ...         # pydantic
    def selftest(self) -> SelfTestReport: ...                    # ver abajo
```

`selftest()` es obligatorio y debe verificar, contra una **fixture grabada** y contra **una muestra
viva de ≤5 documentos**:
- el parser extrae ≥95% de los campos requeridos,
- los tipos y rangos son plausibles (precio_uf entre 500 y 60.000; m² entre 15 y 400;
  dormitorios 0–6; UF/m² entre 20 y 200),
- el conteo de resultados no cayó >30% vs la última corrida exitosa (**detector de parser roto**),
- `robots_ok()` devuelve `allowed` para el `legal_tier` declarado.

Un colector cuyo `selftest` falla queda `disabled: true` en `config/fuentes.yml` con la razón,
y se abre una tarea en el backlog. **No se borra el dato viejo.**

### 7.2 Gate del motor financiero (`tests/golden/`)
El motor es puro (sin I/O) y va con `mypy --strict`. Los casos de oro son ficheros YAML
`entrada → salida esperada` calculados a mano y revisados. Mínimo obligatorio:

1. **Dividendo francés**: UF 4.500 a 30 años al 3,40% → verificar contra una calculadora
   independiente implementada por separado en `tests/golden/reference_impl.py`
   (dos implementaciones, distinto autor lógico, deben coincidir a 1e-6).
2. **Pie de equilibrio**: con yield bruto 4,0% y tasa 4,10%, `pie_minimo_flujo_cero` ∈ [0,40; 0,43].
   Con yield 3,6% y tasa 4,85%, ∈ [0,50; 0,53]. *(Anclas derivadas en la investigación.)*
3. **Erosión intra-anual**: con π=3%, `arriendo_uf_promedio/arriendo_uf_inicial` = 0,985 ± 0,001.
4. **DFL2 on/off**: activar DFL2 debe subir el NOI exactamente en
   (impuesto de renta evitado + 50% de contribuciones), ni un peso más.
5. **TIR real**: una unidad comprada y vendida al mismo precio real, sin flujo, sin costos,
   debe dar TIR real = 0,000 ± 1e-9.
6. **Invariante de coherencia**: `cap_rate ≥ 0` y `NOI ≤ PGI` siempre, para 10.000 casos
   generados con `hypothesis`.
7. **Conservación**: `BTCF·12 + servicio_deuda_anual + opex_anual == EGI_anual` (identidad contable).

### 7.3 Gate de datos (`quality/checks.py`)
- **Cobertura**: ≥ el 80% de las unidades de venta tienen `precio_uf` real (no "desde") y
  microzona asignada. Si no, el ranking se marca `parcial` en la UI.
- **Reconciliación de arriendo**: para cada microzona con ≥8 comparables, la mediana debe estar
  dentro de ±25% del benchmark publicado más cercano en `docs/00-hallazgos.md`.
  Fuera de eso → alerta, no borrado.
- **Detección de outliers**: `precio_uf/m²` fuera del rango [p1, p99] de su microzona se marca
  `sospechoso=true` y se excluye del cálculo de medianas, pero se conserva.
- **Frescura**: ninguna fila usada en el ranking puede tener `fetched_at` > 21 días.
- **Anti-duplicado**: dos unidades con mismo `(proyecto_id, numero_unidad)` colapsan;
  dos avisos con misma `(direccion_normalizada, m2, dormitorios, precio)` en ≤30 días se deduplican.
- **Ancla externa**: el UF/m² mediano de cada comuna se compara contra la tabla de referencia
  Colliers de `docs/00-hallazgos.md`. Desviación >20% ⇒ falla el gate.

### 7.4 Gate del parser de listas de precios (PDF)
Los PDFs de sala de ventas chilenos tienen convenciones hostiles, verificadas en un ejemplo real:
- mezclan **UF** (precio unidad, estacionamiento desde 360 UF, bodega desde 90 UF) con
  **CLP** (reserva $400.000, cuotas del pie);
- a menudo **no dan el precio total**, sino *"promedio 3500 en 36 cuotas de $270.000"* → hay que despejarlo;
- la **reserva se descuenta del pie**, no es una línea adicional;
- estacionamiento y bodega son **líneas de precio independientes**, no incluidas.

El parser debe: detectar moneda por token, reconstruir el total desde `pie% + n cuotas × monto`
cuando falte, separar unidad principal de secundarios, y capturar la **fecha de vigencia**
(las listas caducan y en UF además se reajustan solas).
Gate: sobre el corpus en `tests/fixtures/pdf/`, ≥90% de unidades extraídas con precio total correcto.

### 7.5 Gate del dashboard
Playwright E2E: carga en <3 s con 10.000 unidades, el ranking respeta el filtro de pie,
el mapa dibuja las microzonas, la ficha de unidad muestra **las seis columnas de procedencia**,
y ningún número aparece sin su `evidence_level`.

### 7.6 Gate de auto-crítica (obligatorio antes de cerrar cualquier tarea grande)
Lanza el subagente `verificador` con instrucción adversarial:
*"Busca la forma en que este cambio produce un número incorrecto o una oportunidad falsa.
Asume que hay un error. Encuéntralo."*
Su reporte se pega en `state/RUNLOG.md`. Si encuentra algo material, la tarea no se cierra.

---

## 8. El harness — cómo trabajas de forma autónoma

### 8.1 El tablero
`state/BACKLOG.md` es la fuente de verdad. Formato por tarea:

```markdown
## T-042 · Colector PlanOK cotizador
estado: pendiente | en_curso | bloqueada | hecha
agente: scraper-builder
fase: 2
depende_de: [T-011, T-013]
paraleliza_con: [T-043, T-044]
criterio_de_aceptacion:
  - selftest() pasa contra fixture y muestra viva
  - ≥300 unidades con precio por unidad en la RM
  - ADR escrito en docs/adr/ con robots + legal_tier
gate: make gates
```

### 8.2 El ciclo
Cada iteración del harness:

1. **Leer** `state/BACKLOG.md` y elegir las tareas `pendiente` cuyas dependencias estén `hecha`.
2. **Agrupar en olas paralelas**: todas las tareas que comparten `paraleliza_con` y no tocan
   los mismos archivos salen en **una sola llamada con múltiples subagentes**.
3. **Ejecutar**. Cada subagente trabaja en su propio worktree cuando toca código compartido.
4. **Validar**: `make gates`. Nunca marques `hecha` sin gates verdes.
5. **Auto-crítica** (§7.6) si la tarea es de fase completa o toca el motor financiero.
6. **Registrar** en `state/RUNLOG.md`: qué corrió, cuántas filas, qué falló, qué se aprendió.
7. **Reponer el backlog**: todo hallazgo nuevo (endpoint roto, fuente nueva, dato faltante)
   se convierte en una tarea, con su criterio de aceptación.
8. **Commit** por tarea, mensaje `T-042: <qué cambió> [gates: verde]`.

### 8.3 Reglas de paralelización
- **Sí paralelizar**: colectores de fuentes distintas, parsers independientes, investigación,
  verificación adversarial de hallazgos distintos.
- **No paralelizar**: cambios al esquema de la base, al motor financiero, o a `config/params.yml`.
  Esos van en serie, uno a la vez, con gate entre medio.
- **Regla de oro**: dos agentes nunca editan el mismo archivo en la misma ola.
  Si el plan lo requiere, es señal de que la tarea está mal cortada.
- Ola típica: **4–6 subagentes**. Más de 8 degrada la calidad de la revisión.

### 8.4 Cuándo detenerse y preguntar
Detente y escribe la pregunta en `docs/05-decisiones.md` si:
- una fuente exige romper `robots.txt` o los T&C;
- hay que **pagar** por un dato (DataBAM, Data Inmobiliaria plan pago, proxies);
- vas a **enviar emails** a terceros (siempre requiere aprobación humana, ver §9);
- un supuesto `E` mueve el ranking en >10% de posiciones;
- descubres que un hallazgo del §2 es falso.

---

## 9. Outreach por email — reglas estrictas

El proyecto tiene permiso del usuario para contactar salas de venta e inmobiliarias pidiendo
listas de precios. Ese permiso es acotado:

- **Nunca se envía nada sin aprobación humana del lote.** El agente **redacta y encola**
  en `state/outreach/queue.jsonl`; una persona aprueba y recién ahí se envía.
- **Identificación honesta.** El correo dice quién eres y qué buscas: un inversionista particular
  pidiendo lista de precios y disponibilidad. **Prohibido** suplantar a un corredor, a una empresa,
  o insinuar un mandato que no existe.
- **Máximo 40 envíos por día, 1 por proyecto, 1 recordatorio a los 7 días. Y se acabó.**
- Todo destinatario que pida no ser contactado entra en `state/outreach/optout.json` **para siempre**.
- Los adjuntos entran a `data/raw/email/` y se parsean con el pipeline de PDF (§7.4).
  El **cuerpo del email y los datos del remitente no entran a la base analítica** (§3.4).
- Canal preferido, por tasa de respuesta observada: **cotizador PlanOK** (genera cotización formal
  automática, sin hablar con nadie) > formulario web de la inmobiliaria > WhatsApp del proyecto >
  email corporativo genérico. Los portales **no exponen email**: el contacto va por su mensajero interno.

---

## 10. Alcance geográfico por fases

Definido en `config/zonas.yml`. Resumen del razonamiento (detalle en `docs/00-hallazgos.md`):

**Fase 1 — pilotos de yield y riesgo contrastados (validan el pipeline completo):**
`San Miguel` (yield 4,06%, **vacancia multifamily 3,2% — la más baja de la RM**, normativa
restrictiva que impide sobreoferta) · `La Florida` (yield 4,06–4,22%, mercado profundo, **pero
4.810 unidades multifamily entrando**: exige microzona) · `Ñuñoa` (demanda más profunda de la RM,
plusvalía 5,5% anual, **pero vacancia MF 12,2%** y ticket que casi no cabe bajo UF 6.000).

**Fase 2 — expansión RM:** `Cerrillos` (único catalizador cercano: extensión L6 a Lo Errázuriz,
46% de avance, apertura 2027) · `La Cisterna` · `Macul` · `Santiago Centro` (máxima liquidez pero
cap rate neto 2,8% y **10.900 unidades con permiso sin iniciar obras**) · `Independencia` ·
`Recoleta` (mayor alza de la RM +9,6% a/a, eje L7 2028) · `Estación Central` (**solo eje 5 de Abril,
nunca Santa Isabel**; el nuevo PRC de 12 pisos corta la oferta futura).

**Fase 3 — el mercado de flujo:** `Gran Concepción` (cap rate neto 4,0% vs 2,8% de Santiago;
82% de las ventas bajo UF 4.000; **el único mercado del alcance donde el pie de equilibrio baja a ~32%**)
· `La Serena` · `Antofagasta`.

**Excluidos de v1, con razón registrada:** Viña del Mar (absorción 24,6 meses, la peor del Gran
Valparaíso), Valparaíso (deterioro estructural del stock), San Joaquín (vacancia MF 42,1%),
Las Condes/Vitacura/Lo Barnechea/Providencia (ticket sobre el tope, yields 3,0–3,8%),
Cerro Navia/Lo Prado/La Pintana (los "13,3% de rentabilidad" son stock usado de UF 700–1.400;
no existe producto nuevo ahí).

---

## 11. Convenciones de código

- Un módulo por fuente, nombre `sources/<slug>.py`, slug igual al `source_id`.
- Funciones puras en `finance/`. **Cero I/O, cero fechas del sistema, cero `random` sin semilla.**
  Todo parámetro entra por argumento. Esto es lo que hace testeable el motor.
- Todos los montos monetarios como `Decimal` en el motor; `float` solo en la capa de presentación.
- Fechas siempre `datetime` con `tzinfo=UTC` en la base; se convierte a `America/Santiago` solo en la UI.
- Nada de `try/except: pass`. Un error de parseo se registra en `parse_errors` con el documento crudo.
- Un colector nunca borra: escribe una versión nueva con `valid_from` / `valid_to` (SCD tipo 2)
  para poder responder *"¿cuándo bajó el precio de esta unidad?"* — que es señal de compra.
- `ruff format` antes de cada commit. `mypy --strict src/flujocero/finance`.

---

## 12. Definición de "oportunidad"

El score no es una nota mágica; es una suma ponderada explícita, con cada componente auditable
en la ficha de la unidad. Ponderadores en `config/params.yml`, no en el código.

| Componente | Peso inicial | Qué mide |
|---|---|---|
| `deficit_flujo_mensual_uf` | 30% | Cuánto hay que poner de tu bolsillo cada mes al pie objetivo. Menos es mejor. |
| `pie_minimo_flujo_cero` | 20% | Qué pie necesitarías para no poner nada. La métrica honesta. |
| `tir_real_apalancada_10a` | 20% | Retorno total, en términos reales |
| `riesgo_microzona` | 15% | Saturación de arriendo, vacancia, stock entrando, absorción |
| `catalizador` | 10% | Distancia a Metro operativo o en construcción **con fecha creíble** (≤3 años) |
| `descuento_vs_microzona` | 5% | UF/m² de la unidad vs mediana de su microzona |

**Penalizaciones duras (excluyen del ranking, no restan puntos):**
precio > UF 6.000 · m² útiles > 140 (pierde DFL2) · microzona marcada como
saturada en `config/zonas.yml` · sin comparables de arriendo suficientes (n < 8) ·
dato de precio con `evidence_level` = `E`.

**La vivienda usada dejó de ser exclusión el 28-ago-2026 (D-015).** Compite en el ranking
como escenario, no como igual: el subsidio a la tasa es condición del **inmueble** —el
Decreto 180 art. 3 exige *"primera venta"*— así que un usado se evalúa siempre a tasa sin
subsidio, y el motor se lo niega en `finance/modelo.tasa_aplicable` aunque el escenario pida
`con_subsidio`. No lo decide `params.yml`: ahí solo se abre la puerta al usado.
El **Subsidio Tramo 4.000 (DS1 Tramo 4)** sí admite usadas, pero obliga a habitar la vivienda
y prohíbe arrendarla 5 años: es incompatible con este inversionista. No lo re-descubras.

---

## 13. Errores que ya cometimos — no los repitas

1. **Confiar en el yield publicado por las tasadoras.** Colliers Tasaciones publica 5,5–6,5%;
   al dividir los precios y arriendos de los propios reportes de Colliers sale 3,5–4,2%,
   y Assetplan con 2.628 arriendos reales reporta cap rates netos de 2,8–3,0%.
   **Recalcula siempre desde precio y arriendo. Nunca copies un yield.**
2. **Confundir cap rate bruto con neto.** El "cap rate" de AP Capital es **neto de ~13–14%**
   de vacancia y opex: para llevarlo a bruto, divide por 0,87. Verifica la aritmética de toda
   cifra publicada antes de usarla como ancla.
3. **Tomar rankings de "comunas más rentables" al pie de la letra.** Los 13,3% de Cerro Navia
   corresponden a stock usado de UF 700–1.400. **No existe producto nuevo a ese precio.**
4. **Tratar "Ley 21.748" como el número de la ley ampliada.** Varios medios reciclan mal ese número;
   la ley original es de may-2025. El número de la norma de agosto 2026 **debe verificarse en
   LeyChile / Diario Oficial** antes de citarlo en la UI.
5. **Asumir que la inflación ayuda.** Con crédito en UF, no licúa nada. Ver §3.3.
6. **Scrapear Portal Inmobiliario en HTML.** `robots.txt` bloquea `/propiedades/` y permite solo
   `/*_Desde_` (listados paginados). El detalle está prohibido y hay WAF con 403 desde datacenter.
   **Usa la API oficial de MercadoLibre (site MLC). Es la misma data, por la puerta.**

---

## 14. Glosario mínimo

**UF** unidad de fomento, reajustada por IPC diariamente · **pie** enganche/down payment ·
**dividendo** cuota mensual del crédito · **FOGAES** Fondo de Garantías Especiales, permite 90% LTV ·
**DFL2** régimen tributario de viviendas ≤140 m² útiles, máx. 2 por persona natural ·
**rol SII** identificador fiscal del predio (comuna-manzana-predial) · **CBR** Conservador de Bienes
Raíces · **absorción** meses para agotar el stock al ritmo de venta actual · **en verde** comprado
en construcción · **en blanco** comprado en planos · **gastos comunes** los paga el arrendatario,
salvo en vacancia · **microzona** barrio o submercado dentro de una comuna: **la unidad de análisis real**.
