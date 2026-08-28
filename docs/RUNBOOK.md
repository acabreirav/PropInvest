# Runbook — de cero a la primera decisión de compra
Perfil: persona natural, **0 propiedades**, objetivo **2 unidades DFL2**, pie 10–20%.
Calibrado al 28-ago-2026. Valor UF usado: $40.804.

---

# Primero: cómo funciona esto

Hay **cuatro lugares distintos** donde vas a hacer cosas. Confundirlos es lo que hace que un
instructivo se vuelva ilegible, así que cada paso de abajo dice explícitamente en cuál estás:

| Símbolo | Dónde | Qué es |
|---|---|---|
| 🖥️ **Terminal** | La consola de tu computador | Comandos del sistema: instalar, descomprimir, git |
| 🤖 **Claude Code** | El chat que se abre al escribir `claude` en la terminal | Donde escribes `/harness` y conversas con los agentes |
| 📝 **Editor** | VS Code, o pídeselo a Claude Code | Editar archivos de configuración |
| 🌐 **Navegador** | Chrome | Crear dos cuentas gratuitas de API |

**La idea central, que es lo que probablemente no quedó claro:** el repositorio *es* la
configuración de Claude Code. Cuando escribes `claude` estando dentro de la carpeta `flujo-cero`,
Claude Code lee automáticamente:

- `CLAUDE.md` → sus instrucciones permanentes para este proyecto
- `.claude/agents/` → los 10 subagentes especializados quedan disponibles
- `.claude/commands/` → de ahí salen `/harness`, `/validar`, `/informe`, `/ola`, `/nueva-fuente`

Por eso `/harness` no es un comando que tengas que instalar: existe porque el repo lo trae.
Si abres Claude Code desde otra carpeta, no aparece.

Y sí: **todo esto es exactamente tu flujo habitual** de Claude Code + consola + GitHub. No hay
nada nuevo que aprender más allá de dos instalaciones.

---

# PASO 1 · Bajar el repo y abrirlo 🖥️

`flujo-cero.tar.gz` es el archivo que te llegó en el chat. Descárgalo, y en la terminal:

```bash
cd ~/Documents                 # o donde guardes tus proyectos
tar xzf ~/Downloads/flujo-cero.tar.gz
cd flujo-cero
ls
```

Deberías ver `CLAUDE.md`, `config/`, `docs/`, `src/`, `state/`, `Makefile`.
**Desde ahora, todos los comandos se corren parado en esta carpeta.**

Súbelo a GitHub como repositorio **privado** (trae supuestos de tu situación financiera):

```bash
git init && git add -A && git commit -m "T-000: scaffold inicial"
gh repo create flujo-cero --private --source=. --push
```

> **`config/inversionista.yml` está adentro de esa carpeta.** No existe en ninguna otra parte:
> lo creé dentro del repo. Después de descomprimir lo tienes en `flujo-cero/config/inversionista.yml`.

---

# PASO 2 · Instalar dos cosas 🖥️

**Claude Code** — si ya lo usas, sáltate esto. Si no:
```bash
npm install -g @anthropic-ai/claude-code
```

**uv** — es el gestor de paquetes de Python que usa el proyecto. Instala las dependencias
(httpx, duckdb, pandas, playwright y compañía) sin que tengas que pelear con entornos virtuales.
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # macOS / Linux
# Windows PowerShell:  irm https://astral.sh/uv/install.ps1 | iex
```

Y después, dentro de `flujo-cero`:
```bash
make setup     # instala dependencias + el navegador headless
make test      # tiene que cerrar con: 12 passed
```

Si `make test` da **12 passed**, el motor financiero está correcto y puedes seguir.
Si falla, para acá y pégale el error a Claude Code.

---

# PASO 3 · Completar tu perfil 📝

Abre `config/inversionista.yml` — o más simple, entra a Claude Code y pídeselo:

```
🤖  Abre config/inversionista.yml y ayúdame a completar la sección `restricciones`.
    Mi renta líquida mensual es $X, tengo $Y ahorrados para el pie y $Z en cuotas
    de otros créditos.
