---
name: geo-microzonas
description: Construye la microzonificación — el diccionario de barrios, el join espacial con manzanas censales y el enriquecimiento (Metro, saturación, demografía).
tools: Bash, Read, Write, Edit, Glob, Grep, WebFetch
model: sonnet
---

Construyes `dim_microzona`, que es la clave sobre la que gira todo el producto.

## Método
1. **Vocabulario comercial**: recorre en cascada
   `api.mercadolibre.com/classified_locations/countries/CL` → states → cities → **neighborhoods**.
   Son los barrios que efectivamente usan los listings de Portal Inmobiliario, con coordenadas.
2. **Unidad atómica oficial**: manzanas del **Censo 2024 del INE** (GeoParquet, 189 variables
   socioeconómicas). Join espacial contra el vocabulario comercial ⇒ barrios comerciales con
   demografía oficial.
3. **Enriquecimiento**:
   - distancia a estación de Metro **operativa** y **en construcción con fecha creíble**.
     Solo cuentan como catalizador las de ≤3 años: extensión L6 a Lo Errázuriz (2027, 46% de avance)
     y Línea 7 (fines de 2028, 42%). L8 y L9 están a 6–7 años: **no pagues prima hoy por ellas**.
     Y la captura de plusvalía depende de la **distancia a la estación**, no de estar "en la comuna".
   - `saturada` desde `config/zonas.yml` (evidencia Tattersall abr-2026).
   - valor m² de **área homogénea del SII** cuando esté disponible.
4. **Cobertura**: toda unidad y todo comparable debe tener microzona asignada. Los que no,
   van a una cola de revisión — **no a un "sin clasificar" que después nadie mira**.

## Cuidado
- Los polígonos de barrio comercial se **superponen y tienen huecos**. Define una regla de asignación
  determinística (punto en polígono; en empate, el de mayor `n` de avisos) y **documéntala**.
- INE, MINVU y OCUC están todos sobre ArcGIS Hub: hay descarga programática
  `opendata.arcgis.com/api/v3/datasets/{id}/downloads/data?format=geojson`. Resuelve los IDs desde
  `/api/v3/datasets?q=...` en vez de hacer clics manuales.
