# ADR-004 · Auditoría del proyecto anterior (`investop`)

**Estado:** auditado · **Fecha:** 28-ago-2026 · **Tarea:** T-916

## Qué es

3.036 líneas de Python del proyecto anterior del usuario, más **3,2 GB de HTML scrapeado**
de Portal Inmobiliario entre el **30-abr y el 5-may de 2026**. Stack: Playwright + selectolax
+ SQLite + Streamlit + statsmodels.

**No usa Apify.** El usuario recordaba mal: son cero referencias en todo el repo. Es Playwright
con un perfil persistente de Chromium autenticado con su cuenta de MercadoLibre.

## Lo que se midió, no lo que se supone

Se corrió el parser heredado sobre los 6.229 archivos. Resultado: **6.180 parseables,
5.870 unidades únicas** (2.629 de arriendo, 3.240 de venta).

Cobertura de campos sobre una muestra aleatoria de 300, verificada:

| Campo | Cobertura |
|---|---|
| precio, m² útiles, dormitorios, baños, comuna | **100%** |
| microzona (barrio) | **99,3%** |
| estacionamientos | 90,9% |
| antigüedad | 82,2% |
| gastos comunes | 77,4% |

Por comuna, y contra el alcance de `config/zonas.yml`:

| Comuna | Total | Arriendo | Venta | En alcance |
|---|---|---|---|---|
| Ñuñoa | 1.041 | 501 | 540 | **Fase 1** |
| San Miguel | 960 | 523 | 437 | **Fase 1** |
| Macul | 957 | 507 | 450 | **Fase 2** |
| Santiago | 954 | 525 | 428 | **Fase 2** |
| Providencia | 985 | 369 | 616 | excluida (ticket) |
| Las Condes | 957 | 201 | 756 | excluida (ticket) |

**Cuatro de seis comunas están en alcance.**

### El gate de comparables (§7.3, n ≥ 8)

- Por **microzona**: 59 de 81 microzonas llegan a n ≥ 8 de arriendo (**73%**), cubriendo
  2.495 unidades.
- Por **(microzona, dormitorios)** —la clave real del contrato—: 93 de 256 combinaciones
  (**36%**), cubriendo 2.136 unidades.

No es cobertura total, pero es un piso real donde hoy hay cero.

## Los seis hallazgos

### H1 · El camino permitido alcanza para la vivienda usada

Las páginas de búsqueda con sufijo `_Desde_` son **las que el `robots.txt` de Portal
Inmobiliario permite** (§13.6). Se verificó su contenido: de 48 tarjetas por página,
**38 son unidades individuales con precio exacto en UF, dormitorios, baños, m² útiles y
barrio**. Las otras 10 son proyectos con "Desde UF X" y rangos.

> `Departamento en venta | UF 3.200 | 2 dormitorios | 2 baños | 58 m² útiles | El Llano, San Miguel`

**Consecuencia: para el stock usado no hace falta invocar D-016.** Todo lo que el motor
necesita para rankear está en la ruta permitida. La autorización queda como respaldo, no como
la vía principal — que es exactamente el orden que manda el §3.5.

### H2 · La ficha de detalle (prohibida) aporta tres cosas, y una importa mucho

Lo que sólo está en la página de detalle: **antigüedad** (82%), **gastos comunes** (77%) y la
descripción. La antigüedad es justo lo que T-911 necesita para saber si la ventana de rebaja
DFL2 de contribuciones sigue abierta.

Es una decisión con matiz, no un todo o nada: se puede rankear con la ruta permitida y bajar a
la ficha sólo para las unidades que ya quedaron arriba en el ranking. Decenas de fichas en vez
de miles.

### H3 · El DFL2 no está en los avisos

**16 de 5.870 listings mencionan DFL2. El 0,3%.**

`config/inversionista.yml` tiene `exigir_dfl2: true` como exclusión dura. Aplicado sobre datos
de portal, **excluiría el 99,7% del universo** — y no porque las unidades no sean DFL2, sino
porque el aviso no lo dice.

Esto confirma el §2.5 del contrato al pie de la letra: *"el DFL2 se verifica en la escritura o
el certificado municipal, nunca en lo que diga el vendedor."* El dato tiene que venir del SII
o de la municipalidad. Mientras tanto, `exigir_dfl2` no puede aplicarse contra datos de aviso
sin vaciar el ranking. → T-917.

### H4 · El valor irrepetible es el delta de precio

5.870 unidades con su precio al 4-may-2026. **Un aviso de portal desaparece cuando se vende:
esa foto no se puede volver a tomar.**

Volviendo a scrapear las mismas comunas hoy tenemos, el primer día, qué unidades siguen a la
venta cuatro meses después y **cuáles bajaron de precio** — que el §11 declara señal de compra
y para lo que el esquema ya tiene SCD tipo 2 (`valid_from`/`valid_to`). Normalmente eso exige
meses de recolección. Acá ya está la mitad hecha.

### H5 · El código anterior resolvió algo que al motor actual le falta

`finanzas/metricas.py` aplica la rebaja DFL2 de contribuciones **sólo si
`antiguedad_anos < 20`**. Es exactamente T-911, que abrí ayer como deuda del motor nuevo.
El código viejo ya tenía esa distinción y el nuevo no.

