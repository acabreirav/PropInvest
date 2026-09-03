# 00 · Hallazgos de investigación de mercado
**Corte: 28-ago-2026.** Marcas: `[V]` verificado con fuente · `[D]` derivado por cálculo sobre `[V]` ·
`[E]` estimado · `[C]` fuentes en conflicto · `[ND]` no disponible.

> Este archivo es el **ancla externa** contra la que el gate de calidad (`quality/checks.py`)
> compara los datos que recolecta el pipeline. Si el UF/m² mediano que calculamos para una comuna
> se desvía >20% de estas tablas, el gate falla y hay que investigar antes de publicar el ranking.

---

## 1. Marco financiero vigente

| Variable | Valor | Marca |
|---|---|---|
| Valor UF (28-ago-2026) | $40.804 – $40.870 | `[V]` (dos fuentes, misma fecha) |
| Tasa promedio colocaciones vivienda UF (serie BCCh `F022.VIV.TIP.MA03.UF.Z.M`) | **3,97%** anual, jul-2026 | `[V]` |
| Rango de tasa con subsidio (MINVU, 9 bancos participantes) | **3,28% – 4,31%** | `[V]` |
| Rebaja atribuible al subsidio + FOGAES | 0,61% – 1,16% | `[V]` |
| Subsidio puro (Decreto 180 exento, arts. 1 y 13) | **60 puntos base** | `[V]` |
| TPM | 4,50% | `[V]` |
| Precio promedio depto nuevo RM (Colliers 1T-2026) | **79,4 UF/m²** | `[V]` |
| Stock deptos en venta Gran Santiago (1T-2026) | **34.307 unidades** | `[V]` |
| Meses para agotar stock RM | 14,3 (mercado); 20–40 por submercado | `[V]` |

### Tasas por banco (agosto 2026)

| Banco | Sin subsidio | Con subsidio/FOGAES | Marca |
|---|---|---|---|
| Itaú | **3,39%** fija (la más baja del mercado) | ND | `[V]` |
| Santander | <3,60% | **<3,30%** | `[V]` |
| Banco de Chile | ND | **<3,30%** | `[V]` |
| Falabella | 3,70% (UF+2,75%) | ND | `[V]` |
| BancoEstado | 4,19% (EcoVivienda) | ND | `[V]` |
| Coopeuch | 4,50% | ND | `[V]` |
| Scotiabank | 4,84%–5,07% (feb-2026) | ND | `[V]` dato antiguo |
| BCI, BICE, Consorcio, Security | ND | participan en FOGAES | `[C]` |

**Advertencia:** Chile no publica tarifarios hipotecarios homogéneos; los bancos cotizan por perfil.
**Compara siempre por CAE, no por tasa nominal** — el CAE incorpora seguros y comisiones.
Adjudicados FOGAES (jun-2025): BancoEstado, Santander, Banco de Chile, Internacional, Scotiabank,
Bci, Itaú, BICE, Falabella, Consorcio, Coopeuch y Mutuo Hipotecario Renta Nacional. `[V]`

### Subsidio: estado de consumo de cupos

| | |
|---|---|
| Cupos ampliados | **80.000** (desde 50.000) `[V]` |
| Solicitudes ingresadas al 21-ago-2026 | **43.278** `[V]` |
| Créditos formalizados al 21-ago-2026 | **34.917** `[V]` |
| Cupos restantes estimados | ~45.000 `[D]` |
| Ritmo de consumo | ~35.000 en 14 meses ⇒ **agotamiento hacia fines de 2027** `[D]` |
| Plazo legal | 31-may-2028 (+3 meses para escriturar) `[V]` |

Primera licitación FOGAES (18-jun-2025): 10 millones UF ofertados contra demanda >30 millones UF
(**3× sobresuscrito**). Resultado documentado: vivienda de UF 4.000 al 90% a 30 años → **tasa 3,40%**. `[V]`

---

## 2. Arriendo por comuna — UF/m²/mes

Fuente: Colliers y Assetplan, publicado por Emol el 2-abr-2026. La columna **"retail / particular"**
es la relevante para nuestro inversionista (arrendador individual, no multifamily institucional).