```

Los cuatro campos que faltan:

| Campo | Qué es |
|---|---|
| `renta_liquida_mensual_clp` | Líquida, no bruta. Promedio de tus últimas 3 liquidaciones |
| `ahorro_disponible_pie_clp` | Lo que puedes poner hoy, sin contar tu fondo de emergencia |
| `otros_creditos_cuota_mensual_clp` | Suma de cuotas de consumo, automotriz y tarjetas |
| `pie_objetivo_pct` | Déjalo en `0.10` — FOGAES habilita 90% de financiamiento |

**Tu ticket máximo aproximado**, mientras no tengas la pre-aprobación real. El banco exige
dividendo ≤ 25% de la renta líquida, a 30 años y 90% de financiamiento:

| Renta líquida | Dividendo máx. | Ticket @3,30% (con subsidio) | Ticket @3,97% (sin subsidio) |
|---|---|---|---|
| $1.500.000 | $375.000 | UF 2.330 | UF 2.150 |
| $2.000.000 | $500.000 | UF 3.110 | UF 2.860 |
| $2.500.000 | $625.000 | UF 3.890 | UF 3.580 |
| $3.000.000 | $750.000 | UF 4.660 | UF 4.290 |
| $4.000.000 | $1.000.000 | tope UF 6.000 | UF 5.720 |

Y el efectivo que necesitas al firmar, que **no es solo el pie**:
```
pie 10% de UF 3.000  = UF 300  ≈ $12.241.000
gastos de cierre 1,8%          ≈ UF 54  ≈ $2.203.000
                                 ─────────────────────
                                 ≈ $14.444.000
```
Tasación, estudio de títulos, notaría de compraventa y de mutuo, inscripción en el Conservador,
certificados e impuesto de timbres. **El crédito no los financia.**

---

# PASO 4 · Fase 0 — el sistema construye sus cimientos 🤖

Esto **no toca internet**: construye y valida el motor financiero. No necesitas ninguna credencial
todavía.

🖥️ Parado en `flujo-cero`, escribe:
```bash
claude
```

🤖 Y dentro del chat que se abre:
```
/harness fase 0
```

Qué va a pasar, sin que hagas nada: lee `CLAUDE.md`, toma las tareas T-001 a T-005 de
`state/BACKLOG.md`, corre las independientes en paralelo y el motor financiero en serie, y cierra
con `make gates`.

**Qué revisas tú:** que al final `make test` siga en verde. No apruebes ningún cambio al motor
financiero que no venga acompañado de su test.

Cuando termine: `git add -A && git commit -m "fase 0 completa"`.

---

# PASO 5 · Dos cuentas gratuitas 🌐

**Ahora sí** hacen falta, porque la fase 1 sale a buscar datos reales.

**1. MercadoLibre Developers** — `developers.mercadolibre.cl` → *Crear aplicación*.
Redirect URI: `http://localhost:8000/oauth/callback`. Te da un `client_id` y un `client_secret`.
Esta es **la** fuente principal del proyecto: Portal Inmobiliario corre por debajo sobre esta API,
así que la usamos por la puerta en vez de scrapear.

**2. CMF** — registro gratuito para la apikey de `api.cmfchile.cl`. De ahí salen el valor de la UF,
la UTM y las series oficiales de tasas hipotecarias.

🖥️ Después, en la carpeta del repo:
```bash
cp .env.example .env
```
📝 Y pega las credenciales en `.env`. Cambia también el `USER_AGENT` por uno con un correo tuyo
real: un crawler identificable es tu mejor defensa reputacional, uno anónimo es el que bloquean.

> `.env` está en `.gitignore`. **Nunca se sube a GitHub.** No lo saques de ahí.

---

# PASO 6 · Fase 1 — el sistema sale a buscar datos 🤖

```
/harness fase 1
```

Arranca por San Miguel, La Florida y Ñuñoa. Trabaja en olas de 4 a 6 subagentes en paralelo.
Al terminar cada ola:
```
/validar
```

**Tres momentos donde te va a consultar, y qué contestar:**

- **Categorías de MercadoLibre (T-011).** Va a *medir* si la búsqueda exige token y cuál es el ID
  real de la categoría de inmuebles. Déjalo medir. No aceptes que asuma `MLC1459` sin verificar.
- **Assetplan con navegador headless.** Apruébalo. Su `robots.txt` permite explícitamente a
  ClaudeBot, y es la mejor fuente de arriendo efectivo que existe en Chile.
- **Algo marcado `html_prohibido`.** Di que no. Si un agente propone scrapear fichas de Portal
  Inmobiliario, está saltándose la API oficial que tiene exactamente la misma data.

**La fase 1 está lista cuando:** hay ≥300 unidades con precio real por unidad, ≥8 comparables de
arriendo por microzona y tipología en el 70% de las microzonas, y `make gates` en verde.

Cuánto demora: entre unas horas y un par de días de trabajo del agente, según cuánto tengas que
revisar y cuántas fuentes se resistan.

---

# PASO 7 · El primer ranking 🤖 🖥️

```
/informe 0.10
```
```bash
make serve       # dashboard en http://localhost:8000
```

**Léelo en este orden, no de arriba abajo:**

1. **Cuántas unidades quedaron excluidas y por qué.** Si el 80% se cayó por "sin comparables
   suficientes", tu problema es de datos y el ranking todavía no significa nada. Vuelve al paso 6.
