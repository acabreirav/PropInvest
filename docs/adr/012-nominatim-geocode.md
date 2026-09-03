# ADR 012 · Geocodificación de proyectos vía Nominatim (OSM) — T-931c

**Fecha:** 03-sep-2026 · **Estado:** aprobada (deriva de T-931b, pedida por el usuario:
"mientras más volumen mejor" + informe con nuevas compitiendo)

## Contexto

La sección "nuevas evaluadas al desde" del informe exige microzona por coordenadas
(el §2.4 prohíbe la mediana comunal como comparable). Solo Fundamenta y RVC publican
GeoCoordinates: 217 unidades quedaban `sin_geo` el 03-sep-2026.

## Decisión

Geocodificar con **Nominatim** (`nominatim.openstreetmap.org/search`), la API de
búsqueda de OSM. `legal_tier: json_publico`, datos ODbL — el mismo proveedor y licencia
que ya usamos para las estaciones de Metro (ADR implícito en T-922).

**Condiciones de la política de uso** (operations.osmfoundation.org/policies/nominatim/),
codificadas en `geo/geocodificar.py`:
- máximo absoluto **1 request/segundo** (`PAUSA_S = 1.1`, solo los tests la bajan);
- **User-Agent identificable** (el mismo del colector de Metro);
- volumen acotado: solo proyectos de oferta nueva sin geo (~60 hoy, ~1 minuto), nunca
  todo `dim_proyecto`.

**Guardas de calidad (§3.2):**
- el resultado se acepta solo si su `display_name` menciona la comuna declarada del
  proyecto (comparación sin acentos). Comuna distinta ⇒ se descarta y se cuenta:
  una coordenada equivocada asignaría la microzona equivocada y con ella el arriendo
  comparable equivocado — peor que ND;
- raw primero: cada respuesta a `data/raw/nominatim_geocode/`;
- resultado a `geo_proyecto` (tabla propia, upsert, seis columnas de procedencia,
  `evidence_level: V` con la URL de la consulta). No es UPDATE de `dim_proyecto`
  porque la FK de DuckDB lo veta con facts referenciando; el informe hace COALESCE
  (la coordenada publicada por la inmobiliaria siempre manda sobre la geocodificada).

## Alternativas descartadas

- **Google Geocoding API**: de pago, términos prohíben almacenar resultados fuera de
  su plataforma.
- **Georreferenciar contra ejes viales INE**: sin dirección estructurada limpia por
  proyecto todavía; queda como refinamiento si Nominatim deja huecos.
- **Dibujar a mano**: no escala y no tiene procedencia.

## Riesgos

- Nominatim puede resolver el *centroide de la calle* y no el edificio exacto: el tope
  de 2,5 km de `microzonas_por_geo` y la validación de comuna acotan el daño (a lo más
  asigna un barrio vecino dentro de la misma comuna, el mismo error que ya aceptamos
  en el puente de Voronoi, ADR 009).
- La calidad depende de la `direccion` capturada; hoy muchas fichas wp-json no la
  traen y se consulta por nombre de edificio. Si la tasa de acierto viva es baja,
  el siguiente paso es extraer `streetAddress` de los JSON-LD (deuda anotada en la
  tarea).
