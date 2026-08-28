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


---

## D-011 · ¿Conviene sumar la renta de la cónyuge? **BLOQUEA el ticket objetivo**
**Estado:** parcialmente resuelta · **Dueño:** banco + notaría · **Abierta:** 28-ago-2026
**Actualizada:** 28-ago-2026 con los datos del inversionista.

El inversionista plantea complementar renta con su cónyuge ($2.500.000 líquidos).
Aritméticamente el efecto es grande y está calculado:

| Renta considerada | Dividendo máx | Ticket máx (con subsidio, 3,30%, 30 años, LTV 90%) |
|---|---|---|
| Solo él, $2.250.000 | $562.500 | **UF 3.497** |
| Conjunta, $4.750.000 | $1.187.500 | **UF 6.000** (tope legal) |

O sea: **la restricción deja de ser la renta y pasa a ser la ley.** Eso cambia el universo
de búsqueda por completo.

**Pero el beneficio tributario y el subsidio no son aritmética, y no están resueltos.**
Cuatro preguntas, ninguna respondible desde el modelo:

1. ~~Régimen patrimonial~~ → **RESUELTO: participación en los gananciales.** Durante el
   matrimonio los patrimonios se mantienen **separados** y cada cónyuge administra y es dueño
   de lo suyo; al disolverse no se dividen bienes, se compara la ganancia de cada uno y se
   compensa con un **crédito en dinero**. Para lo que nos importa —quién figura como dueño y
   a quién se le imputa el cupo DFL2— **funciona como separación de bienes.**
   *Confianza alta, pero se confirma con el notario antes de escriturar. El §2.5 del contrato
   es explícito: el DFL2 se verifica en la escritura, nunca en lo que diga un tercero.*
2. ~~¿Tiene propiedades?~~ → **RESUELTO: no tiene ninguna.** Califica al subsidio bajo las dos
   lecturas del requisito en disputa, igual que él. **Son dos solicitantes elegibles, no uno.**
3. ~~¿Cupos DFL2 usados?~~ → **RESUELTO: cero.** El hogar dispone de **4 cupos DFL2**
   (2 por persona natural, Ley 20.455), no de 2.
4. **¿El banco acepta co-deudor sin exigir co-propiedad?** ÚNICA PREGUNTA ABIERTA. Sólo
   importa si se elige la Estructura A. **Debe confirmarse por escrito** con cada banco.

## Las dos estructuras, ahora que los datos están

| | **A · una unidad, ambos co-deudores** | **B · una unidad cada uno** |
|---|---|---|
| Ticket máximo | UF 6.000 (tope legal) | UF 3.497 él + UF 3.886 ella = **UF 7.383** |
| Propiedades | 1 | **2** |
| Subsidios usados | 1 | **2** (ambos califican) |
| Cupos DFL2 consumidos | 1 o 2, según quién escriture | **1 de cada uno; quedan 2 libres** |
| Diversificación de microzona | ninguna | **dos microzonas distintas** |
| Depende del banco | **sí** (pregunta 4) | no |

**La Estructura B domina en todas las dimensiones medibles.** Más ladrillo total, dos
subsidios en vez de uno, dos cupos DFL2 preservados para después, riesgo repartido en dos
microzonas, y no depende de que el banco acepte co-deudor sin co-propiedad.

Y encaja con el hallazgo del §2.3 del contrato: **dos tickets chicos alcanzan el pie de
equilibrio antes que uno grande**, porque el ahorro disponible se reparte sobre un precio
total menor por unidad. Además ambos tickets caben bajo UF 3.000 si se apunta ahí, que es el
tramo especial de D-009.

**Riesgo específico de la Estructura A** que ya no aplica si se elige B: escriturar a nombre
de los dos consume **dos cupos DFL2 en una sola propiedad**, la peor asignación posible de un
recurso del que sólo hay cuatro en toda la vida del hogar.

### CORRECCIÓN 28-ago-2026 · la Estructura B no aplica

El inversionista aclara que **los $40.000.000 son suyos, no del hogar**, y que su intención
nunca fue una compra conjunta: la idea de sumar la renta era para **respaldar su propia
solicitud ante el banco**, incurriendo él en la deuda y quedando él como dueño.

Eso invalida la Estructura B tal como estaba planteada: suponía que cada comprador financiaba
su propio pie. Sin ahorro propio de la cónyuge, la segunda unidad no tiene con qué escriturarse.
**La comparación anterior era correcta en la aritmética y equivocada en el supuesto.**

### La estructura que sí corresponde

**C · compra individual, cónyuge como codeudora solidaria sin co-propiedad.**
Él pone el pie, él escritura, él usa 1 de sus 2 cupos DFL2. Ella respalda la solicitud.

Lo que hay que separar con cuidado, porque el lenguaje del banco los mezcla:

