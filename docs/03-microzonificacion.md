# 03 · Microzonificación

## Por qué la comuna es la unidad equivocada

Tres evidencias, todas verificadas:

1. **Estación Central**: el mismo producto renta ~$300.000 en Santa Isabel y ~$350.000 a pocas
   cuadras. **17% de brecha dentro de la misma comuna** (Tattersall, abr-2026). Sobre un yield de
   4%, eso son ~70 pb — más que toda la diferencia entre comunas.
2. **Viña del Mar**: rango intercuartil de UF/m² de 45,0 a 82,5 sobre mediana 66,1, con 1.671
   transacciones reales del CBR. **El p75 vale 83% más que el p25.**
3. **Ñuñoa Plaza Egaña**: 3D en $860.333 contra un promedio comunal de $785.661. ~10% sobre la comuna.

## Mapa de saturación de arriendo (Tattersall, abr-2026)

| Comuna | Saturada — **excluir** | En equilibrio |
|---|---|---|
| Estación Central | **Santa Isabel** | Av. 5 de Abril |
| Santiago Centro | **Teatinos, Parque Almagro** | Morandé, Plaza de Armas |
| La Florida | **Vicuña Mackenna × Américo Vespucio** | resto |
| Ñuñoa | **entorno Estadio Nacional** (emergente) | resto |
| Macul | **Quilín × Av. Macul** (emergente) | resto |
| La Cisterna | **JM Carrera × Briones Luco** (emergente) | resto |
| San Miguel, Providencia, Lo Barnechea | — (normativa restrictiva) | toda la comuna |

Está codificado en `config/zonas.yml` bajo `saturadas` y se aplica como **exclusión dura** del ranking.

## Cómo se construye `dim_microzona`

**Vocabulario comercial** — el que usan los listings:
```
GET api.mercadolibre.com/classified_locations/countries/CL
  → states/{id} → cities/{id} → neighborhoods/{id}
```
Jerarquía `country → state → city → neighborhood`, con coordenadas. Encaja 1:1 con Portal
Inmobiliario, cuyas URLs ya llevan el barrio en la ruta:
`/arriendo/departamento/rm-metropolitana/nunoa/plaza-egana/`.

**Unidad atómica oficial** — manzanas del **Censo 2024 del INE** (GeoParquet, 189 variables
socioeconómicas por manzana). El join espacial da barrios comerciales con demografía oficial.

**Enriquecimiento**:
- distancia a estación de Metro **operativa** y **en construcción con fecha creíble**;
- `saturada` desde `config/zonas.yml`;
- valor m²/**área homogénea del SII** (`BaseAPI /sii/avaluo/area-homogenea`), que es una
  microzonificación de valor construida por el propio fisco.

**Regla de asignación**: punto en polígono; en empate entre barrios superpuestos, gana el de mayor
`n` de avisos activos. Los polígonos comerciales se superponen y dejan huecos — la regla tiene que
ser determinística y estar documentada, y lo no asignado va a una cola de revisión, no a un
"sin clasificar" que nadie mira.

## Catalizadores de Metro — qué cuenta y qué no

| Proyecto | Comunas | Avance | Apertura | ¿Cuenta? |
|---|---|---|---|---|
| Extensión L6 poniente (Lo Errázuriz) | Cerrillos | 46% físico | **2027** | ✅ |
| Línea 7 | Renca, Cerro Navia, Quinta Normal, Santiago, Recoleta, Providencia, Las Condes, Vitacura | 42%, 68% túneles | **fines de 2028** | ✅ |
| Línea 9 (eje Santa Rosa) | Recoleta, Santiago, San Miguel, San Joaquín, La Granja, La Pintana, Puente Alto | 3,7% | 2030/2032/2033 | ❌ |
| Línea 8 | Providencia, Ñuñoa, Macul, La Florida, Peñalolén, Puente Alto | ingeniería | 2032–2033 | ❌ |

Cercanía a Metro suma **15–30% al valor**, y el anuncio de una línea genera alzas anticipatorias de
**10–20%**. Pero la captura depende de la **distancia a la estación** (radio de 600 m en
`params.yml`), no de estar "en la comuna". Para un horizonte de 3–5 años, **solo cuentan L6 y L7**.

## Fuentes de polígonos

| Fuente | Contenido | Acceso |
|---|---|---|
| INE Censo 2024 | manzanas país + 189 variables | GeoParquet + CSV |
| INE Geodatos Abiertos | zona censal, distrito, límites DPA, límite urbano | SHP / GDB / ArcGIS API |
| MINVU IDE | IPT, planes reguladores | ArcGIS Hub |
| OCUC UC | indicadores urbanos RM | ArcGIS Hub |

Los tres últimos están sobre ArcGIS Hub: descarga programática con
`opendata.arcgis.com/api/v3/datasets/{id}/downloads/data?format=geojson`, IDs resolubles desde
`/api/v3/datasets?q=...`.
