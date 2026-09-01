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
- **La desocupación censal en la costa mezcla dos cosas** (medido 01-sep-2026 sobre la
  base real): las 10 microzonas más riesgosas del alcance son casi todas costeras —
  `la-serena/avenida-del-mar` 60,1% de viviendas desocupadas, `coquimbo/guanaquero`
  61,6%, Tongoy 41,1%. Eso no es abandono: es **segunda vivienda de veraneo vacía el día
  del censo**. Para un arrendador de largo plazo sigue siendo señal de riesgo real
  (demanda estacional, competencia de temporada), así que se mantiene en el índice, pero
  su MAGNITUD viene de otro fenómeno y no es comparable 1:1 con el 16,3% de
  `nunoa/estadio-nacional` — que sí es vacancia urbana, y que además **coincide con la
  evidencia independiente de Tattersall** que ya tenía esa microzona marcada saturada:
  dos fuentes distintas apuntando al mismo lugar.

## Reversa

`map_microzona_manzana` y `agg_riesgo_microzona` son derivados puros: `cli puente-censo`
los reconstruye entero. Un polígono real de microzona (si alguna vez existe una fuente)
reemplaza el Voronoi cambiando solo `geo/puente.py::asignar_manzanas`.