| Comuna | Multifamily | Retail / particular |
|---|---|---|
| Las Condes | 0,44 | 0,35 |
| Providencia | 0,43 | 0,31 |
| Ñuñoa | 0,29 | 0,30 |
| La Florida | 0,26 | 0,25 |
| Santiago | 0,26 | 0,24 |
| San Miguel | 0,24 | 0,24 |
| La Cisterna | 0,22 | 0,22 |
| Estación Central | 0,21 | 0,20 |

**Fase 3 — benchmarks derivados `[D]` (03-sep-2026).** Emol/Colliers no cubre las ciudades
de fase 3; se derivan de la tabla AP Capital/Assetplan del §5 `[V]` con el método que este
documento ya estableció: `cap bruto = cap neto ÷ 0,865` (§4) y `1D1B ≈ 35 m²` (§4, tarifa BDO).
Fórmula: `UF/m² = precio_UF × cap_bruto ÷ 12 ÷ 35`. Son cifras de 1D1B, no promedio comunal
(sesgo alcista conocido: el 1D1B rinde más por m²; el ±25% del gate lo absorbe — verificación
cruzada: el 2D2B de Concepción por la misma vía da 0,28).

| Ciudad | UF/m² `[D]` | Aritmética |
|---|---|---|
| Concepción | 0,30 | 2.761 × (0,040/0,865) ÷ 12 = 10,64 UF/mes ÷ 35 |
| La Serena | 0,31 | 2.648 × (0,042/0,865) ÷ 12 = 10,71 UF/mes ÷ 35 |
| Antofagasta | 0,39 | 3.128 × (0,045/0,865) ÷ 12 = 13,56 UF/mes ÷ 35 |

Sin benchmark aún (sin cifra publicada conocida, se dice y no se inventa): las comunas
satélite del Gran Concepción (Chiguayante, Hualpén, San Pedro de la Paz, Talcahuano —
la cifra AP Capital es de Concepción ciudad), Coquimbo comuna, y en la RM Recoleta,
Independencia, Macul y Cerrillos.

## 3. Venta de departamento nuevo — UF/m²

| Comuna | UF/m² | Fuente / periodo |
|---|---|---|
| Vitacura | 133 | Colliers 4T-2025 `[V]` |
| Las Condes | 110,7 | Colliers 4T-2025 `[V]` |
| Ñuñoa | 88,4 | Colliers 3T-2025 `[V]` |
| Santiago Centro | 80,9 | Colliers 3T-2025 `[V]` |
| La Florida | 73,9 → 75,0 | Colliers 3T/4T-2025 `[V]` |
| Macul | 72,9 | Portal PM jun-2026 `[V]` portal |
| Recoleta | 71,0 (+9,6% a/a, mayor alza RM) | Colliers nov-2024 `[V]` |
| San Miguel | 71 | BDO/Transsa 2025 `[V]` |
| Estación Central | 67,1 (ticket mínimo UF 2.112) | DeptoScore ago-2026 `[V]` |
| La Cisterna | 66,1 | Colliers 3T-2025 `[V]` |
| Independencia | 65–70 | Colliers Tasaciones ene-2026 `[V]` rango |
| Cerrillos | 64,3 | Colliers 3T-2025 `[V]` |
| Maipú | 58–65 | Colliers Tasaciones ene-2026 `[V]` |

## 4. Yield bruto derivado — y por qué NO se copia el publicado

`yield = (arriendo UF/m² × 12) ÷ venta UF/m²`, usando la columna "retail".

| Comuna | Yield bruto `[D]` | Cap rate **neto** AP Capital 1D1B `[V]` |
|---|---|---|
| Ñuñoa | **4,07%** | 2,9% |
| La Florida | **4,06%** | 2,9% |
| San Miguel | **4,06%** | ND |
| La Cisterna | **3,99%** | ND |
| Las Condes | 3,79% | ND |
| Estación Central | 3,58% | 3,4%–4,4% (DeptoScore) |
| Santiago Centro | 3,56% | **2,8%** |
| Providencia | 3,54% | 3,0% |

