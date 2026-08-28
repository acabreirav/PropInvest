# 02 · Modelo financiero
Todas las fórmulas que implementa `src/flujocero/finance/`. Este documento y el código deben
coincidir; si divergen, el documento manda y el código es el bug.

## 1. Convención central: todo en UF, términos reales

El crédito está en UF, las contribuciones se reajustan por IPC, los gastos comunes suben con
inflación y el arriendo se reajusta anualmente por IPC.
**Modela todo en UF y descuenta con una tasa real. Nunca mezcles flujos nominales en pesos con
un crédito en UF.**

### 1.1 La erosión intra-anual que casi todos omiten

El arriendo se pacta en pesos y se reajusta **una vez al año**; la UF sube **todos los días**.
Dentro de cada año, el arriendo medido en UF decae mes a mes y se recompone en el aniversario.

```
arriendo_uf(mes m del año) = arriendo_uf_inicial / (1 + π)^(m/12)
arriendo_uf_promedio_anual ≈ arriendo_uf_inicial / (1 + π/2)
```

Con π = 3% ⇒ factor **0,985**: se pierde **~1,5% de renta real todos los años, permanentemente**.
Si tu modelo asume arriendo constante en UF, sobreestima el flujo en esa magnitud.

### 1.2 La consecuencia estructural
Con un crédito en UF, **el dividendo es real constante**: la inflación **no licúa la deuda**.
El flujo no mejora con el tiempo salvo que el arriendo real crezca por encima de la inflación.
Es la diferencia estructural con mercados de crédito nominal, y la falacia más repetida del rubro.

## 2. Fórmulas

**Ingreso bruto potencial**
```
PGI = arriendo_mensual_uf × 12
```

**Ingreso bruto efectivo**
```
EGI = PGI × (1 − vacancia) × (1 − incobrabilidad) / (1 + π/2)
```

**NOI** — en Chile el NOI **excluye** el servicio de la deuda:
```
NOI = EGI
    − contribuciones
    − gastos comunes en periodos de vacancia
    − seguro de incendio/sismo
    − administración (% × EGI)
    − corretaje amortizado (0,595 meses ÷ años de permanencia del arrendatario)
    − mantención y reparaciones (% del PGI)
    − impuesto a la renta si NO es DFL2
```

**Rentabilidad bruta / cap rate / GRM**
```
rentabilidad_bruta = PGI / precio_compra
cap_rate           = NOI / (precio_compra + gastos_de_cierre)     ← declara el denominador
GRM                = precio_compra / PGI                          ← = 1 / rentabilidad_bruta
```
Benchmark neto de mercado: 3,5–4,5% aceptable · 4,5–6% bueno · >6% excelente.

**Dividendo (sistema francés, en UF)**
```
i = tasa_anual / 12                 (o (1+tasa)^(1/12) − 1 si el banco capitaliza anual)
n = plazo_años × 12
dividendo_uf = credito_uf × [ i(1+i)^n ] / [ (1+i)^n − 1 ]
dividendo_total = dividendo_uf + desgravamen + incendio/sismo
```

**Flujos**
```
BTCF_mensual = NOI/12 − dividendo_total_mensual
ATCF         = BTCF − impuesto_renta
  impuesto_renta = 0                                          si DFL2 y ≤2 viviendas
  impuesto_renta = tasa_marginal_IGC × (renta − contribuciones) en otro caso
```
⚠️ En Chile la amortización de capital **no es deducible**, y los intereses hipotecarios solo lo son
bajo el art. 55 bis con topes y límite de renta. No importes la lógica tributaria estadounidense.

**Cobertura y equilibrio**
```
DSCR = NOI_anual / servicio_deuda_anual
arriendo_min_uf = (dividendo_total_anual + opex_anual) / [ 12 × (1−vacancia) / (1+π/2) ]
BEO             = (opex_anual + servicio_deuda_anual) / PGI
```
Con 90% LTV y cap rates de 4–5%, el **DSCR típico de un departamento nuevo chileno está entre
0,55 y 0,80**: el inversionista aporta flujo todos los meses. Es lo normal, y el retorno viene de
la amortización y la plusvalía, no del carry.

**Pie mínimo para flujo cero — la métrica insignia del producto**
```
pie_minimo = 1 − [ (1 − opex_pct) × yield_bruto / factor_dividendo_anual ]

factor_dividendo_anual = 12 × [ i(1+i)^n ] / [ (1+i)^n − 1 ]
```
Anclas para el gate de tests: 5,798% anual a 30 años al 4,10%; 6,332% al 4,85%.

**Cash-on-cash**
```
capital_invertido = pie + gastos_de_cierre + habilitación
CoC = BTCF_anual / capital_invertido
```

