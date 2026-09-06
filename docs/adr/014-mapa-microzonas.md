# ADR 014 · El mapa de microzonas: geometría vía shapely, no vía DuckDB spatial — T-928

**Fecha:** 06-sep-2026 · **Estado:** aceptada

## Contexto

`dim_microzona.geom` estaba vacía en las 165 microzonas: sin polígono, el §7.5 no podía
cumplirse ("el mapa dibuja las microzonas") y `capacidades.mapa` quedaba fijo en `False`
(T-027, ADR 007). T-014b ya había resuelto la mitad del problema — el puente Voronoi
manzana → microzona (`map_microzona_manzana`) y el riesgo por microzona — pero nunca
escribió geometría de vuelta a `dim_microzona`: solo dejó el CAMINO para hacerlo.

`dim_manzana.geom_wkb` (el polígono censal por manzana, cargado por `cli ingerir-censo`)
y `dim_manzana`/`map_microzona_manzana` están **vacías en este contenedor**: el GeoParquet
del Censo 2024 vive solo en la máquina del usuario (§10 del `CLAUDE.md` no lo dice, pero
es la realidad operativa medida). Este ADR describe cómo T-928 se construyó y se probó
sin ese dato real, contra fixtures sintéticas.

## Decisión 1 — la unión y la simplificación corren en `shapely`, no en SQL de DuckDB

El §5 del contrato pide `duckdb spatial` (`ST_Union`, `ST_Simplify`) para esto. Se probó:
`INSTALL spatial` devuelve **HTTP 403** contra `extensions.duckdb.org` a través del proxy
de este entorno, y `~/.duckdb/extensions/` está vacío — no hay forma de bajarla acá.
`db.aplicar_esquema` ya sabía degradar (`GEOMETRY` → `BLOB` si la instalación falla,
D-desde T-014), así que el patrón de "intenta, si no se puede sigue andando" ya existía;
lo que faltaba era una ruta de cálculo que NO depend­iera de que la extensión cargara.

`shapely` ya es dependencia del proyecto (§5, para `geo/`) y hace exactamente lo que se
necesita: `shapely.ops.unary_union` + `Geometry.simplify(tolerancia, preserve_topology=True)`,
serializado a WKB de vuelta. `geo/microzona_geom.py` hace TODO el cálculo geométrico ahí,
y solo decide, mirando el tipo real de columna (`information_schema.columns`), CÓMO
escribir el resultado:

- columna `GEOMETRY` (la extensión cargó en algún proceso anterior sobre esta base):
  `UPDATE ... SET geom = ST_GeomFromWKB(?)` — el WKB de shapely, ahora tipado nativo.
- columna `BLOB` (degradada, como en este contenedor): `UPDATE ... SET geom = ?` directo.

Las dos rutas producen el **mismo polígono**; la diferencia es solo el tipo de columna.
`Servicio.geometria_microzonas()` lee con el mismo criterio a la inversa (`ST_AsWKB` si
es espacial, la columna cruda si no), y traduce a GeoJSON con `shapely.geometry.mapping`,
nunca con `ST_AsGeoJSON` — por la misma razón: no depender de que la extensión esté
cargada en el proceso que sirve la API.

**Cuándo revisar esto:** si algún día el proxy permite instalar `spatial`, vale la pena
medir si mover la unión a SQL (sobre postgres/duckdb, en la propia base) es más rápido
para miles de microzonas — hoy no hay ese volumen para justificar el cambio.

## Decisión 2 — la tolerancia de simplificación es una constante de código, no un `E` de `params.yml`

`TOLERANCIA_GRADOS = 0.00035` (~35-40 m en la latitud de Chile) vive en
`geo/microzona_geom.py`. El §3.2 exige que todo supuesto `E` esté declarado en
`params.yml` con rango de sensibilidad — pero esto no es un supuesto de **mercado**: no
mueve ningún número financiero, solo cuánto detalle visual sirve un polígono al
navegador. Es una decisión de rendering, análoga a un `line-width` de estilo, y vive en
código por eso.

## Decisión 3 — el mapa sirve DOS veces `pie_flujo_cero_minimo`: plano para MapLibre, envuelto para el popup

Se intentó primero envolver `pie_flujo_cero_minimo` en el objeto `{valor, evidence_level,
unidad}` (`cifra()`, el mismo patrón que el resto de la API) DENTRO de las `properties`
del GeoJSON. **No sobrevive**: MapLibre tilea cualquier fuente GeoJSON con `geojson-vt`
internamente, incluso una fuente 100% local sin red — y esa capa de tileado solo
transporta valores primitivos por feature. Medido en vivo con Playwright: el objeto
anidado llega al otro lado sin `.valor` ni `.evidence_level` legibles (se degrada a algo
sin esas propiedades), y el popup mostraba `—` con una etiqueta `ND` que era mentira: el
dato SÍ existía, solo que MapLibre lo había mudo.

La solución: el GeoJSON de `/api/mapa` lleva `pie_flujo_cero_minimo` como número plano
(o `null`) — el único canal que una expresión de `paint` puede leer para colorear la
capa. El objeto CON evidencia se pide aparte, a `/api/microzonas` (JSON plano de siempre,
nunca tocado por MapLibre), y el tablero lo cruza por `microzona_id` al construir el
popup. Dos peticiones en paralelo (`Promise.all`) en vez de una, pero el §7.5 —ningún
número visible sin su nivel de evidencia— se cumple donde importa: en lo que el usuario
lee, no en el canal de estilo interno.

## Decisión 4 — un solo `navegador` de Playwright por sesión de tests

Al agregar `pagina_mapa` (una segunda página E2E, para la base con geometría) junto a la
`pagina` ya existente, cada una abriendo y cerrando su propio `sync_playwright()`, **todos
los tests que corrían después del primer módulo empezaron a fallar** con `"using
Playwright Sync API inside the asyncio loop"`. Playwright Sync API no tolera bien un
segundo `sync_playwright()` en el mismo proceso tras cerrar el primero. La solución no es
reordenar tests (frágil, se rompe de nuevo con el próximo fixture de página) sino
compartir UN solo navegador de alcance `session` (`tests/integration/test_dashboard_e2e.py`)
y que cada fixture de página solo abra/cierre su propia pestaña.

## Qué se prueba acá y qué prueba el usuario en su máquina

- **Acá (fixtures sintéticas):** `tests/unit/test_microzona_geom.py` (el cargador, contra
  polígonos WKT chicos y `dim_manzana`/`map_microzona_manzana` armadas a mano),
  `tests/unit/test_api.py` (el endpoint `/api/mapa`, con una base que sí tiene 2
  microzonas con geometría) y `tests/integration/test_dashboard_e2e.py::test_el_mapa_dibuja_las_microzonas`
  (Playwright real, canvas de MapLibre + fuente GeoJSON cargada + popup con evidencia).
- **En la máquina del usuario:** `cli ingerir-censo` (si no corrió) y `cli puente-censo`
  ya pueblan `dim_manzana`/`map_microzona_manzana` reales. Después:

  ```
  uv run python -m flujocero.cli cargar-geometria-microzonas
  ```

  reconstruye `dim_microzona.geom` desde el Censo real. Es un derivado puro (igual que
  `map_microzona_manzana`): se puede correr las veces que haga falta, nunca duplica ni
  inventa, y dice cuántas microzonas quedaron con y sin geometría.