**Tres verdades en circulación, y solo una resiste la aritmética:**
- Colliers Tasaciones publica "rentabilidad anual" de **5,5%–6,5%** `[V]`.
- Dividiendo precios y arriendos **de los propios reportes de Colliers**: **3,5%–4,2%** `[D]`.
- AP Capital / Assetplan, con muestra de **2.628 arriendos reales** (may-2026): cap rates
  netos **2,8%–3,0%** `[V]`.

→ **Las cifras de 5,5–6,5% son marketing.** Modela con 3,5%–4,5% bruto.

**Conversión bruto↔neto de AP Capital `[D]`:** Antofagasta 2D2B: $828.000×12 sobre UF 4.477
= 5,43% bruto, pero reportan 4,7%. Ratio **0,865** ⇒ su "cap rate" es neto de ~13–14% de
vacancia y opex. **Para llevarlo a bruto, divide por 0,87.**

**Ajuste por tipología:** el 1D1B de ~35 m² renta más UF/m² que el promedio comunal
(tarifa BDO 10,91 UF para 1D1B de ~35 m² = 0,31 UF/m² `[V]`), y es el **48% del stock
multifamily** `[V]` — el producto de mayor liquidez de arriendo. Un 1D1B nuevo bien ubicado
alcanza **4,3%–4,8% bruto** `[D/E]`: el techo realista del Gran Santiago hoy.

## 5. Cap rate neto por ciudad — AP Capital / Assetplan, may-2026 `[V]`

| Ciudad | Cap neto 1D1B | Arriendo | Precio |
|---|---|---|---|
| Antofagasta | **4,5%** | $554.000 | UF 3.128 |
| La Serena | **4,2%** | $440.000 | UF 2.648 |
| **Concepción** | **4,0%** | $430.000 | UF 2.761 |
| Providencia | 3,0% | $656.000 | UF 5.490 |
| Ñuñoa | 2,9% | $408.000 | — |
| La Florida | 2,9% | $353.000 | — |
| Santiago | **2,8%** | $337.000 | — |

2D2B: Antofagasta 4,7% ($828.000 / UF 4.477) · **Concepción 4,4%** ($620.000 / UF 3.614) ·
La Serena 3,9% · Viña del Mar 3,1%.

## 6. La aritmética del pie — el hallazgo que define el producto

```
pie_mínimo_flujo_cero = 1 − [ 0,85 × yield_bruto ÷ factor_dividendo_anual ]
```
Factor de dividendo anualizado a 30 años `[D]`: **5,798%** del crédito al 4,10% (con subsidio);
**6,332%** al 4,85% (sin subsidio). Opex del arrendador: 15% del arriendo `[E]`.

| Yield bruto | Pie mínimo @4,10% | Pie mínimo @4,85% | Dónde existe |
|---|---|---|---|
| 3,6% | **47,2%** | 51,7% | Santiago Centro, Estación Central |
| 4,0% | **41,4%** | 46,3% | Ñuñoa, La Florida, San Miguel, La Cisterna |
| 4,5% | **34,0%** | 39,6% | 1D1B compacto bien ubicado `[E]` |
| 4,6% | 32,5% | 38,3% | **Concepción 1D1B** `[D]` |
| 4,9% | 28,4% | 34,5% | La Serena 1D1B |
| 5,2% | **23,7%** | 30,1% | Antofagasta 1D1B |
| 5,5% | 19,4% ✅ | 26,2% | **No existe en producto nuevo de la RM** |

> **Veredicto: "pie 10–20%" y "flujo no negativo" son incompatibles en departamentos nuevos del
> Gran Santiago en agosto de 2026.** Salidas, en orden: (1) subir el pie a 35–40%;
> (2) aceptar déficit de 1–3 UF/mes como ahorro forzoso — es lo que hace el mercado, y Assetplan
> lo describe como normal `[V]`; (3) salir a Concepción, donde el pie de equilibrio baja a ~32%;
> (4) comprar en verde con descuento (12–18% típico, `[E]` no verificado).

## 7. Vacancia y ocupación

**TOCTOC InfoRenta, ago-2026** `[V]`: ocupación general RM **97,9%** · multifamily **94,6%**
(vacancia 5,4%) · Sector Oriente vacancia ~1% y precio +12% anual en UF · Sector Norte con precios
deteriorándose y **vacancias al alza** · Sector Sur-Oriente (lidera La Florida) **mantiene la
vacancia promedio más alta de la región**.