**TIR real apalancada y VAN**
```
t=0    : −(pie + gastos_de_cierre)
t=1..N : +ATCF_anual                                   (en UF)
t=N    : +valor_venta_uf × (1 − 0,03×1,19)             (comisión de venta)
         −saldo_insoluto_uf(N)
         −impuesto_ganancia_capital
valor_venta_uf = precio_compra_uf × (1 + g_real)^N
```
Como los flujos están en UF, **la TIR resultante es REAL**. Para compararla con un depósito a plazo
nominal, súmale la inflación esperada. Este es el error de comparación más común del rubro.

## 3. Impuestos que sí importan

**DFL2** — vivienda ≤140 m² útiles, **máx. 2 por persona natural** (Ley 20.455, desde 01-nov-2010),
**la persona jurídica no accede**:
- arriendo = **ingreso no renta** (exento de IGC y Adicional)
- **50% de rebaja de contribuciones** por 20 años si ≤70 m², 15 si 70–100 m², 10 si 100–140 m²
- arriendo sin muebles exento de IVA (**amoblado paga 19% — evita amoblar**)
- exento de impuesto de herencias

> En valor presente, este paquete **supera al subsidio a la tasa**. El límite de 2 por persona natural
> es la restricción real de escalamiento: la tercera propiedad tiene una economía estructuralmente peor.
> Estructurar a nombre de dos personas naturales antes que constituir una sociedad.

**Ganancia de capital en la venta (persona natural):** exención acumulativa **de por vida de
UF 8.000**; sobre el exceso, tasa única de 10% o IGC a elección. Requiere adquisición posterior al
01-ene-2004 y contraparte no relacionada.

**Impuesto de timbres:** 0,8% sobre el monto del crédito. Para DFL2 las fuentes divergen
(0,2% / 0,5% / exento) — `[C]`, el modelo usa 0,8% por conservador y lo marca como sensible.

## 4. Escenarios que el motor calcula siempre

```
{con_subsidio, sin_subsidio}
  × {pie 10%, 15%, 20%, pie_equilibrio}
  × {DFL2 sí, DFL2 no}
  × {vacancia gestión individual 8%, gestión profesional 4,5%}
```
El escenario `sin_subsidio` **no es opcional**: hasta que se publique el reglamento del tramo
UF 4.000–6.000, no sabemos si el inversionista con propiedad previa califica.

## 5. Más allá del flujo — lo que un corredor experto pondera

1. **Apalancamiento 10:1 a tasa real ~3,3% a 30 años** contra un activo que aprecia 2–4% real y
   renta 4–5% bruto. Es, matemáticamente, el mejor apalancamiento disponible a una persona natural
   en Chile. **El retorno no está en el flujo: está en la amortización que paga el arrendatario.**
2. **Compra en verde con precio congelado y pie en 12–36 cuotas** durante la construcción.
   Captura la apreciación del período de obra sin costo financiero. Compatible con el subsidio:
   promesa posterior al 31-dic-2024 y escritura dentro de la vigencia.
3. **Ventana regulatoria irrepetible**: subsidio ampliado a UF 6.000 + FOGAES al 90% +
   exención transitoria de IVA + tasas en mínimos desde dic-2021. Todos transitorios y con cupo.
4. **Cercanía a Metro**: +15–30% de valor; +10–20% anticipatorio ante el anuncio de una línea.
   Es la variable de localización con mejor evidencia cuantitativa.
5. **Gestión profesional / multifamily**: baja la vacancia de 8–10% (individual) a 3–5%.
   El costo de administración se paga solo si reduce la vacancia en más de ~4 puntos.
6. **DS52 (subsidio de arriendo)**: aporte total 170 UF en hasta 8 años, hasta 4,9 UF/mes en la RM.
   No es un instrumento de yield: es un **estabilizador de flujo** en el segmento de 8–10 UF, que es
   justamente donde se concentra la demanda. Requiere recepción municipal final y prohíbe parentesco
   entre propietario y arrendatario.
7. **Escasez de oferta de arriendo**: los avisos activos en la RM cayeron 37% en tres años y los
   precios quebraron tres años de estabilidad a la baja.

## 6. Checklist antes de comprometer capital

1. ¿El tramo UF 4.000–6.000 exige no ser propietario? *(decreto reglamentario pendiente)*
2. ¿Se publicó la exención de IVA y con qué tope? Vale ~800 UF en un depto de UF 5.000.
3. ¿Cuál es el número de la ley de ampliación? La prensa recicla mal "21.748".
4. ¿La escritura dice **DFL2** y la superficie útil es ≤140 m²?
5. ¿Cuántas viviendas DFL2 tiene ya el comprador? La 3ª pierde todos los beneficios.
6. ¿La promesa es posterior al 31-dic-2024?
7. **Compara CAE, no tasa nominal.** Los seguros son el ítem estimado, no verificado.
8. ¿Cuántos cupos FOGAES quedan? ~45.000 de 80.000, agotándose antes de may-2028.
9. ¿Cuál es el avalúo fiscal real de la unidad? El ratio 0,55 sobre mercado es un estimado.
10. ¿Cuál es la vacancia de la **microzona** específica? Las Condes 19,6% vs San Miguel 3,2%.
