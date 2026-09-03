# Scouting · segunda ronda de inmobiliarias WordPress para T-925c (03-sep-2026)

**Estado: reconocimiento, no verificación.** Igual que la ronda 1 (`docs/scouting-wpjson-2026-09.md`),
este documento **no es un ADR de fuente**: el protocolo de fuente-scout exige `robots.txt` verbatim +
SHA256 antes de clasificar `legal_tier`, y ese paso no se pudo ejecutar aquí. Es el insumo para que
la siguiente corrida de `probar-wpjson` en la máquina local sepa a quién sondear a continuación.

No se repiten candidatas de la ronda 1: `iarmas.cl`, `fundamenta.cl`, `rvc.cl`, `imagina.cl`,
`santolaya.cl`, `ingevecinmobiliaria.cl`, `iaconcagua.com`, `py.cl`, `exxacon.cl` (ya ALTA/MEDIA en
ronda 1, wp-json en curso o confirmado), ni las ya operativas `socovesa.cl`/`pilares.cl`/`almagro.cl`.
Tampoco se re-investigan `isinergia.cl`, `icafalinmobiliaria.cl`, `euroinmobiliaria.cl`,
`simonetti.cl`, `paz.cl`, `gimax.cl`, `pocuro.cl`, `bricsa.cl`: ya están en la tabla MEDIA/BAJA de la
ronda 1 con su propia evidencia — usar ese documento para ellas, no este.

## 0 · Bloqueo de red — confirmado de nuevo, no reintentado más allá de una prueba

Un único intento de `WebFetch` contra `https://www.absal.cl/robots.txt` (elegido porque es un
candidato nuevo, no uno ya probado en ronda 1) confirma que el bloqueo sigue vigente en este
contenedor:

```
{"error_type":"EGRESS_BLOCKED","domain":"www.absal.cl","message":"Access to www.absal.cl is blocked by the network egress proxy."}
```

No se reintentó. Toda esta ronda corre exclusivamente sobre `WebSearch`. Consecuencia idéntica a
la ronda 1: **cero robots.txt descargado, cero SHA256, cero `/wp-json/` probado en vivo.** "¿WordPress?"
abajo es inferencia por indicios indirectos (URLs `/wp-content/uploads/`, patrones de ruta,
subdominios de plataforma compartida) — nunca una confirmación. Ningún candidato de este documento
puede clasificarse `legal_tier` todavía.

## 1 · Método

Igual que ronda 1: `WebSearch` por inmobiliaria — (a) ¿existe y vende departamentos NUEVOS?,
(b) ¿en qué comunas/ciudades, cruzado contra el §10 de `CLAUDE.md`?, (c) ¿qué rango de ticket UF
citan fuentes/listados?, (d) indicios de stack. Se agregaron búsquedas específicas
`"{dominio}/wp-content"` para cada candidato con overlap de comuna confirmado, para intentar
encontrar una URL de `/wp-content/uploads/` indexada (la señal más fuerte posible sin tocar la red
directamente, porque `wp-content` es exclusivo del núcleo de WordPress — a diferencia de un slug de
categoría, que un tema a medida podría replicar).

## 2 · Tabla de candidatas