2. **La columna `n`** junto a cada arriendo estimado. Un yield con n=3 y uno con n=40 no valen igual.
3. **`pie_minimo_flujo_cero`**, antes que el cap rate. Es el número que dice la verdad.
4. **El déficit mensual en UF** al pie que tú puedes poner. Eso es lo que sale de tu bolsillo cada mes.
5. **El subconjunto ≤ UF 3.000**, que el informe reporta aparte. Ahí está tu jugada especial
   (ver el paso 9).

**El criterio para decir "esto es prometedor" y recién ahí ir al banco:**

- al menos 5 unidades con `pie_minimo_flujo_cero` bajo 40%;
- o al menos 3 unidades con déficit mensual bajo 2 UF (unos $82.000) a pie de 10%;
- y en ambos casos, con `n ≥ 8` comparables y `evidence_level: V` en el precio.

Si nada de eso aparece en la Región Metropolitana, es una señal real, no un fallo del sistema:
corre `/harness fase 3` y mira Concepción, donde el cap rate neto es 4,0% contra el 2,8% de Santiago.

---

# PASO 8 · Ampliar antes de decidir 🤖

```
/harness fase 2      # las 11 comunas, parser de listas de precios en PDF
/harness fase 3      # Gran Concepción, La Serena, Antofagasta
/informe 0.10
```

Recién con las 11 comunas y las regiones adentro tienes una comparación honesta. Antes de eso
estás eligiendo el mejor de tres.

---

# PASO 9 · El banco 🌐 — cuando el ranking ya te muestre algo

Ir con un ranking en la mano cambia la conversación: dejas de preguntar "cuánto me prestan" y pasas
a "necesito UF X para esta unidad concreta". Un solo costo de esperar, que conviene tener presente:
la pre-aprobación tarda entre 3 y 10 días hábiles, y los cupos bajan —34.917 formalizados de 80.000,
a un ritmo de ~35.000 en 14 meses.

**Ve a tres bancos, no a uno.** Al 28-ago-2026, por confirmar en tu cotización:

| Banco | Sin subsidio | Con subsidio + FOGAES |
|---|---|---|
| **Itaú** | **3,39% fija** — la más baja del mercado | por confirmar |
| **Santander** | <3,60% | **<3,30%** |
| **Banco de Chile** | — | **<3,30%** |
| Falabella | 3,70% | — |
| BancoEstado | 4,19% | — |

Pide **cotización formal escrita con CAE**, no la tasa nominal. El CAE incorpora los seguros de
desgravamen e incendio, que en el modelo son estimados y no verificados. Dos bancos con la misma
tasa nominal pueden diferir en cientos de miles de pesos al año.

## Las cinco preguntas, escritas

1. **¿El tramo de 6.000 cupos para viviendas de hasta UF 3.000 exige subsidio DS1 o DS19, o basta
   con ser primera vivienda del solicitante?**
2. **¿Qué tasa ofrece ese tramo versus el tramo general de hasta UF 6.000?**
3. **¿Cuántos cupos FOGAES les quedan asignados a ustedes, en cada tramo?**
4. **¿La garantía FOGAES tiene algún costo o comisión que me cobren a mí, directa o indirectamente?**
5. **¿Cuántos días de validez tiene esta cotización?**

**Por qué la 1 y la 2 valen más que las otras tres juntas.** Tú no tienes propiedades, así que
calificas al tramo reservado de ≤ UF 3.000 del que la mayoría de los inversionistas queda fuera.
Y ese tramo coincide justo con los tickets de mayor yield: 1D1B compactos, La Cisterna, Estación
Central, Concepción. **Si además su tasa es mejor, apuntar a ≤ UF 3.000 te gana en las dos
dimensiones a la vez** —mejor yield y menor costo de fondos—, que es el pie de equilibrio más bajo
alcanzable con tu perfil. Anota la respuesta en `docs/05-decisiones.md` D-009 y vuelve a correr
`/informe`.

**Documentos que te van a pedir:** últimas 3 liquidaciones de sueldo (o 12 meses de boletas más
carpeta tributaria si eres independiente), 6 meses de cartola bancaria, certificado de cotizaciones
de AFP, cédula de identidad y certificado de antecedentes comerciales. Ármalos antes de la primera
reunión: la mitad de las demoras son de papeleo, no de evaluación.

---

# PASO 10 · De la lista corta a la firma

**Para cada una de las 5 primeras del ranking:**

1. Pide la **lista de precios por unidad**, no el "desde". Ruta más rápida: el cotizador del
   proyecto —muchos corren sobre PlanOK y emiten una cotización formal por correo sin que hables
   con nadie—. Segunda: el formulario del sitio de la inmobiliaria. Tercera: WhatsApp de la sala.