| Figura | ¿Responde por la deuda? | ¿Queda como dueña? | ¿Gasta su cupo DFL2? |
|---|---|---|---|
| **Codeudora solidaria** | sí | **no** | **no** |
| **Co-propietaria** | sí | sí | **sí — se pierde un cupo** |

**Si el banco exige co-propiedad para aceptar la renta, la operación pasa a costar un cupo
DFL2 del hogar.** Ahí hay que decidir si el mayor monto aprobado lo vale. Con 4 cupos
disponibles y ninguno usado, probablemente no.

### Preguntas al banco, en orden de importancia

1. **¿Aceptan codeudor solidario sin exigir que figure en la escritura como propietario?**
   Es LA pregunta. Si la respuesta es no, la ganancia de monto cuesta un cupo DFL2.
2. **¿Ser codeudora consume su condición de "primera vivienda" para un subsidio futuro?**
   Si la consume, hoy no cuesta nada pero cierra una puerta que hoy está abierta.
3. ¿Cuánto sube efectivamente el monto aprobado al sumarla? Puede ser menos de lo que sugiere
   la aritmética: varios bancos ponderan la renta del codeudor, no la suman entera.

**Y algo que no es financiero:** una codeudora solidaria responde por el 100% de la deuda,
no por la mitad. No es un trámite, es una obligación real de ella. Conviene que lo sepa antes
de firmar, no después.

**Decisión operativa:** el caso base es **compra individual, UF 3.497**, con el pie saliendo
de los $40.000.000 propios. La renta conjunta se modela sólo como escenario de contraste,
condicionado a la respuesta 1.

**Qué falta para cerrar del todo:** (a) confirmación del notario de que bajo participación en
los gananciales la propiedad adquirida es individual para efectos de DFL2 — trámite de
minutos al escriturar; (b) la respuesta del banco a la pregunta 4, que sólo importa si se
vuelve a considerar la Estructura A.


---

## D-012 · ¿El ranking debe ordenar por déficit de caja o por costo real de tenencia?
**Estado:** abierta · **Dueño:** humano · **Abierta:** 28-ago-2026
**§8.4:** cambiar esto mueve el ranking en bastante más del 10% de las posiciones, así que
no se decide sin aprobación explícita.

### El hallazgo

El inversionista declara capacidad de ahorro de $400.000 mensuales y preferencia por **no
tener déficit**, y pide optimizar sobre otros indicadores dado que "pie ≤20% + flujo no
negativo" es inalcanzable en la RM (hallazgo §2.3).

Al descomponer el déficit mensual entre gasto y amortización aparece esto (unidades de
demostración, valores sintéticos — la forma del hallazgo es lo que importa, no las cifras):

| unidad | sale del bolsillo | de eso, es ahorro | costo real | % que es ahorro |
|---|---|---|---|---|
| SM-1D-35 | $225.485 | $157.966 | **$67.518** | 70% |
| CO-1D-40 | $198.895 | $167.748 | **$31.146** | 84% |
| NU-2D-55 | $432.372 | $297.706 | **$134.665** | 69% |

**Entre el 69% y el 84% del "déficit" no es una pérdida: es compra de patrimonio**, pagada
en parte por el arrendatario. El costo económico real es entre 3 y 6 veces menor que la cifra
de caja que hoy encabeza el score con 30% de peso.

### La decisión

`config/params.yml` pondera hoy `deficit_flujo_mensual_uf` con 30%. La pregunta es si ese
componente debe pasar a `costo_tenencia_mensual_uf`.

| | **Mantener déficit de caja** | **Cambiar a costo real de tenencia** |
|---|---|---|
| Qué optimiza | liquidez mensual | rentabilidad económica |
| Riesgo | descarta unidades buenas por una cifra que exagera el costo entre 3 y 6 veces | premia unidades que exigen más caja de la que el inversionista quiere comprometer |
| Encaja con | "no quiero tener déficit" | "capacidad de ahorro $400.000" |

**Las dos preferencias declaradas apuntan a lados opuestos**, y por eso la decisión es suya
y no del modelo.

**Recomendación:** **mostrar ambas columnas y ordenar por costo real, con un filtro duro por
déficit de caja máximo.** Así el ranking premia la economía real y el filtro respeta el
límite de liquidez. El filtro se fija en `deficit_mensual_tolerado_clp`, hoy 0.

**Advertencia que debe quedar en la UI si se adopta:** la amortización **no es líquida**.
Construye patrimonio, pero para convertirlo en plata hay que vender o refinanciar, y ambas
cosas cuestan y toman meses. Un inversionista con déficit sostenido y sin colchón puede ser
solvente y estar ilíquido a la vez.

### Un dato incómodo que conviene decir junto con esto

El modelo corre en UF, términos reales. El arriendo real no crece y el dividendo en UF
tampoco baja. **El déficit mensual no mejora con el tiempo por sí solo** — no hay un año en
que la unidad "empiece a rendir". Lo único que lo mueve es más pie, mejor tasa, o un mercado
con mejor yield. Esperar no es una estrategia.
