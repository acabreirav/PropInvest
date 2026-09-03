# Scouting · más inmobiliarias WordPress para T-925c (ronda 03-sep-2026)

**Estado: reconocimiento, no verificación.** Este documento NO es un ADR de fuente (el protocolo
de fuente-scout exige robots.txt verbatim + SHA256 antes de clasificar `legal_tier`, y ese paso
**no se pudo ejecutar** en esta ronda — ver bloqueo de red abajo). Es el insumo para que la
siguiente corrida de `probar-wpjson` en la máquina local sepa, en orden, a quién sondear primero.

## 0 · Bloqueo de red de este contenedor — leer antes de descartar nada

Intenté `WebFetch` contra `robots.txt` de varios dominios candidatos, incluidos dos ya
**confirmados como operativos** por el propio pipeline (`assetplan.cl`, que ADR 008 usa hoy) y
un control neutro (`google.com`). Los tres fallaron igual:

```
{"error_type":"EGRESS_BLOCKED","domain":"www.fundamenta.cl", ...}
{"error_type":"EGRESS_BLOCKED","domain":"www.icafal.cl", ...}
{"error_type":"EGRESS_BLOCKED","domain":"www.assetplan.cl", ...}
{"error_type":"EGRESS_BLOCKED","domain":"www.google.com", ...}
```

