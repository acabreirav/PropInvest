# 05 · Decisiones abiertas y ADRs

Toda decisión no obvia se registra acá. Las marcadas **BLOQUEA** detienen una tarea del backlog.

---

## D-001 · ¿El tramo UF 4.000–6.000 exige comprador primerizo?
**Estado:** RESUELTA PARA ESTE INVERSIONISTA (28-ago-2026) · **Vigilancia:** T-900

> **El inversionista no tiene propiedades ⇒ califica bajo cualquiera de las dos lecturas.**
> El escenario base pasa a `con_subsidio`; `sin_subsidio` queda solo como contraste.
> La disputa sigue importando para el tramo especial ≤ UF 3.000 (ver D-009). Contexto original abajo.

El **Decreto 180 exento, art. 3** (tramo general) exige *"primera **venta** de la vivienda"* —
condición del **inmueble**. El art. 4 (tramo especial ≤ UF 3.000) sí exige primera vivienda del
**solicitante**. El decreto no fija límite de subsidios por beneficiario.
Pero el comunicado de Hacienda y la guía Ley Fácil de BCN dicen "primera vivienda" para ambos tramos,
y T13 reporta que el FOGAES ampliado aplica a primera **y segunda** vivienda.

**El reglamento del tramo ampliado no está publicado al 28-ago-2026**, y es justamente donde el
Ejecutivo podría introducir una restricción de titularidad, dado que las críticas legislativas
apuntan a que UF 6.000 beneficia a hogares de ingresos altos.

**Decisión provisional:** el sistema modela **siempre** `con_subsidio` y `sin_subsidio`, y la UI
muestra la advertencia. No se toma partido.
**Acción:** vigilar LeyChile y el Diario Oficial semanalmente; confirmar con un ejecutivo bancario.

---

## D-002 · ¿Cuál es el número de la ley de ampliación?
**Estado:** abierta · Varios medios reciclan "Ley 21.748", que es la ley **original de may-2025**.
La norma de agosto 2026 modifica la Ley 21.543 (FOGAES) y la 21.748.
**No citar un número en la UI hasta verificarlo en LeyChile / Diario Oficial.**

---

## D-003 · ¿Se publicó la exención de IVA a viviendas nuevas y con qué tope?
**Estado:** abierta · Aprobada por el Congreso el 04-ago-2026; publicación en Diario Oficial sin
confirmar. Una fuente da tope UF 4.000, otra dice sin tope. Vigencia 12 meses, retroactividad al
22-abr-2026, ahorro ~16% del precio.
**Impacto: ~800 UF en un departamento de UF 5.000.** `params.yml` lo tiene en `null` — el modelo
no lo aplica hasta confirmarlo. Tarea T-902.

---

## D-004 · ¿Qué hacemos con Portal Inmobiliario?
**Estado:** decidida · **Decisión: NO scrapear HTML de fichas.**
`robots.txt` bloquea `/propiedades/`, los T&C de MELI prohíben scrapers, y hay WAF con 403 desde
datacenter. Usamos la **API oficial de MercadoLibre (site MLC)**, que es la misma data por la puerta.
`portalinmobiliario_html` queda `enabled: false` en `config/fuentes.yml` con la razón registrada.

---

## D-005 · ¿Compramos datos de transacciones reales del CBR? **BLOQUEA T-033**
**Estado:** abierta · Requiere presupuesto.
- **Data Inmobiliaria**: tier gratuito con mapa y export Excel, 346 comunas, 15 años, fuentes
  SII+CBR+TGR+portales. **Mejor ROI inmediato — empezar por acá.**
- **DataBAM**: 20+ comunas del Gran Santiago con **ROL, precios y coordenadas**, desde $50.000/mes,
  con API y venta de datasets masivos.

Sin transacciones reales, todos los yields se calculan sobre **precio de lista**, que sobreestima el
precio de cierre por un factor desconocido. Es la brecha metodológica más grande del sistema.

---

## D-006 · Presupuesto general
**Estado:** abierta · Pendiente de definir: APIs de pago (BaseAPI SII discontinúa su tier gratuito
el 11-dic-2026), proxies (**preferencia declarada: no usarlos**), plan de datos CBR, y hosting.

---

## D-007 · ¿Dónde se ejecuta el sistema?
**Estado:** decidida · **Claude Code local + repo git.**
El scraping chileno necesita IP residencial chilena, sesiones persistentes y reintentos largos;
desde un sandbox en la nube el bloqueo es rápido y las sesiones son efímeras. El motor financiero,
los tests y el dashboard corren igual en cualquier lado, pero conviene tener todo en un mismo repo
versionado. Para la corrida diaria de fase 3, evaluar un VPS chileno.

---

## D-008 · Umbral de comparables mínimos
**Estado:** decidida · **n ≥ 8 por (microzona × tipología)** para publicar una mediana.
Bajo eso, `ND` y exclusión del ranking. Relajarlo requiere una entrada nueva acá, con datos que
justifiquen que la varianza a n menor sigue siendo tolerable.


---

## D-009 · ¿Conviene apuntar al tramo especial ≤ UF 3.000? **BLOQUEA el ticket objetivo**
**Estado:** abierta · **Dueño:** humano + banco

El Decreto 180 **art. 4** reserva **6.000 de los 80.000 cupos** a viviendas **≤ UF 3.000**,
exigiendo **primera vivienda del solicitante**. Nuestro inversionista califica; la mayoría de los
inversionistas no. Otras fuentes describen ese tramo atado a subsidios DS1/DS19, lo que sería una
condición distinta y mucho más restrictiva (exige RSH y acreditar vulnerabilidad). **Sin resolver.**

**Por qué importa tanto:** el tramo ≤ UF 3.000 coincide con los tickets donde los yields son más
altos — 1D1B compactos, Concepción, La Cisterna, Estación Central. Si además su tasa es mejor que
la del tramo general, **apuntar a ≤ UF 3.000 domina en las dos dimensiones a la vez**: mejor yield
y menor costo de fondos, o sea el pie de equilibrio más bajo alcanzable con este perfil.

**Preguntas exactas para el ejecutivo del banco:**
1. ¿El tramo de 6.000 cupos para viviendas ≤ UF 3.000 exige DS1/DS19, o basta con ser primera vivienda?
2. ¿Qué tasa ofrece ese tramo versus el tramo general?
3. ¿Cuántos cupos les quedan asignados a ustedes, en cada tramo?

**Hasta resolverlo:** `ticket_max_uf: 6000`, pero el informe reporta por separado el subconjunto ≤ UF 3.000.

---

## D-010 · Estrategia de las dos unidades DFL2
**Estado:** decidida · Objetivo: **2 unidades**, el máximo por persona natural.

La 3ª propiedad pierde el arriendo exento de renta, la rebaja del 50% de contribuciones y la
exención de IVA de arriendo. Su economía es estructuralmente peor y ningún modelo lo compensa.
**Antes de llegar ahí, la vía es una segunda persona natural** (cónyuge con separación de bienes),
que duplica el cupo DFL2 **y** la exención de ganancia de capital de UF 8.000.
**Nunca una sociedad: la persona jurídica no accede a DFL2 en absoluto.**

Operativamente: `exigir_dfl2: true`, exclusión dura de todo lo que supere 140 m² útiles, y
verificación del DFL2 en escritura o certificado municipal antes de firmar.
