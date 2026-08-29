# PRD — Flujo Cero
**Versión 1.0 · 28-ago-2026 · Autor: Alvaro Cabreira**

---

## 1. Problema

En agosto de 2026 coinciden en Chile cuatro condiciones que no se habían dado juntas:

1. **Subsidio a la tasa hipotecaria ampliado** (Ley 21.748 + ampliación promulgada el 26-ago-2026):
   viviendas **nuevas** hasta **UF 6.000**, **80.000 cupos**, vigencia hasta **31-may-2028**,
   **60 puntos base** de rebaja directa sobre la tasa.
2. **Garantía estatal FOGAES** que habilita **90% de financiamiento** (pie de 10%).
3. **Tasas hipotecarias en mínimos desde diciembre de 2021** (promedio BCCh 3,97% en jul-2026;
   3,28%–4,31% con subsidio según MINVU).
4. **Exención transitoria de IVA a viviendas nuevas** (aprobada por el Congreso el 04-ago-2026;
   publicación en Diario Oficial **pendiente de verificar**).

Y una restricción dura: al **21-ago-2026** ya hay **43.278 solicitudes** y **34.917 créditos
formalizados** de los 80.000 cupos. Al ritmo actual (~35.000 en 14 meses) **los cupos se agotan
hacia fines de 2027**, antes del vencimiento legal. **La ventana es de meses, no de años.**

El inversionista particular no tiene forma de responder, hoy, con datos:
- qué proyectos nuevos existen y **a qué precio por unidad** (los portales muestran "desde");
- cuánto renta **realmente** un departamento equivalente en esa **microzona** exacta;
- cuál es el flujo de caja, el cap rate y el pie mínimo para que el activo no le cueste plata cada mes.

## 2. Objetivo

Un sistema que recolecte, normalice y evalúe continuamente el universo de departamentos nuevos
elegibles, y produzca un **ranking auditable de oportunidades de inversión**, donde cada número
sea trazable hasta su fuente.

### 2.1 Métrica de éxito del producto
- **Cobertura**: ≥ 2.000 unidades de proyectos nuevos con **precio real por unidad** en la RM al cierre de Fase 2.
- **Profundidad de comparables**: ≥ 8 comparables de arriendo por `(microzona × tipología)` en el 80% de las microzonas activas.
- **Exactitud financiera**: el dividendo calculado difiere <1% del simulador del banco en 10 casos reales verificados a mano.
- **Utilidad**: el usuario identifica en <5 minutos las 10 unidades con menor déficit mensual a su pie objetivo, y puede explicar por qué.

### 2.2 No objetivos (v1)
- No es un CRM ni un gestor de visitas.
- No hace tasación automática de propiedades usadas.
- No opera ni ejecuta compras.
- No cubre casas, oficinas, locales ni terrenos.
- No pretende predecir precios futuros más allá de un supuesto declarado de plusvalía real.

## 3. Usuario

Un único usuario primario: un inversionista particular chileno, financieramente sofisticado,
que evalúa comprar **entre una y tres unidades** con pie de 10–20%, y que prioriza —
por orden declarado — **flujo de caja no negativo**, luego plusvalía, luego liquidez de salida.

**Restricción estructural que el producto debe comunicarle, no ocultarle:** con yields brutos de
3,5–4,3% en stock nuevo del Gran Santiago y dividendos a 30 años, el pie de equilibrio está en
**34%–47%**. Un pie de 10–20% implica déficit mensual. El producto **minimiza y cuantifica ese
déficit** y muestra dónde desaparece (Concepción, La Serena, Antofagasta), en vez de fabricar
optimismo.

## 4. Alcance funcional

### F1 · Base de proyectos nuevos en venta
- Descubrimiento de proyectos por comuna vía API MercadoLibre (site `MLC`), Pabellón, Enlace
  Inmobiliario y las tiendas oficiales de inmobiliarias en Portal Inmobiliario.