Como `google.com` también quedó bloqueado, **`WebFetch` no llega a ningún host HTTP directo
desde este contenedor** — no es un bloqueo específico contra dominios `.cl` que se pueda sortear
reintentando. Solo `WebSearch` tuvo salida (usa un backend de búsqueda distinto). Esto reproduce
exactamente la limitación que ADR 010 y ADR 011 ya documentaron ("el entorno remoto no alcanza
el host"; las corridas reales se hicieron "desde la máquina del inversionista").

**Consecuencia dura para este documento:**
- Ningún `robots.txt` fue descargado, guardado en `data/raw/robots/{host}/{fecha}.txt` ni
  hasheado. Cero SHA256 en esta ronda.
- Ningún `/wp-json/` fue probado en vivo. "¿WordPress?" abajo es **inferencia por indicios
  indirectos** (estructura de URL, nombres de clases PHP que aparecen en query strings
  indexados, patrones ya vistos en Socovesa/Pilares) — **nunca una confirmación**.
- Por lo tanto **ningún candidato de este documento puede clasificarse `legal_tier` todavía**.
  Todos quedan en `❓ a verificar`. Nadie pasa a `html_permitido` sin el paso 1 del protocolo
  corrido de verdad, con bytes de robots.txt en la mano.
- Lo que SÍ aporta esta ronda: acotar el universo (existencia real, comunas que cubre, rango de
  ticket UF) para que la sonda local no pierda tiempo en dominios sin overlap con `config/zonas.yml`.

## 1 · Método

Búsquedas con `WebSearch` por inmobiliaria: (a) ¿existe y vende departamentos NUEVOS?,
(b) ¿en qué comunas — cruzado contra el §10 de `CLAUDE.md`?, (c) ¿qué rango de ticket UF citan
fuentes/listados?, (d) cualquier indicio de stack (URLs con `/wp-content/`, `/category/` con
slugs por defecto de WordPress, nombres de clase PHP tipo `DB_CustomSearch_Widget` que delatan
un plugin de WP, o al contrario `public/index.php` que delata Laravel/CodeIgniter — NO WordPress).
Cero llamadas HTTP propias; todo cita la URL que devolvió el snippet.

## 2 · Tabla de candidatas

| Dominio | Comunas observadas (fuente) | Ticket UF observado | ¿WordPress? | Estado | Prioridad | Razón |
|---|---|---|---|---|---|---|
| **iarmas.cl** (Inmobiliaria Armas) | San Miguel (Plaza San Miguel), Santiago Centro, Ñuñoa, La Florida — Las Condes y Providencia también, fuera de alcance ([iarmas.cl/proyectos](https://www.iarmas.cl/proyectos/), [cl.linkedin.com](https://cl.linkedin.com/company/inmobiliariaarmas)) | Plaza San Miguel UF 1.836 (sin bodega/estac.) — muy bajo el tope ([MercadoLibre](https://departamento.mercadolibre.cl/MLC-935539935-plaza-san-miguel-_JM)) | **Indicio fuerte de sí** — `iarmas.cl/category/sin-categoria/` es un slug de categoría **por defecto de WordPress**, y las URLs de búsqueda traen `search-class=DB_CustomSearch_Widget-db_customsearch_widget` (un `WP_Widget` de un plugin de búsqueda/filtro) ([iarmas.cl/category](https://www.iarmas.cl/category/sin-categoria/), [búsqueda filtrada](https://iarmas.cl/?comunas_plantas=nunoa&search-class=DB_CustomSearch_Widget-db_customsearch_widget)) | por verificar | **ALTA** | Mejor match de comuna+ticket+indicio-WP de toda la ronda. Menciona FOGAES explícitamente en su propio marketing. |
| **fundamenta.cl** | Ñuñoa, Macul, La Florida, Estación Central, Santiago Centro, Cerrillos ([fundamenta.cl](https://www.fundamenta.cl/), [proyectos-en-venta/departamento-en-nunoa](https://www.fundamenta.cl/proyectos-en-venta/departamento-en-nunoa/)) | No cuantificado en esta ronda; `docs/01-fuentes.md` B.2 ya reporta "Desde UF X" en HTML | **Ya confirmado ✅ en `docs/01-fuentes.md` B.2**: CPT `proyecto` + `tipologias_proyectos`, `liquidacion`, `promociones`, `estacionamiento`; `acf` vacío (mismo patrón que Socovesa: precio vive en HTML) | wp-json confirmado, precio por verificar | **ALTA** | Es trabajo incremental, no descubrimiento: sumarlo a `PERFILES` solo exige un selector HTML nuevo, calcado del patrón de `wpjson_inmobiliarias.py`. Comunas calcadas al §10. |
| **rvc.cl** | Ñuñoa, Estación Central + Antofagasta, Viña del Mar (fuera de alcance) ([rvc.cl/comuna/nunoa](https://www.rvc.cl/comuna/nunoa/), [rvc.cl/comuna/estacion-central](https://www.rvc.cl/comuna/estacion-central/), [rvc.cl/ciudad/antofagasta](https://www.rvc.cl/ciudad/antofagasta/)) | No cuantificado en esta ronda | **Ya confirmado ✅** en `docs/01-fuentes.md` B.2 ("Sí" wp-json, "No en API" el precio → vive en HTML) | wp-json confirmado, precio por verificar | **ALTA** | Único candidato que además cubre Antofagasta (Fase 3). |
| **imagina.cl** | Santiago Centro (ONE TOWN, BEST TOO, BEST SITE, HOMETOWN, MORE II) ([imagina.cl/departamentos-en-venta/santiago](https://www.imagina.cl/departamentos-en-venta/santiago/)) | UF ~2.480–3.550 en Santiago Centro ([imagina.cl/departamentos-en-venta/santiago](https://www.imagina.cl/departamentos-en-venta/santiago/)) | **Ya confirmado ✅** en `docs/01-fuentes.md` B.2 (wp-json "Sí", precio "No en API") | wp-json confirmado, precio por verificar | **ALTA** | Ticket bien bajo el tope, comuna núcleo del alcance. |
| **santolaya.cl** | Cerrillos, La Cisterna, La Florida, Macul, Ñuñoa, Santiago — además Las Condes, Lo Barnechea, Providencia (fuera) ([santolaya.cl/proyectos-venta](https://santolaya.cl/proyectos-venta)) | UF 2.260–2.884 (Edificio JMC 608, Zañartu 1908, Mapocho 2880) ([santolaya.cl/proyectos-venta](https://santolaya.cl/proyectos-venta)) | **Indicio en contra**: una de las URLs indexadas es `www.santolaya.cl/public/index.php/proyecto/ns440` — el patrón `public/index.php` es de **Laravel o CodeIgniter**, no de WordPress (WP nunca expone `public/index.php` en la URL pública) ([santolaya.cl/public/index.php/proyecto/ns440](https://www.santolaya.cl/public/index.php/proyecto/ns440)) | por verificar — probable NO-WP | **ALTA para verificar, BAJA para construir si se confirma el indicio** | Comunas y ticket son el mejor calce del alcance de toda la ronda, pero si no es WordPress esto no es un colector de T-925c: sería un scraper HTML nuevo (otro `legal_tier`, otra decisión). Sondear primero, con `curl`/`probar-wpjson`, para no perder el hallazgo si es el caso raro de un WP con router custom. |
| **ingevecinmobiliaria.cl** (ojo: NO `ingevec.cl`, que es la corporativa) | Santiago Centro, La Cisterna, Independencia, La Florida, Estación Central, Macul, San Miguel, Ñuñoa ([ingevecinmobiliaria.cl/proyectos-en-venta](https://ingevecinmobiliaria.cl/proyectos-en-venta), [ingevecinmobiliaria.cl/proyecto-santarosa](https://ingevecinmobiliaria.cl/proyecto-santarosa)) | UF 2.500–4.500 | por verificar, sin indicios en esta ronda | por verificar | **ALTA** | Cobertura de comunas casi idéntica al §10 completo de Fase 1+2 RM. |
| **iaconcagua.com** | Ñuñoa (Edificio Nueva Ñuñoa) en RM; **La Serena, Antofagasta, Concepción/Talcahuano** — calzan Fase 3 completa ([iaconcagua.com/proyectos/nueva-nunoa](https://www.iaconcagua.com/proyectos/nueva-nunoa), [iaconcagua.com/proyectos?lugar=la+serena](https://www.iaconcagua.com/proyectos?lugar=la+serena), [iaconcagua.com/articulos/proyectos-concepcion-talcahuano](https://www.iaconcagua.com/articulos/proyectos-concepcion-talcahuano)) | Nueva Ñuñoa desde UF 2.699; Concepción desde UF 1.756–2.849 | por verificar, sin indicios en esta ronda | por verificar | **ALTA** | Único candidato de esta ronda con presencia fuerte y verificada en LAS TRES ciudades de Fase 3, con tickets bajos. |
| **py.cl** | Cerrillos, San Pedro de la Paz (Gran Concepción) — resto (Colina, Buin, Ovalle, Caldera, Machalí, Copiapó, Coquimbo, Puerto Varas, San Bernardo, La Pintana, Los Andes) fuera de alcance ([py.cl/proyectos](https://py.cl/proyectos/)) | No cuantificado | **Ya confirmado ✅** en `docs/01-fuentes.md` B.2 (wp-json "Sí", "No en API") | wp-json confirmado, precio por verificar | MEDIA | wp-json ya resuelto pero el overlap real con `config/zonas.yml` es apenas 2 comunas de un catálogo grande — bajo rendimiento por unidad de esfuerzo de sonda. |
| **exxacon.cl** | Ñuñoa, La Florida (dentro) — Las Condes, Vitacura, Peñalolén (fuera, y sobre tope) ([exxacon.cl/proyectos-en-venta](https://exxacon.cl/proyectos-en-venta/), [exxacon.cl/venta-proyectos-departamentos-en-las-condes](https://exxacon.cl/venta-proyectos-departamentos-en-las-condes/)) | No cuantificado; posicionamiento "diseño y ubicación" sugiere ticket alto | **Ya confirmado ✅** en `docs/01-fuentes.md` B.2 (wp-json "Sí", "No en API") | wp-json confirmado, precio por verificar | MEDIA | El colector tendría que filtrar agresivamente por comuna; media parte del catálogo (Las Condes/Vitacura) es descarte seguro. |
| **isinergia.cl** | Estación Central, La Florida (dentro) — Providencia, Colina, Buin (fuera) ([isinergia.cl/proyectos](https://isinergia.cl/proyectos/)) | No cuantificado | por verificar, sin indicios en esta ronda | por verificar | MEDIA | Overlap parcial, sin dato de ticket todavía. |
| **icafalinmobiliaria.cl** (ojo: NO `icafal.cl`, que es la constructora/ingeniería) | La Florida (Tempo Carrera), y menciona San Miguel, Puente Alto, Maipú, Lampa en su historial ([icafalinmobiliaria.cl/proyectos-en-venta/tempo-carrera](https://www.icafalinmobiliaria.cl/proyectos-en-venta/tempo-carrera/)) | UF 4.219–7.819 (2–3 dorm, entrega inmediata) — **parte del rango queda sobre el tope UF 6.000** ([búsqueda agregada, ver nota]) | por verificar, sin indicios en esta ronda | por verificar | MEDIA | Filtrar por unidad, no por proyecto: algunas unidades sí calzan, otras no. No descartar el dominio completo. |
| **euroinmobiliaria.cl** | La Florida (Entre Vicuñas, cerca de Metro Pedrero) ([euroinmobiliaria.cl/edificios/entre-vicunas](https://euroinmobiliaria.cl/edificios/entre-vicunas/)) | No cuantificado | por verificar, sin indicios en esta ronda | por verificar | MEDIA | Un solo proyecto confirmado en comuna de alcance; falta ver el resto del catálogo. |
| **simonetti.cl** | San Miguel, La Florida, Macul (dentro) — Providencia, Las Condes, La Reina, Vitacura, Huechuraba (fuera) ([simonetti.cl](https://simonetti.cl/)) | No cuantificado | por verificar, sin indicios en esta ronda | por verificar | MEDIA | Overlap parcial, historial de 80+ proyectos sugiere volumen si el filtro de comuna funciona. |
| **paz.cl** | Santiago Centro, Independencia, San Miguel, Estación Central, La Florida (dentro) — Providencia, Las Condes, Vitacura, Lo Barnechea (fuera) ([paz.cl/comunas/santiago-centro](https://www.paz.cl/comunas/santiago-centro), [paz.cl](https://www.paz.cl/)) | UF 1.500–6.000 (rango declarado, todo el catálogo) | **Indicio en contra**: rutas como `nuevaweb.paz.cl/HOME`, `paz.cl/AccesoUsuario`, `paz.cl/resultado-de-busqueda` no son slugs de WordPress — huelen a SPA/app a medida (Angular/React) sobre un backend propio | por verificar — probable NO-WP | MEDIA-BAJA | Comunas y ticket son excelentes, pero si no es WP esto tampoco es un colector de T-925c. Verificar antes de invertir tiempo de parser. |
| **gimax.cl** | Un solo proyecto identificado ("HOY", Santiago — comuna exacta sin confirmar) ([gimax.cl/proyecto/hoy](http://www.gimax.cl/proyecto/hoy)) | No cuantificado | sin indicios | por verificar | BAJA | Evidencia insuficiente para priorizar sobre las anteriores; requiere una ronda de investigación aparte antes de sondear. |
| **pocuro.cl** | Sin comunas identificadas en esta ronda; se declara venta directa "sin corredores" ([pocuro.cl](https://pocuro.cl/)) | No cuantificado | sin indicios | por verificar | BAJA | Mismo motivo que Gimax. |
| **bricsa.cl** (sucesora de la inmobiliaria de Brotec, según LinkedIn/EMB Construcción) | Sin investigar en esta ronda ([brotec.cl/inmobiliaria.php](https://www.brotec.cl/inmobiliaria.php)) | No cuantificado | sin indicios | por verificar | BAJA | Pista nueva encontrada al buscar "Brotec" (candidata original del brief): el negocio inmobiliario de Brotec hoy opera bajo la marca BRICSA. Queda para una ronda dedicada. |

## 3 · Comandos de sonda para las prioridades ALTA (ejecutar en la máquina local, no en este contenedor)

Cada comando corre primero `robots_check.verificar()` contra `/wp-json/` (o `/nuestros-proyectos/`
en el colector real) y **aborta con exit 2 si robots.txt prohíbe** — ese es el paso 1 del
protocolo, ya implementado en `probar_wpjson` (`src/flujocero/cli.py`). Guarda automáticamente
cada respuesta a `data/raw/wpjson_inmobiliarias/` con su `robots_snapshot_sha`.

```bash
# 1 · solo tipos/CPT y una muestra de 5 registros — confirma "¿es WordPress con REST?"
uv run python -m flujocero.cli probar-wpjson --dominio iarmas.cl
uv run python -m flujocero.cli probar-wpjson --dominio fundamenta.cl
uv run python -m flujocero.cli probar-wpjson --dominio rvc.cl
uv run python -m flujocero.cli probar-wpjson --dominio imagina.cl
uv run python -m flujocero.cli probar-wpjson --dominio santolaya.cl     # esperar que FALLE — confirmaría el indicio Laravel/CI
uv run python -m flujocero.cli probar-wpjson --dominio ingevecinmobiliaria.cl
uv run python -m flujocero.cli probar-wpjson --dominio iaconcagua.com

# 2 · para los que SÍ respondan JSON en el paso 1: enumerar sitemap + volcar JSON-LD de 2-3
#     páginas de proyecto real, para escribir el selector de precio (como se hizo con Socovesa/Pilares)
uv run python -m flujocero.cli probar-wpjson --dominio iarmas.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio fundamenta.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio rvc.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio imagina.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio ingevecinmobiliaria.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio iaconcagua.com --volcar-ld 2
```

Orden sugerido: `fundamenta.cl`, `rvc.cl` e `imagina.cl` primero (wp-json ya confirmado por
investigación anterior — es la corrida de menor riesgo y mayor certeza de éxito), después
`iarmas.cl` (indicio fuerte pero no confirmado, mayor payoff de comuna/ticket), y por último
`santolaya.cl`/`paz.cl` como pruebas de descarte rápido (si `probar-wpjson` falla en el primer
paso — ni `/wp-json/wp/v2/types/proyecto` ni `/wp-json/wp/v2/proyecto?per_page=5` devuelven JSON —
confirma el indicio de Laravel/CodeIgniter/SPA y cierra la pregunta sin gastar más tiempo).

## 4 · Descartadas, con razón

| Candidato | Razón de descarte | Fuente |
|---|---|---|
| **almagro.cl** | **Ya descartado en ADR 011** (03-sep-2026): tickets observados UF 10.590–16.790, todos sobre el tope UF 6.000 de la Ley 21.748; además su theme no expone REST por proyecto. No se re-investigó en esta ronda — se cita para que nadie lo vuelva a sondear pensando que es nuevo. | `docs/adr/011-wpjson-inmobiliarias.md` |
| **manquehue.cl** | Catálogo mayoritariamente en comunas EXCLUIDAS del alcance del §10 (Las Condes, Providencia, Lo Barnechea, Colina); el único ejemplo de ticket encontrado (Las Condes) fue UF 9.340, sobre el tope. Tiene proyectos en Ñuñoa/La Florida (p.ej. "Estadio Nacional") que sí calzarían, pero el volumen que aportaría un colector completo del dominio sería mayormente descarte. Prioridad baja; revisitar solo si se decide filtrar por proyecto individual en vez de por dominio. | [bancoestado.enlaceinmobiliario.cl/inmobiliaria-manquehue](https://bancoestado.enlaceinmobiliario.cl/inmobiliaria-manquehue/152) |
| **ecasa.cl** | Su huella geográfica declarada (Santiago sin comuna específica, Concón, Papudo, Coquimbo, Arica, Temuco, La Serena, Villarrica, Ovalle, San Felipe) no mostró, en esta ronda, ninguna comuna concreta del §10 ni un proyecto verificado en las tres ciudades de Fase 3. Sin overlap confirmado, no justifica sonda antes que las candidatas ALTA. | [linkedin.com/company/ecasainmobiliariayconstructora](https://cl.linkedin.com/company/ecasainmobiliariayconstructora), [ecasa.cl/proyecto/el-real](https://www.ecasa.cl/proyecto/el-real) |
| **Inmobiliaria Núcleos** | Sin dominio propio identificable en esta ronda — solo una página de Facebook ("Inmobiliaria Núcleos \| Santiago"). El resultado más prominente para "Inmobiliaria Núcleo" fue una agencia de **idealista.com**, que es **española**, no chilena — riesgo de confundir entidades si se avanza sin más evidencia. Descartada por evidencia insuficiente, no por mal ajuste. | [facebook.com/inmobiliarianucleos](https://www.facebook.com/inmobiliarianucleos/), [idealista.com/en/pro/inmobiliarianucleo](https://www.idealista.com/en/pro/inmobiliarianucleo/venta-viviendas/) |
| **Urbánika** (urbanikaoficial.com) | Sin evidencia en esta ronda de que opere en alguna comuna del alcance chileno; el dominio y el nombre de marca son ambiguos (podría ser una operación fuera de Chile). Descartada por evidencia insuficiente. | [urbanikaoficial.com](http://www.urbanikaoficial.com/) |
| **"Croacia"** | Cero resultados relevantes de una inmobiliaria chilena con ese nombre en el segmento de departamentos nuevos. Podría ser un nombre de proyecto puntual (no de una inmobiliaria) o un error en el listado de candidatas del brief. Descartada por falta de evidencia de existencia como entidad separada. | (sin fuente — búsqueda sin resultados) |
| **icom.cl** (visto en `icom.cl/macul`, proyecto UF 2.852) | Parece ser un dominio de landing/agregador de terceros (posible herramienta de marketing compartida entre inmobiliarias) y no el sitio propio de una inmobiliaria — no se pudo atribuir con certeza a una empresa concreta en esta ronda. Se anota la duda para una ronda dedicada, no se descarta la comuna/ticket (Macul, UF 2.852 es un buen dato), se descarta el dominio como candidato de colector por ahora. | [icom.cl/macul](https://icom.cl/macul/) |

No se encontró en esta ronda evidencia de que alguno de los candidatos ALTA/MEDIA dependa
**exclusivamente** del cotizador PlanOK para el precio (que exigiría el mismo descarte que
ADR 010 le aplicó a esa vía): eso solo se puede confirmar mirando si la página del proyecto
tiene un iframe/redirect a `cotizador.saladeventasdigital.com`, algo que exige la corrida viva —
`probar-wpjson --volcar-ld` ya vuelca el HTML completo de la página de proyecto, así que el
`grep saladeventasdigital` es gratis en la misma corrida.

## 5 · Entrada sugerida para `config/fuentes.yml` (NO aplicada — solo para pegar tras verificar)

La entrada `wpjson_inmobiliarias` ya existe y hoy dice `dominios: [socovesa.cl, pilares.cl]`.
Una vez que `probar-wpjson` confirme wp-json vivo + robots permitido para los candidatos ALTA,
la lista a ampliar (dentro de la MISMA entrada, no una nueva — mismo colector, mismo `PERFILES`)
sería:

```yaml
  - id: wpjson_inmobiliarias
    dominios: [socovesa.cl, pilares.cl]   # + candidatos de esta ronda, uno a uno, según confirme probar-wpjson:
    dominios_candidatos_2026_09:          # NO enabled — pendientes de robots+wp-json vivo
      - iarmas.cl          # San Miguel/Ñuñoa/Santiago Centro/La Florida, indicio WP fuerte, ticket bajo (UF 1.836 observado)
      - fundamenta.cl      # wp-json ya confirmado (01-fuentes.md); falta perfil de precio HTML
      - rvc.cl             # wp-json ya confirmado; único con Antofagasta (Fase 3)
      - imagina.cl         # wp-json ya confirmado; Santiago Centro UF 2.480-3.550
      - ingevecinmobiliaria.cl   # comunas casi idénticas al §10; wp-json sin verificar
      - iaconcagua.com     # única con Fase 3 completa (La Serena/Antofagasta/Concepción); wp-json sin verificar
    dominios_a_verificar_si_es_wordpress:   # indicios EN CONTRA de WP — sondear para descartar rápido, no para construir
      - santolaya.cl       # URL con /public/index.php/ → probable Laravel/CodeIgniter
      - paz.cl             # rutas tipo SPA (nuevaweb.paz.cl, AccesoUsuario) → probable app a medida
```

## 6 · Qué falta para que esto se vuelva un ADR real

Por cada dominio de la lista ALTA, en la máquina local:
1. `probar-wpjson --dominio X` → si falla el robots o el JSON, se anota y se pasa al siguiente.
2. Si responde JSON, `probar-wpjson --dominio X --volcar-ld 2` → fixture cruda + inspección manual
   del HTML de la página de proyecto para localizar el bloque de precio (puede no calzar con los
   selectores de Socovesa/Pilares: cada theme es distinto, como ya pasó entre esos dos).
3. Con eso, un nuevo par de fixtures en `tests/fixtures/wpjson/` + entrada en `PERFILES` +
   `selftest_fixture()` actualizado — trabajo de implementación normal de T-925c, no de scouting.
4. Solo entonces se escribe el ADR con robots verbatim + SHA y se sube `enabled: true`.
