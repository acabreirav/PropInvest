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


---

## D-013 · ¿Debe un `robots.txt` caído detener una API oficial con credencial?
**Estado:** abierta · **Dueño:** humano · **Abierta:** 28-ago-2026

`api.cmfchile.cl` devolvió `robots.txt` con 404 en una corrida y con 500 veinte minutos
después, mientras sus endpoints de datos respondían HTTP 200 sin problema. El colector se
detuvo, correctamente según el RFC 9309, pero la situación deja una pregunta de fondo.

**El caso.** La CMF es `legal_tier: api_oficial`: API pública documentada, con apikey bajo
registro gratuito a nombre del inversionista. `robots.txt` es un protocolo para **crawlers
anónimos**; el acceso a una API con credencial lo gobiernan sus términos de servicio, no un
archivo pensado para buscadores. Aun así el §3.1 exige un `robots_snapshot_sha` en cada
fila, y para tenerlo hay que consultarlo.

**Lo que ya se hizo, sin cambiar política:** cuando el servidor está caído se reutiliza el
snapshot guardado en una corrida anterior, que es lo que el RFC 9309 §2.3.1.3 admite. Un
snapshot real es mejor evidencia que cualquier suposición, y si ese snapshot decía
`Disallow`, sigue prohibiendo. Eso resuelve el caso práctico sin relajar nada.

**Lo que queda por decidir**, y no lo decide el modelo:

| | **Mantener como está** | **Eximir a `api_oficial`** |
|---|---|---|
| Qué pasa | sin snapshot y con el servidor caído, no se recolecta | se recolecta igual, registrando el intento fallido en la procedencia |
| A favor | una sola regla para todas las fuentes; imposible relajarla por accidente | robots.txt no gobierna una API con credencial, y un servidor caído bloquea un acceso legítimo |
| En contra | la primera corrida en una máquina nueva puede quedar bloqueada por una caída ajena | abre una excepción por `legal_tier`, y las excepciones se erosionan |

**Recomendación: mantener como está.** El respaldo por snapshot ya cubre el caso real, y la
excepción por tier es exactamente la clase de puerta que después se usa para otra cosa. Si
en la práctica vuelve a bloquear, se reabre con evidencia.

---

## D-014 · MercadoLibre cerró la búsqueda: ¿de dónde sale la oferta ahora?
**Estado:** abierta, a la espera de la medición G5 · **Dueño:** humano · **Abierta:** 28-ago-2026

`/sites/MLC/search` devolvió **HTTP 403 con token válido y sin token**, el 28-ago-2026, desde
la máquina del usuario con IP residencial chilena. El mismo token, en la misma corrida, leyó
`/sites/MLC/categories` sin problema: no es la app, no es el token, no es la IP. Es ese recurso.
Detalle completo en `docs/adr/003-meli.md`.

**Por qué esto es una decisión y no un bug.** El §13.6 del contrato prohíbe scrapear Portal
Inmobiliario en HTML y da una razón concreta: *"Usa la API oficial de MercadoLibre (site MLC).
Es la misma data, por la puerta."* Si esa puerta se cerró, el §13.6 pierde su alternativa —y
el §8.4 manda detenerse y preguntar cuando un hallazgo del contrato deja de ser cierto.

**Lo que falta antes de decidir.** La medición G5, ya escrita, prueba las formas que la
documentación todavía describe (`category=`, `seller_id=`, `/highlights/`, `/trends/`, multiget)
y dice si queda alguna. No tiene sentido decidir sobre una hipótesis cuando la medición cuesta
un comando.

**Si G5 confirma que no queda ruta**, las opciones son:

| | **A · Capa 3 por las inmobiliarias** | **B · Comprar el dato** | **C · Scrapear Portal Inmobiliario** |
|---|---|---|---|
| Qué es | `planok_cotizador`, `inmobiliarias_wpjson`, `pabellon`, `enlace_inmobiliario` — todas `json_publico` o `html_permitido` | Data Inmobiliaria plan pago, DataBAM | HTML prohibido por su `robots.txt`, con WAF |
| Dato que da | **precio por unidad**, estacionamiento y bodega aparte: mejor que un aviso | transacciones reales (CBR), no oferta | avisos, igual que MELI |
| Costo | trabajo de colectores, ya presupuestado en el backlog | plata, y requiere tu aprobación (§8.4) | — |
| Riesgo | cobertura desigual entre inmobiliarias | ninguno legal | **viola el §3.5 y el §13.6** |

**Recomendación: A, y B solo para calibrar el gap lista→cierre.** La opción A no es un plan de
contingencia peor: el cotizador PlanOK entrega precio **por unidad** con estacionamiento y
bodega separados, que es exactamente lo que el §7.4 pide y lo que un aviso de portal no tiene.
MELI servía para amplitud, no para calidad.

**C queda descartada de entrada, pase lo que pase.** Que la alternativa oficial se cierre no
convierte en permitido lo que un `robots.txt` prohíbe. Si esa es la única salida, el alcance se
recorta antes que la regla.

**Efecto colateral, ya aplicado:** `assetplan_arriendo` sube a fuente **primaria** de la capa 4.
Su `robots.txt` permite explícitamente ClaudeBot, cubre 175 edificios con `lastmod` diario, y es
arriendo **efectivo** —no precio pedido—, que es lo que el §4 exige como numerador del yield.

---

## D-015 · El stock usado entra al ranking como escenario
**Estado:** decidida por el usuario · **Fecha:** 28-ago-2026

El usuario aportó que "el subsidio ahora incluye viviendas usadas hasta UF 4.000". La
información es real, pero corresponde a **un instrumento distinto** del que el proyecto
modela. La prensa los junta en un solo titular y por eso conviene dejarlos separados aquí.

### Los tres instrumentos, separados

| Instrumento | Tope | ¿Usadas? | Fuente |
|---|---|---|---|
| **Subsidio a la tasa** (Ley 21.748, Decreto 180) — 60 pb | UF 6.000 | **No.** Exige *primera venta del inmueble* (art. 3) | BCN Ley Fácil; Decreto 180 exento |
| **FOGAES ampliado** — garantía, habilita 90% LTV | UF 6.000 (subió desde 4.000), desde sept-2026 | **Sin confirmar** | prensa ago-2026 |
| **Subsidio Tramo 4.000 (DS1 Tramo 4)** — aporte directo 400 UF | UF 4.000 (4.500 zonas extremas) | **Sí** | Minvu / gob.cl ago-2026 |

### Por qué el Tramo 4.000 no sirve para este inversionista

El DS1, **en cualquiera de sus tramos**, exige que la vivienda *"sea habitada personalmente
por el beneficiario y/o su núcleo familiar"* y **prohíbe arrendarla o venderla durante 5 años**
desde la compra. Pide además Registro Social de Hogares y 200 UF de ahorro con 12 meses de
antigüedad, y son 5.000 cupos en un llamado de nov-2026.

La tesis completa del proyecto es arrendar desde el primer mes. No es que el subsidio sea
subóptimo: es **incompatible**, y tomarlo arrendando igual es causal de revocación. Queda
declarado en `params.yml:subsidio_ds1_tramo4` con `aplicable_a_este_inversionista: false`
para que ningún agente futuro lo vuelva a proponer.

### Lo que sí se decidió

La intuición económica de fondo es correcta y sobrevive al error de vehículo: **el stock
usado rinde más y por eso llega a flujo cero con menos pie.** El propio §13.3 del contrato lo
admite sin decirlo cuando advierte que los "13,3% de Cerro Navia" son stock usado.

**Decisión: el usado entra como escenario, no como pivote.** Concretamente:

