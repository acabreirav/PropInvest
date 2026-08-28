# 01 · Catálogo de fuentes de datos
Verificado al 28-ago-2026. `✅` verificado por fetch directo o documentación oficial ·
`⚠️` inferido de fuentes secundarias · `❓` **a verificar, no lo tomes como cierto**.

> **Tesis:** no scrapees Portal Inmobiliario. Usa la **API oficial de MercadoLibre** para el stock,
> **PlanOK / wp-json** para el precio unitario de proyectos nuevos, **Assetplan** para el arriendo
> efectivo, y **SII / CBR** para el ancla de valor real. El scraping HTML es relleno.

## Orden de ataque

| # | Fuente | Por qué primero | Esfuerzo | Riesgo legal |
|---|---|---|---|---|
| 1 | **API oficial MercadoLibre** (`api.mercadolibre.com`, site `MLC`) | Es Portal Inmobiliario por debajo. OAuth legítimo, JSON limpio, `classified_locations` con **barrios** | Medio | 🟢 Bajo |
| 2 | **`cotizador.saladeventasdigital.com`** (PlanOK) ✅ | Cotizador estándar de la industria → **precio por unidad**, mismo esquema para decenas de inmobiliarias | Bajo | 🟡 Medio-bajo |
| 3 | **`/wp-json/wp/v2/proyecto`** de inmobiliarias ✅ | JSON público sin auth; Socovesa devuelve precios en `CLF` (=UF) vía JSON-LD | Muy bajo | 🟢 Muy bajo |
| 4 | **Assetplan** (`edificios.xml` + fichas) ✅ | Mejor proxy de arriendo real y vacancia; `robots.txt` **permite explícitamente ClaudeBot** | Bajo | 🟢 Muy bajo |
| 5 | **SII catastro + contribuciones** ✅ | Rol, avalúo, m² construidos, año — ancla determinística | Medio | 🟢 Nulo |
| 6 | **CMF + Gael** (UF, UTM, tasas) ✅ | Sin ellas no hay modelo financiero | Muy bajo | 🟢 Nulo |
| 7 | **INE Censo 2024 manzanas** ✅ | Microzonificación oficial, 189 variables | Medio | 🟢 Nulo |
| 8 | Pabellón / Enlace Inmobiliario ✅ | Cobertura de proyectos nuevos, **sin anti-bot** | Bajo | 🟢 Bajo |
| 9 | TOCTOC API interna ✅ | Único con ficha de proyecto nuevo estructurada | Medio-alto | 🟡 Medio |
| 10 | DataBAM / Data Inmobiliaria (CBR) ✅ | Precios de **transacción real**. Comprar, no scrapear | Bajo (pagar) | 🟢 Nulo |

---

## A · MercadoLibre / Portal Inmobiliario

**Portal Inmobiliario ES MercadoLibre.** Confirmado por la estructura de `robots.txt`
(`/vip/`, `/perfil/vendedor/`, `/catalogo/`, `/mongo/` — el stack MELI) y por las tiendas oficiales
bajo `portalinmobiliario.com/tienda-oficial/`.

### robots.txt de Portal Inmobiliario (verificado ✅)
```
Disallow: /propiedades/   /diario/*   /catalogo/*   /productos/*
Disallow: /vip/   /perfil/vendedor/   /perfil/comprador/   /checkout
Disallow: /*.php  /*.asp  /*.html
Allow:    /*_Desde_        ← autoriza EXPLÍCITAMENTE las URLs de paginación
Allow:    /*_JM$
```
Lectura: **permiten crawl de listados paginados, prohíben el detalle.** Un scraper de fichas viola
robots; uno de listados, no. Aun así: **usa la API.** GET a `/venta/departamento/...` devolvió
**403** desde datacenter ✅ (WAF propio de MELI; vendor exacto ❓).