También trae un **modelo hedónico OLS** (`modelo/regresion.py`):
`log(precio) ~ log(m2) + dormitorios + baños + antigüedad + estacionamiento + bodega + C(microzona)`,
con intervalos de confianza y agrupación de microzonas con menos de 15 observaciones. Es
mejor que una mediana simple cuando los comparables escasean — que es el 64% de los casos
según H0. Vale la pena portarlo.

### H6 · Usa evasión de detección, y eso D-016 no lo cubre

El scraper corre con:

```python
user_agent = "Mozilla/5.0 (Windows NT 10.0...) Chrome/124.0.0.0 Safari/537.36"
args = ["--disable-blink-features=AutomationControlled"]
```

Un User-Agent de Chrome falso y una bandera cuyo único propósito es ocultar que es un
navegador automatizado. Además se autentica **con la cuenta personal de MercadoLibre del
usuario** para pasar el `suspicious-traffic-frontend`.

D-016 dice, textual: *"la aprobación cubre recolectar, no cubre esquivar"*. Esto es esquivar.
Y tiene un riesgo que no es legal sino práctico y personal: **lo que se expone no es una IP,
es su cuenta.** Si MercadoLibre lo detecta, le suspenden la cuenta con la que compra.

Recomendación: reemplazar por el `USER_AGENT` honesto que ya usa Flujo Cero, sacar la bandera,
y no scrapear autenticado. Si sin eso el portal bloquea, el §3.5 ya dice qué significa: estás
en la categoría equivocada, replantea. Y H1 dice que no hace falta.

## Lo que se le escapó al trabajo anterior

El usuario pidió explícitamente esta parte.

| # | Problema | Por qué importa |
|---|---|---|
| 1 | **`uf_clp: float = 38_000.0` hardcodeado** | La UF hoy está en ~40.800. Todo arriendo publicado en UF quedó convertido con un **7% de error**, y silencioso |
| 2 | **`float` para dinero** | El §11 exige `Decimal`. Con floats el error se acumula sin avisar |
| 3 | **Cero columnas de procedencia** | Ninguna fila puede entrar a la base de Flujo Cero tal como está (§3.1) |
| 4 | **`fecha_scraping = date.today()`** | Sin zona horaria y sin hora. El §11 exige `datetime` con `tzinfo=UTC` |
| 5 | **`tests/scrapers/` vacío** | El README promete *"HTML guardado para tests de parseo"*. No existe. El parser no tiene ni un test, y es la pieza que más se rompe |
| 6 | **Plazo 25 años, tasa 4,5%, pie 20% como defaults** | Números de otro momento, sin fuente citada |
| 7 | **Contribuciones con tramos propios** (0,998% / 1,164% sobre avalúo en UF) | No calzan con los del contrato (0,893% / 1,042% en pesos). Uno de los dos está mal y hay que reconciliarlo |
| 8 | **`_price_uf` decide punto/coma por heurística** | Es la misma familia del bug de 1000x que apareció en el colector de la CMF. En formato chileno el punto es **siempre** separador de miles |
| 9 | **Sin deduplicación proyecto ↔ unidad** | Un proyecto aparece como tarjeta y también como unidades sueltas; se cuentan dos veces |
| 10 | **Sin detección de parser roto** | No compara el conteo contra la corrida anterior (§7.1). Si el portal cambia una clase CSS, baja cero avisos y nadie se entera |

## Qué se toma y qué no

**Se toma:**
- Los **6.180 HTML** como fixtures de test (`tests/integration/` está vacío hoy) y como
  la foto de precios del 4-may-2026.
- La **estrategia de URL `_Desde_`** y los selectores validados: son el activo real.
- El **diccionario de microzonas** — 81 barrios reales con sus nombres tal como los usa el
  portal. Es la Capa 2 del §4 sin tocar ninguna API, justo cuando la de MELI devolvió 403.
- El **modelo hedónico OLS** y la **ventana de antigüedad del DFL2**.
- La **detección de bloqueo que aborta la corrida** en vez de fallar en silencio: es buena
  ingeniería y calza con el §11.

**No se toma:**
- La evasión de detección (H6).
- El scraping autenticado con la cuenta personal.
- Los `float`, el modelo `Listing` sin procedencia, y el esquema SQLite: Flujo Cero ya tiene
  DuckDB con las seis columnas.
- Los supuestos financieros hardcodeados: `config/params.yml` es la fuente única.

## Veredicto

El trabajo anterior es serio. No es un prototipo: tiene detección de bloqueo, caché por día,
rate limit aleatorio de 3–5 s, separación de parseo puro y 32 tests en el módulo financiero.
Lo que le faltaba no era rigor de ingeniería sino el contrato de procedencia, y eso es
justamente lo que Flujo Cero ya trae.

**Adelanta trabajo real:** T-013 (microzonas) deja de depender de la API caída de MELI,
T-021/T-022 arrancan con 2.629 comparables de arriendo en vez de cero, T-911 tiene una
implementación de referencia, y aparece un delta de precios de cuatro meses que no se puede
comprar ni reconstruir.