**Vacancia multifamily por comuna — Inciti, may-2026** `[V]`:

| Comuna | Vacancia |
|---|---|
| **San Miguel** | **3,2%** (la más baja) |
| Santiago | 4,8% |
| Independencia | 5,1% |
| Estación Central | 5,8% |
| **Ñuñoa** | **12,2%** |
| Las Condes | 19,6% (oferta nueva reciente) |
| San Joaquín | 42,1% (3 proyectos, uno en lease-up) |

⚠️ La vacancia multifamily **no** es la del arrendador particular: un edificio en lease-up
distorsiona el número. Úsala como señal de **presión competitiva futura**.

**Dinámica de oferta (HousePricing/Assetplan, 1T-2026)** `[V]`: avisos activos de arriendo en la RM
cayeron de 35.000 (2023) a **22.000 (−37%)**; Estación Central −43%. Recuperación de ocupación:
Estación Central +36%, Independencia +19%, Santiago +14%, La Florida +13%. Precio quiebra tres años
de estabilidad: 0,26 → 0,27 UF/m².

## 8. Microzonificación — la evidencia dura

**Mapa de saturación de arriendo, Tattersall abr-2026** `[V]`:

| Comuna | Microzona **saturada** | Microzona **en equilibrio** |
|---|---|---|
| Estación Central | **Santa Isabel** | **Av. 5 de Abril** |
| Santiago Centro | **Teatinos, Parque Almagro** | **Morandé, Plaza de Armas** |
| La Florida | **Vicuña Mackenna × Américo Vespucio** | resto |
| Ñuñoa | **entorno Estadio Nacional** (emergente) | resto |
| Macul | **Quilín × Av. Macul** (emergente) | resto |
| La Cisterna | **JM Carrera × Briones Luco** (emergente) | resto |
| San Miguel / Providencia / Lo Barnechea | — sin saturación (normativa restrictiva) | toda la comuna |

**Magnitud:** mismo producto, **~$300.000 en Santa Isabel vs ~$350.000 fuera de la zona saturada
= 17% dentro de la misma comuna** `[V]`. Sobre un yield de 4%, eso son ~70 pb: **más que toda la
diferencia entre comunas.**

En Viña del Mar, el rango intercuartil de UF/m² va de **45,0 a 82,5** sobre mediana 66,1, con
1.671 transacciones reales del CBR: **el p75 vale 83% más que el p25 dentro de la misma comuna** `[V]`.

Plataformas que ya exponen esta granularidad: Portal Inmobiliario
(`/arriendo/departamento/rm-metropolitana/nunoa/plaza-egana/`) `[V]` · HousePricing (16 barrios
solo en Ñuñoa) `[V]` · TOCTOC "Comparador de barrios" e InfoInmobiliario con polígonos propios `[V]` ·
UFHouse (24 comunas, +80 barrios) `[V]` · DeptoScore (cap rate contra mediana del barrio) `[V]`.

## 9. Catalizadores de infraestructura — Metro `[V]`

| Proyecto | Comunas | Estado 2026 | Apertura |
|---|---|---|---|
| **Extensión L6 poniente** (Lo Errázuriz) | **Cerrillos** | **46% avance físico** | **2027** ← único catalizador cercano |
| **Línea 7** (26 km, 19 est.) | Renca, Cerro Navia, Quinta Normal, Santiago, **Recoleta**, Providencia, Las Condes, Vitacura | 42% avance, 68% túneles | **fines de 2028** |
| Línea 9 (eje Santa Rosa) | Recoleta, Santiago, **San Miguel**, San Joaquín, La Granja, La Pintana, Puente Alto | 3,7% avance | 2030 / 2032 / 2033 |
| Línea 8 | Providencia, **Ñuñoa**, **Macul**, **La Florida**, Peñalolén, Puente Alto | Ingeniería | 2032–2033 |

Cercanía a Metro suma **15%–30% al valor**; el anuncio de una nueva línea genera alzas
anticipatorias de **10%–20%** `[V]`. Pero la captura depende de la **distancia a la estación**,
no de estar "en la comuna" `[V]`.
→ **Para un horizonte de 3–5 años, solo Cerrillos (2027) y el eje L7 (2028) tienen fecha creíble.
No pagues prima hoy por L8 ni L9.**