### URLs útiles (verificadas ✅)
```
/{operacion}/{tipo}/{comuna}-{region}
/venta/departamento/proyectos                      ← proyectos nuevos
/venta/departamento/proyectos/{comuna}-metropolitana
/arriendo/departamento/rm-metropolitana/nunoa/plaza-egana/    ← ¡barrio en la ruta!
/tienda-oficial/_Tienda_{slug}                     ← por inmobiliaria
```
Paginación: `_Desde_N`, offset 1-based de 50 en 50 (observado hasta `_Desde_1551` ✅).
Tokens de filtro estilo MELI: `_PriceRange_2000UF-4000UF` ❓, `_iug_{id}` (¿unidad geográfica?) ❓.

### API oficial (la ruta recomendada) ✅
```
GET /sites/MLC                                  GET /sites/MLC/categories
GET /categories/{CATEGORY_ID}
GET /sites/MLC/search?category={CAT}&offset=&limit=&include_filters=true
GET /sites/MLC/search?item_location=lat:$LAT1_$LAT2,lon:$LON1_$LON2&category=...   ← bounding box
GET /items/{ITEM_ID}
GET /marketplace/users/{USER_ID}/items/search?search_type=scan                     ← >1000 resultados
```
- Site ID `MLC`. Categoría raíz inmuebles: `MLA1459` en Argentina; **`MLC1459` por paralelismo ⚠️ —
  confirmar contra `/sites/MLC/categories`**. `MLC1466` (departamentos) ❓.
- OAuth 2.0 Authorization Code. Access token **6 h**; refresh token **6 meses, de un solo uso**;
  se invalida si la app queda sin uso 4 meses ✅.
- Rate limit numérico **no publicado** ❓. Solo se documenta `local_rate_limited (429)`.
  Empieza con token-bucket de 5–10 req/s y backoff exponencial con jitter.
- ⚠️ Asume que `/sites/{SITE}/search` **exige** `Authorization: Bearer` hoy.

### `classified_locations` — el diccionario de barrios ✅
```
GET /classified_locations/countries            /countries/CL
GET /classified_locations/states/{STATE_ID}    /cities/{CITY_ID}
GET /classified_locations/neighborhoods/{NEIGHBORHOOD_ID}
```
Jerarquía `country → state → city → neighborhood`. Los ítems devuelven `neighborhood`, `city`,
`state` y **coordenadas**. La doc dice literalmente que *"enviar solo el Neighborhood ID basta para
que la API complete State y City"*.
→ **Recorre `countries/CL` en cascada y materializa `dim_microzona`.** Encaja 1:1 con los listings
de Portal Inmobiliario. Es la vía más limpia a la microzonificación comercial.

---

## B · Precio por unidad de proyectos nuevos

### B.1 PlanOK — el CRM que domina el back-office chileno
**Cotizador público "Sala de Ventas Digital" (verificado ✅):**
```
https://cotizador.saladeventasdigital.com/cotizador/index.php?id_subagrupaciones={N}&key={slug}&open_dialog=true
https://cotizador.saladeventasdigital.com/cotizador/datos.php      ← endpoint AJAX
```
Ejemplo vivo: `?id_subagrupaciones=52&key=inmobiliariagpr&open_dialog=true` ✅
Flujo de 3 pasos: buscar unidades → seleccionar → agregar secundarios (estacionamiento/bodega).
Campos por unidad: **departamento, precio UF, m², orientación, estacionamiento, bodega**, y flags
de subsidio ✅. **Un solo parser sirve para todas las inmobiliarias que usan PlanOK**: enumera
`key` (slug de inmobiliaria) e `id_subagrupaciones` (etapa/proyecto).
Método y payload exactos de `datos.php` ❓ — inspeccionar con DevTools.

**API REST PVI (B2B, con credenciales) ✅** — base `https://www.pvi.cl/api/v2/`, API KEY bajo
solicitud + JWT: `/client`, `POST /user/login`, `/proyectos`, `/etapas?idProyecto=`,
`/productos?idProyecto=&idEtapa=&estado=` ⇒ incluye **`valorVentaUF` a nivel de producto individual**.
Requiere ser cliente/partner: **vía de negociación, no de scraping.**
Doc: `https://planok.atlassian.net/wiki/spaces/DeP/pages/4497965059/API+REST+PVI`