1. `score.exclusiones_duras.solo_vivienda_nueva` pasa a `false`. El usado compite.
2. **El motor le niega el subsidio a la tasa, y eso no lo decide la config.** Se agregó
   `finance/modelo.tasa_aplicable(u, e, p)`: si la unidad no es de primera venta, devuelve la
   tasa sin subsidio aunque el escenario pida `con_subsidio`, y deja el motivo escrito en la
   evaluación. Es la clase de error que el §7.6 manda buscar: aplicarle 60 pb de rebaja a un
   inmueble que la norma no cubre produce una oportunidad falsa, más atractiva en la pantalla
   que en la escritura.
3. La tasa aplicada manda en **todo** el cálculo —dividendo, amortización, pie de equilibrio
   y saldo insoluto para la TIR—, no solo en el dividendo. Bajar el dividendo y dejar el resto
   a la tasa vieja dejaría el modelo incoherente consigo mismo sin que se note.
4. Se agregó el caso de oro simétrico: **sin subsidio de por medio, un usado y un nuevo
   idénticos deben dar exactamente lo mismo.** Si difieren, es que se coló una penalización
   encubierta en vez de un supuesto declarado.

### Lo que encontró la revisión adversarial (§7.6)

La primera versión de `tasa_aplicable` hacía caer al usado a
`financiamiento.tasa_anual_sin_subsidio` (3,97%, el **promedio** de mercado) mientras el nuevo
conservaba `tasa_mejor_caso_fogaes` (3,30%, un **mejor caso**). Eso son **67 pb** de castigo
donde la norma solo quita 60, y mezcla dos cosas distintas: "no califica al subsidio" con
"consiguió peor banco". El mejor caso sin subsidio es 3,39% — a **9 pb**.

La diferencia entre 9 y 67 pb decide si el usado gana o pierde la comparación. Corregido: el
`Escenario` ahora declara `tasa_sin_subsidio` explícitamente y el emparejamiento es mejor caso
con mejor caso. Caso de oro: **perder el subsidio no puede costar más de 60 pb.**

Queda una pregunta de datos que esto destapó: que el mejor caso con subsidio (3,30%) y sin
subsidio (3,39%) estén a 9 pb, cuando el subsidio son 60 pb, sugiere que las tasas observadas
no aíslan el efecto del subsidio —vienen de bancos y fechas distintas. → T-914.

### Lo que queda abierto

- **¿FOGAES cubre viviendas usadas o solo primera venta?** Es la pregunta que más mueve la
  aguja y no la pude resolver con fuentes públicas. Si las cubre, el usado se compra con 10%
  de pie y el objetivo de minimizar pie sobrevive. Si no, exige ~20% y la comparación cambia
  por completo. **Va al banco.**
- **¿El subsidio a la tasa tiene límite de unidades por persona?** Una fuente bancaria sugiere
  que no; el inversionista quiere dos. `params.yml` lo tiene como `null` con evidencia `C`.
  **Va al banco.**
- **DFL2 en usado:** el beneficio de renta sigue a la propiedad, pero la rebaja de
  contribuciones corre desde la recepción municipal. Un usado de 15 años podría tener esa
  ventana consumida, y el DFL2 es lo que más vale en valor presente (§2.5). El modelo hoy
  **no** distingue antigüedad al aplicar la rebaja: es un supuesto optimista y hay que
  cerrarlo antes de rankear usado con datos reales. → T-911.
- **De dónde salen los avisos de usado.** Esto empeora con el 403 de MercadoLibre, no mejora:
  la obra nueva tiene caminos permitidos que no pasan por portales (PlanOK, wp-json de
  inmobiliarias, Pabellón, Enlace); el usado vive disperso en los portales, que es justo donde
  se cerró la puerta. Queda Chilepropiedades (permite crawling) y el catastro SII. → T-912.

### Efecto colateral que juega a favor

La **Capa 1 (catastro SII)** estaba planificada como ancla determinística y resulta ser mucho
más valiosa para usado que para nuevo: un departamento usado tiene rol SII con avalúo, año de
construcción, materialidad y m² registrados. Un proyecto nuevo a veces ni tiene roles
individuales todavía. Esa capa pasa de ancla a fuente de atributos.