- Obtención de **precio por unidad** vía: cotizador PlanOK (`cotizador.saladeventasdigital.com`),
  `/wp-json/wp/v2/proyecto` + JSON-LD de las inmobiliarias, y parseo de listas de precios en PDF.
- Campos por unidad: `proyecto_id, numero_unidad, tipologia, dormitorios, banos, m2_utiles,
  m2_terraza, piso, orientacion, precio_uf, precio_estacionamiento_uf, precio_bodega_uf,
  fecha_entrega, estado (blanco/verde/inmediata), descuentos_vigentes, acogido_dfl2`.
- Historización SCD-2: **cambios de precio a lo largo del tiempo** (una baja de precio es señal de compra).

### F2 · Base de comparables de arriendo
- Assetplan (`edificios.xml`, 175 edificios, `lastmod` diario) como ancla de arriendo efectivo y vacancia.
- MELI `MLC` arriendo y Chilepropiedades (respetando `Crawl-delay: 2`) como mercado abierto.
- Agregación a `(microzona × tipologia × rango_m2)`: mediana, p25, p75, n, días en mercado
  cuando esté disponible, y **conteo de avisos activos como proxy de saturación**.

### F3 · Microzonificación
- Diccionario de barrios desde `classified_locations/countries/CL` de MercadoLibre
  (cascada country → state → city → neighborhood): son los barrios que efectivamente usan los listings.
- Join espacial contra **manzanas del Censo 2024 del INE** (GeoParquet, 189 variables socioeconómicas).
- Enriquecimiento: distancia a estación de Metro operativa y en construcción con fecha;
  valor m² de **área homogénea del SII**; marcas de saturación de `config/zonas.yml`.

### F4 · Motor financiero
Por unidad y por escenario de financiamiento, todo en UF reales:
dividendo (sistema francés), PGI, EGI (con erosión intra-anual), NOI, cap rate bruto y neto,
DSCR, cash-on-cash, BTCF y ATCF mensual, **arriendo de equilibrio**, **pie mínimo para flujo cero**,
break-even occupancy, TIR real apalancada a 10/20/30 años, VAN, y GRM.
Escenarios obligatorios: `{con_subsidio, sin_subsidio} × {pie 10%, 15%, 20%, pie_equilibrio} × {DFL2 sí/no}`.

### F5 · Ranking y score
Score explícito y auditable (ver CLAUDE.md §12), con penalizaciones duras que excluyen
en vez de restar. Cada componente visible en la ficha de la unidad.

### F6 · Dashboard
- **Ranking** con filtros: comuna, microzona, tipología, rango UF, pie objetivo, DFL2, entrega.
- **Ficha de unidad**: cascada financiera completa, comparables usados con enlace a la fuente,
  las seis columnas de procedencia, y `evidence_level` visible en cada número.
- **Mapa** (MapLibre) coloreado por yield o por déficit de flujo, a nivel de microzona.
- **Comparador** de hasta 4 unidades lado a lado.
- **Simulador**: mover pie, tasa, plazo, vacancia y arriendo y ver el flujo recalcularse en vivo.
- **Alertas**: unidades nuevas que entran al top 20, y bajadas de precio.

### F7 · Outreach asistido
Redacción y encolado de solicitudes de lista de precios a salas de venta, con **aprobación humana
obligatoria por lote**, tope de 40/día, un recordatorio único, opt-out permanente, e ingesta
automática de los PDF/XLSX que lleguen por respuesta.

### F8 · Export
XLSX con el ranking y las cascadas financieras; PDF de una página por unidad para llevar al banco
o a la sala de ventas.

## 5. Criterios de aceptación por fase

### Fase 0 · Cimientos (sin red)
- [ ] Motor financiero completo con `mypy --strict` y 7 casos de oro verdes (CLAUDE.md §7.2).
- [ ] `config/params.yml` con todos los supuestos y su `evidence_level`.
- [ ] Esquema DuckDB creado y `make rebuild` reconstruye desde cero.
- [ ] Dos implementaciones independientes del dividendo coinciden a 1e-6.