### B.2 WordPress REST API de inmobiliarias
Procedimiento estándar, barato y de bajo riesgo, para cada dominio:
1. `GET /wp-json/wp/v2/types` → ¿existe `proyecto` / `unidad` / `tipologia`?
2. `GET /wp-json/wp/v2/{rest_base}?per_page=100&_embed`
3. Si `acf` viene vacío, parsea el **JSON-LD** (`<script type="application/ld+json">`) de la ficha.
4. Si nada, busca iframe/redirect a `cotizador.saladeventasdigital.com`.

| Inmobiliaria | wp-json | Precio | Nota |
|---|---|---|---|
| **Socovesa** ✅ | Sí — CPT `proyecto` + taxonomías `ciudad, tipologia, estado, disponibilidad, dormitorios, zona` | **Sí** — JSON-LD `"price": 10500, "priceCurrency": "CLF"` (CLF = ISO-4217 de la UF), `floorSize`, `numberOfBedrooms` ✅ | **el patrón a buscar en todas** |
| Fundamenta ✅ | Sí — `proyecto`, `tipologias_proyectos`, `liquidacion`, `promociones`, `estacionamiento` | "Desde UF X" en HTML | `acf` vacío |
| Exxacon, RVC, PY, Imagina ✅ | Sí | No en API | |
| Almagro ✅ | ❓ | Buscador con rango UF y estado (blanco/verde/inmediata); asesor IA por WhatsApp | |
| Aconcagua, Paz, Manquehue, Actual, Euro, Numancia, Armas, Brotec, Icafal, Pocuro, Norte Verde, Bemi, Enaco, Sinergia, Simonetti | ❓ | ❓ | **no verificadas** — el procedimiento B.2 las resuelve en minutos |

### B.3 Agregadores de proyectos nuevos
| Agregador | Qué aporta |
|---|---|
| **Pabellón** (`pabellon.cl`) ✅ | Muestra **"Unidad 95" + precio UF + dividendo estimado + dorm/baños/m²** → **datos a nivel de unidad**. Sin anti-bot. Rutas: `/proyectos`, `/comprar/{tipo}`, `/region/{region}` |
| **Enlace Inmobiliario** ✅ | **589 proyectos / 19.433 propiedades solo en RM**. White-labels bancarios con la **misma data en distintos hosts**: `bancoestado.`, `bci.`, `coopeuch.`, `consorcio.`, `alianzanuevos.` (Santander), `bancochile-promociones.` → rotación natural de origen |
| Portal Inmobiliario Proyectos ✅ | Mayor cobertura nacional |
| TOCTOC Proyectos ✅ | Ficha rica, pero 403 al fetcher |
| MINVU — portales de proyectos ✅ | Listado **oficial** de portales avalados |
| Urbani ✅ | Entrante 2026, foco en subsidios |
| Nuevos.cl, Casaideal, Vitrina Inmobiliaria ❓ | Sin evidencia de operación actual |

---

## C · Arriendo

### Assetplan — la mejor fuente, y la más amigable legalmente ✅
`robots.txt` **permite acceso irrestricto a `ClaudeBot`, `Claude-User`, `GPTBot`, `PerplexityBot`,
`CCBot`, Google-Extended y otros**, y restringe query params solo a Googlebot/Bingbot ✅.
`/cdn-cgi/` confirma **Cloudflare** delante (único WAF identificado positivamente en el estudio).