## 10. Riesgos por comuna

| Comuna | Sobreoferta | Otros riesgos | Veredicto |
|---|---|---|---|
| **San Miguel** | **Baja** — normativa restrictiva limita explosiones de oferta; vacancia MF 3,2% | Baja | **Mejor perfil de riesgo** |
| **Cerrillos** | Baja-media — 2.017 u.; no aparece en el mapa de saturación | Baja | **Buen perfil** |
| **La Florida** | **Muy alta** — 19 proyectos MF = 4.810 unidades entrando; stock 4.864 u. | Sur-Oriente con la vacancia promedio más alta de la RM | Buen yield, exige microzona |
| **Ñuñoa** | Media-alta — vacancia MF 12,2%; stock 3.946 u. | Ticket alto: casi no cabe bajo UF 6.000 | Microzona crítica |
| **Santiago Centro** | **Alta latente** — 10.900 unidades con permiso **sin iniciar obras**; 28 proyectos MF / 7.758 u. | Capital de altos patrimonios "en pausa" por seguridad (DF) | Solo microzonas selectas |
| **Estación Central** | **Alta** — 3.647 unidades MF adicionales; vacancia 5,8% | Idem seguridad. Santa Isabel saturada | Solo eje 5 de Abril |
| **Independencia** | Media — stock bajo (934 u.), vacancia 5,1% | Idem seguridad; sector Norte deteriorándose | Riesgo alto |
| **Recoleta** | Baja — stock bajo | Sector Norte con vacancias al alza | Microzonificación estricta |
| San Joaquín | **Muy alta** — vacancia MF 42,1% | — | Esperar |
| Viña del Mar | **Alta** — absorción **24,6 meses**, la peor del Gran Valparaíso; ventas −6,4% s/s | Mercado estacional, no de flujo | No priorizar |

**Contraintuición útil en Estación Central:** el nuevo Plan Regulador fija **altura máxima de
12 pisos** (4–9 en ciertos sectores), validado por la Corte de Apelaciones tras congelamientos
sucesivos de permisos `[V]`. Eso **corta la oferta futura de raíz** y protege al stock existente.
Es una apuesta de microzona, no de comuna.

## 11. Stock por comuna — Colliers `[V]`

| Comuna | Stock 4T-2025 | Ventas 1T-2026 | UF/m² |
|---|---|---|---|
| Santiago | 6.958 | **914** | 80,9 |
| La Florida | 4.864 | **835** | 73,9–75,0 |
| Ñuñoa | 3.946 | **659** | 88,4 |
| Macul | 2.128 | — | 72,9 |
| Cerrillos | 2.017 | 248 (3T-25) | 64,3 |
| La Cisterna | 1.430 | 347 (3T-25) | 66,1 |
| Las Condes | 1.289 | — | 110,7 |
| San Joaquín | 1.177 | — | — |
| Independencia | 934 | — | 65–70 |
| **Gran Santiago** | **34.141 → 34.307** | **5.114** | **79,4** |

Santiago + La Florida + Ñuñoa = **48% del stock de la RM** `[V]`.

**Proporción bajo UF 6.000:** no existe publicado ese corte por comuna `[ND]`. Lo verificado:
70–80% del mercado RM está bajo **UF 4.000** `[V]` ⇒ **>90% del stock RM está bajo UF 6.000** `[D]`.
**El techo de UF 6.000 no es una restricción binding en la RM** salvo en Vitacura, Las Condes,
Lo Barnechea y Providencia. En el resto, el problema no es el techo: es el yield.

## 12. Gastos comunes — el costo que destruye competitividad

Dispersión brutal entre comunas: **Santiago Centro $72.000 vs Las Condes $236.000** para un 1D1B —
hasta **$164.000 mensuales de diferencia** (Assetplan, 82 edificios en 11 comunas) `[V]`.
Los paga el **arrendatario**, pero un gasto común alto **reduce el arriendo que el mercado tolera**.
El modelo debe restarlo del presupuesto del arrendatario, no del flujo del propietario.

## 13. Vacíos de datos declarados `[ND]`

