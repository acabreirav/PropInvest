# ADR 009 · El puente manzana → microzona es un Voronoi sobre centros de barrio

**Fecha**: 01-sep-2026 · **Estado**: aceptado · **Tarea**: T-014b

## Contexto

`riesgo_microzona` (15% del score del §12) estuvo inerte desde el día uno: no existía
camino entre las manzanas censales (T-014: 77.733 con polígono) y las microzonas del
ranking. Las microzonas nacieron del vocabulario de barrios del portal y **no tienen
polígono**. Caminos evaluados:

1. **Coordenadas por aviso** — las tarjetas del portal no las traen (verificado en el
   crudo: la única lat/lon de la página es el centro de Chile, un default del mapa) y el
   detalle por aviso está prohibido por robots (§13.6). Muerto.
2. **Polígonos de barrio de MELI** — `classified_locations` entrega el diccionario de
   barrios con `geo_information.location` (un **centro**, no un polígono). Vivo: 196
   requests, 158 barrios, 18/18 comunas, 0 errores (01-sep-2026).
3. **Dibujar polígonos a mano** — 107+ barrios; inviable y no reproducible.

## Decisión

Cada manzana censal con centroide se asigna al **barrio más cercano dentro de su misma
comuna** (partición de Voronoi sobre los centros MELI, distancia equirectangular). Sobre
las manzanas asignadas se agregan tres insumos, todos `D` sobre datos `V`:

- **desocupación censal**: viv. desocupadas / (ocupadas + desocupadas)
- **profundidad de arriendo**: hogares arrendatarios / hogares (más = menos riesgo)
- **saturación de oferta**: avisos de arriendo activos / hogares arrendatarios (la B2)

El `riesgo` combina los tres, min-max sobre el alcance, con pesos `E` declarados en
`params.yml` (`riesgo_microzona.*`, con rango — medibles con `cli sensibilidad`).

## Lo que esta aproximación se puede equivocar, dicho de frente

- **El borde entre dos barrios**: una manzana equidistante puede caer al lado equivocado.
  Mitiga: las variables censales varían suave dentro de una comuna, y el riesgo es un
  agregado sobre decenas de manzanas, no una lectura puntual.
- **Un centro MELI descentrado** sesga toda su celda de Voronoi.
- **NULL censal** (conteos enmascarados `*`): queda fuera de las sumas — jamás cero. Una
  microzona sin ningún dato queda con riesgo NULL y cae al 0.5 por defecto del motor,
  **contada y reportada** como no-medida en `oportunidades`.

## Reversa

`map_microzona_manzana` y `agg_riesgo_microzona` son derivados puros: `cli puente-censo`
los reconstruye entero. Un polígono real de microzona (si alguna vez existe una fuente)
reemplaza el Voronoi cambiando solo `geo/puente.py::asignar_manzanas`.