**Fuentes:** [BCN Ley Fácil — subsidio a la tasa para viviendas nuevas](https://www.bcn.cl/api-leyfacil/servicio/ObtenerGuiaPublicadaHTML?uri=subsidio-a-la-tasa-de-interes-hipotecaria-para-la-adquisicion-de-viviendas-nuevas) ·
[Decreto 180 exento de 2025](https://fogaes.cl/wp-content/uploads/2026/05/Decreto-180-exento-de-2025.-Reglas-generales-de-funcionamiento-del-Subsidio-a-la-Tasa-de-Interes-de-Creditos-Hipotecarios-de-Viviendas-Nuevas.pdf) ·
[Minvu — Subsidio Sectores Medios D.S.1](https://www.minvu.gob.cl/postulacion/primer-llamado-nacional-2026-para-postular-al-subsidio-para-sectores-medios-d-s-1/) ·
[Serviu Maule — anuncio Tramo 4.000](https://serviumaule.minvu.gob.cl/noticia/minvu-anuncio-nuevo-tramo-4-000-en-expo-vivienda-y-bancoestado-presenta-hipotecario-pro/) ·
[T13 — Fogaes ampliado](https://www.t13.cl/noticia/te-puede-servir/para-viviendas-hasta-6000-uf-como-funciona-fogaes-ampliado-desde-cuando-estara-26-8-2026) ·
[UsaTuSubsidio — prohibiciones de las viviendas con subsidio habitacional](https://usatusubsidio.cl/noticias/prohibiciones-de-las-viviendas-con-subsidio-habitacional/) ·
[BioBioChile — razones por las que te pueden quitar el subsidio](https://www.biobiochile.cl/noticias/servicios/explicado/2023/11/29/las-6-razones-por-las-que-te-pueden-quitar-el-subsidio-habitacional.shtml)

---

## D-016 · Aprobación humana para scrapear fuentes `html_prohibido`
**Estado:** aprobada por el usuario · **Fecha:** 28-ago-2026 · **Autoriza:** Álvaro Cabreira

El §3.5 del contrato clasifica Portal Inmobiliario como `html_prohibido` —su `robots.txt`
bloquea `/propiedades/`— y establece que esa categoría **requiere aprobación humana explícita
registrada aquí**. Este es ese registro.

### Lo que el usuario autoriza, textual

> *"no tengo problema que corras el scrapper de nuevo, creo que es clave actualizar la data
> (...) No comercializaré la data ni nada (...) es solo para yo detectar oportunidades, es
> como un vitrineo masivo con ayuda de scrapping."*

Se le planteó la objeción antes de que decidiera (Ley 21.719, `robots.txt`, y que Portal
Inmobiliario corre sobre la API de MercadoLibre que acaba de cerrarse). La reafirmó. Decisión
tomada: **se procede.**

### Qué cambia

`legal_tier: html_prohibido` deja de ser un bloqueo absoluto y pasa a ser **una fuente que
exige esta aprobación citada en su ADR**. Todo colector de esa categoría debe referenciar
D-016 en `config/fuentes.yml` y en su ADR, o no se habilita.

El uso personal y no comercial sí modifica el análisis de **términos de servicio**: no hay
reventa, ni producto derivado, ni redistribución. Eso es real y es lo que sostiene la decisión.

### Qué NO cambia, y no depende de la intención del usuario

1. **Ley 21.719.** Que el uso sea personal no saca a un dato personal de su ámbito, y el hecho
   de que sea público tampoco. Los avisos traen nombre, teléfono y correo del corredor:
   **eso no entra a la base analítica, punto.** El §3.4 sigue vigente sin excepción.
2. **No se escala contra bloqueos técnicos.** Si el sitio responde 403 o pone un WAF, se acata.
   Nada de proxies residenciales, rotación de identidad ni evasión de detección: el §3.5 ya
   dice que un scraper que necesita proxies residenciales es la señal de que estás en la
   categoría equivocada. La aprobación cubre recolectar, no cubre esquivar.
3. **Cadencia moderada y `User-Agent` honesto.** Se respeta `Crawl-delay` donde exista y se
   sigue identificando con el UA declarado. No se disfraza de navegador.
4. **La data no se redistribuye.** Queda en la máquina del usuario y en su base local.

### Consecuencia inmediata

Desbloquea T-912 (de dónde salen los avisos de vivienda usada). El orden de preferencia del
§3.5 **no se invierte**: se sigue prefiriendo API oficial y `json_publico` cuando existan. Lo
que esta decisión habilita es el último recurso, no el primero.

Nota de realidad, medida ayer: Portal Inmobiliario corre sobre MercadoLibre, y
`/sites/MLC/search` devuelve 403 desde el 28-ago-2026 (ADR-003). Es posible que el código
heredado del usuario ya no funcione por esa razón y no por el `robots.txt`. Se verifica al
revisarlo.


---

## D-017 · Las tres respuestas del banco, y la que sigue en conflicto
**Estado:** dos cerradas, una abierta · **Fecha:** 29-ago-2026

El usuario consultó las preguntas de T-913. Tres volvieron con respuesta.

### 1. FOGAES cubre solo primera venta — CERRADA, y es la que más movió el modelo

El FOGAES tradicional **no cubre viviendas usadas**. Un usado comprado por el mercado
convencional exige 20% o 30% de pie. La única excepción es el Subsidio Tramo 4.000 (DS1),
que autoriza combinarlo sobre una usada de hasta UF 4.000 con 10% de pie — pero prohíbe
arrendar cinco años, así que es incompatible con esta tesis (ya establecido en D-015).

**Consecuencia, implementada:** el stock usado no solo pierde 99 pb de tasa. Pierde el 90%
de financiamiento, y su pie mínimo pasa de 10% a **20%**. Es el doble de plata sobre la mesa,
y modelarlo con 10% habría producido oportunidades que ningún banco financiaría.

Sobre el mismo departamento de UF 3.000, manteniendo todo lo demás igual:

| | tasa | pie | capital UF | costo real de tenencia |
|---|---|---|---|---|
| nuevo | 3,30% | 10% | 340 | −1,23 UF/mes |
| usado | 4,29% | 20% | 638 | −2,28 UF/mes |

Esa tabla aísla **solo la penalización de financiamiento**, con el precio fijo. La ventaja
del usado —mayor yield por m²— es otra cosa y depende de datos que todavía no están
agregados (T-023). Lo que la tabla dice es cuánto tiene que ganar el usado por el lado del
arriendo para dar vuelta esto.

**Implementado:** `Escenario.con_fogaes` separado de `con_subsidio`, `fogaes_aplicable()` como
condición del inmueble, y el pie efectivo como `max(pie_deseado, pie_mínimo_exigido)`. El
capital invertido y el cash-on-cash van sobre el pie efectivo: con el deseado, el retorno de
un usado salía inflado al doble. Cierra **T-915**.

### 2. La tasa es plana entre tramos — CERRADA, cierra D-009

No hay tasa preferente por elegir un ticket más chico. El subsidio opera como rebaja plana,
igual para una propiedad de UF 3.000 que para una de UF 5.000. Registrado como
`tasa_uniforme_entre_tramos: true`.

Sigue siendo cierto que un ticket menor da un dividendo menor y por lo tanto más chance de
que el arriendo lo cubra — pero eso el motor ya lo calcula; no era una ventaja de tasa.

### 3. ¿Una sola unidad por persona? — SIGUE ABIERTA, y no por terquedad

La respuesta afirma un límite estricto de **una unidad**, por el requisito de "primera
vivienda", con cruce SII/CBR que bloquea si el RUT ya registra propiedades habitacionales.

**Queda en `evidence: C` (fuentes en conflicto), no en `V`, por dos razones concretas:**

1. **Llegó sin fuente primaria.** Las otras dos respuestas venían con enlaces; esta no.
2. **Contradice el texto del reglamento.** El Decreto 180 art. 3 ata el beneficio del tramo
   general a la *"primera **venta** de la vivienda"* — condición del **inmueble**. El art. 4
   reserva el tramo ≤ UF 3.000 exigiendo *primera vivienda del solicitante* — condición del
   **comprador**. Que el art. 4 lo diga explícitamente sugiere que el art. 3 no lo exige; si
   lo exigiera para todos, el art. 4 sería redundante. Esa es la disputa D-001, que sigue viva.

**Por qué no bloquea nada hoy:** el inversionista no declaró querer dos unidades
(`objetivo_unidades: null`), así que el modelo no depende de la respuesta. Si alguna vez
quiere una segunda, la forma de zanjarlo es pedir por escrito al banco o al Minvu el
fundamento normativo, no la interpretación de un ejecutivo.

**Cómo lo trata el modelo mientras tanto:** ambos escenarios ya se calculan. La segunda
unidad, si existiera, correría `sin_subsidio` — que es el supuesto conservador.

---

## D-018 · Partir la banda de m² `0-35` en `0-25` y `25-35`

- **Fecha:** 30-ago-2026
- **Estado:** aceptada por el inversionista
- **Tarea:** T-941
- **Cambia:** `config/params.yml:ingresos.rangos_m2`

### El problema

Las primeras filas del ranking real eran unidades de **18 a 23 m²**, todas emparejadas
contra la celda de arriendo `0-35 m²`. Medido sobre 1D1B en esa banda:

| tramo | n | arriendo mediano |
|---|---|---|
| 17–21 m² | 11 | $320.000 |
| 22–26 m² | 37 | **$300.000** |
| 27–30 m² | 145 | $334.800 |
| 31–35 m² | 289 | $370.000 |
| **la banda entera** | **482** | **$350.000** |

El **60% de los comparables mide 31–35 m²**, así que la mediana de la banda describe a un
departamento grande. Acreditársela a uno de 22–26 le regalaba **+17% de arriendo**.

Y el arriendo es el **numerador del yield**: ese +17% se trasladaba entero al yield y
empujaba a la unidad hacia arriba en el ranking. El sesgo **no se promedia**, porque va
siempre en la misma dirección —infla lo chico— y lo chico es justo lo que quedaba arriba.

Sobre la corrida real, **9 de las 20 primeras** estaban más chicas que el depto típico de su
celda, con desvíos de −15% a −44%. La #1 estaba −26%; la #3, −32%.

### La decisión

Se agrega el corte en 25 m². La banda más heterogénea pasa de mezclar **2,1x de superficie a
1,5x**.

### El costo, medido antes de decidir

| | |
|---|---|
| celdas que pueden rankear | 138 → 135 (−3) |
| **unidades que dejan de rankear** | **34** (de 1.045 ≈ 3%) |
| unidades que empiezan a rankear | 0 |

Las 34 se recuperan recolectando: `recolectar-portal --dirigida`.

**El umbral de 8 comparables del §7.3 NO se bajó para compensar.** Partir la muestra deja
algunas celdas bajo el mínimo, y la respuesta correcta es conseguir comparables, no dejar de
exigirlos: una mediana de tres avisos es ruido con cara de dato.

### Lo que esto NO arregla

`0-25` sigue mezclando 17 con 25 m². **El sesgo baja a la mitad, no desaparece.** La solución
de fondo son comparables con superficie exacta por unidad, no medianas de banda — que es lo
que Assetplan podría dar si su página renderizada trae unidades (ADR 008 §4).

Tampoco se corrige el arriendo de ninguna unidad: inventar un ajuste por m² sería imputar, y
el §3.2 lo prohíbe. Lo que se hizo fue cambiar cómo se agrupa, no cómo se calcula.

### Por qué se decidió con el humano y no solo

El §8.4 manda detenerse cuando un supuesto mueve el ranking en más de un 10% de posiciones.
Este lo mueve. Se midió el costo con `cli bandas`, se presentó el canje, y el inversionista
aprobó el 30-ago-2026.

### Cómo se revierte

Cambiando una línea en `params.yml`. Ningún dato se pierde: la agregación es un derivado que
se recalcula con `agregar-arriendo`.