1. Velocidad de arriendo (días en mercado) por comuna — el blog de TOCTOC devuelve 403. Solo hay Providencia: 29 días.
2. Arriendo en UF/m² para Cerrillos, Recoleta, Independencia, Macul, Quinta Normal, San Joaquín — Colliers solo publicó 8 comunas. **Sin esto no se cierra el yield de 4 de las 11 comunas recomendadas. Prioridad #1 del pipeline.**
3. Proporción exacta del stock bajo UF 6.000 por comuna.
4. Serie de morosidad/impago de arriendo por comuna.
5. Estado y zonas del Subsidio de Renovación Urbana 2026.
6. Series de precio por barrio dentro de Ñuñoa (Irarrázaval, Chile-España, Villa Frei) — recolectable por scraping propio.
7. Descuento típico de compra en verde vs entrega inmediata.
8. **Si el subsidio admite compradores con propiedad previa. Prioridad legal #1.**

---

## Fuentes

**Legal y financiamiento**
[BCN Ley Fácil — Subsidio a la tasa](https://www.bcn.cl/portal/leyfacil/recurso/subsidio-a-la-tasa-de-interes-hipotecaria-para-la-adquisicion-de-viviendas-nuevas) ·
[Ley 21.748 en LeyChile](https://www.bcn.cl/leychile/navegar?idNorma=1213759) ·
[Decreto 180 exento de 2025 (PDF, FOGAES)](https://fogaes.cl/wp-content/uploads/2026/05/Decreto-180-exento-de-2025.-Reglas-generales-de-funcionamiento-del-Subsidio-a-la-Tasa-de-Interes-de-Creditos-Hipotecarios-de-Viviendas-Nuevas.pdf) ·
[Decreto 181 exento (FOGAES)](https://www.bcn.cl/leychile/navegar?idNorma=1214070) ·
[JDF — Análisis Ley 21.748](https://www.jdf.cl/en/2457-2/) ·
[DF — Senado despacha extensión hasta 2028](https://www.df.cl/economia-y-politica/congreso/senado-aprueba-y-despacha-a-ley-proyecto-que-extiende-el-subsidio-a-la-tasa) ·
[Promulgación FOGAES ampliado, 26-ago-2026](https://g5noticias.cl/2026/08/26/presidente-jose-antonio-kast-encabeza-promulgacion-del-fogaes-ampliado-y-nuevo-subsidio-para-adquirir-viviendas-de-hasta-6-mil-uf/) ·
[MINVU — Subsidio al Crédito Hipotecario](https://www.minvu.gob.cl/nuevo-subsidio-al-credito-hipotecario/) ·
[FOGAES — requisitos](https://fogaes.cl/sitio/requisitos/) ·
[SII — valor UF 2026](https://www.sii.cl/valores_y_fechas/uf/uf2026.htm)

**Mercado, stock y precios**
[Colliers — Reporte residencial 1T-2026](https://www.colliers.com/es-cl/investigacion/reporte-residencial-1t-2026) ·
[Santiago, La Florida y Ñuñoa = 48% del stock RM](https://eldiarioinmobiliario.cl/destacadas/santiago-la-florida-nunoa-stock-departamentos-region-metropolitana-2026/) ·
[34 mil deptos en venta en la RM](https://www.expovivienda.cl/region-metropolitana-tiene-34-mil-departamentos-en-venta-estas-son-las-comunas-con-mas-oferta/) ·
[Santiago Centro acelera su recuperación (CChC/Toctoc)](https://mercadosinmobiliarios.cl/articulo/santiago-centro-acelera-su-recuperacion-inmobiliaria-ventas-impulsan-la-absorcion-de-stock-y-abren-espacio-para-una-nueva-etapa-de-desarrollo) ·
[Tinsa — stock de viviendas 2026](https://www.tinsa.cl/stock-de-viviendas-en-chile/) ·
[Colliers Tasaciones — mejores comunas bajo UF 4.000](https://tasaciones.colliers.cl/2026/01/22/mejores-comunas-para-invertir-en-santiago/) *(rentabilidades no reconciliables; usar con reserva)*

**Arriendo, vacancia y rentabilidad**
[TOCTOC InfoRenta ago-2026](https://www.mediabanco.com/sector-oriente-lidera-alzas-mientras-el-resto-de-la-capital-se-mantiene-estable/) ·
[Inciti — vacancia multifamily may-2026](https://eldiarioinmobiliario.cl/destacadas/multifamily-reduce-vacancia-bajo-el-5-en-santiago-y-san-miguel-mientras-demanda-se-concentra-en-arriendos-de-hasta-10-uf/) ·
[Emol — ¿qué alcanza con $500 mil? (Colliers/Assetplan)](https://www.emol.com/noticias/Economia/2026/04/02/1196074/arriendos-en-la-rm.html) ·
[CNN — oferta de arriendos cae 37%](https://www.cnnchile.com/pais/oferta-de-arriendos-en-santiago-se-desploma-un-37-y-los-precios-quiebran-tres-anos-de-estabilidad-a-la-baja/) ·
[La Tercera — ciudades que superan a Santiago en rentabilidad (AP Capital)](https://www.latercera.com/pulso/noticia/ciudades-y-comunas-donde-es-mas-rentable-comprar-un-departamento-para-arrendarlo/) ·
[BDO — qué departamentos más se arriendan](https://www.24horas.cl/actualidad/economia/estudio-revela-cuales-son-los-departamentos-que-mas-se-arriendan) ·
[CNN — gastos comunes, hasta 200% de diferencia](https://www.cnnchile.com/pais/gastos-comunes-en-santiago-la-diferencia-entre-comunas-puede-llegar-al-200-y-sumar-hasta-164-000-mensuales_20260421/) ·
[Assetplan — guía de inversión 2026](https://blog.assetplan.cl/inversiones/guia-de-inversion-inmobiliaria-en-chile-2026)

**Riesgo, sobreoferta y microzonificación**
[DF — sobreoferta de arriendo por zonas (Tattersall)](https://www.df.cl/empresas/industria/sobreoferta-de-departamentos-en-arriendo-se-concentra-en-zonas-de-santiago) ·
[DF — altos patrimonios pausan multifamily por seguridad](https://www.df.cl/mercados/bolsa-monedas/altos-patrimonios-ponen-en-pausa-inversiones-multifamily-en-estacion) ·
[La Tercera — 100 permisos en Santiago Centro, más de la mitad sin iniciar](https://www.latercera.com/pulso/noticia/hay-casi-100-permisos-de-edificacion-de-viviendas-aprobados-en-santiago-centro-pero-mas-de-la-mitad-no-ha-iniciado-obras/) ·
[The Clinic — PRC de Estación Central, máx. 12 pisos](https://www.theclinic.cl/2025/07/14/el-fin-de-los-guetos-verticales-en-estacion-central-alcalde-munoz-confirma-nuevo-plan-regulador-que-fija-altura-maxima-de-construccion-en-12-pisos/) ·
[CEDEUS — ranking de arriendo de 20 barrios de Santiago](https://www.cedeus.cl/blog/2022/09/28/ranking-de-precios-de-arriendo-de-20-barrios-de-la-comuna-de-santiago/)

**Infraestructura**
[Metro — Línea 7 al 42%](https://www.metro.cl/noticias/linea-7-de-metro-alcanza-42-de-avance-con-177-kilometros-excavados) ·
[Red completa con L7, L8 y L9](https://www.infraestructurapublica.cl/asi-sera-la-red-completa-del-metro-con-las-futuras-lineas-7-8-y-9-por-donde-pasaran-y-cuando-inician-sus-operaciones/) ·
[Valuaciones — plusvalía y nuevas líneas](https://valuaciones.cl/plusvalia-santiago-nuevas-lineas-metro/)

**Regiones**
[Tinsa Incoin — Gran Valparaíso feb-2026](https://www.df.cl/regiones/valparaiso/mercados/mercado-inmobiliario-del-gran-valparaiso-vina-del-mar-lidera-venta-de) ·
[Diario Concepción — mapa inmobiliario del Gran Concepción](https://www.diarioconcepcion.cl/economia/2026/04/13/alta-demanda-baja-oferta-y-precios-al-alza-el-complejo-mapa-inmobiliario-del-gran-concepcion.html) ·
[Urbani — valor de departamentos en Concepción](https://urbani.cl/precio-y-valor-departamentos-en-concepcion/)