```
https://www.assetplan.cl/sitemap.xml        → índice
https://www.assetplan.cl/comunas.xml
https://www.assetplan.cl/edificios.xml      → 175 URLs, changefreq=daily, lastmod = hoy
patrón: /arriendo/departamento/{comuna}/{edificio-slug}/{building_id}/{tipologia}
ventas:  /ventas/resultados?type=new_project | ?type=resale
Disallow: /arriendo/departamento/*/edificio/  /cart/  /checkout/  /search
```
**Limitación:** el listado de unidades **se hidrata con JS** (se observó `selectedModel?.name` sin
interpolar) → hace falta headless o encontrar el XHR. No hay `__NEXT_DATA__` ni `__INITIAL_STATE__` ✅.
Dominios relacionados: `portalbeta.assetplan.cl` (portal nuevo, probable API JSON limpia ❓).

### Otros portales
| Portal | robots | Nota |
|---|---|---|
| **Chilepropiedades** ✅ | `Allow: /` + **`Crawl-delay: 2`** + **sitemap index declarado** | Respeta el crawl-delay: es tu argumento de buena fe. URLs: `/propiedades/{venta\|arriendo-mensual\|arriendo-diario}/{tipo}/{comuna}/{pagina}` (base 0). Existe `/api/` interno, solo `/api/publicaciones/related` está en Disallow |
| **Yapo.cl** ✅ | El más permisivo: `Allow: /` sin restricción sobre listados | Clasificados C2C, mucho ruido. Solo como control de sesgo |
| Goplaceit ✅ | **`Disallow: /cl/mapa?*`** — justo donde vive la API | SPA React pura, cero contenido en el HTML. Tiene `sitemap-cl-subdivisiones` (vocabulario de barrios) ✅, URL exacta ❓ |
| Doomos ✅ | `Disallow: /ws/` (= sus web services) | Calidad media-baja |
| TOCTOC ✅ | 403 al leer robots | API interna: `GET /api/propiedad/nueva/compra-nuevo?id={ID}` y `/api/propiedades/usadas/{ID}` — el scraper público de referencia tuvo que **interceptarla con Selenium Wire**, señal de validación de sesión. Existe backend ASP.NET con Help page pública en `apientornotoctoc.toctoc.com/Help/` ❓ |
| Multifamily | LAR Group ✅, Level ✅, Houm ⚠️ | Complemento de arriendo real |

---

## D · Datos públicos oficiales

### SII
| Recurso | URL |
|---|---|
| **Layout del catastro masivo** | `https://www.sii.cl/bbrr/descargas/estructura_detalle_catastral.pdf` ✅ |
| Estadísticas BBRR no agrícolas por comuna | `https://www.sii.cl/sobre_el_sii/estadisticas_bienes_raices_no_agricolas.html` ✅ |
| Consulta por rol | `https://zeus.sii.cl/avalu_cgi/br/brc803.sh` ✅ |
| **Reajustes y exenciones impuesto territorial** | `https://www.sii.cl/ayudas/ayudas_por_servicios/2242-reajustes_exenciones-2468.html` ✅ |
| RSS de indicadores (UF/dólar diarios, UTM mensual) | `https://zeus.sii.cl/admin/rss/sii_ind_rss.xml` ✅ |

**Layout verificado (TAB, sin headers):**
`BRORGA2441N_NAC` (1 registro por rol): comuna · manzana · predial · dirección · **avalúo fiscal** ·
contribución semestral · destino · **avalúo exento** · roles comunes · **superficie de terreno**.
`BRORGA2441NL_NAC` (N líneas de construcción por rol): comuna · manzana · predial · nº línea ·
material · calidad · **año de construcción** · **superficie construida** · destino · condición.
→ Ancla determinística para normalizar UF/m² y **detectar edificios nuevos**.

⚠️ **El SII NO publica descarga masiva de compraventas con precio** ✅. La consulta de transferencias
es autenticada y por contribuyente. Quien te ofrezca ese bulk, lo obtuvo del CBR.

**Contribuciones 2026 (verificado, al 01.07.2026):** habitacional **0,893%** hasta $220.398.431 de
avalúo · **1,042%** sobre el excedente · exención habitacional **$61.711.570** ✅
*(el informe financiero cita alternativamente $58.040.000 — `[C]`, verificar en SII).*