| Dominio | Comunas/ciudades observadas (fuente) | Ticket UF observado | ¿WordPress? | Estado | Prioridad | Razón |
|---|---|---|---|---|---|---|
| **aitue.cl** (Inmobiliaria Aitue) | Concepción, San Pedro de la Paz, Los Ángeles — dentro de Fase 3; también Santiago (sin comuna específica) ([aitue.cl/proyectos](https://www.aitue.cl/proyectos/), [aitue.cl/propiedades-departamentos](https://www.aitue.cl/propiedades-departamentos/)) | UF 2.443–4.828 en Concepción (Altos del Valle, 2 dorm. desde 4.828) ([aitue.cl/propiedades-departamentos/altos-del-valle/concepcion](https://www.aitue.cl/propiedades-departamentos/altos-del-valle/concepcion/)) | **Indicio fuerte de sí**: dos PDFs indexados en `aitue.cl/wp-content/uploads/2021/04/...` — `wp-content` es una carpeta exclusiva del núcleo de WordPress, no un slug que un theme a medida pueda imitar ([Hacienda-Las-Cruces.pdf](https://www.aitue.cl/wp-content/uploads/2021/04/Hacienda-Las-Cruces.pdf), [Edificio-Espacio-Freire.pdf](https://www.aitue.cl/wp-content/uploads/2021/04/Edificio-Espacio-Freire.pdf)) | por verificar — WP núcleo confirmado, CPT sin confirmar | **ALTA** | 25 años en Concepción, 8.000+ viviendas históricas, ticket bien dentro del tope, y el único indicio de `wp-content` real (no inferido) de toda esta ronda. Máxima prioridad para Fase 3. |
| **neourbe.cl** (Inmobiliaria NeoUrbe / Neo Urbe) | **La Cisterna** (NeoBrisas, NeoCisterna, NeoCisterna2 — 3 proyectos), Santiago Centro/Barrio Yungay (NeoYungay), San Bernardo (NeoCentro, fuera de alcance) ([neourbe.cl/proyectos-inmobiliarios/neobrisas](https://neourbe.cl/proyectos-inmobiliarios/neobrisas), [neourbe.cl/blog/neobrisas](https://www.neourbe.cl/blog/neobrisas-conoce-este-nuevo-departamento-en-venta-en-la-cisterna)) | NeoBrisas desde UF 2.274–2.430 (1 dorm., ~29,5 m²) hasta UF 2.361+ listado agregado ([amh.enlaceinmobiliario.cl/la-cisterna/neobrisas](https://amh.enlaceinmobiliario.cl/la-cisterna/departamento/neobrisas/9181)) | Sin indicio directo de `wp-content` en esta ronda; ruta `/proyectos-inmobiliarios/{slug}` no es un slug WP por defecto pero es compatible con un CPT custom | por verificar | **ALTA** | Único candidato de la ronda con **tres** proyectos confirmados en La Cisterna (yield 4,06%, vacancia MF más baja de la RM — hallazgo §2 del PRD), ticket muy bajo el tope, y menciona FOGAES explícitamente en su propio marketing. |
| **absal.cl** (Inmobiliaria Absal) | Santiago Centro (Zenteno, Chiloé-Prat, Eleuterio Plaza), Recoleta (Avenida Perú Plaza), Macul (Exequiel II), Estación Central — cobertura casi completa del §10 RM ([absal.cl/proyectos](https://absal.cl/proyectos/), [absal.cl/blog/proyectos-inmobiliarios-santiago-guia-2025-absal](https://absal.cl/blog/proyectos-inmobiliarios-santiago-guia-2025-absal)) | UF 2.550 (Recoleta), UF 2.584–2.790 (Santiago Centro) — bien bajo el tope ([mismo fuente]) | **Indicio en contra**: una URL indexada es `absal.3a.cl/proyectos/` — el subdominio `3a.cl` sugiere una plataforma/CMS compartida de terceros (posible proveedor de sitios para inmobiliarias chicas), no necesariamente WordPress propio; el dominio principal `absal.cl` no mostró ningún `/wp-content/` indexado en esta ronda | por verificar — señal mixta | **ALTA** | Mejor calce de comuna+ticket de toda la ronda 2 (5 comunas del §10), pero el indicio del subdominio `3a.cl` es una bandera real: sondear primero con `probar-wpjson` antes de invertir en parser. |
| **siena.cl** (Siena Inmobiliaria) | Macul (Siena Santa Cristina, cerca de futura L8), La Florida (Siena Parque Vicuña Mackenna) — Las Condes, Vitacura, Lo Barnechea fuera de alcance. **Ojo**: su proyecto de La Cisterna citado en prensa (La Tercera) es **multifamily de ARRIENDO, no de venta** — no cuenta para B3/oferta de venta | UF 3.599–5.400 en Macul (Santa Cristina, 2–3 dorm.) — dentro del tope pero en el extremo alto ([enlaceinmobiliario.cl/macul/siena-santa-cristina](https://bancoestado.enlaceinmobiliario.cl/macul/departamento/siena-santa-cristina/6977)) | Sin indicios en esta ronda | por verificar | MEDIA | Overlap real pero acotado a 2 comunas para VENTA (el de La Cisterna es arriendo, se descarta esa línea); ticket en el rango alto reduce margen bajo el tope UF 6.000. |
| **norte-verde.cl** (Inmobiliaria Norte Verde) | **La Serena** (Playa Serena, Rengifo 120, Umbrales) — Fase 3 ([norte-verde.cl/proyectos-ventas](https://norte-verde.cl/proyectos-ventas/), [norte-verde.cl/proyecto/playa-serena](https://norte-verde.cl/proyecto/playa-serena/)) | No cuantificado en esta ronda (Playa Serena reporta "más del 60% vendido" pero sin precio UF en los snippets) | Indicio débil: ruta singular `/proyecto/{slug}/` + versión `/en/proyecto/{slug}/` (sugiere plugin WPML de WordPress, aunque no es concluyente); ya listado como `❓ no verificada` en `docs/01-fuentes.md` B.2 | por verificar | MEDIA | Único candidato exclusivo de La Serena de esta ronda; falta cuantificar ticket antes de subir prioridad. |
| **malpo.cl** (Constructora e Inmobiliaria Malpo) | La Florida, Ñuñoa, Santiago (dominio general, según agregador) — resto de su catálogo en Melipilla, Talca, Parral, Los Ángeles, Rengo, Curicó, Linares, fuera de alcance ([enlaceinmobiliario.cl/metropolitano/inmobiliaria-malpo](https://www.enlaceinmobiliario.cl/metropolitano/inmobiliaria-malpo/244/)) | UF 1.600–3.900 citado para su catálogo general (no aislado a RM); un listado agregado de "La Florida" (posiblemente multi-inmobiliaria, no solo Malpo) muestra UF 2.853–4.990 — **el ticket específico de Malpo en comunas de alcance no está aislado en esta ronda** | Sin indicios en esta ronda | por verificar | MEDIA | Cobertura RM real pero minoritaria dentro de un catálogo mayormente regional (Maule/O'Higgins); no se pudo aislar el ticket de las unidades RM del resto del catálogo — riesgo de que el colector traiga mucho ruido fuera de alcance. |
| **actual.cl** (Inmobiliaria Actual) | Ñuñoa, Macul (dentro) — Las Condes, Providencia, Huechuraba (fuera) ([actual.cl](https://actual.cl/), [portalinmobiliario.com/h/blog/inmobiliaria-actual](https://www.portalinmobiliario.com/h/blog/inmobiliaria-actual)) | No cuantificado para Ñuñoa/Macul específicamente en esta ronda; rangos de m² conocidos (23–149 m²) pero sin precio UF aislado | Sin indicios en esta ronda | por verificar | MEDIA | Solo 2 de sus ~5 comunas activas caen en el alcance; sin ticket aislado, no se puede confirmar que esas unidades queden bajo UF 6.000. |
| **galilea.cl** | **La Serena** y **Concepción** (Praderas de Coronel desde UF 1.720–1.600 con subsidio, Cumbres de Lomas Verdes desde UF 2.160) — dentro de Fase 3; resto del catálogo nacional (Valparaíso, Limache, Quilpué, Los Andes, Chicureo, Buin, Rancagua, Machalí, Rengo, Curicó, Talca, Linares, San Carlos, Chillán, Los Ángeles, Valdivia, Osorno, Puerto Montt) fuera de alcance ([galilea.cl/ciudad/la-serena](https://www.galilea.cl/ciudad/la-serena/), [galilea.cl/category/concepcion](http://www.galilea.cl/category/concepcion/)) | UF 1.600–2.160 en los proyectos de Concepción citados — muy bajo el tope | Sin indicios en esta ronda | por verificar | MEDIA | Ticket excelente y presencia confirmada en 2 de las 3 ciudades de Fase 3, pero el catálogo nacional es 15+ ciudades: mismo riesgo de ruido que Malpo — el colector tendría que filtrar agresivamente por ciudad. |
| **lontue.com** (Inmobiliaria Lontue) | **Concepción** exclusivamente (Edificio Nuevo Lientur, Edificio Antuco) — Fase 3 ([lontue.com/departamentos-en-venta-en-concepcion](https://lontue.com/departamentos-en-venta-en-concepcion/), [lontue.com/proyectos/edificio-antuco-concepcion-centro-udd](https://lontue.com/proyectos/edificio-antuco-concepcion-centro-udd/)) | UF 2.064–3.345 (Studio a 2 dorm., DS1 Tramo 3) ([bancoestado.enlaceinmobiliario.cl vía búsqueda agregada]) | Sin indicios en esta ronda (dominio `.com`, no `.cl` — no cambia el análisis legal pero es atípico entre las candidatas) | por verificar | MEDIA | 30+ años en Concepción, catálogo 100% dentro de Fase 3, ticket bajo — pero sin overlap RM, así que no aporta a Fase 1/2. Buen complemento de `aitue.cl` para diversificar Concepción. |
| **urbani.cl** | Concepción (mayor cartera del sur, según prensa), Chillán, Los Ángeles, Pucón, Puerto Montt (mayoría fuera de alcance) — **ya anotado en `docs/01-fuentes.md` B.3 como "Entrante 2026, foco en subsidios"**, pero esa entrada lo trata como AGREGADOR, no como wp-json candidato ([urbani.cl/comuna/concepcion](https://urbani.cl/comuna/concepcion/), [df.cl/urbani-mayor-cartera-sur](https://www.df.cl/regiones/biobio/empresas/urbani-la-inmobiliaria-con-la-mayor-cartera-de-proyectos-del-sur-critica)) | UF 1.400–8.000 en todo su catálogo nacional (sin aislar Concepción) | Sin indicios en esta ronda | por verificar | MEDIA | **Advertencia de duplicidad**: Urbani opera como "brazo comercial" de terceros — el 95% de su oferta pertenece a otras constructoras. Si esas mismas constructoras ya están en `wpjson_inmobiliarias` o se agregan por su cuenta (p.ej. Aitue, Lontue), sondear Urbani podría **duplicar filas** en vez de sumar cobertura nueva. Verificar solapamiento de proyectos antes de construir el parser. |
| **iproyeccion.cl** (Inmobiliaria Proyección) | Concepción (dentro de Fase 3); San Joaquín (**excluido explícitamente del alcance — vacancia MF 42,1%, §10**), Las Condes (fuera, sobre tope), Puerto Montt (fuera de alcance geográfico) ([iproyeccion.cl/departamentos](https://www.iproyeccion.cl/departamentos)) | No cuantificado para Concepción en esta ronda | Sin indicios en esta ronda | por verificar | BAJA | De 4 ubicaciones observadas, solo 1 (Concepción) cae dentro del alcance — la peor tasa de acierto de la ronda entre los candidatos con evidencia real. |

## 3 · Comandos de sonda, en orden de prioridad

```bash
# 1 · ALTA — máxima certeza de payoff (comuna+ticket confirmados, indicio de stack)
uv run python -m flujocero.cli probar-wpjson --dominio aitue.cl        # wp-content confirmado por indexación
uv run python -m flujocero.cli probar-wpjson --dominio neourbe.cl      # 3 proyectos en La Cisterna
uv run python -m flujocero.cli probar-wpjson --dominio absal.cl        # ojo: puede fallar si de verdad vive en absal.3a.cl

# 2 · Si el paso 1 falla para absal.cl, probar el subdominio de plataforma compartida directamente
#     (esto NO es wp-json de absal.cl — es una hipótesis a descartar rápido, no un nuevo candidato)
uv run python -m flujocero.cli probar-wpjson --dominio absal.3a.cl

# 3 · Para los que SÍ respondan JSON: volcar JSON-LD / HTML de proyecto real
uv run python -m flujocero.cli probar-wpjson --dominio aitue.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio neourbe.cl --volcar-ld 2
uv run python -m flujocero.cli probar-wpjson --dominio absal.cl --volcar-ld 2

# 4 · MEDIA — segunda ola, después de agotar la ALTA
uv run python -m flujocero.cli probar-wpjson --dominio siena.cl
uv run python -m flujocero.cli probar-wpjson --dominio norte-verde.cl
uv run python -m flujocero.cli probar-wpjson --dominio malpo.cl
uv run python -m flujocero.cli probar-wpjson --dominio actual.cl
uv run python -m flujocero.cli probar-wpjson --dominio galilea.cl
uv run python -m flujocero.cli probar-wpjson --dominio lontue.com
uv run python -m flujocero.cli probar-wpjson --dominio urbani.cl       # verificar solapamiento de proyectos con Aitue/Lontue antes de construir el parser, no solo el wp-json
```

## 4 · Descartadas, con razón

| Candidato | Razón de descarte | Fuente |
|---|---|---|
| **Vimac** (vimac.cl) | Catálogo 100% en la región de Valparaíso (Quilpué, Quillota, Villa Alemana, Viña del Mar/Reñaca) — **Viña del Mar y Valparaíso están explícitamente excluidos del alcance en el §10 de `CLAUDE.md`** (absorción 24,6 meses / deterioro estructural del stock). Ningún proyecto cae en comuna del alcance. | [vimac.cl/proyectos-en-venta](https://vimac.cl/proyectos-en-venta/) |
| **BCF** | Cero resultados relevantes que identifiquen una inmobiliaria chilena activa con ese nombre/sigla en el segmento de departamentos nuevos — los resultados devolvieron solo portales bancarios y agregadores sin relación. Descartada por evidencia insuficiente. | (sin fuente — búsqueda sin resultados atribuibles) |
| **"Índice"** | La búsqueda solo devolvió papers académicos sobre índices de precios de vivienda y portales genéricos — ninguna entidad identificable como "Inmobiliaria Índice". Mismo patrón que "Croacia" en la ronda 1: probable error o nombre de proyecto puntual, no de empresa. Descartada por falta de evidencia de existencia. | (sin fuente — búsqueda sin resultados atribuibles) |
| **Suksa** (suksa.cl) | Las únicas direcciones concretas encontradas son oficinas (venta en Providencia/Las Condes, post-venta en Estación Central, oficina central en Las Condes) — **direcciones de oficina no son ubicación de proyecto**. Ningún proyecto propio con comuna confirmada dentro del alcance en esta ronda. Revisitar solo si una ronda dedicada aísla proyectos reales por comuna. | [laborum.cl/suksa](https://www.laborum.cl/perfiles/empresa_inmobiliaria-suksa-limitada_13355172.html), [suksa.cl](https://www.suksa.cl/) |
| **Ecasa, Núcleos, Urbanika, "Croacia"** | **Ya descartadas en ronda 1** (`docs/scouting-wpjson-2026-09.md` §4) por huella geográfica sin overlap confirmado o evidencia insuficiente de existencia como entidad separada. No se re-investigaron aquí — se listan para que nadie las vuelva a sondear pensando que son nuevas. | `docs/scouting-wpjson-2026-09.md` |

Ningún candidato de esta ronda mostró depender **exclusivamente** de PlanOK para el precio (mismo
chequeo que ronda 1: se confirma recién con `--volcar-ld`, buscando `saladeventasdigital.com` en el
HTML volcado).

## 5 · Entrada sugerida para `config/fuentes.yml` (NO aplicada — solo para pegar tras verificar)

Misma entrada `wpjson_inmobiliarias` de siempre (mismo colector, mismo `PERFILES`); esta ronda solo
amplía la lista de candidatos pendientes:

```yaml
  - id: wpjson_inmobiliarias
    dominios: [socovesa.cl, pilares.cl]
    dominios_candidatos_2026_09_ronda2:      # NO enabled — pendientes de robots+wp-json vivo
      - aitue.cl           # Concepción/San Pedro de la Paz/Los Ángeles; único wp-content confirmado por indexación
      - neourbe.cl         # 3 proyectos en La Cisterna (yield 4,06%, vacancia MF más baja de la RM)
      - absal.cl           # Santiago Centro/Recoleta/Macul/Estación Central; ojo con absal.3a.cl
      - siena.cl           # Macul/La Florida (ticket en el extremo alto del tope); su proyecto de La Cisterna es ARRIENDO, no venta
      - norte-verde.cl     # La Serena (Fase 3); ticket sin cuantificar
      - malpo.cl           # La Florida/Ñuñoa/Santiago; catálogo mayormente fuera de alcance (Maule/O'Higgins)
      - actual.cl          # Ñuñoa/Macul; ticket sin aislar de sus comunas fuera de alcance
      - galilea.cl         # La Serena/Concepción (Fase 3); catálogo mayormente fuera de alcance (15+ ciudades)
      - lontue.com         # Concepción exclusivamente (Fase 3); dominio .com, no .cl
      - urbani.cl          # Concepción y sur; riesgo de duplicar filas de Aitue/Lontue (95% de su oferta es de terceros)
      - iproyeccion.cl     # Concepción; baja prioridad, 3 de 4 ubicaciones fuera de alcance
```

## 6 · Qué falta para que esto se vuelva un ADR real

Idéntico al cierre de la ronda 1: por cada dominio ALTA, en la máquina local, `probar-wpjson
--dominio X` (aborta si robots.txt prohíbe) → si responde JSON, `--volcar-ld 2` para fixture cruda +
localizar el bloque de precio en el HTML de la ficha de proyecto → nuevas fixtures en
`tests/fixtures/wpjson/` + entrada en `PERFILES` + `selftest_fixture()` → **solo entonces** se
escribe el ADR con robots verbatim + SHA y se sube `enabled: true`. Para `urbani.cl` específicamente,
sumar un paso previo: comparar los `slug` de proyecto contra los de `aitue.cl`/`lontue.com` una vez
que esos dos tengan datos reales, para confirmar si aporta cobertura nueva o solo redundancia.