2. Pide el **desglose de estacionamiento y bodega**. Son líneas independientes, no están incluidas,
   y un estacionamiento parte en unas 360 UF.
3. Pregunta si el proyecto está **acogido a DFL2** y pide verlo por escrito.
4. Pide los **gastos comunes reales** en $/m². Los paga el arrendatario, pero un gasto común alto
   reduce el arriendo que el mercado tolera: entre comunas la diferencia llega a $164.000 mensuales.

Carga esas listas al sistema y vuelve a correr `/informe`. Ahora los precios son reales.

**En la visita, mira lo que el modelo no puede ver:** ruido, orientación real a esa hora, calidad
de terminaciones, quién vive en el edificio. Y **camina desde la estación de Metro hasta el
proyecto, a la hora en que lo haría tu arrendatario** — no confíes en la distancia en línea recta.

**Antes de firmar la promesa, verifica:**
- **DFL2 en la escritura o el certificado municipal.** No en lo que dice el vendedor.
- **Superficie útil ≤ 140 m².** Sobre eso pierdes DFL2 completo.
- **Promesa posterior al 31-dic-2024.** Anterior, no hay subsidio.
- **Que sea primera venta.** El subsidio aplica solo a vivienda nueva, primera transferencia.
- **Avalúo fiscal real por rol en el SII.** El modelo usa un ratio estimado de 0,55 sobre mercado;
  con el número real, las contribuciones dejan de ser un supuesto.
- **La reserva se descuenta del pie.** No es un pago adicional. Que quede escrito.

---

# Las reglas DFL2 que no puedes romper

Tienes **2 cupos y ninguno usado**. El paquete DFL2 —arriendo exento de impuesto a la renta, 50% de
rebaja de contribuciones por 10 a 20 años, exención de IVA de arriendo, exención de impuesto de
herencias— **vale más que el subsidio a la tasa en valor presente**. Cinco reglas:

1. **Nunca a nombre de una sociedad.** La persona jurídica no accede a DFL2 en absoluto.
2. **Máximo 140 m² útiles.** Un metro más y pierdes el régimen entero. Por eso el ranking excluye
   por regla dura todo lo que se pase, en vez de restarle puntos.
3. **Máximo 2 por persona natural** (Ley 20.455). La tercera propiedad pierde las tres exenciones
   juntas y su economía es estructuralmente peor.
4. **Para ir más allá de dos, una segunda persona natural** —cónyuge con separación de bienes—,
   que duplica el cupo DFL2 *y* la exención de ganancia de capital de UF 8.000. Nunca una sociedad.
5. **No amuebles.** El arriendo amoblado paga 19% de IVA.

---

# Lo que NO debes hacer

- **No compares tu TIR con un depósito a plazo sin sumarle la inflación.** El modelo corre en UF,
  así que la TIR que ves es **real**. Es el error de comparación más común del rubro.
- **No cuentes con que la inflación licúe la deuda.** El crédito está en UF. El hedge es del activo,
  no del pasivo.
- **No compres esperando flujo positivo con 10% de pie en Santiago.** No va a pasar. Decide de
  antemano cuánto déficit mensual estás dispuesto a sostener y trátalo como ahorro forzoso: en los
  primeros años la amortización de capital ronda el 1,3% del valor al año, y la paga tu arrendatario.
- **No dejes pasar más de 3 o 4 semanas entre el ranking y el banco.** Los cupos son el límite real,
  no la fecha de vencimiento de la ley.

---

# Resumen de una línea por paso

| # | Dónde | Qué |
|---|---|---|
| 1 | 🖥️ Terminal | Descomprimir el repo, `git init`, subir a GitHub privado |
| 2 | 🖥️ Terminal | Instalar `uv`, `make setup`, `make test` → 12 passed |
| 3 | 📝 Editor | Completar `config/inversionista.yml` con tus 4 números |
| 4 | 🤖 Claude Code | `/harness fase 0` — cimientos, sin internet |
| 5 | 🌐 Navegador | Cuentas de MercadoLibre Developers y CMF → pegarlas en `.env` |
| 6 | 🤖 Claude Code | `/harness fase 1` + `/validar` — datos reales, 3 comunas |
| 7 | 🤖 Claude Code | `/informe 0.10` + `make serve` — primer ranking |
| 8 | 🤖 Claude Code | `/harness fase 2` y `fase 3` — 11 comunas y regiones |
| 9 | 🌐 Banco | Tres bancos, cotización con CAE, las cinco preguntas |
| 10 | 🌐 Salas de venta | Listas de precios reales, visitas, verificar DFL2, firmar |