**APIs de terceros sobre SII:** BaseAPI (`/sii/avaluo/predio/{comuna}/{manzana}/{predio}`,
`/sii/avaluo/area-homogenea` ← **valor m² oficial por zona homogénea**, free 50/mes,
**discontinúa el tier gratuito el 11-dic-2026**) ✅ · APIGateway (`/api/v2/sii/bienes_raices/...`) ✅.

### Conservador de Bienes Raíces
`https://conservador.cl/portal/indice_propiedad` expone el **índice** (fojas, número, año, nombres,
dirección, naturaleza) pero **no el precio**, requiere login y no tiene API ✅.
→ El precio se compra ya extraído:
- **Data Inmobiliaria** (`datainmobiliaria.cl`): 346 comunas, 15 años, 9,5M propiedades,
  3,5M transacciones. Fuentes SII + CBR + TGR + portales. **Tier gratuito con mapa y export Excel** ✅
  ← **mejor ROI inmediato del catálogo.**
- **DataBAM** (`databam.cl`): 20+ comunas del Gran Santiago, incluye **ROL, precios y coordenadas**.
  Desde $50.000/mes. API y venta de datasets masivos ✅.

### Indicadores financieros
```
CMF (oficial, apikey gratuita):
  https://api.cmfchile.cl/api-sbifv3/recursos_api/uf[/{AAAA}[/{MM}[/dias/{DD}]]]?apikey=&formato=json
  series: UF, UTM, IPC, TMC, dólar, euro   ·  docs: api.cmfchile.cl/documentacion/{UF|UTM|IPC|TMC}.html
Gael Cloud (sin auth, fallback):
  https://api.gael.cloud/general/public/monedas[/{codigo}]
  ⚠️ LÍMITE DURO: >9 requests en 10 s ⇒ IP baneada 1 hora (HTTP 429)
mindicador.cl  → open source, pero se observó caído. NO lo uses como única fuente.
Banco Central API BDE → si3.bcentral.cl/estadisticas/principal1/web_services/  (series IDs ❓)
```
**Tasas hipotecarias CMF, descarga directa sin auth ✅:**
`https://www.cmfchile.cl/portal/estadisticas/617/articles-46417_recurso_1.xls`
Desagregado por institución individual: portal InfoFinanciera ✅, archivo exacto ❓.

### Cartografía y censo
| Fuente | Contenido | Formato |
|---|---|---|
| **INE Censo 2024 — manzanas** | `Cartografia_censo2024_Pais_Manzanas.parquet` | **GeoParquet** ✅ |
| **INE Censo 2024 — BD manzana** | **189 variables** (personas, hogares, viviendas) | CSV ✅ |
| INE Geodatos Abiertos | zona censal, distrito, límites DPA, límite urbano, ejes viales | SHP / File GDB ✅ |
| INE ArcGIS Open Data | mismas capas con **API GeoJSON** | `geoine-ine-chile.opendata.arcgis.com` ✅ |
| MINVU IDE | IPT, planes reguladores, límite urbano | ArcGIS Hub ✅ |
| OCUC (Observatorio Ciudades UC) | indicadores urbanos RM | ArcGIS Hub ✅ |

> **Truco:** INE, MINVU y OCUC están **todos sobre ArcGIS Hub**. Cada dataset tiene descarga
> programática canónica:
> `https://opendata.arcgis.com/api/v3/datasets/{dataset_id}/downloads/data?format=geojson&spatialRefId=4326`
> y un `FeatureServer` detrás con `?where=1=1&outFields=*&f=geojson`.
> Resuelve los IDs desde `/api/v3/datasets?q=...` de cada hub. Formato ✅, IDs concretos ❓.