### Fase 1 · Un extremo a otro sobre 3 comunas
- [ ] UF, UTM y tasas ingestadas desde CMF con fallback a Gael Cloud.
      *(29-ago-2026: UF y UTM listas, fallback implementado (T-908, ADR 006). Falta
      la parte de **tasas**: la CMF no tiene fuente vigente por banco — T-907.)*
- [ ] Diccionario de microzonas de MELI materializado y unido a manzanas INE.
- [ ] ≥300 unidades con precio real en San Miguel, La Florida y Ñuñoa.
- [ ] ≥8 comparables de arriendo por `(microzona × tipología)` en el 70% de las microzonas activas.
- [ ] Ranking generado y `make gates` verde.
- [ ] Dashboard sirviendo ranking + ficha + mapa.

### Fase 2 · Expansión RM
- [ ] ≥2.000 unidades con precio real en las 11 comunas de fase 1+2.
- [ ] Parser de PDF con ≥90% de acierto sobre el corpus de fixtures.
- [ ] Pipeline de outreach operativo con aprobación humana.
- [ ] Reconciliación contra transacciones reales (Data Inmobiliaria) con `factor_gap_lista_cierre` calibrado.

### Fase 3 · Regiones y automatización
- [ ] Gran Concepción, La Serena y Antofagasta incorporadas.
- [ ] Corrida diaria automatizada con alertas.
- [ ] Backtest: ¿las unidades que el score puso en el top 20 hace N semanas se vendieron antes que el resto?

## 6. Riesgos y mitigación

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **El tramo UF 4.000–6.000 exige comprador primerizo** | Invalida la tesis completa para quien ya tiene propiedades | Modelar **siempre** los dos escenarios; monitorear la publicación del decreto reglamentario en LeyChile; verificar con el banco antes de comprometer capital |
| Cupos de subsidio agotados antes de tiempo | La ventana se cierra | Mostrar contador de cupos consumidos en el dashboard y priorizar unidades con entrega inmediata |
| Portal Inmobiliario bloquea (WAF, 403) | Se pierde cobertura | La ruta principal es la **API oficial de MercadoLibre**, no el HTML. Pabellón y Enlace Inmobiliario como respaldo |
| Parser roto en silencio | Datos malos que parecen buenos | Gate de caída >30% en conteo de resultados vs corrida anterior (CLAUDE.md §7.1) |
| Ley 21.719 en vigor el 01-dic-2026 | Multas de hasta 20.000 UTM | Cero datos personales en la base analítica desde el día uno (CLAUDE.md §3.4) |
| Comparables de arriendo insuficientes en una microzona | Yield inventado | Penalización dura: `n < 8` excluye del ranking, no se imputa |
| Precio de lista ≠ precio de cierre | Yields optimistas | Calibración con transacciones reales del CBR (Capa 5) |

## 7. Preguntas abiertas (bloquean decisiones, no el desarrollo)

Registradas y actualizadas en `docs/05-decisiones.md`:

1. ¿El tramo UF 4.000–6.000 exige no ser propietario? *(decreto reglamentario pendiente al 28-ago-2026)*
2. ¿Cuál es el **número** de la ley de ampliación? La prensa recicla mal "21.748", que es la ley original de may-2025.
3. ¿Se publicó la exención de IVA y con qué tope? Vale ~800 UF en un departamento de UF 5.000.
4. ¿`/sites/MLC/search` exige `Bearer` hoy? ¿Cuál es el tope real de resultados y el rate limit numérico?
5. ¿Se compra el dataset de transacciones del CBR (DataBAM / Data Inmobiliaria) o basta el tier gratuito?
6. ¿Qué presupuesto hay para proxies, APIs de pago y el plan de datos?
