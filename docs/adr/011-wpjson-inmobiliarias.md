# ADR 011 · Colector wp-json + HTML permitido de inmobiliarias WordPress (T-925c)

- **Estado:** aceptada · 03-sep-2026
- **Fuente:** `wpjson_inmobiliarias` · capa 3 · `legal_tier: html_permitido` · piloto: `socovesa.cl`
- **Contexto:** ADR 010 y su adenda descartaron el cotizador PlanOK como fuente masiva
  (la cotización exige datos personales). Esta es la ruta #3 de `docs/01-fuentes.md`:
  el JSON público de WordPress más el HTML que robots permite.

## La ruta, verificada contra el sitio vivo

Cuatro corridas de `probar-wpjson --volcar-ld` (02/03-sep-2026, desde la máquina del
inversionista; todas las respuestas en `data/raw/wpjson_inmobiliarias/`) fijaron esto:

1. **Enumeración:** `sitemap.xml` → `proyecto-sitemap.xml` lista 116 páginas de **unidad**
   (`…/nuestros-proyectos/<proyecto>/<unidad>/`). El slug de proyecto del sitemap puede
   estar desactualizado — `punta-maitenes-…/` da 404 mientras la canónica real es otra —
   así que **no se navega por el path**, se resuelve por REST.
2. **Metadata:** cada página declara `<link rel="alternate" type="application/json">` →
   `wp/v2/proyecto/<id>`. La colección (`?per_page=`) redirige a HTML, pero el registro
   individual responde JSON con `parent` (unidad → proyecto), `link` (URL canónica) y
   `class_list` con las taxonomías: `ciudad-*`, `estado-*` (venta-en-blanco /
   entrega-inmediata), `tipologia-*` (casa/departamento), `disponibilidad-*` (agotada).
3. **Precio:** NO está en el REST (`acf` vacío). Vive en el HTML de la página del
   proyecto: bloques de modelo con `ul.planta_list` (m², dormitorios, baños),
   `div.planta_precio > p.uf` ("3.390 UF") y el botón "Cotizar unidad" cuyo `data-url`
   trae el slug del modelo. El JSON-LD de la página de unidad solo trae la Organization.

## Decisión

- **Colector híbrido:** sitemap para enumerar, REST para metadata y canónicas, HTML del
  proyecto para el precio. Una unidad representante por proyecto (4 requests por
  proyecto, pausa ≥1 s o el Crawl-delay de robots, raw primero, §3.6).
- **`precio_es_desde=TRUE` y fuera del ranking.** Lo que Socovesa publica es
  *"Precio desde"* **por modelo**, no precio por unidad. B1 exige precio real, así que el
  emparejamiento excluye estas filas (`agg/oportunidades.py`, `agg/faltantes.py`). Lo que
  sí aportan: censo de la oferta nueva con su piso de precio, comuna/estado por proyecto,
  y la señal de baja de precio vía SCD tipo 2.
- Columna nueva `fact_unidad_venta.precio_es_desde BOOLEAN` (migración idempotente en
  `schema/schema.sql`).

## Legal

- robots.txt de socovesa.cl: **permitido** para `/nuestros-proyectos/` y `/wp-json/`
  (verificado en cada corrida de la sonda; el veredicto y su sha viajan en cada fila).
- Sin formularios, sin datos personales, sin simular navegador: User-Agent honesto
  `FlujoCero-ResearchBot/1.0`.
- El `wp-json` es la API pública estándar de WordPress; el HTML es el mismo que ve
  cualquier visitante.

## Adenda 03-sep-2026 · el grupo Socovesa completo

La sonda contra los otros dominios de Empresas Socovesa (detectados por el
`almagro_widget` en el HTML) resolvió el siguiente paso:

- **Pilares (`pilares.cl`): INCORPORADO.** Departamentos en la RM (La Florida, Estación
  Central observadas), tickets UF 1.690–3.990 — justo el rango del subsidio. Jerarquía de
  TRES niveles (`proyecto → modelo → unidad`, cada uno un post `proyecto` encadenado por
  `parent`); el precio "desde" vive en la página del MODELO
  (`p.single__details__dividendo`), y el REST del modelo trae comuna (`comuna-*`), estado,
  disponibilidad y dormitorios/baños como tags. El colector generaliza: escala la cadena
  `parent` completa y un `PERFILES[dominio]` dice en qué nivel parsear el precio.
- **Almagro (`almagro.cl`): DESCARTADO por ahora, con dato.** Precios desde observados
  UF 10.590–16.790: todo sobre el tope UF 6.000 de la Ley 21.748 — ningún proyecto puede
  entrar al ranking. Además su theme no expone REST por proyecto (solo `pages/`). Queda
  anotado en `fuentes.yml`; se revisita solo si el alcance deja de estar atado al subsidio.

## Límites conocidos

- El catálogo de Socovesa es mayormente **casas** (Huechuraba, Chicureo, Chillán) y varias
  unidades `disponibilidad-agotada`: pocos departamentos en las comunas del §10. El valor
  del piloto es la **ruta**, replicable en otras inmobiliarias WordPress (el criterio de
  T-925c pide ≥300 unidades/tipologías en la RM: exige sumar dominios).
- El precio por unidad de proyectos nuevos sigue abierto (los canales del §9 — cotizador
  PlanOK uno a uno, formularios — son la vía, con aprobación humana por lote).
- `modelos_de_html` está calibrado al theme de Socovesa (`planta_precio`/`planta_list`);
  otro dominio puede requerir un segundo juego de selectores. El selftest de fixture
  corre antes de cada recolección y la corrida imprime conteos para el ojo humano.
- **`dim_proyecto` queda congelada apenas tiene filas de fact que la referencian**: DuckDB
  implementa UPDATE reescribiendo la fila y la FK lo veta. Un cambio posterior de
  nombre/estado no se aplica pero SÍ se cuenta (`proyectos_congelados_con_cambio` en el
  resumen de la corrida). Refrescarla exigiría soltar la FK: decisión aparte si el
  contador empieza a moverse.