**Recomendación de microzona:** unidad atómica = **manzana censal INE 2024** (geoparquet, con las
189 variables ya adjuntas); mapea el `neighborhood_id` de MELI contra ella por intersección espacial.
Barrios "comerciales" con demografía "oficial".

---

## E · Listas de precios por email y PDF

**Los portales NO exponen email.** Portal Inmobiliario bloquea `/perfil/vendedor/`;
Chilepropiedades bloquea literalmente `/publicacion/*/revelar-datos-contacto`; Almagro canaliza
por asesor IA en WhatsApp ✅.

**Canales reales, por tasa de respuesta esperada:**
1. **WhatsApp del proyecto** — el estándar de facto de sala de ventas chilena en 2026.
2. **Formulario web de la inmobiliaria** (`form_cotizacion`, `form_info_proyecto`, `form_agendar`) →
   lead en PlanOK CRM → ejecutivo responde con PDF/Excel adjunto.
3. **Cotizador PlanOK** — genera una cotización formal por email automáticamente.
   **La vía más rápida para un price list estructurado sin hablar con nadie.**
4. Email corporativo genérico (`contacto@`, `ventas@`) desde el sitio, no desde el portal.
5. Enlace Inmobiliario / Pabellón como intermediarios.

**Anatomía de un PDF de lista de precios** (verificado en el proyecto SUCRE, Pedro de Valdivia, Ñuñoa):
3 secciones (A características, B tipologías y pago, C FAQ). Tipologías `1D-1B (36 m²)`, `2D-2B (45 m²)`.
Estacionamiento **desde 360 UF**, bodega **desde 90 UF** — líneas independientes, no incluidas.
Convención anti-parsing: **el precio no aparece como total en UF**, sino como
*"Promedio 3500 en 36 cuotas de $270.000"*. Reserva $400.000–$600.000, **que se descuenta del pie**.
Pie: 20% en 24 cuotas, o 10% en 24 cuotas promocional.

→ Requisitos del parser en CLAUDE.md §7.4.

---

## F · Legal y anti-bot — ver `docs/04-legal.md`

Resumen de riesgo por fuente:

| Fuente | Riesgo |
|---|---|
| API MELI con OAuth · Assetplan · wp-json · SII/INE/CMF/BCCh | 🟢 Bajo o nulo |
| Chilepropiedades respetando `Crawl-delay: 2` · Yapo (`Allow: /`) · Pabellón · Enlace | 🟢 Bajo |
| PlanOK cotizador público · Goplaceit `/cl/mapa?*` · TOCTOC API interna | 🟡 Medio |
| **Scraping HTML de fichas de Portal Inmobiliario** | 🔴 **Alto** — `/propiedades/` prohibido |
| **Emails / RUT / nombres de vendedores** | 🔴 **Alto** — Ley 21.719 desde 01-dic-2026 |

## G · Brechas abiertas — medir antes de comprometer arquitectura

1. `MLC1459` / `MLC1466` contra `GET /sites/MLC/categories` con token.
2. ¿`/sites/MLC/search` exige Bearer hoy? Probar con y sin.
3. Tope real de resultados de la API y de `_Desde_N`.
4. Rate limit numérico de MELI.
5. Vendor anti-bot de Portal Inmobiliario y TOCTOC (headers `cf-ray` / `x-datadome` / `server`).
6. Semántica de `_iug_`, `_tp_`, `_sp_`, `_ca_`, `_mn_`, `_i_`.
7. Método y payload de `cotizador/datos.php` + universo de valores `key`.
8. Mapa completo de `apientornotoctoc.toctoc.com/Help`.
9. URL exacta de `sitemap-cl-subdivisiones` de Goplaceit.
10. URLs directas de descarga del Censo 2024 (BD manzana y geoparquet de cartografía).
11. Series IDs de la API BDE del Banco Central.
12. Texto literal de los T&C de Portal Inmobiliario y MercadoLibre Chile.
13. XLS de tasas hipotecarias desagregado por banco.
14. Cotizadores de las ~15 inmobiliarias no verificadas.
