# Runlog
Append-only. Una entrada por iteración del harness.

Formato:
```
## YYYY-MM-DD HH:MM · iteración N
tareas: T-0xx (hecha), T-0yy (falló)
gates: verde | rojo — detalle
filas: fuente → insertadas / actualizadas
hallazgos:
aprendizajes:
tareas nuevas abiertas:
```

---

## 2026-08-28 · iteración 0 — bootstrap
tareas: ninguna ejecutada
gates: n/a
notas: repositorio inicializado con CLAUDE.md, PRD, catálogo de fuentes, modelo financiero,
params, zonas, esquema, agentes, comandos y backlog. Investigación de mercado consolidada en
`docs/00-hallazgos.md`. Siguiente paso: `/harness fase 0`.


## 2026-08-28 · iteración 1 — FASE 0 COMPLETA
tareas: T-001, T-002, T-003, T-004, T-005 → hechas
gates: **VERDE** · `pytest`: **28 passed**

qué se construyó:
- `src/flujocero/config.py` — carga de params/inversionista con validación de evidencia
- `src/flujocero/finance/core.py` — dividendo, saldo insoluto, erosión, NOI, TIR, pie de equilibrio
- `src/flujocero/finance/modelo.py` — evaluación de unidad × escenario, opex, exclusiones duras
- `src/flujocero/finance/escenarios.py` — producto cartesiano de escenarios + score auditable
- `src/flujocero/db.py` — esquema DuckDB aplicado (13 tablas)
- `src/flujocero/cli.py` — `build`, `rebuild`, `capacidad`, `demo`, `gates`
- `tests/golden/` — 28 casos: doble implementación del dividendo, anclas del pie de equilibrio,
  identidad contable, delta DFL2 exacto, exclusiones duras, monotonías, score

hallazgos:
1. **El gate de evidencia encontró un bug real de configuración**: 6 supuestos marcados `E` en
   `params.yml` no declaraban rango de sensibilidad. Corregidos. Hoy hay 11 estimados, todos
   con rango — que es exactamente la lista que debe recorrer el análisis de sensibilidad.
2. **Doble conteo de seguros en `docs/02-modelo-financiero.md`**: el NOI restaba el seguro de
   incendio/sismo y `dividendo_total` lo sumaba otra vez. En Chile el banco los cobra con el
   dividendo, así que van solo ahí. Documento corregido y test que lo fija.
3. El motor reproduce el hallazgo central de la investigación sin que se le imponga: con pie de
   10% y tasa 3,30%, el pie de equilibrio sale 36–37% en la RM y **27% en Concepción**.

aprendizajes: el escenario `sin_subsidio` se construye siempre, aunque el inversionista califique.

siguiente: T-010 a T-012 (CMF, OAuth de MercadoLibre, tasas por banco) — se paralelizan.
Requiere credenciales en `.env` y, para los colectores, IP chilena.

## 2026-08-28 · iteración 2 — reproducibilidad del entorno y del gate de estilo
tareas: ninguna del backlog cerrada; trabajo de infraestructura previo a fase 1
gates: **VERDE** · ruff + ruff format + mypy --strict + `pytest`: **28 passed** + gates de CLI

qué se arregló:
1. **`make test` no corría desde un checkout limpio.** `pyproject.toml` no declaraba
   `[build-system]`, así que `uv sync` no instalaba el paquete y ni los tests ni
   `python -m flujocero.cli` podían importar `flujocero`. Además las dependencias de
   desarrollo vivían en `[project.optional-dependencies]`, que `uv sync` no instala por
   defecto. Pasan a `[dependency-groups]`.
2. **`uv.lock` versionado.** Sin lock, la versión de ruff que resuelve `uv` cambia el
   conjunto de reglas por defecto y con ello el veredicto del gate.
3. **Gate de estilo determinístico.** `ruff>=0.5` sin fijar resolvía ruff 0.16.5, cuyo
   default es mucho más amplio: 42 hallazgos donde antes había 0. Se declara
   `[tool.ruff.lint] select = ["E4","E7","E9","F","I"]` y se fija `ruff==0.16.5`.
   El gate deja de depender del default de turno.

hallazgos:
1. **Bajo los 42 hallazgos de estilo había 2 reales**, no cero: `E702` (dos sentencias en
   una línea en `cli.py`) y `F401` (import sin usar en `tests/golden/test_modelo.py`).
   Corregidos. El resto era inflación del conjunto de reglas.
2. **El contenedor remoto no alcanza ninguna de las dos fuentes de fase 1.** El proxy de
   egreso bloquea `api.mercadolibre.com`, `api.cmfchile.cl` y `developers.mercadolibre.cl`.
   No es el bloqueo por IP de datacenter previsto en D-007: es una pared anterior.
   **Confirma D-007 por una razón distinta a la registrada:** los colectores se ejecutan en
   la máquina del inversionista. El código y sus tests contra fixtures sí se escriben acá.
3. **El Redirect URI de `.env.example` era inválido.** El formulario de MercadoLibre exige
   HTTPS y valida que el dominio resuelva, así que rechaza `http://localhost:8000/...`.
   Valor adoptado y verificado por el usuario contra el formulario:
   `https://acabreirav.github.io/PropInvest/oauth/callback`. No necesita servir nada: solo
   es el destino al que MELI devuelve el navegador con el `?code=` en la barra.
4. `docs/RUNBOOK.md` sigue diciendo "make test → 12 passed" en el paso 2 y en la tabla
   resumen. Son 28. Documento desactualizado respecto a la iteración 1.

verificación: `demo` produce salida idéntica antes y después del reformateo de 7 archivos.

tareas nuevas abiertas: T-905 (corregir el conteo de tests en RUNBOOK), T-906 (borrar el
`flujo-cero.tar.gz` vacío commiteado en la raíz).

siguiente: T-010 y T-012 (CMF: UF/UTM/IPC y tasas por banco) — código y tests contra
fixtures grabadas acá; ejecución contra la red, en la máquina del usuario.

## 2026-08-28 · iteración 3 — T-010 (colector CMF) y el contrato de fuentes
tareas: T-010 → **en_curso** (no `hecha`: falta ejecución contra la API viva)
gates: **VERDE** · ruff + ruff format + mypy --strict + `pytest`: **67 passed** (eran 28)

qué se construyó:
- `sources/base.py` — el contrato `Source` del §7.1, que no existía. Aporta `Procedencia`
  (las seis columnas, imposible de construir incompleta), la zona cruda del §3.6 y
  `SelfTestReport`.
- `sources/robots_check.py` — el `python -m flujocero.sources.robots_check <url>` que el
  §3.5 exige antes de cualquier scraper. Guarda snapshot y devuelve su sha.
- `sources/cmf_indicadores.py` — colector de UF, UTM e IPC. `legal_tier: api_oficial`.
- `quality/source_contract.py` — el gate: verifica el protocolo y, por separado, que las
  filas lleven las seis columnas y un `evidence_level` legal.
- `cli.py ingest` — recolecta, verifica contrato, corre selftest y carga en DuckDB.
- 39 tests nuevos, ninguno toca la red.

hallazgos:
1. **`dim_tiempo_financiero` violaba el §3.1**: no tenía ninguna columna de procedencia, y
   su formato ancho las hacía imposibles — UF, UTM, IPC y TPM vienen de endpoints distintos
   y un solo juego de seis columnas por fila no puede describir cuatro orígenes. Pasa a
   formato largo `(fecha, serie)` + vista `v_tiempo_financiero` para la forma ancha.
   `dim_tasa_banco` tenía 2 de 6; completada.
2. **La auto-crítica del §7.6 encontró un error real de mil veces.** `a_decimal("40.804")`
   devolvía `40.804` en vez de `40804`: el código decidía caso a caso si el punto era
   separador de miles o decimal. En formato chileno el punto es SIEMPRE separador de miles.
   Es exactamente la clase de error contra la que advertía el ADR que yo mismo había escrito
   tres archivos antes. Corregido, con tres casos de prueba que lo fijan.
   (La auto-crítica la hice yo mismo sobre el código, no vía subagente.)
3. **`collect()` recolectaba aunque la verificación de robots fallara.** El §3.5 dice que
   pasa ANTES de recolectar. Corregido: sin veredicto favorable y sin `snapshot_sha` no se
   descarga nada — y de todos modos la fila no podría insertarse sin procedencia completa.
4. **La forma de la respuesta de la CMF no está verificada contra la API viva.** El proxy de
   red bloquea `api.cmfchile.cl`. La estructura se tomó de la documentación oficial, la
   fixture está marcada como derivada de documentación con valores sintéticos declarados
   prohibidos como dato de mercado, y `selftest()` reporta `forma_verificada: false`
   mientras no vea una muestra viva. Por eso T-010 queda `en_curso`.

perfil del inversionista: renta líquida $2.250.000, ahorro $40.000.000, sin otros créditos.
**Ticket máximo por capacidad de crédito: UF 3.497 con subsidio, UF 3.220 sin él.** La
restricción vinculante no es el tope legal de UF 6.000 sino la renta. Eso deja el tramo
especial de <= UF 3.000 (Decreto 180 art. 4) dentro del rango y el tramo general fuera de
toda relevancia práctica. Sube la prioridad de D-009.

tareas nuevas abiertas: D-011 (renta conjunta con la cónyuge — cuatro preguntas sin resolver
sobre régimen patrimonial, propiedades previas, cupos DFL2 y co-deudor sin co-propiedad).

siguiente: T-012 (tasas hipotecarias por banco, XLS de la CMF). No depende de red para
escribirse. Y ejecutar `cli ingest` desde una máquina con internet para cerrar T-010.

## 2026-08-28 · iteración 4 — descomposición del déficit
tareas: motor financiero (cambio en serie, §8.3) · D-011 corregida · D-012 abierta
gates: **VERDE** · `pytest`: **73 passed**

qué se agregó al motor:
- `core.amortizacion_periodo()` y `amortizacion_mensual_promedio()` — capital amortizado
  como diferencia de saldos insolutos.
- `core.costo_tenencia_mensual()` — el déficit de caja neto de la amortización.
- `Evaluacion.amortizacion_mensual_uf`, `costo_tenencia_mensual_uf`,
  `fraccion_deficit_que_es_ahorro`.
- 6 casos de oro nuevos, incluida la identidad `capital + interés == dividendo` a 1e-18.

hallazgo:
**Entre el 69% y el 84% del "déficit mensual" no es gasto: es amortización.** Sobre las
unidades de demostración, un egreso de $225.485 esconde un costo económico real de $67.518;
en Concepción, $198.895 esconde $31.146. El componente que hoy pesa 30% del score exagera el
costo entre 3 y 6 veces.

**No se cambiaron los pesos del score.** El §8.4 obliga a detenerse cuando un cambio mueve el
ranking en más del 10% de las posiciones. Queda como **D-012**, con recomendación explícita
(ordenar por costo real + filtro duro por déficit de caja) y con la advertencia de que la
amortización no es líquida.

Segundo hallazgo, menos agradable: **el déficit no mejora solo con el tiempo.** El modelo
corre en UF reales; el arriendo real no crece y el dividendo en UF no baja. No existe el año
en que la unidad "empieza a rendir". Sólo lo mueven más pie, mejor tasa o mejor mercado.

perfil: capacidad de ahorro $400.000/mes, tolerancia declarada al déficit = 0. Son cosas
distintas y el ranking usa la tolerancia, no la capacidad.

corrección de la iteración anterior: la Estructura B de D-011 (una unidad por comprador)
suponía que la cónyuge financiaba su propio pie. Los $40.000.000 son de él. Caso base vuelve
a compra individual; la cónyuge entra sólo como codeudora solidaria sin co-propiedad.

siguiente: T-012, tasas hipotecarias por banco.

## 2026-08-28 · iteración 5 — T-026, gates de calidad de datos
tareas: T-026 → **en_curso** · T-012 → **bloqueada** (ver abajo)
gates: **VERDE** · `pytest`: **101 passed** (eran 73)

qué se construyó — `quality/checks.py`, los diez checks del §7.3:
procedencia completa · cobertura ≥80% · frescura ≤21 días · outliers p1/p99 por microzona ·
duplicados de venta por clave natural · duplicados de arriendo en ventana de 30 días ·
ancla externa UF/m² contra Colliers · n≥8 comparables · reconciliación de arriendo ±25% ·
**datos personales por regex sobre valores**.

Tres severidades, y la distinción es deliberada:
- `FALLA` detiene el ranking (datos personales, procedencia, frescura, duplicados, ancla)
- `ALERTA` lo publica marcado `parcial` (cobertura, reconciliación)
- `MARCA` sólo etiqueta (`sospechoso = true`) — outliers y n<8

**Ningún check borra ni imputa.** El §7.3 dice "alerta, no borrado" y el §3.2 prohíbe imputar
en silencio. El módulo entero hace una sola mutación: poner `sospechoso = true`.

hallazgos:
1. El check de datos personales distingue **RUT de persona natural de RUT de empresa** (corte
   en 60.000.000). Sin eso, el nombre de la inmobiliaria — que el §3.4 sí permite persistir —
   habría hecho fallar el gate.
2. **Un test mío estaba mal y el código tenía razón.** El caso "limpio" del reporte usaba diez
   unidades idénticas, y el detector de duplicados las rechazó correctamente: la clave natural
   es `(proyecto_id, numero_unidad)`. Se corrigió el test y se agregó uno que fija ese
   comportamiento como esperado.
3. **T-026 no se marca `hecha`.** Los checks nunca han visto una fila real. Hasta que T-020 y
   T-023 carguen datos, no se puede afirmar que los umbrales están bien calibrados.

**T-012 bloqueada, y no se escribió código especulativo.** El proxy bloquea también
`www.cmfchile.cl`, así que no fue posible ver el XLS de tasas hipotecarias por banco. Escribir
un parser para una planilla cuya estructura no se ha visto sería código a ciegas disfrazado de
avance. Se pide el archivo al usuario: es una descarga de navegador, sin terminal.

siguiente: T-012 en cuanto llegue el XLS. Mientras, el resto de fase 1 depende de red.

## 2026-08-28 · iteración 6 — T-012 y D-012 aprobada
gates: **VERDE** · `pytest`: **117 passed** (eran 101)

**Hallazgo mayor: la fuente de tasas por banco sirve datos de 2006.**
El inversionista adjuntó `articles-46417_recurso_1.xls`. Su propia celda dice "Fecha de la
consulta: 22 al 26 de mayo de 2006", lo firma la SBIF (disuelta en 2019) y lista BankBoston,
Banco del Desarrollo, Banco Paris y Citibank NA. Tasas de 4,8% a 7,5%.

Se escribió el parser igual —la estructura es real y verificada: 117 filas, 17 bancos, 3
montos, 3 productos— con la **detección de obsolescencia adentro**: `parse()` lanza
`PlanillaObsoleta` sobre los 12 meses. La fuente queda `enabled: false` con la razón escrita
(§7.1) y el archivo se conserva como fixture de estructura, con un PROCEDENCIA.md que
prohíbe usar sus números. Se abre **T-907** con cuatro pistas para la fuente vigente.

Tres decisiones que el archivo obligó:
1. **Localización por etiqueta, nunca por índice.** Entre hojas del mismo archivo el
   contenido se corre una fila: índices fijos habrían leído la hoja 1 bien y las otras dos
   mal, en silencio.
2. **`n/o` es ND, no cero.** Convertirlo a 0,0% habría hecho aparecer a ese banco como el
   más barato del mercado.
3. **Una tasa por banco al cargar, la mínima**, explícita y no un promedio silencioso.

**D-012 aprobada por el inversionista y aplicada.** El componente de 30% del score pasa de
`deficit_flujo_mensual_uf` a `costo_tenencia_mensual_uf`, y la liquidez se protege con una
exclusión dura por déficit de caja máximo, leída de `inversionista.yml`.

Hallazgo al aplicarla: **con `deficit_mensual_tolerado_clp: 0` el filtro excluye el 100% del
universo** y el ranking queda vacío. No es un bug: es el §2.3 hecho carne. Se separó el
concepto — el filtro es el TECHO de liquidez ($400.000, su capacidad declarada) y el deseo de
cero déficit se expresa en el ORDEN del ranking, no en el filtro. Filtro = cuánto puede;
orden = cuánto quiere.

Efecto sobre la demo: Ñuñoa se cae por liquidez ($432.372 > $400.000) y San Miguel baja de
55,4 a 40,5 puntos al medirse por costo real. Concepción sigue primera.

siguiente: T-907 (fuente vigente de tasas). El resto de fase 1 depende de red.

## 2026-08-28 · iteración 7 — el script de instalacion, y un fallo de codificacion
gates: **VERDE** · `pytest`: **126 passed** (eran 117)

`scripts/setup.ps1` y `scripts/setup.sh`: instalacion en un paso. Verifican e instalan git
y uv, clonan o actualizan el repo, instalan dependencias, crean el `.env` desde la plantilla
avisando cuales de las cuatro credenciales siguen vacias, y corren tests, gates y demo.
Ninguno contiene credenciales: estan versionados.

**Fallo real en la primera entrega, reportado por el usuario.** El script reventaba con
"Falta la cadena en el terminador" apuntando a la linea 138, que no tenia nada malo. La
causa estaba 70 lineas mas arriba: un guion largo (U+2014) dentro de una cadena.

Windows PowerShell 5.1 lee los `.ps1` en **Windows-1252**, no en UTF-8. El guion largo son
tres bytes en UTF-8 (E2 80 94); leidos como cp1252 dan `â€"`, y ese tercer caracter **es una
comilla de cierre**. La cadena se cerraba antes de tiempo y todo el parseo se desalineaba
hasta morir al final del archivo.

Aprendizaje que vale mas alla de este script: **el error se reporta donde el parser se
rinde, no donde esta la causa.** Con un fallo de codificacion, la linea que acusa el mensaje
es casi siempre inocente.

Correccion: `setup.ps1` pasa a **ASCII puro**, verificado byte a byte — el archivo se decodifica
identico como cp1252 y como UTF-8. Y `tests/unit/test_scripts.py` lo fija con 9 guardias:
ASCII puro, sin BOM, llaves y parentesis balanceados, comillas pares por linea, sin
credenciales versionadas y apuntando a la rama correcta.

Ensayado antes de entregar desde un clon limpio: 78 archivos, `uv sync` desde cero, tests y
gates en verde. Lo unico que no se pudo ensayar es la ejecucion en Windows, porque este
entorno es Linux — y ahi es exactamente donde estaba el fallo.

siguiente: que el usuario corra `cli ingest` para cerrar T-010.

## 2026-08-28 · iteración 8 — reintentos, troceado del periodo y diagnostico
gates: **VERDE** · `pytest`: **141 passed** (eran 130)

**Primera ejecucion real del colector, en la maquina del usuario.** El setup funciono, la
verificacion de robots.txt paso, y el colector llego a hacer la peticion. Fallo asi:

    RemoteProtocolError: Server disconnected without sending a response.
    .../uf/periodo/2024/01/2026/08

O sea: la conexion y el TLS funcionan (robots.txt se descargo bien contra el mismo host),
y lo que falla es la peticion de 32 meses de serie diaria.

**Hallazgo sobre mi propio trabajo:** el §5 del contrato exige `httpx` **+ `tenacity` con
backoff exponencial y jitter**, y el colector no lo implementaba. Un corte de conexion
mataba la corrida completa sin un solo reintento.

qué se agregó:
1. **Reintentos con backoff exponencial y jitter** sobre los fallos transitorios
   (`RemoteProtocolError`, `ConnectError`, `ReadTimeout`, `ConnectTimeout`, `ReadError`),
   4 intentos. **Un 401 o un 404 no se reintentan nunca**: reintentar un error de
   credencial solo consigue que te bloqueen.
2. **`ventanas()`**: trocea el periodo en tramos de a lo mas un ano calendario. Funcion
   pura, con test de que los tramos cubren el rango sin huecos ni solapes. `parser_version`
   sube a 1.1.0.
3. **`cli probe`**: diagnostico que prueba URLs de complejidad creciente — robots.txt, hoy,
   1 mes, 8 meses, 1 ano, 32 meses — y reporta cual pasa. Existe para no adivinar donde
   esta el limite. La primera prueba que falla lo acota.

Un test propio salio mal: `zip(tramos, tramos[1:], strict=True)` exige listas del mismo
largo y la segunda es una mas corta por construccion. Corregido a `tramos[:-1]`.

siguiente: que el usuario corra `cli probe` y despues `cli ingest`. Si el troceado por ano
resuelve el corte, T-010 se cierra.

## 2026-08-28 · iteración 9 — el diagnostico desmiente mi hipotesis
gates: **VERDE** · `pytest`: **141 passed**

`cli probe` corrido por el usuario contra la API real:

    robots.txt  HTTP 404                    327 bytes
    hoy         RemoteProtocolError          —
    1 mes       HTTP 200    2.159 bytes     31 registros
    8 meses     HTTP 200   16.778 bytes    243 registros
    1 ano       HTTP 200   25.196 bytes    365 registros
    32 meses    HTTP 200   67.193 bytes    974 registros

**Mi hipotesis era falsa.** Supuse que el `Server disconnected` venia del tamano del rango.
La medicion dice lo contrario: 32 meses responden perfecto, y es exactamente la MISMA URL
que habia fallado minutos antes. **El corte es intermitente, no depende del tamano.**

Lo que arregla el fallo son los reintentos con backoff, que agregué por otra razon —haber
encontrado que el colector no cumplia el §5 del contrato—. El troceado por ano no era la
solucion que yo creia.

Se corrigieron los comentarios del modulo, el docstring de `ventanas()` y el de `collect()`,
que afirmaban la causa equivocada. **Una explicacion falsa en el codigo es peor que ninguna:
sobrevive al que la escribio y desvia al que venga despues.** El troceado se conserva con su
razon verdadera: que un corte cueste rehacer una ventana y no el periodo entero.

hallazgos secundarios:
1. `api.cmfchile.cl/robots.txt` devuelve **404**. La lectura estandar del protocolo es que
   sin robots.txt todo esta permitido, y `robots_check.verificar()` ya lo trata asi,
   guardando el snapshot vacio con su sha. Comportamiento correcto, ahora confirmado contra
   el servidor real.
2. **El endpoint sin periodo (`/uf` a secas, el valor de hoy) fallo.** No se puede distinguir
   con una sola muestra si es el mismo corte intermitente o si esta roto. Queda anotado en el
   docstring; el colector solo lo usa cuando no se le da rango.

lección metodologica: el `probe` valio la pena. Sin el habria "arreglado" el problema con el
troceado, habria funcionado por casualidad —gracias a los reintentos— y habria quedado en el
codigo una explicacion equivocada de por que.

## 2026-08-28 · iteración 10 — el mismo servidor, ahora en robots.txt
gates: **VERDE** · `pytest`: **154 passed** (eran 141)

Segunda corrida del usuario:

    ✗ no se recolecta: verificación de robots.txt no superada — robots.txt respondió 500

Veinte minutos antes, en el `probe`, ese mismo `robots.txt` devolvia **404**. Es la misma
inestabilidad del servidor, ahora en el otro extremo.

**Dos errores mios, y el segundo es de criterio, no de codigo.**

1. Le puse reintentos a las peticiones de datos y **no a la de robots.txt**, contra el mismo
   host que ya habia demostrado ser inestable. Corregido: mismo backoff exponencial con
   jitter, 4 intentos.
2. **Trataba un 500 como una prohibicion.** No lo es. El RFC 9309 distingue tres casos que
   es facil confundir:
   - **4xx (no disponible)**, 404 incluido: NO hay restricciones. Se permite.
   - **5xx (inalcanzable)**: se reintenta; agotados los intentos se asume prohibicion, pero
     **por caida del servidor y no por decision del sitio**, y el mensaje ahora lo dice.
   - **2xx**: se parsea y manda lo que diga.

   El codigo anterior mandaba todo 4xx que no fuera 404 al mismo saco que el 5xx. Un 403 en
   `robots.txt` significa "no disponible", no "prohibido crawlear".

La distincion no es academica: un 500 transitorio tratado como prohibicion detiene una
recoleccion legitima, y un 5xx tratado como permiso saltaria una prohibicion real.

13 tests nuevos, incluida la secuencia exacta que fallo (500, 500, 404) y la que debe seguir
prohibiendo (un `Disallow: /` de verdad).

Tambien se corrigio la pista de error de la CLI, que solo hablaba de proxy y 403 y no servia
para este caso. Ahora distingue tres sintomas y menciona `cli probe`.

## 2026-08-28 · iteración 11 — respaldo por snapshot cuando el servidor se cae
gates: **VERDE** · `pytest`: **160 passed** (eran 154)

Tercera corrida: `robots.txt respondio 500 tras 4 intentos`. Los reintentos hicieron su
trabajo y el servidor sigue caído, mientras los endpoints de datos responden HTTP 200.

**Lo que faltaba: usar el snapshot que ya teníamos.** El §3.1 obliga a guardar un
`robots_snapshot_sha` en cada verificación exitosa, así que la zona cruda ya contenía el
robots.txt de la primera corrida del usuario. El RFC 9309 §2.3.1.3 admite apoyarse en una
copia cacheada cuando el archivo es inalcanzable. **Un snapshot real es mejor evidencia que
una suposición**, en cualquiera de las dos direcciones.

Reglas del respaldo, todas con test:
- El servidor vivo **siempre** gana sobre la cache: es un respaldo, no un atajo.
- Un snapshot que decía `Disallow` **sigue prohibiendo**. No es una puerta trasera.
- Un snapshot vacío (de un 4xx) significa que no había robots.txt: permite.
- Pasados **30 días** ya no se usa: es el límite que da el RFC.
- Sin snapshot y con el servidor caído, no se recolecta.

Se abre **D-013**, que es la pregunta de fondo y no la decide el modelo: si un `robots.txt`
caído debe detener una API oficial con credencial a nombre del inversionista, cuando ese
protocolo está pensado para crawlers anónimos. **Recomendación: mantener como está** — el
respaldo por snapshot ya cubre el caso real, y una excepción por `legal_tier` es la clase de
puerta que después se usa para otra cosa.

## 2026-08-28 · iteración 12 — T-010 CERRADA, y auditoría de deuda técnica
tareas: **T-010 → hecha** · T-908, T-909 abiertas
gates: **VERDE** · `pytest`: **165 passed** (eran 160)

**T-010 cerrada con datos reales**, desde la máquina del usuario:

    ✓ 9 documentos en la zona cruda
    ✓ contrato de fuente: 1037 filas con procedencia completa
    ✓ selftest: {..., 'robots': True, 'forma_verificada': True}
    uf         974 filas   2024-01-01 → 2026-08-31
    utm         32 filas
    ipc_var_m   31 filas

`forma_verificada: true` es lo que importa: la estructura deducida de la documentación
resultó ser la real. Se dedujo bien, pero recién ahora está **verificada**.

---

## Auditoría de deuda técnica

El usuario planteó la sospecha de que estábamos saltándonos cosas. **Tenía razón.** Se
auditó con evidencia, no con tranquilidad. Seis hallazgos:

1. **`make rebuild --from-raw` era una mentira.** Borraba la base y aplicaba el esquema
   vacío; el flag `--from-raw` se ignoraba por completo. El §3.6 lo exige explícitamente.
2. **Y era IMPOSIBLE de implementar**, que es peor. La zona cruda guardaba solo el cuerpo
   del documento. De las seis columnas del §3.1, la ruta permite deducir tres —`source_id`,
   `fetched_at`, `raw_blob_path`— y las otras tres **se perdían**. Reconstruir una fila
   habría exigido inventarle procedencia: no es que fuera difícil, es que era ilegal.
   Corregido: cada blob va con un `.meta.json` al lado. Y un blob sin sidecar **no se
   reconstruye**, se reporta y se conserva.
3. **El caso de oro de la TIR usaba tolerancia 1e-6 y el §7.2 punto 5 pide 1e-9.** Apretado.
   Pasa: el motor era más preciso de lo que su propio test exigía.
4. `tests/integration/` está vacío pese a que el §7.1 habla de fixtures grabadas. Los tests
   de fuentes viven en `unit/` y no llevan el marcador `integration`.
5. **La UF sigue siendo un parámetro fijo** (`valor_uf_clp: 40804`) aunque ahora hay 974
   valores reales cargados. El motor no lee de la base. → deuda declarada, no cerrada.
6. La fixture de la CMF sigue siendo la derivada de documentación. → T-909.

**Lo pagado en esta iteración: 1, 2 y 3.** La 2 es la que justificaba la sospecha del
usuario: se habría descubierto al final, con meses de datos recolectados y sin forma de
reconstruirlos. Las 4, 5 y 6 quedan **declaradas en el backlog**, no escondidas.

Prueba de fuego del §3.6, ahora con test: recolectar → borrar la base entera → reconstruir
desde la zona cruda → **las filas salen idénticas**, incluidas `source_url` y
`robots_snapshot_sha`.

Se agrega `sources/registro.py`: el mapa de qué colector reconstruye qué `source_id`. Una
fuente sin entrada no se reconstruye y se reporta; nunca se descarta un blob por no saber
leerlo.

## 2026-08-28 · iteración 13 — segunda ronda de deuda: la bitácora y la UF real
gates: **VERDE** · `pytest`: **184 passed** (eran 165)

La auditoría anterior dejó tres deudas declaradas. Al ir a pagarlas aparecieron **dos más**,
y una dejaba un gate del contrato inoperante.

### Lo nuevo que encontró esta ronda

**`run_log` y `parse_errors` existían en el esquema y nadie las escribía.** Consecuencia
concreta: el §7.1 exige que el `selftest` compare el conteo de filas contra *la última
corrida exitosa* y falle si cayó más de 30% — el detector de parser roto. Sin persistir ese
conteo, el detector recibía `None` y **nunca podía disparar**. El gate existía en el código
y era decorativo.

Se construye `quality/bitacora.py`, y se conecta al `ingest`:
- La corrida se abre **antes** de salir a la red. Una recolección fallida también es
  información, y si no queda escrita el detector no puede usarla.
- Solo se compara contra corridas con `selftest_ok`. Comparar contra una fallida
  convertiría el fallo en la nueva referencia y el detector dejaría de disparar **para
  siempre**.
- Un error de parseo se registra con su documento crudo y la corrida continúa (§11). Se
  guarda la **ruta** del blob, no una copia: el documento ya está en la zona cruda.

**`pytz` faltaba como dependencia.** DuckDB lo necesita para devolver `TIMESTAMPTZ`, y el
§11 obliga a que toda fecha en la base lleve zona horaria. Habría explotado en la primera
lectura de cualquier marca de tiempo.

### La deuda declarada que se pagó

**La UF deja de ser un parámetro fijo.** T-010 cargó 974 valores reales y el motor seguía
usando `40804`. El §11 le prohíbe I/O al motor, así que la lectura ocurre afuera:
`uf_desde_la_base()` la busca y `con_valor()` arma una copia de la config con ella, marcada
`evidence: V` y con su fuente. Verificado con prueba negativa: alterando la UF de la base a
99.999, el `demo` la usa.

Si no hay serie cargada, `uf_desde_la_base()` devuelve `None` y el `demo` cae al valor de
`params.yml` **diciéndolo en pantalla**. No imputa en silencio (§3.2).

### Estado de la deuda

| # | Deuda | Estado |
|---|---|---|
| 1 | `rebuild --from-raw` no reconstruía | pagada (iteración 12) |
| 2 | La zona cruda perdía 3 de las 6 columnas | pagada (iteración 12) |
| 3 | Caso de oro de la TIR con 1e-6 en vez de 1e-9 | pagada (iteración 12) |
| 4 | La UF como parámetro fijo | **pagada** |
| 5 | `run_log` / `parse_errors` sin escribir | **pagada** |
| 6 | `pytz` ausente | **pagada** |
| 7 | `tests/integration/` vacío | pendiente, declarada |
| 8 | Fixture derivada de documentación | T-909, necesita el archivo del usuario |

## 2026-08-28 · iteración 14 — T-011: el módulo de MercadoLibre y sus mediciones
gates: **VERDE** · `pytest`: **199 passed** (eran 184)

`sources/meli.py`. Dos cosas, y ninguna es recolectar todavía:

**1 · Autenticación.** El `refresh_token` de MercadoLibre dura seis meses pero es de **un
solo uso**: cada canje devuelve uno nuevo y mata el anterior. Por eso `desde_entorno()`
**persiste el token nuevo ANTES de usar el access token**. Si el proceso muriera entre el
canje y el guardado, el viejo ya estaría muerto y el nuevo perdido: habría que rehacer la
autorización por navegador. El orden importa y está fijado con test.

**2 · Medición.** `cli medir-meli` responde las cuatro brechas del §G de
`docs/01-fuentes.md` con evidencia:

- **G1 · categoría.** Recorre `/sites/MLC/categories`, baja a los hijos de Inmuebles y
  **contrasta contra el `MLC1459` que `fuentes.yml` da por supuesto**, gritando si no
  coincide. El RUNBOOK es explícito en no aceptar ese ID sin verificarlo.
- **G2 · bearer.** Prueba la misma búsqueda **con y sin token** y compara los códigos.
- **G3 · tope.** Pagina con offsets crecientes hasta que la API rechaza.
- **G4 · rate limit.** Ráfaga corta leyendo las cabeceras de límite y `Retry-After`.

Si una medición no se puede hacer, se reporta `ND` con el motivo. Ninguna adivina (§3.2).

15 tests con transporte simulado, ninguno toca la red. Dos fallaron al principio por una
razón que valía la pena: httpx normaliza los nombres de cabecera a minúsculas, así que
`X-RateLimit-Limit` llega como `x-ratelimit-limit`. El test estaba mal, no el código.

**Falta ejecutarlo.** Necesita red y credenciales, o sea la máquina del usuario.

---

## 2026-08-28 · T-011 · La puerta oficial de MercadoLibre devolvio 403

**Que corrio.** El usuario ejecuto `cli medir-meli` en su maquina (IP residencial chilena,
21:57 UTC). Cuatro brechas del §G medidas contra la API real.

**Que salio.**

| Brecha | Resultado | Nivel |
|---|---|---|
| G1 · categoria | `MLC1459` = **raiz** Inmuebles; departamentos = **`MLC1472`** | V |
| G2 · bearer | `/sites/MLC/search` -> **403 con token y 403 sin token** | ND |
| G3 · tope | bloqueada por el mismo 403 | ND |
| G4 · rate limit | 12 peticiones en 3,3 s sin 429; sin cabeceras `X-RateLimit-*` | D |

**Que se aprendio.**

1. **`fuentes.yml` apuntaba al nodo equivocado del arbol de categorias.** No era un ID falso:
   era la raiz. Corregido a `categoria_raiz: MLC1459` + `categoria: MLC1472`, ya medido.
2. **El 403 no se explica por nada comodo.** El mismo token leyo `/sites/MLC/categories` en
   la misma corrida: no es la app, no es el token, no es la IP de datacenter (corrio en casa
   del usuario). Queda una hipotesis viva —que MELI cerro la busqueda abierta— respaldada
   solo por evidencia secundaria, y asi quedo escrita en el ADR-003. No pude confirmarla
   contra la documentacion oficial: los tres dominios de developers de MELI estan bloqueados
   por el proxy de egreso del contenedor.
3. **Defecto propio de instrumentacion.** La medicion registraba `HTTP 403` y tiraba el
   cuerpo. Un 403 pelado no distingue "el recurso murio" de "te falta un scope", y MELI manda
   esa diferencia en `message`/`error`/`cause`. Costo una corrida del usuario. Corregido:
   ahora el cuerpo entra a la evidencia, con el access token enmascarado.
4. **Un test mio pasaba con la respuesta contraria.** `assert "COINCIDE" in m.evidencia` daba
   verde tambien cuando el texto decia `"NO COINCIDE"` — es subcadena. Reescrito, y agregado
   el caso positivo real con `monkeypatch`.

**Que se hizo.**
- `meli_venta` y `meli_arriendo` -> `enabled: false`, con la razon en `fuentes.yml`.
  `meli_locations` sigue habilitada: pega contra otro recurso y T-013 no esta bloqueada.
- Brecha **G5** nueva: prueba `category=`, `category=`+`scan`, `seller_id=`, `/highlights/`,
  `/trends/` y, si alguna devuelve IDs, el multiget `/items?ids=` — porque una lista de IDs
  sin precio ni m2 no alimenta ninguna tabla.
- `docs/adr/003-meli.md` con las mediciones y las hipotesis separadas de los hechos.
- **D-014** abierta en `docs/05-decisiones.md`: si G5 confirma el cierre, se cae la premisa
  del §13.6 y eso lo decide el usuario, no el agente. Scrapear Portal Inmobiliario queda
  descartado de entrada.

**Estado.** 206 tests verdes (+7). T-011 sigue `en_curso`: falta una corrida mas del usuario.

---

## 2026-08-28 · D-015 · El usado entra al ranking, sin el subsidio

**De donde salio.** El usuario aporto que "el subsidio ahora incluye viviendas usadas hasta
UF 4.000". Verificado antes de actuar: es cierto, pero es **otro instrumento**.

**Que se encontro.** Tres cosas distintas que la prensa junta en un titular:
subsidio a la tasa (Ley 21.748, solo primera venta, tope UF 6.000) · FOGAES ampliado
(garantia, tope UF 6.000, cobertura de usadas SIN CONFIRMAR) · **Subsidio Tramo 4.000
(DS1 Tramo 4)**, que si admite usadas pero **obliga a habitar la vivienda y prohibe
arrendarla 5 anos**. Para una tesis de arriendo desde el primer mes no es suboptimo:
es incompatible.

**Que se decidio (por el usuario).** El usado entra como **escenario**, no como pivote.

**Que se hizo.**
- `solo_vivienda_nueva: false`. El usado compite.
- `finance/modelo.tasa_aplicable()`: el subsidio es condicion del INMUEBLE, no del escenario.
  Un usado se evalua a tasa sin subsidio aunque el escenario pida `con_subsidio`, con el
  motivo escrito en la evaluacion.
- **La tasa negada manda en todo el calculo**, no solo en el dividendo: amortizacion, pie de
  equilibrio y saldo insoluto para la TIR. Dejar tres de esos a la tasa vieja habria dejado el
  modelo incoherente consigo mismo sin que se notara. Es el bug que casi cometo.
- Caso de oro simetrico: **sin subsidio de por medio, un usado y un nuevo identicos dan
  exactamente lo mismo.** Si difieren, se colo una penalizacion encubierta.
- `params.yml:subsidio_ds1_tramo4` documenta el instrumento con
  `aplicable_a_este_inversionista: false` y la razon, para no re-descubrirlo.
- CLAUDE.md §12 actualizado: la vivienda usada deja de ser exclusion dura.

**Deuda que esto abre.** T-911 (la rebaja DFL2 de contribuciones corre desde la recepcion
municipal; el modelo hoy la aplica sin mirar antiguedad — supuesto optimista sobre el
beneficio de mayor valor presente) · T-912 (de donde salen los avisos de usado; el 403 de
MELI golpea mas fuerte aca) · T-913 (preguntas al banco).

**Estado.** 6 casos de oro nuevos. mypy --strict verde sobre finance/.

**Auto-critica §7.6 — encontro un error material.** La primera version hacia caer al usado a
la tasa PROMEDIO de mercado (3,97%) mientras el nuevo conservaba una tasa de MEJOR CASO
(3,30%): 67 pb de castigo donde la norma quita 60. El mejor caso sin subsidio es 3,39%, a 9 pb.
Entre 9 y 67 pb esta la respuesta a si el usado gana o pierde. Corregido: el `Escenario`
declara `tasa_sin_subsidio` y el par es mejor-caso con mejor-caso. Caso de oro nuevo: perder
el subsidio no puede costar mas de 60 pb. Destapo ademas T-914: las cuatro tasas de params.yml
vienen de bancos y fechas distintas, asi que ninguna resta entre ellas mide el subsidio.

---

## 2026-08-28 · T-914 cerrada con datos del usuario, y un supuesto mio refutado

**Que aporto el usuario.** Tasas de los simuladores de los propios bancos, mismo dia, mismas
condiciones (depto NUEVO UF 3.999, pie 10%, 30 anos):

| Banco | Con subsidio | Sin subsidio | Brecha |
|---|---|---|---|
| BancoEstado | 3,30% | 4,29% | **99 pb** |
| Santander | 3,32% | 4,78% (CAE 5,35) | **146 pb** |

**Que refuto.** El caso de oro que escribi hace una hora afirmaba que "perder el subsidio no
puede costar mas de 60 pb", porque 60 pb son los del Decreto 180. Falso: la brecha real es
99-146 pb. Y ademas el test pasaba por la razon equivocada — comparaba contra un valor fijo en
el fixture, no contra la configuracion. Un test que valida su propio fixture no valida nada.

**Que confirma.** El §2.1 del contrato, textual: el subsidio son 60 pb y *"el resto de la
rebaja que cita la prensa viene del efecto FOGAES sobre el spread del banco"*. Los datos lo
miden: 99 pb menos 60 = 39 pb de FOGAES en BancoEstado; 86 pb en Santander.

**Consecuencia para D-015.** Perder el subsidio cuesta el doble de lo que yo modelaba. Si el
usado ademas pierde FOGAES, cae a 80% de LTV. La pregunta al banco sobre FOGAES en usadas
pasa de importante a decisiva.

**Que se corrigio.**
- `params.yml`: bloque `tasas_pareadas_simulador` con los cuatro valores y su procedencia.
  `tasa_mejor_sin_subsidio` 3,39% -> **4,29%** (era de otro banco y otro producto).
- El caso de oro ahora afirma lo medido y exige que la brecha SUPERE los 60 pb.
- `cli capacidad` usaba el promedio de mercado contra una tasa de mejor caso: mismo error de
  emparejamiento. Ahora muestra tres casos con su LTV y **el pie en pesos** contra el ahorro
  disponible — un ticket mayor con menos LTV es aritmetica correcta y consejo falso si el pie
  no esta en la cuenta.
- Se destapo que `ltv_sin_fogaes: 0.80` estaba en la config **sin que nadie lo usara**: el
  motor permitia pie de 10% sin FOGAES, que la propia config declara imposible. -> T-915.

**Correccion de perfil.** El usuario nunca dijo que quisiera dos viviendas; dos es el tope
legal. `objetivo_unidades: 2` -> `null`, con `tope_legal_unidades: 2` aparte, y el gate deja de
tratar "no declarado" como "quiere el maximo". CLAUDE.md §2.5 corregido.

**Estado.** 216 tests verdes.

---

## 2026-08-28 · T-916 · Auditoria del proyecto anterior del usuario

**Que llego.** 3.036 lineas de Python y 3,2 GB de HTML de Portal Inmobiliario scrapeado entre
el 30-abr y el 5-may de 2026. Detalle completo en `docs/adr/004-legado-investop.md`.

**Incidente de seguridad, primero.** El filtro de PowerShell que YO escribi incluia `.html` y
`.json`, y barrio 3,2 GB de paginas scrapeadas y un `storage_state` de Playwright con 25
cookies de sesion de Portal Inmobiliario, todo a un repo PUBLICO de GitHub. Se le pidio al
usuario borrar el repo y cerrar sesiones. La copia local quedo clonada, no se perdio nada.
Leccion: filtrar por extension no separa codigo de datos. Para la proxima, lista blanca de
rutas, no de extensiones.

**No era Apify.** El usuario recordaba mal: cero referencias en todo el repo. Es Playwright con
perfil persistente autenticado con su cuenta de MercadoLibre.

**Lo medido** (parser heredado corrido sobre los 6.229 archivos): 6.180 parseables, **5.870
unidades unicas** (2.629 arriendo, 3.240 venta). Cobertura 100% en precio, m2, dormitorios,
banos y comuna; 99,3% microzona; 82% antiguedad; 77% gastos comunes.

**Los hallazgos que cambian el plan:**

1. **La ruta permitida alcanza para el usado.** Las paginas `_Desde_` —las que el robots.txt
   SI permite— traen 38 de 48 tarjetas como unidades individuales con precio exacto,
   dormitorios, banos, m2 y barrio. Para stock usado **no hace falta invocar D-016**.
2. **El DFL2 no esta en los avisos: 16 de 5.870, el 0,3%.** `exigir_dfl2: true` como exclusion
   dura vaciaria el ranking. Confirma el §2.5 al pie de la letra. -> T-917.
3. **El delta de precios de 4 meses es lo irrepetible.** Un aviso desaparece al venderse; esa
   foto no se vuelve a tomar. -> T-919.
4. **El codigo viejo resolvia T-911**: aplica la rebaja DFL2 de contribuciones solo si
   `antiguedad < 20`. El motor nuevo no hace esa distincion.
5. **Usa evasion**: UA de Chrome falso y `--disable-blink-features=AutomationControlled`, y
   scrapea autenticado. D-016 no lo cubre, y lo que se arriesga no es una IP: es su cuenta.
6. **La UF estaba hardcodeada en 38.000.** Hoy esta en ~40.800: 7% de error silencioso en cada
   arriendo publicado en UF.

**Gate de comparables:** 59 de 81 microzonas llegan a n>=8 de arriendo (73%). Por
(microzona, dormitorios): 93 de 256 (36%), cubriendo 2.136 unidades. Piso real donde hoy hay cero.

**Abre** T-917, T-918, T-919, T-920.

---

## 2026-08-29 · T-918 · La foto de mayo entra a la base

**Que se hizo.** Colector `portal_legado_2026_05`: ingiere los 6.229 HTML del proyecto
anterior a la zona cruda, anonimizando antes de escribir, y carga microzonas, ventas y
comparables. Comando `cli ingerir-legado`. `rebuild --from-raw` lo reconstruye entero.

**Resultado.** 6.180 documentos a la zona cruda (745 MB comprimidos) · 6.038 parseados
(97,7%) · **2.701 unidades de venta, 2.850 comparables de arriendo, 84 microzonas, 7 comunas**
· procedencia 100% en ambas tablas · 264 tests verdes · `make gates` VERDE.

**Cuatro bugs que aparecieron y que valen mas que el colector:**

1. **`a_decimal("35 - 61 m2")` devolvia 3.561 m2.** Los avisos de proyecto publican rangos, y
   la funcion borraba lo que no fuera digito y pegaba lo que quedaba. Un depto de 3.561 m2 no
   lo pilla nadie mirando un ranking, y contamina la mediana de su microzona para siempre.
   Es la misma familia del error de mil veces del colector CMF. Ahora un rango es ND.
2. **El gate de datos personales daba 6.443 falsos positivos.** `MLC-3939132164` contiene
   `939132164`, que calza con el formato de celular chileno. El patron no tenia anclaje por
   la izquierda. Un gate que grita en falso se termina desactivando, y ese es el peor final
   posible para el gate que implementa la Ley 21.719.
3. **Un dato personal REAL que el gate si encontro:** un vendedor escribio su celular en el
   TITULO del aviso, y el titulo va en la URL, y la URL es una de las seis columnas de
   procedencia. Anonimizar el HTML no alcanzaba. Ahora la URL se recorta a su forma canonica
   por ID cuando trae contacto.
4. **El mismo aviso capturado el 4 y el 5 de mayo se contaba como duplicado.** No lo es: es
   SCD tipo 2, que el §11 pide justamente para responder "cuando bajo el precio". El cargador
   ahora abre version nueva solo si el precio cambio, cierra la anterior, y no deja que una
   captura mas vieja pise el presente.

**Decision de diseno que quedo escrita.** El §3.6 (zona cruda inmutable) y el §3.4 (cero datos
personales) chocan. Gana el §3.4: es obligacion legal, y lo que se borra son campos que el
parser nunca lee, asi que la reconstruccion queda intacta.

**Lo que esto desbloquea.** T-013 (microzonas) ya no depende de la API caida de MELI: hay 84
barrios reales con el nombre que usa el portal. T-919 tiene su linea base de precios.
`tests/integration/` dejo de estar vacio con 6 fichas reales y 20 tests.

---

## 2026-08-29 · T-920 · Colector vivo, por la puerta que si esta abierta

**Que se hizo.** `portal_busqueda`: recolecta Portal Inmobiliario usando **solo** las rutas
`_Desde_` que el `robots.txt` permite. Reemplaza al scraper heredado. `docs/adr/005`.

**Lo que cambia respecto del legado, que es el punto de la tarea:**

| | legado | este |
|---|---|---|
| ruta | fichas `/MLC-` (prohibidas) | listados `_Desde_` (permitidas) |
| identidad | UA de Chrome falso | el UA declarado de Flujo Cero |
| navegador | `--disable-blink-features` | ninguno: httpx a secas |
| sesion | autenticado con la cuenta del usuario | anonimo |
| moneda | float, UF fija en 38.000 | Decimal, sin conversion en el parser |
| procedencia | ninguna | las seis columnas |

El constructor **rechaza** cualquier User-Agent que contenga "Mozilla": disfrazarse no es un
detalle de configuracion que se pueda dejar a mano. Un 403 levanta `Bloqueado` y detiene la
corrida; no hay segundo intento por otra via.

**Verificado contra las 130 paginas reales del corpus, no contra fixtures inventadas:**
6.076 tarjetas parseadas, 5.608 unidades y 468 proyectos. microzona 99,8%, m2 99,3% sobre
unidades, dormitorios 98,9%.

**Detalle que no es cosmetico.** La pagina 1 se pide con `_Desde_1`. El portal la sirve sin
sufijo, pero esa forma no calza con `/*_Desde_` y quedaria fuera de lo permitido. Devuelve lo
mismo. Elegir la URL permitida cuando existe una equivalente no cuesta nada.

**Refactor que salio de aca.** `portal_comun`: anonimizacion, numeros chilenos, slugs y el
cargador SCD tipo 2, compartidos por el colector historico y el vivo. Tener el versionado
duplicado seria peor que tenerlo lejos: se corrige una copia y el error queda escondido en la
que nadie mira. Efecto colateral util: la primera corrida real cruza contra la foto de mayo y
produce el delta de T-919 **sin codigo adicional**, porque la unidad que bajo de precio abre
version nueva y la anterior se cierra sola.

**Lo que falta y por que.** La primera corrida real. Dos cosas solo se miden contra el portal
vivo desde IP chilena: si el listado exige JavaScript (las 130 paginas del corpus se
capturaron con Playwright, asi que no prueban que un GET simple alcance) y si el portal acepta
a un cliente honesto sin sesion. Si vuelve una cascara sin tarjetas, el selftest falla con
"ninguna tarjeta parseo" y ahi se justifica Playwright en el ADR, no antes.

---

## 2026-08-29 · T-920 corrida real, y T-919 · el delta

**La corrida del usuario respondio las dos incognitas del ADR-005, y las dos a favor:**

```
✓ robots.txt: permitido por robots.txt
✓ 12 paginas, 571 avisos
✓ 552 filas nuevas o versionadas
✓ selftest: precio 100% · m2 99,8% · dormitorios 99,1% · comuna 100% · microzona 100%
```

1. **No necesita JavaScript.** `httpx` a secas trae el listado completo. Playwright no se
   justifica y no se agrega: el §5 lo admite solo cuando el ADR de la fuente lo justifica.
2. **El portal acepta un cliente anonimo y honesto.** HTTP 200 sin sesion, sin UA de navegador
   y sin banderas de evasion. Todo el disfraz del scraper anterior era innecesario para esta
   ruta, y arriesgaba la cuenta de MercadoLibre del usuario a cambio de nada.

**T-919: `quality/delta.py` + `cli delta`.** Cruza las versiones que el SCD tipo 2 ya guarda y
reporta cinco categorias. No hizo falta codigo de recoleccion: el cargador compartido ya
versionaba.

**Dos decisiones que costaron un bug cada una:**

- **La clasificacion va por fechas, no por `source_id`.** Cuando una unidad sigue publicada al
  mismo precio, el cargador actualiza su procedencia a la captura de hoy —dejarla apuntando al
  blob de mayo diria que la evidencia de esa fila es un documento viejo—. Clasificar por fuente
  habria dicho que esa unidad desaparecio, exactamente lo contrario de lo que paso.
- **Una unidad que bajo de precio se contaba TAMBIEN como nueva**, porque su version vigente
  nace hoy igual que la de un aviso nuevo. Lo que las separa es tener una version cerrada
  detras. Sin ese filtro, el universo se infla con unidades que ya estaban.

**Hueco que aparecio al escribir la consulta (T-921).** `fact_unidad_venta` **no tenia
`microzona_id`**. Sin ella no hay yield: el arriendo comparable esta indexado por microzona y
no habia por donde cruzarlos. Se llegaba a la comuna via `dim_proyecto`, que solo existe para
obra nueva; un usado de portal no tiene proyecto. Corregido con migracion idempotente.
Verificado: 2.607 de 2.701 ventas con microzona, 83 distintas, y el cruce ya devuelve filas
—san-miguel/el-llano con 152 ventas y 111 arriendos, por ejemplo—.

**Correccion tras la corrida del usuario (29-ago-2026).** Su salida destapo dos defectos:

1. **`microzona_id` no se escribia en las ramas de UPDATE, solo en el INSERT.** Una columna
   agregada despues queda NULL para siempre en las filas que ya existian: la fila se
   "actualiza" en cada corrida y nunca se llena. Sus 552 filas de la primera corrida quedaron
   asi. Corregido en las dos ramas, con caso de oro que simula exactamente ese escenario.
2. **El `delta` imprimia un informe con numeros cuando no habia con que comparar.** Con una
   sola captura cargada, "266 nuevas" es una tautologia: son todas las que hay, no unidades
   que aparecieron. Ahora lo dice y explica como conseguir la foto anterior. Un informe que
   parece significativo y no lo es se lee como 266 oportunidades.

---

## 2026-08-29 · D-017 · Tres respuestas del banco, y la deuda mas alta se cierra

**La que mas movio el modelo: el FOGAES cubre solo primera venta.** Un usado no accede, y el
banco le exige 20% o 30% de pie. No es un detalle de tasa: **es el doble de plata sobre la
mesa**, y modelarlo con 10% habria producido oportunidades que ningun banco financiaria.

Sobre el mismo depto de UF 3.000, aislando solo la penalizacion de financiamiento:

| | tasa | pie | capital UF | costo de tenencia |
|---|---|---|---|---|
| nuevo | 3,30% | 10% | 340 | -1,23 UF/mes |
| usado | 4,29% | 20% | 638 | -2,28 UF/mes |

Eso NO dice que el usado pierda: dice cuanto tiene que ganar por el lado del arriendo para dar
vuelta la cuenta. La ventaja de yield del usado depende de T-023, que todavia no esta.

**T-915 cerrada.** `Escenario.con_fogaes` separado de `con_subsidio`; `fogaes_aplicable()` como
condicion del INMUEBLE igual que el subsidio; y el pie efectivo pasa a ser
`max(pie_deseado, pie_minimo_exigido)`. El capital invertido y el cash-on-cash van sobre el pie
efectivo: con el deseado, el retorno de un usado salia **inflado al doble**.

**Un caso de oro que resulto estar mal, y la correccion importa.** Afirmaba que "sin subsidio,
un usado y un nuevo identicos dan lo mismo". Falso: sin subsidio el nuevo TODAVIA accede a
FOGAES y el usado no, asi que uno financia 90% y el otro 80%. Reescrito como "sin subsidio NI
FOGAES son identicos", que es el invariante que de verdad protege contra penalizaciones
encubiertas.

**D-009 cerrada:** la tasa es plana entre tramos. Apuntar a <= UF 3.000 no da mejor tasa. Sigue
dando menor dividendo, pero eso el motor ya lo calculaba; no era una ventaja de tasa.

**La tercera respuesta NO se acepto como verificada.** Afirma un limite de una unidad por
persona por el requisito de "primera vivienda". Queda en `evidence: C` porque llego sin fuente
primaria —las otras dos traian enlaces— y porque contradice el Decreto 180 art. 3, que ata el
tramo general a la *primera VENTA de la vivienda*, condicion del inmueble. Que el art. 4 exija
explicitamente primera vivienda del solicitante para el tramo <= UF 3.000 sugiere que el art. 3
no lo hace: si lo hiciera, el art. 4 sobraria. No bloquea nada: el inversionista no declaro
querer dos unidades, y la segunda correria `sin_subsidio`, que es el supuesto conservador.

**Tambien se corrigio `cli capacidad`**, que ofrecia "solo FOGAES (usado?)" como escenario. Ya
sabemos que ese caso no existe. Las tres lineas ahora son casos reales.

---

## 2026-08-29 · Dos bugs que solo aparecen con dos fotos de verdad

La corrida del usuario cargo la foto de mayo DESPUES de haber recolectado agosto, y el informe
salio con **cero cambios de precio, cero confirmadas y 2.691 desapariciones**. Los tres
numeros estaban mal, por dos causas distintas.

**1. El orden de carga decidia el resultado.** Cuando llegaba una captura mas vieja que la
version vigente, el cargador hacia `return 0` con el comentario "no reescribe el presente".
La intencion era correcta y la accion no: **tiraba la historia**. Toda unidad presente en las
dos fotos perdia su version de mayo, y por eso ningun cambio de precio podia detectarse.

Ahora se rellena hacia atras, con dos casos que no son lo mismo:
- **mismo precio** -> se retrocede el `valid_from` de la version vigente. Ya estaba a ese
  precio en mayo: no hay dos versiones, hay una que empezo antes. Crear una nueva inventaria
  un cambio que nunca ocurrio.
- **precio distinto** -> version cerrada `[fecha_vieja, valid_from_actual)`.

Caso de oro nuevo: cargar mayo->agosto y agosto->mayo tiene que dar tablas **byte a byte
identicas**. Un almacen versionado no puede depender del orden de carga.

**2. "Ya no estan" medía el alcance de la corrida, no el mercado.** El usuario recolecto tres
comunas y dos paginas de cada una; la foto de mayo tiene seis comunas paginadas completas.
Las 2.691 unidades que "desaparecieron" en su mayoria simplemente **no se volvieron a mirar**.

Ahora el cruce se limita a las microzonas que la captura nueva efectivamente toco, y las
demas se reportan aparte como `fuera_de_alcance`, con el texto que dice que no desaparecieron.
Un numero que mide el alcance de la corrida disfrazado de senal de mercado es peor que no
tener el numero: se lee como ventas.

**Un caso de oro que estaba mal.** Exigia que una captura vieja **no dejara rastro**. Eso era
exactamente el bug. Reescrito: el presente no se toca, y el pasado si se guarda.

---

## 2026-08-29 · El portal publica dos precios para el mismo aviso

Verificando por que el delta encontro un cambio de UF 8.600 a UF 8.100 aparecio algo que no
estaba en ninguna documentacion: **el precio depende de la superficie del portal.**

Medido sobre 2.689 unidades presentes el mismo dia en la tarjeta del listado y en la ficha de
detalle: 2.627 coinciden (97,7%), 14 difieren por truncado de decimales en la tarjeta, y
**48 traen precios realmente distintos**. El peor caso: `MLC-3893367924`, UF 13.000 en la
tarjeta contra UF 15.900 en la ficha — mismo aviso, mismo dia, mismo titulo, mismos 167 m2,
22% de diferencia.

**Consecuencia:** comparar una tarjeta de hoy contra una ficha de mayo inventa cambios de
precio que nunca ocurrieron. La linea base tiene que ser tarjeta contra tarjeta.

**Tres cambios, en orden de importancia:**

1. **`ingerir-legado --busqueda`**: las 130 paginas de LISTADO de mayo que el usuario ya tenia
   en disco entran a la zona cruda parseadas con el colector vivo. Ahi esta la linea base
   correcta: 6.076 tarjetas, 2.974 filas de venta.
2. **Candado entre superficies, asimetrico a proposito.** No se abre version comparando
   tarjeta con ficha. Y cuando las dos existen, **manda la tarjeta**: es la superficie que el
   colector vivo va a seguir viendo corrida tras corrida. Si mandara la ficha, la linea base
   quedaria en una superficie que ya nadie vuelve a leer y el delta no cruzaria nunca.
   Resultado: 2.696 filas en la superficie correcta, cero versiones falsas.
3. **El gate de frescura pasa de FALLA a ALERTA.** El §7.3 prohibe que una fila vieja entre al
   RANKING, no que exista en la base — la linea base historica es vieja por definicion.
   Exonerar por `source_id` funcionaba solo mientras lo viejo y lo fresco vinieran de fuentes
   distintas, y dejo de funcionar en cuanto la misma fuente tuvo las dos cosas. Ahora lo que
   decide es la fecha de cada fila, y las viejas se reportan como excluidas del ranking.

---

## 2026-08-29 · La ingesta cara no hacia falta, y escondia un bug

**El usuario reporto una hora de ingesta para el 20%.** Acá los mismos 6.229 archivos toman
4 minutos: 74 veces mas rapido. La causa razonable es Windows Defender escaneando 3,2 GB de
lecturas y 12.400 archivos nuevos, pero el diagnostico importante fue otro: **esos archivos
no hacen falta para el delta.**

Las 130 paginas de LISTADO son el 2% de los archivos y el 100% de lo que el cruce necesita,
porque son la misma superficie que lee el colector vivo. Las 6.229 fichas de detalle solo
suman antiguedad y gastos comunes, y su precio vive en la otra superficie.

`--origen` pasa a ser opcional. La linea base completa toma **69 segundos**.

**Y al correr esa ruta rapida aparecio un bug que habria roto todo el analisis.** El texto de
ubicacion de la tarjeta es irregular y no hay forma de saber por su forma que parte es que:

    "Milán 1242, El Llano, San Miguel"   -> direccion, barrio, comuna
    "Apoquindo 4900, Barrio El Golf"     -> direccion, barrio        (sin comuna)
    "Barrio Italia"                      -> barrio                   (sin comuna)

Contando desde el final salian **46 comunas donde habia 6**: "El Llano", "Plaza Egaña" y
"Metro Ñuñoa" entraron a `dim_comuna` como si fueran municipios, y 233 microzonas mal armadas.
La microzona es "la unidad de analisis real" del §2.4: con la comuna mal, todo el cruce entre
venta y arriendo se desarma en silencio.

**La comuna verdadera siempre estuvo a mano: es el filtro que el propio portal aplico**, en la
URL (`san-miguel-metropolitana`). Ahora la comuna sale de ahi —dato duro— y el barrio es la
ultima parte del texto que no sea la comuna. Si lo que queda tiene numeros es una calle, y no
se inventa un barrio.

Resultado: **6 comunas, 165 microzonas, 62 con n>=8 comparables de arriendo.**

---

## 2026-08-29 · El primer delta real, y dos cosas que el numero todavia no decia

La corrida del usuario cruzo por fin las dos fotos: **26 bajadas de precio, 3 alzas, 5 sin
cambio**, con caidas de hasta 12,7% en cuatro meses. Esa parte es observacion directa de la
misma unidad dos veces y es confiable.

**Lo que no era confiable: las 852 "ya no estan".** Recolecto 20 paginas contra una foto
paginada completa, asi que la mayoria de esas unidades sigue publicada — en una pagina que
nadie pidio. Scoping por microzona no alcanzaba: hay que mirar la cobertura DENTRO de cada
microzona. Ahora el informe compara cuantas unidades tenia la foto vieja en el alcance contra
cuantas trajo la corrida nueva, y cuando cae bajo el 90% marca el numero como POCO FIABLE con
la razon y el remedio. Un numero que se lee como ventas y no lo es era el peor de los dos.

**Y aparecio una microzona invertida en su salida: `estadio-nacional/nunoa`.** Es una fila
vieja, parseada antes del arreglo de comuna: confirma que el texto de la tarjeta a veces pone
el barrio al final. `rebuild --from-raw` la normaliza, porque re-parsea con el parser nuevo.

Se agrego **UF/m2** a cada linea del listado: sin eso, "bajo 12,7%" no se puede comparar
contra nada. Con eso se ve al instante si el precio nuevo es caro o barato para su microzona.

---

## 2026-08-29 · T-023 · La mediana de arriendo, que es el numerador de todo

`src/flujocero/agg/arriendo.py` + `cli agregar-arriendo`. El yield bruto sale de
`arriendo_mediano x 12 / precio`, y ese arriendo se calcula aca.

**Tres decisiones que gobiernan el modulo:**

1. **La clave es `(microzona, tipologia, rango_m2)`, nunca la comuna.** El §2.4 lo fija con
   evidencia: dentro de Estacion Central el mismo producto renta ~$300.000 en una calle y
   ~$350.000 a pocas cuadras. Agregar por comuna promedia dos mercados distintos y produce un
   yield que no existe en ninguna de las dos calles. Los rangos de m2 quedan en `params.yml`
   con el tope en 140, que no es arbitrario: sobre eso se pierde el DFL2.
2. **La conversion a UF usa la UF del DIA DE CADA AVISO.** Un arriendo de mayo se convierte
   con la UF de mayo. Con la de hoy se mezclaria el movimiento de la UF con el del mercado,
   que es justo lo que el §3.3 manda separar trabajando en terminos reales. Si falta la UF de
   ese dia se retrocede hasta siete dias y no mas; despues, la fila se descarta.
3. **Mediana, no promedio**, con p25 y p75 al lado. Un aviso mal parseado mueve un promedio y
   no mueve una mediana. La `dispersion` = (p75-p25)/mediana delata un rango que esconde dos
   mercados.

**Los descartes se cuentan por motivo y se muestran.** En esta maquina: 2.201 de 2.835 quedan
fuera por `sin_uf_del_dia`, porque la serie de la CMF esta cargada en la maquina del usuario y
no aca. El numero hace visible de inmediato que falta un insumo, en vez de producir una
mediana sobre el 16% de los datos sin decirlo.

**20 casos de oro**, incluido el que compara mediana contra promedio ante un outlier.

---

## 2026-08-29 · Deuda pagada antes de T-029: las dos que lo bloqueaban

**Auditoria previa.** Cero TODO/FIXME reales en el codigo, un solo `skipif` legitimo (el
corpus del legado no esta en toda maquina), todos los modulos con tests propios. La deuda
acumulada es la declarada en el backlog, no cruft escondido.

De la lista, dos bloqueaban T-029 y se pagaron:

**T-917 · el DFL2 pasa a TRI-ESTADO.** Medido sobre 5.870 avisos: 16 mencionan DFL2, el 0,3%
— y no porque no lo sean, sino porque el aviso no lo dice. Con un booleano, `exigir_dfl2`
vaciaba el ranking entero. Ahora `acogida_dfl2: bool | None`, y la exclusion dura solo alcanza
a lo que se sabe que NO es DFL2. Un `None` **compite pero se evalua SIN el beneficio**: la
asimetria va a proposito hacia no mostrar nunca una oportunidad mejor de lo que se puede
probar. Si despues resulta ser DFL2, los numeros solo mejoran.

**T-911 · la ventana de contribuciones se agota.** La rebaja del 50% no es perpetua: corre
desde la recepcion municipal y dura mas mientras mas chica la vivienda (20 anios hasta 70 m2,
15 hasta 100, 10 hasta 140). El motor se la aplicaba a TODOS, que era un supuesto optimista
justo sobre el beneficio que el §2.5 declara de mayor valor presente. Los tramos quedan en
`params.yml` con evidencia `C`: vienen de la practica del rubro y hay que verificarlos en el
DFL2 art. 14 antes de subirlos a `V`.

De paso quedaron separados los DOS beneficios del DFL2, que se aplicaban juntos: la exencion
de renta vale mientras la vivienda este acogida; la rebaja de contribuciones, solo mientras su
ventana siga abierta. Tratarlos como uno regalaba la rebaja a un usado de veinte anios.

**Lo que NO se pudo pagar y por que:** T-907 (fuente vigente de tasas por banco) necesita una
fuente externa que todavia no existe; T-909 (fixture real de la CMF) necesita un archivo de la
maquina del usuario; T-014 y T-022 son colectores nuevos, no deuda.

11 casos de oro nuevos.

---

## 2026-08-29 · El pipeline se valido contra una fuente externa, y coincidio

Con la serie de UF cargada, la corrida del usuario dio **4.681 de 4.915 comparables
utilizables (95%)**, **721 celdas** y **115 con n>=8**. Mi advertencia de que "la mayoria no
va a rankear" era pesimista por un factor grande: estaba mirando el 12% de los datos.

**Y aparecio el gate que estaba escrito y nadie llamaba.** El §7.3 pide reconciliar nuestra
mediana de arriendo contra la tabla publicada por Colliers/Assetplan (Emol 2-abr-2026), y la
funcion existia desde el principio sin que ningun comando le pasara datos. Ahora corre dentro
de `agregar-arriendo`, que es donde nacen las medianas.

**El resultado es la mejor senal que tuvo el proyecto hasta ahora:**

| comuna | nuestro UF/m2 | publicado | desviacion |
|---|---|---|---|
| San Miguel | 0,240 | 0,24 | **0,0%** |
| Ñuñoa | 0,280 | 0,30 | −6,7% |

Nuestra mediana sale de miles de avisos crudos, parseados por nosotros y convertidos uno a uno
con la UF de su dia. La referencia la publico un tercero con otra metodologia. Que coincidan a
menos de 7% hace muy improbable que las dos esten mal de la misma forma.

Se uso la columna **"retail / particular"** y no la multifamily: el inversionista es un
arrendador individual y las dos columnas difieren hasta 26%.

**El check tambien demostro que sirve.** En esta maquina, con solo los arriendos publicados en
UF —una muestra sesgada a lujo— Las Condes salio en 0,52 contra 0,35 publicado, +50%, y el
gate lo marco. Detectar una muestra sesgada es exactamente para lo que esta.

**Correccion de tamano de muestra, medida.** Las medianas de las celdas que antes tenian n=8
se movieron al crecer: Estadio Nacional 2D2B de 0,285 a 0,262 UF/m2 (-8,1%) con n=123, y 1D1B
de 0,326 a 0,280 (-14,1%) con n=121. El umbral de 8 del §7.3 es un minimo, no un objetivo.

---

## 2026-08-29 · T-029 · El puente. El motor corre por primera vez sobre datos reales

`src/flujocero/agg/oportunidades.py` + `cli oportunidades`. Hasta hoy el motor financiero solo
habia corrido sobre departamentos inventados por `demo`.

**La regla de emparejamiento es `(microzona, tipologia, rango_m2)`, y NO hay caida a comuna.**
Si una unidad no tiene su celda con 8 comparables, no se rankea. Prestarle la mediana de la
comuna seria exactamente lo que el §2.4 prohibe: dentro de una comuna hay 17% de brecha a
pocas cuadras, mas que entre dos comunas distintas. Es la regla que mas unidades bota y es la
correcta.

**Dos cosas que el comando dice y que no son cosmeticas:**

1. **Que parte del score esta INERTE.** `riesgo_microzona` (15%) y `catalizador` (10%) no
   tienen fuente todavia —falta el Censo y las distancias a Metro, T-014—. Al valer todos lo
   mismo, la normalizacion los vuelve constante: reparten identico puntaje y no mueven una
   sola posicion del ranking. **El 25% del score esta muerto y el comando lo declara.** Un
   score que se presenta como completo cuando un cuarto de su peso no diferencia nada miente
   por omision.
2. **Las exclusiones agrupadas por REGLA, no por unidad.** "26 excluidas" obliga a adivinar si
   el filtro trabaja o se come el universo; "19 sobre el tope de UF 6.000 y 7 sobre el tope de
   deficit" se lee solo.

**Corrida en esta maquina:** 2.380 unidades con precio verificado, 26 emparejadas, 0
sobrevivientes — 19 pasan de UF 6.000 y 7 exceden el tope de deficit. Las exclusiones son
correctas; el universo local es el problema, porque aca solo estan los arriendos publicados en
UF, que sesgan a Las Condes. En la maquina del usuario hay 115 celdas cubriendo San Miguel y
Ñuñoa, que es donde vive su ticket.

El DFL2 llega como `None` —por verificar— y no como negativo: el portal lo declara en 16 de
5.870 avisos, y marcarlo `False` vaciaria el ranking mientras que marcarlo `True` regalaria un
beneficio sin probar.

12 casos de oro nuevos.

---

## 2026-08-29 · El primer ranking real, y tres cosas que escondia

**1.166 unidades rankeadas** en la maquina del usuario, de 4.203 con precio verificado. Las
1.648 que quedaron fuera por `sin_comparables` son la regla del §2.4 haciendo su trabajo: sin
celda de arriendo propia no se rankea, y no hay caida a comuna.

Mirando la salida aparecieron tres problemas.

**1. El encabezado mentia sobre la plata.** Decia "Escenario: pie 10% · con subsidio", que es
lo PEDIDO. Pero casi todas esas unidades son usadas, y a un usado el motor le niega el subsidio
y el FOGAES y le exige **20% de pie**. Los numeros ya estaban bien —se verifico que el
$34.035 de la primera fila calza con el caso usado y no con el nuevo— pero el titulo anunciaba
la mitad del pie real. Ahora se imprimen las dos cosas: lo pedido y lo aplicado, con el conteo
de cuantas recibieron cada beneficio, y el pie efectivo va como columna por unidad.

**2. El mismo departamento ocupaba dos lugares del top.** `MLC-2076401873` y `MLC-1981549115`,
identicos en UF 1.200 y 57,1 UF/m2. Dos corredores publican el mismo depto y cada uno tiene su
`MLC-`, asi que la clave natural del §7.3 —(proyecto_id, numero_unidad)— no los agarra: ninguno
de esos dos campos existe en un aviso de portal. Se colapsa por la firma que el §7.3 ya usa
para arriendo: mismo barrio, tipologia, m2 y precio. Se colapsa **para el ranking**; en la
tabla siguen los dos, porque el dato crudo no se toca.

**3. El top esta dominado por micro-unidades y eso hay que decirlo.** La primera fila es de
23 m2 a UF 890 con 10,24% de yield. El §13.3 advierte exactamente de esto: los retornos de dos
digitos del mercado chileno **son stock usado chico y barato**. Alto yield bruto no es lo mismo
que buena inversion — una unidad de 25 m2 tiene mas rotacion, mas vacancia, gastos comunes mas
altos por m2 y mucha menos liquidez de salida, y el ranking no mide nada de eso. Se agrego un
aviso que salta cuando un tercio o mas del top esta bajo 35 m2.

**Lo que el ranking SI dice, y es un hallazgo.** El §2.3 del contrato afirma que el pie de
equilibrio en el Gran Santiago esta en 34-47%. Estas unidades salen con pie de flujo cero de
**17-20%**, y la primera en **-7%** (se paga sola). El contrato tenia razon para el stock NUEVO
que era su alcance original; abrir a usado (D-015) cambio ese piso. No invalida el hallazgo:
lo acota.

---

## 2026-08-29 · La metrica insignia del producto estaba optimista, y por mucho

Mirando el primer ranking real aparecio una contradiccion en la misma fila:
`MLC-1933353711` marcaba pie de flujo cero **17%**, estaba puesta al **20%**, y aun asi
costaba **-$3.380 al mes**. Dos numeros lado a lado que se desmentian.

**La causa.** `pie_minimo_flujo_cero` es la forma cerrada `1 - (1-opex)·yield/factor`, que
parte del yield **BRUTO**: ignora la vacancia, la incobrabilidad, la erosion intra-anual del
§3.3 y los seguros que el banco cobra junto al dividendo. Todo eso empeora el flujo, asi que
la forma cerrada **subestima sistematicamente el pie necesario**.

**Cuanto.** Medido por biseccion sobre el modelo completo, en unidades reales del ranking:

| unidad | forma cerrada | REAL | diferencia |
|---|---|---|---|
| MLC-3907646442 | -6% | 24% | +30 pts |
| MLC-1933353711 | 18% | 43% | +25 pts |
| MLC-1948762123 | 20% | 44% | +24 pts |
| MLC-4125847944 | 20% | 44% | +24 pts |

Y esos 43-44% caen exactamente dentro del **34-47% que el §2.3 del contrato predecia**. O sea:
el contrato tenia razon y yo le dije al usuario lo contrario hace una hora, apoyado en la
metrica sesgada. **Correccion entregada.**

**Que se hizo.** `pie_flujo_cero_real()` busca por biseccion el pie donde el flujo del modelo
completo cruza cero — el mismo modelo que produce el resto de la fila, para que lo mostrado
sea internamente coherente. `core.pie_minimo_flujo_cero` se conserva intacta: esta anclada por
el §7.2 contra la literatura y sirve para comparar con cifras publicadas, pero deja de ser lo
que se muestra y lo que rankea.

El score tambien pasa a usar la real. Rankear con la cerrada ordenaba el **20% del score** por
una metrica sesgada, y ademas de forma desigual: subestima mas donde la vacancia y el opex
pesan mas. Cuesta ~90 s sobre 1.000 unidades y los vale.

**El hallazgo grande, que sale de la misma medicion.** Con DFL2 **confirmado**, esa misma
unidad pasa de 44% a **0%** de pie de flujo cero: se paga sola. Toda la diferencia es el
impuesto a la renta sobre el arriendo, UF 37,8 al ano. El §2.5 dice que el DFL2 vale mas que
el subsidio en valor presente; esto lo cuantifica. Y como el portal declara DFL2 en el 0,3% de
los avisos, **el ranking de hoy es sistematicamente pesimista justo en la dimension que mas
importa**. Verificar el DFL2 en la escritura pasa a ser la accion de mayor valor del proyecto.

---

## 2026-08-29 · T-908 · La UF tenia una sola fuente, y esa fuente esta medida como inestable

Sin el valor de la UF no se convierte ni un arriendo publicado en pesos, y el **83% de los
avisos de arriendo se publican en pesos**. La serie de UF es el unico dato del que depende,
literalmente, todo lo demas — y hasta hoy venia de una sola API que `cli probe` midio
cortando la conexion al azar el 28-ago: la misma URL de 32 meses fallo y minutos despues
devolvio 974 registros.

Se agrego **Gael Cloud como respaldo** (ADR 006). Cuatro decisiones que no son de estilo:

**1. El respaldo NUNCA pisa a la fuente primaria.** `gael_indicadores.cargar_en_duckdb` hace
`ON CONFLICT DO NOTHING`; el de la CMF hace `DO UPDATE`. Una fuente de respaldo que
sobrescribe a la primaria convierte **una caida pasajera de la CMF en un cambio permanente
de los datos**, sin que nadie lo pida y sin que quede rastro. Efecto lateral bueno: como el
respaldo solo inserta si falta y la primaria sobrescribe siempre, la CMF gana venga en el
orden que venga, y eso hace que `make rebuild --from-raw` sea determinista sin ordenar las
fuentes. Hay test.

**2. Una discrepancia entre fuentes se reporta, no se resuelve.** Si las dos tienen el mismo
`(fecha, serie)` y no coinciden mas alla del redondeo, sale una `Discrepancia` en pantalla y
la fila que ya estaba no se toca. Dos fuentes oficiales que dicen cosas distintas del mismo
dia es un hallazgo, no algo que un cargador deba decidir solo.

**3. El cupo se respeta del lado del cliente y un 429 no se reintenta nunca.** El limite de
Gael es >9 peticiones en 10 s = **IP baneada una hora**. El limitador frena ANTES de pedir
con cupo 6, no 9, porque no sabemos si el servidor cuenta la ventana igual que nosotros. Y
un 429 corta de inmediato: es la diferencia deliberada con la CMF, donde el corte SI es
transitorio. Reintentar un baneo solo lo prolonga.

**4. Gael NO reemplaza a la CMF para el historico.** El endpoint publico no toma fechas:
entrega el valor vigente. `collect()` **falla** si se le pide un periodo, en vez de devolver
un dia y dejar creer que devolvio treinta. Un hoyo silencioso en la serie es peor que un
error.

**Lo que este colector todavia no puede afirmar.** El egreso hacia `api.gael.cloud` esta
bloqueado en este entorno (comprobado: `EGRESS_BLOCKED`), asi que la forma de la respuesta
viene de documentacion y `forma_verificada` queda en `false`. El parser esta escrito para
**fallar ruidosamente** si la forma difiere, nunca para adivinar: nombres de campo por
niveles de preferencia, formato de miles resuelto por rango de plausibilidad (y rechazado si
las dos lecturas caben), y fecha ambigua rechazada. `05-08-2026` es 5 de agosto en Chile y
8 de mayo en formato gringo, y una UF con tres meses de error corrompe toda conversion de
ese dia sin que se note mirando la tabla.

### Auto-critica §7.6 — cuatro hallazgos sobre codigo mio, uno era un bug

1. **`"1.234.567"` se rechazaba.** La rama de "solo punto" calculaba las dos lecturas
   siempre, y `Decimal("1.234.567")` revienta. Un valor perfectamente legible fallaba porque
   la lectura decimal ni siquiera existe con dos puntos. Corregido: mas de un punto = todos
   son separadores de miles, sin ambiguedad.
2. **La consulta de robots.txt no pasaba por el limitador.** El servidor cuenta TODOS los
   GET. Con 2 series + robots eran 3 peticiones y el contador veia 2. Con cupo 6 sobre un
   limite real de 9 no llegaba a banear, pero un contador que ignora una de cada tres
   peticiones no es un contador.
3. **Una `ValidationError` de pydantic se escapaba del fallback.** Hereda de `ValueError`,
   no de `ErrorDeFuente`, asi que una fila mal formada mataba con traceback justo al
   colector que queda cuando la CMF ya fallo.
4. **La conexion a DuckDB podia quedar abierta** si el fallback reventaba, y el siguiente
   comando no habria podido ni abrir la base. Ahora va en `try/finally`.

Los cuatro con test de regresion.

**Gates:** VERDE. 445 tests (eran 382).

## 2026-08-30 · La corrida viva de Gael cerro la advertencia del ADR 006, y trajo un regalo

`cli ingest --fuente gael_indicadores` desde la maquina del usuario (IP chilena residencial):

```
✓ selftest: {'parseo': True, 'campos_requeridos': True, 'rangos_plausibles': True,
             'conteo_estable': True, 'robots': True, 'forma_verificada': True}
✓ 1 insertadas · 1 ya estaban
```

**1. La forma documentada resulto ser la real.** El parser defensivo no tuvo que rechazar
nada: ni ambiguedad de miles, ni fecha ambigua, ni campos duplicados. Haberlo escrito para
fallar ruidosamente sigue valiendo —es lo que lo hace seguro el dia que Gael cambie el
formato— pero hoy no hizo falta. `forma_verificada` pasa a `true` en fuentes.yml.

**2. El hallazgo que no estaba planificado: las dos fuentes coinciden.** De la serie que se
solapaba con la CMF **no salio ninguna `Discrepancia`**, o sea que los dos valores caen
dentro del 0,01%. Eso es una validacion externa que antes no existia: la UF que usa el
modelo la confirman dos fuentes oficiales independientes, no una sola API inestable. Es el
mismo tipo de evidencia que el 0,0% de desviacion contra Colliers en el arriendo de San
Miguel, y vale por la misma razon: dos caminos distintos que llegan al mismo numero.

**Lo que sigue abierto.** Los tests de Gael corren contra una fixture reconstruida desde
documentacion, igual que los de la CMF (T-909). El blob real ya existe en la maquina del
usuario, en `data/raw/gael_indicadores/2026/08/30/`. Convertirlo en fixture es lo unico que
falta para cerrar la deuda de las dos fuentes de indicadores a la vez.

---

## 2026-08-30 · Las fixtures reales cerraron T-909 y destaparon dos cosas que no buscabamos

El usuario subio al repo los blobs reales: tres tramos de UF de la CMF (28-ago) y las dos
respuestas de Gael (30-ago), con sus `.meta.json` y el snapshot de robots. Se pueden
versionar porque `base.ocultar_secreto` reemplaza la apikey por `apikey=OCULTA` ANTES de
persistir — hay test que lo fija.

**Lo que confirmaron.** CMF: 243 registros solo en 2026, envoltorio `UFs`, `"40.871,14"`.
Gael: `"40871,14"`, fecha `2026-08-29T22:00:03.403Z`. Los dos valores **identicos al peso**,
y eso resolvio un riesgo concreto: Gael fecha con la marca de su refresco diario, no con una
fecha de calendario limpia, asi que si esa marca correspondiera al dia siguiente **toda
conversion de pesos a UF quedaria corrida en un dia**. No lo esta. Ademas cruza dos formatos
distintos —`"40.871,14"` con punto de miles vs `"40871,14"` sin el— por ramas distintas del
parser hasta el mismo Decimal.

### Hallazgo 1 (T-926) · El verificador de robots SUB-BLOQUEABA

Lo destapo una **contraprueba**: puse un test exigiendo que lo que el robots de Gael prohibe
saliera prohibido, y fallo. `/admin/x` salia PERMITIDO teniendo un `Disallow: /admin/*` al
frente.

La causa es el `RobotFileParser` de la libreria estandar: **no implementa comodines**.
Guarda la regla como el literal `/admin/%2A`. Cualquier `Disallow` con `*` o `$` no
bloqueaba nada. Y la direccion del error es la peligrosa: sobre-bloquear molesta,
**sub-bloquear te hace pedir lo que el sitio prohibio**, y el §3.5 es regla dura.

Se escribio `robots_rfc9309.py`: comodines, gana el patron mas largo, empate a favor de
Allow, lineas malformadas ignoradas, grupo de user-agent mas especifico. `robots_check`
ahora corre los dos evaluadores y **toma la conjuncion**: permitido solo si los dos dicen
que si. Sobre-bloquear es el lado seguro del error.

**Impacto medido: ninguna recoleccion pasada violo robots.** El unico robots con comodines
que habiamos evaluado es el de Gael y nunca pedimos esas rutas; el del portal
—`Disallow: /propiedades/`— no usa comodines. Pero hay un matiz que conviene saber: su
`Allow: /*_Desde_`, que es la justificacion documentada del `legal_tier: html_permitido` del
colector del portal, **la stdlib nunca lo leyo**. El permiso venia de que ningun Disallow
calzaba. Ahora el veredicto se sostiene por dos caminos en vez de uno.

De paso: el robots real de Gael trae `Allow /general/public/*` **sin los dos puntos**. Es una
linea malformada y el RFC manda ignorarla, asi que nuestro permiso no depende de ella. Queda
anotado en la fixture porque quien lea el archivo a ojo puede creer lo contrario.

### Hallazgo 2 (T-927) · La UF no es monotona ni lineal, y asumi las dos cosas

Escribiendo tests contra la serie real puse el invariante "la UF nunca baja". **Falso**:
entre el 2026-01-10 y el 2026-02-09 cayo -0,2%, porque el IPC del mes anterior fue negativo.
Lo cambie por "se mueve en tramos lineales". **Tambien falso**: dentro del mismo tramo el
monto diario va de 13,22 a 13,35.

Lo que si se cumple: la UF se recalcula el dia 10 de cada mes con el IPC del mes anterior y
**compone a tasa diaria constante** hasta el 9 del siguiente. La razon entre dias
consecutivos es constante hasta 4e-07, el redondeo al centavo. Con IPC cero queda
EXACTAMENTE plana un mes entero (paso en feb-2026, tramo 10-mar a 09-abr).

Nada en el codigo asumia monotonia —verificado por grep— asi que no hubo bug. Pero queda
fijado por test y es una advertencia para el dashboard: **la UF puede bajar**, y un grafico
que la dibuje siempre creciente miente. Como test ademas es el mas fuerte de los tres que
intente: un valor con los miles mal leidos da una razon de ~1000 en vez de ~1,0003.

**Gates:** VERDE. 492 tests (eran 445).

---

## 2026-08-30 · T-027 · El tablero. Y el E2E encontro un error de diseno que ninguna revision vio

Ya no hay que leer rankings en la consola: `make serve` levanta la API y el tablero en
localhost:8000. Ranking filtrable por pie, comuna, m2 y pie de flujo cero maximo; ficha de
unidad con las seis columnas de procedencia; el motivo textual de cada beneficio que el motor
NEGO; y el desglose del score barra por barra.

### El problema real era el rendimiento, y se resolvio con una propiedad del calculo

El gate §7.5 pide que la pagina cargue en menos de 3 s. Calcular el ranking cuesta **~90 s
sobre mil unidades**, casi todo en la biseccion de T-923. Servir eso por peticion es imposible.

Lo que lo arregla no es un truco de cache: es que **la biseccion no depende del pie pedido**.
Busca el pie donde el flujo cruza cero, asi que mover el control no cambia su resultado. Se
cachea por unidad y el pie deja de costar 90 s. Lo que SI depende —tasa, vacancia, plazo,
DFL2, y los supuestos de params.yml— entra en la firma de la cache, **incluido el hash de los
dos YAML de configuracion**: editar un supuesto la invalida sola, en vez de servir un numero
viejo, que es peor que servirlo lento.

**Trampa que casi entra:** `escenario_id` se construye como `pie20`, `pie40`… o sea que
codifica el pie. Meterlo en la firma habria dado una firma por cada pie y anulado la cache
entera **sin que nada fallara**: solo lenta, para siempre, sin sintoma. Queda fijado por test.

### El E2E encontro lo que yo no

Escribi el test de los 3 s esperando que pasara. Dio **8,08 s**.

La causa no era el test: la pagina mandaba `pie=20%` fijo en el primer request, mientras el
servidor precalcula la foto del pie del PERFIL. O sea que **toda primera carga descartaba la
foto precalculada y re-evaluaba el universo entero**. Medido con 10.000 unidades: 8,1 s
contra 0,3 s. Ahora la primera carga no manda pie y el control se sincroniza con lo que el
servidor uso de verdad.

Es exactamente el tipo de error que una revision de codigo no ve —las dos mitades estaban
bien por separado— y que un gate medido si.

Tambien salto, al levantar el E2E, que Playwright buscaba un build exacto de Chromium
(`chromium_headless_shell-1234`) que este contenedor no tiene, y se **saltaba los 7 tests en
silencio**. Un gate que se salta sin avisar es un gate que no existe. Ahora cae al Chromium
que haya en la maquina.

### Lo que NO se pudo hacer, y no se disimulo

**El mapa del §7.5 no existe.** `dim_microzona.geom` esta vacio en las 165 microzonas y
`fact_unidad_venta` no guarda coordenadas. No hay nada que dibujar.

La tentacion era poner el centroide de la comuna y que se viera completo. No se hizo, y la
razon es del §2.4: **la microzona ES la unidad de analisis de este producto**. Todo el
argumento se apoya en que dentro de Estacion Central el mismo producto renta $300.000 en
Santa Isabel y $350.000 a pocas cuadras. Un mapa que ubique mal una microzona no es un mapa
incompleto: es un mapa que **contradice la tesis del producto mientras aparenta confirmarla**.

En su lugar el tablero dice por que falta, y `/api/microzonas` responde la misma pregunta con
una tabla ordenada por el pie de flujo cero mas bajo. Abierta como T-928, bloqueada por T-014.
El test `test_el_tablero_dice_por_que_no_hay_mapa` esta escrito para FALLAR cuando entre la
geometria, para que nadie se olvide de reemplazarlo.

### Desviacion declarada del §5

El contrato sugiere Alpine.js + MapLibre + Chart.js por CDN. **No se uso ninguna.** El gate
E2E corre en un contenedor sin internet: un tablero que depende de un CDN no se puede testear
ahi, y el gate se saltaria en silencio. Ademas un tablero de decision financiera que se cae
con un CDN ajeno es peor que uno que no se cae. Dos tests fijan la ausencia de dependencias
externas: uno revisa el HTML, otro escucha las peticiones reales del navegador.

Se pierde reactividad declarativa y graficos vistosos —el desglose del score va con barras de
CSS— y se gana que el archivo funciona solo. Se revisa cuando haya mapa, con su ADR.

**Gates:** VERDE. 531 tests (eran 492).

---

## 2026-08-30 · Donde esta el cuello de botella, medido sobre la base real

El usuario corrio `cli faltantes` sobre su base:

```
  3875 unidades con precio verificado · 2227 rankean hoy (57%)
  1648 esperan comparables de arriendo. Conseguir 4135 avisos las desbloquea TODAS.
```

**Correccion primero.** Yo habia dicho "el 86% se cae por sin_comparables". Ese numero salio
de la base PARCIAL de mi contenedor. En la base real es el 43%. El diagnostico de DONDE
estaba el hueco era correcto; la gravedad no. Se lo dije.

**La palanca es mejor de lo que estime.** Las 20 celdas de mayor rendimiento suman ~290
unidades esperando y necesitan **~35 avisos en total**. `nunoa/estadio-nacional 3D2B 70-100`
tiene **30 unidades esperando y le falta UN aviso**. No es una recoleccion grande: es
quirurgica. Nunoa concentra 571 unidades esperando, Providencia 286, Macul 246.

`recolectar-portal --dirigida N` toma las N comunas con mas unidades esperando, recolecta
SOLO arriendo, y al terminar **mide cuantas unidades desbloqueo**. Sin esa medida, "traje 340
avisos" es una metrica de esfuerzo y no de resultado: los 340 pueden haber caido todos en
celdas que ya tenian sus 8 comparables.

El orden es por unidades que esperan, no por avisos que faltan, y hay test: Macul necesita
mas avisos que Nunoa pero rinde menos unidades. Ordenar por esfuerzo en vez de por resultado
manda la corrida al lugar equivocado.

## 2026-08-30 · Exploracion de Assetplan: el robots permite y el HTML no regala nada

```
robots.txt PERMITE: ninguna regla del grupo calza con la ruta
  es un sitemap con 176 URLs; se traen 3
  https://www.assetplan.cl/arriendo/departamento/estacion-central/alto-conde/2933/estudio
    1,015,671 bytes · text/html
    JSON-LD: 1 bloques · @type ['BreadcrumbList']
    hay montos en UF
```

Dos cosas. El motivo del veredicto —"ninguna regla del grupo calza"— es el evaluador RFC de
T-926 razonando bien: el permiso no viene de un `Allow` generico sino de que ningun `Disallow`
cubre esa ruta. Y su robots trae `Disallow: /arriendo/departamento/*/edificio/` con comodin,
que el parser de la stdlib ignoraba.

Lo otro: **1 MB de HTML por ficha y el unico JSON-LD es un `BreadcrumbList`**, o sea inutil.
El dato esta enterrado en el HTML o en un estado de app que el detector no reconocio. No se
escribe el parser hasta ver los bytes — se pidieron como fixture.

---

## 2026-08-30 · El arreglo del alcance se ve, y el top del ranking puede ser un artefacto

**El alcance funciona.** La corrida del usuario despues de T-938:
`fuera_de_alcance: 837` · `microzona_saturada: 188`. Mil veinticinco unidades que antes se
colaban al ranking ya no estan. El ranking quedo en 1.045 contra 1.048 de antes: numero
parecido, composicion distinta.

**Pero las primeras filas son de 18, 21, 22 y 23 m2**, todas emparejadas contra la celda
`0-35 m2`. Se midio si eso es oportunidad o artefacto, sobre 1D1B en esa banda:

```
  17-21 m2   n= 11   $320.000
  22-26 m2   n= 37   $300.000
  27-30 m2   n=145   $334.800
  31-35 m2   n=289   $370.000
  LA BANDA   n=482   $350.000
```

El **60% de los comparables mide 31-35 m2**. La mediana de la banda describe a un depto
grande, y acreditarsela a uno de 22-26 le regala **+17% de arriendo**. Como el arriendo es el
numerador del yield, ese +17% se traslada entero al yield y lo sube en el ranking. Las
primeras filas del top **pueden ser un artefacto del banding**.

Lo que se hizo: `m2_mediana` por celda, el desvio medido por unidad, el aviso en el ranking
con el numero, y `cli bandas` para medir el costo de angostar.

Lo que NO se hizo, a proposito: **no se corrige el arriendo** —inventar un ajuste por m2 es
imputar (§3.2)— y **no se cambian las bandas por mi cuenta**, porque mover `rangos_m2` cambia
el ranking en mas de un 10% de posiciones y el §8.4 manda decidir eso con el humano.

**Bug que salio de paso, y era de los que rompen la base del usuario.** `schema.sql` usa
`CREATE TABLE IF NOT EXISTS`, asi que una base ya creada **nunca recibe una columna nueva**:
el DDL corre sin error y sin efecto, y el primer INSERT que la mencione revienta. Paso con
`m2_mediana` en la base de desarrollo y habria pasado igual en la del usuario. Ahora
`db.migrar()` agrega las columnas nuevas de forma idempotente, con test que simula una base
vieja.

## 2026-08-30 · Assetplan renderizado: +664 KB, pendiente de mirar

`explorar --render` sobre la misma ficha: **1.679.613 bytes contra 1.015.671 del estatico**.
Livewire cargo algo. Los montos visibles siguen siendo `$231.000` y `$45.000`, que son el
`min_price` y el `min_ggcc` del Estudio, o sea los mismos del estatico. Falta mirar el blob
para saber si aparecieron unidades con m2. Pedido al usuario.

---

## 2026-08-30 · D-018: se parte la banda `0-35`. Decidido con numeros, no con intuicion

La corrida del usuario despues de llenar `m2_mediana` dio el numero que faltaba:
**9 de las 20 primeras** estaban mas chicas que el depto tipico de su celda, con desvios de
-15% a -44%. La #1 en -26%; la #3 en -32%; una de 18 m2 en **-44%**.

Y el costo, medido con `cli bandas` sobre datos reales: **34 unidades dejan de rankear**
(de 1.045, un 3%), cero empiezan, y la banda mas heterogenea pasa de mezclar 2,1x de
superficie a 1,5x.

El canje se presento asi y el usuario aprobo: 34 unidades recuperables recolectando, a cambio
de sacar un sesgo sistematico que afectaba a casi la mitad del top. **El sesgo no se promedia**
—va siempre en la misma direccion, infla lo chico— y lo chico es justo lo que quedaba arriba.

Queda un test que impide volver atras: ninguna banda puede mezclar mas del doble de
superficie. La banda `0-35` daba 2,33x contra el m2 minimo que acepta el colector, asi que el
test la rechaza. El invariante vale mas que el valor: alguien puede querer re-ensanchar
mañana para ganar celdas, y ahi el test le recuerda por que no.

**Lo que NO arregla, y esta escrito en la decision:** `0-25` sigue mezclando 17 con 25 m2. El
sesgo baja a la mitad, no desaparece. La solucion de fondo son comparables con superficie
exacta por unidad —lo que Assetplan podria dar si su pagina renderizada trae unidades— y no
medianas de banda.

**Gates:** VERDE.

---

## 2026-08-30 · D-018 aplicada: la que era #1 del ranking era un artefacto

Corrida del usuario despues del cambio de bandas. Antes → despues:

```
  rankeables            1.843 → 1.811   (-32; se habian predicho -34)
  llegan al ranking     1.045 → 1.015
  sesgadas en el top20      9 →     3
  sin_comparables       1.027 → 1.061   (+34: las que perdieron su celda)
```

**Lo que se cayo del top 15**, todas unidades chicas con sesgo grande:

```
  MLC-3907646442   23 m2   yield 10,24%   sesgo -26%   ← era la #1
  MLC-2076401873   21 m2   yield  7,83%   sesgo -32%   ← era la #3
  MLC-1903256663   18 m2   yield  6,88%   sesgo -44%
  MLC-1942658997   18 m2   yield  6,83%   sesgo -44%
```

La #1 tenia **10,24% de yield bruto**, muy por encima de todo lo demas, y estaba emparejada
contra una celda cuyo depto tipico era 26% mas grande. Con la banda partida ya no tiene 8
comparables en `0-25`: su numero no bajo, **se quedo sin forma de medirlo**. Es la distincion
que importa — no descubrimos que era mala, descubrimos que no podiamos evaluarla.

El nuevo tope es 7,97%, y el bloque que lo sigue son unidades de 51 a 70 m2 en
`san-miguel/lo-vial`, comparadas contra celdas de su tamano.

**Lo que quedo**: 3 de 20 siguen sesgadas, ahora en la banda `50-70` con desvios de -15% a
-22%. Es la mitad del problema de antes y vive en otra banda. El aviso del ranking ahora dice
en que banda esta el sesgo restante, en vez de repetir el consejo que ya tomamos.


---

## 2026-08-30 · La celda mas profunda del proyecto no le sirve a nadie

Segunda corrida dirigida: 711 avisos, **+41 unidades** desbloqueadas, celdas utiles de 138 a
154. Rendimiento decreciente contra la anterior (+111 con 710 avisos), y la salida mostraba
por que sin que nadie lo hubiera notado:

```
  Las más profundas:
    nunoa/estadio-nacional   2D2B   50-70 m²  n=124   ← SATURADA. Ninguna unidad rankea ahi.
    nunoa/estadio-nacional   1D1B   35-50 m²  n=122   ← idem
    nunoa/estadio-nacional   1D1B   25-35 m²  n= 88   ← idem
```

**Tres de las diez celdas mas profundas estan en una microzona saturada.** El comando las
presentaba como "nuestro mejor dato" y la recoleccion dirigida —que apunta a NUNOA por
volumen de unidades esperando— sigue trayendo avisos que caen ahi. Es esfuerzo en un callejon
sin salida: por profunda que sea la celda, ninguna unidad de esa microzona va a rankear.

Ahora `agregar-arriendo` separa las celdas que SIRVEN de las que no, con el conteo de
comparables "perdidos" y la razon de cada una.

**Y de paso, dos alertas que eran ruido.** La reconciliacion externa venia disparando por
`las-condes (+49%)` y `providencia (+29%)` en cada corrida. Son justamente las dos comunas
que el §10 excluye. Una alerta que salta por datos que no rankeamos entrena a ignorarla, que
es lo peor que le puede pasar a una alerta. Ahora solo compara comunas en alcance.

**Tercer chequeo vacio de la sesion.** Al filtrar por alcance, sobre la base de desarrollo
quedaron cero comunas comparables y el gate imprimio "✓ medianas dentro de ±25%". Es la
validacion externa mas fuerte del pipeline declarandose verde **sin haber comparado nada**.
Ahora dice "NO SE PUDO CORRER" y cuenta cuantas comunas comparo cuando si corre.

Van tres del mismo tipo en un dia —el aviso de sesgo de m2, la reconciliacion, y este— y el
patron es siempre el mismo: **la ausencia de hallazgos se lee como ausencia de problema**.

---

## 2026-08-30 · Fase 3 estaba en el alcance y era inalcanzable al mismo tiempo

Decision con el usuario: dejar de pulir Santiago y ampliar a fase 3. Al abrirlo aparecieron
**dos bloqueos que nadie habia visto porque nunca se habia intentado**.

**1. `metropolitana` estaba clavado en la URL del colector**, en tres lugares. Cualquier
recoleccion fuera de la RM habria pedido `concepcion-metropolitana`, que no existe.

**2. Peor, y mas silencioso: una ciudad no es una comuna.** `zonas.yml` declaraba fase 3 con
`ciudad: gran-concepcion`, y el alcance la tomaba como si fuera una comuna. O sea que fase 3
estaba **declarada dentro del alcance y era inalcanzable al mismo tiempo**: ninguna unidad
podia calzar con `gran-concepcion` porque no existe como comuna en ningun portal. Gran
Concepcion son cinco comunas; La Serena, dos.

Ahora cada entrada de fase 3 declara sus `comunas` y su `region_slug`, y el alcance las
expande. La extraccion de la comuna desde la URL se ancla contra la lista de regiones
conocidas: partir por el ultimo guion daria `san-pedro-de-la-paz-bio` para
`san-pedro-de-la-paz-bio-bio`.

**Lo que NO se adivino.** El slug de region que usa el portal. Estan en zonas.yml marcados
SIN VERIFICAR, porque un slug malo **no da error**: el portal responde 200 con cero
resultados y una corrida de veinte minutos "funciona" sin traer nada. Es el mismo patron que
viene apareciendo todo el dia —la ausencia de resultados leida como ausencia de problema— asi
que se le puso un comando encima: `probar-comunas` pide UNA pagina por comuna y cuenta
tarjetas antes de gastar la corrida.

**Gates:** VERDE.

## 31-ago-2026 · T-041 · el contador de `cargar_avisos` mentía en arriendo

**Síntoma reportado por el usuario:** corrió `recolectar-portal --fase 3 --paginas 5` dos
veces seguidas. La primera: 2.807 filas. La segunda, sobre los **mismos 3.812 avisos**:
1.911 "filas nuevas o versionadas".

**Causa:** `_cargar_arriendo` devolvía `1` incondicionalmente. Su `INSERT ... ON CONFLICT
(comp_id) DO UPDATE` hace lo correcto con los datos —`comp_id` es clave primaria, no había
un solo duplicado— pero el valor de retorno no distinguía inserción de confirmación.

**Alcance:** solo el contador. Ni una fila mal. `_cargar_venta`, que hace SCD tipo 2, ya
devolvía `0` en sus cuatro caminos de actualización; el bug era exclusivo de arriendo.

**Por qué importa igual:** ese número es el que uno mira para decidir si vale la pena
volver a recolectar una comuna. Inflado, una corrida que no aportó nada se ve productiva.

Es el cuarto caso del mismo día de la misma familia —la m² bias que no se disparaba por
`m2_mediana` NULL, el "ancho relativo máx 35.0x" que dividía por `a or 1`, la
reconciliación externa que imprimía ✓ sobre cero comunas—: **una señal que se lee bien
porque no está midiendo nada**.

**Arreglo:** pre-consulta por `comp_id`, `return 0 if ya_estaba else 1`. Tres tests de
regresión en `tests/unit/test_portal_carga.py`, incluido el que fija que no contar la fila
**no** es dejar de actualizarla (el precio nuevo sí se guarda).

`config/zonas.yml`: se sacaron los tres `SIN VERIFICAR` de los `region_slug` de fase 3.
`probar-comunas --fase 3` dio 8/8 desde IP chilena, 48 tarjetas por comuna.

gates: VERDE — 595 tests, calidad PARCIAL (frescura: 2.696 filas de mayo, línea base
histórica que ya está fuera del ranking por diseño).

## 31-ago-2026 · T-042 · la primera del ranking no era un departamento

El ranking del usuario tenía en el primer lugar a `MLC-1939505225`: **yield 17,58%** contra
7,90% de la segunda, `pie 0%` para flujo cero, tenencia **+$136.405 al mes a favor**. El
único caso de flujo positivo de toda la corrida.

Su URL guarda el título del aviso: `vendo-promesa-con-descuento-de-6-millones`.

No es la venta de un departamento. Es la **cesión de una promesa de compraventa**: alguien
compró en verde, pagó el pie, y vende su posición en el contrato. Los UF 850 son lo que pide
por la cesión — el comprador además hereda el saldo con la inmobiliaria. UF 850 / 0,20 =
UF 4.250, que es un precio normal para un 2D2B de 60 m² en Santiago centro.

**Por qué ninguno de los tres controles que ya existían lo agarró:**

1. `portal_busqueda.plausible` aplica el rango de precio (UF 850 > 500 ✓) y el de superficie
   (60 entre 15 y 400 ✓) **por separado**. El §7.1 declara un tercer rango, `UF/m² entre 20
   y 200`, que es un **cociente** y no un campo: es el único que agarra la fila en la que
   los dos números son plausibles y **no hablan de la misma cosa**.
2. Ese tercer rango sí se verificaba — dentro del `selftest()` de cada fuente, contra ≤5
   documentos vivos. Nunca contra la tabla cargada.
3. `marcar_outliers` debería haberlo marcado (14,2 está bajo el p1=20,5 de su microzona),
   pero **no persiste nada**. Ver T-043.

**Por qué importa mucho más de lo que su conteo sugiere.** Es 1 fila de 2.696. Pero un
ranking por yield ordena por precio bajo, así que **toda fila cuyo precio signifique otra
cosa flota sola hasta el primer lugar**. No queda perdida en el medio del listado: es el
número que el usuario mira primero, y era el único con flujo positivo. Es el §13.3 en ropa
nueva.

**Lo que NO se hizo, a propósito.** No se filtra por la palabra `promesa` en el título: de
9 avisos de cesión de promesa en la base, **8 publican el precio del departamento** (69 a
172 UF/m², de mercado) y solo uno publica el de la cesión. Ese filtro botaría 8 unidades
legítimas para agarrar 1, y sería una heurística de texto disfrazada de regla. El cociente
distingue lo que la palabra no distingue.

Tampoco se descarta al parsear: la fila se conserva en `fact_unidad_venta` con su
procedencia y se excluye en el emparejamiento, con su razón. Una fila descartada al parsear
no se puede mirar después.

**Hallazgo secundario, registrado como T-043:** `marcar_outliers` muta `sospechoso` en un
diccionario que nadie escribe de vuelta. El gate anuncia "161 unidades marcadas" en cada
corrida y la columna sigue en `false` para las 161. Peor: `agg/arriendo.py:205` filtra los
comparables por esa columna —en la consulta que calcula la mediana de arriendo, **el
numerador de todo yield del sistema**— y `marcar_outliers` ni siquiera corre sobre
comparables. Sexto caso de la familia.

gates: VERDE — 610 tests.

## 31-ago-2026 · T-044 · el ranking estaba hecho con precios de mayo

Buscando por qué la nueva primera del ranking (`MLC-1933353711`, UF 1.350, "recién remod.
depto 2 dorm sector Avda Matta sur" — un departamento de verdad esta vez) daba tan buen
número, salió que su `fetched_at` es **2026-05-04**. Cuatro meses.

El gate de frescura la contaba y anunciaba, en cada corrida, que las filas viejas *"quedan
FUERA del ranking"*. `emparejar` no miraba `fetched_at`. El mensaje describía una
consecuencia que no existía.

Los dos lados del yield estaban igual: `comparables_desde_duckdb` leía `fetched_at` solo
para convertir CLP a UF del día. Precio de mayo dividido por arriendo de mayo, presentado
como la oportunidad de hoy.

Séptimo caso de la misma familia en dos días. El patrón ya tiene forma reconocible: **el
check mide bien y el consumidor del check no aplica nada.** Los siete: la advertencia de
sesgo de m² que no se disparaba por `m2_mediana` NULL · el "ancho relativo máx 35.0x" que
dividía por `a or 1` · la reconciliación externa que imprimía ✓ sobre cero comunas · el
contador de arriendo que contaba confirmaciones · `microzona_saturada` que nunca se poblaba ·
`sospechoso` que se muta en un dict que nadie persiste (T-043) · y este.

Lo que hice distinto acá: el test `test_lo_que_el_gate_de_frescura_ANUNCIA_es_lo_que_el
_ranking_HACE` corre las dos mitades y exige que cuenten lo mismo. Es la única forma de que
la próxima vez el desacople falle en vez de imprimirse.

**Costo, y hay que decirlo:** sobre la copia local, que es el corpus de mayo entero, esto
deja el ranking en **cero unidades**. Sobre la base del usuario quedan las que recolectó
estos días. El número honesto lo da su corrida.

gates: VERDE — 615 tests.

## 31-ago-2026 · fase 3 entró al ranking, y con ella el octavo check vacío

La corrida de arriendo de fase 3 funcionó: **La Serena, Antofagasta y Coquimbo** tienen
celdas propias, y `la-serena/avenida-del-mar 2D2B 50-70` con n=77 es hoy la más profunda del
sistema — más que cualquiera de San Miguel. El podio dejó de ser 13/15 San Miguel.

**De Gran Concepción no entró nada** (T-046). Es la única de las tres que el §10 declara
"el único mercado donde el pie de equilibrio baja a ~32%", así que la parte verificable de
la tesis sigue sin verificarse.

**El octavo check vacío, y esta vez lo destapó el propio éxito.** Con el podio en Antofagasta
y La Serena, el gate seguía imprimiendo `✓ medianas dentro de ±25% (4 comunas comparadas)`.
Las cuatro: la-florida, ñuñoa, san-miguel, santiago. Ninguna en el podio. La tabla Colliers
cubre la RM y nada más, y los dos checks hacían `continue` en silencio sobre lo que no podían
comparar. **Cuanto más nuevo el mercado, más fuerte el falso verde.**

No se inventa una referencia (§3.2): se nombra la ausencia. Los dos checks ahora devuelven
ALERTA listando qué no pudieron verificar.

Y como cuando el ancla externa no llega el único control que queda es mirar los avisos, se
agregó `cli comparables <microzona>`: lista los avisos detrás de una mediana con su URL, su
$/m² y su fecha. Las seis columnas de procedencia del §3.1 estaban guardadas desde el
principio sin ninguna forma de leerlas.

**El efecto de la frescura sobre San Miguel, medido:** `lo-vial 3D2B 50-70` pasó de n=30 a
n=21 y su mediana bajó, así que MLC-2189066411 pasó de 44% a 47% de pie de equilibrio. El
número honesto es peor que el que veníamos mostrando.

gates: VERDE — 619 tests.

## 31-ago-2026 · `cli embudo` — la pregunta que no se podía contestar

Gran Concepción respondió 48 tarjetas por comuna en `probar-comunas`, se recolectó, y no
apareció ni una sola unidad suya en el ranking. Las hipótesis eran tres —se cayeron por
viejas, se cayeron por microzona, o nunca llegaron a la base— y **cada una lleva a una
acción distinta**: recolectar venta, arreglar el mapeo de microzonas, o mirar el colector.
Adivinar cuál cuesta veinte minutos de corrida apuntando al lugar equivocado.

`faltantes --comuna concepcion` empeoraba la confusión: devolvía "Las 0 celdas que más
rinden" y **acto seguido listaba ñuñoa, antofagasta y talcahuano**, porque el desglose por
comuna ignoraba el filtro. Se lee como si esas fueran de Concepción.

`cli embudo` cuenta, por comuna, cuántas unidades salieron en cada paso hasta el ranking. Lo
importante del diseño: **lo cuenta `emparejar`, el mismo recorrido que arma el ranking**, no
una consulta paralela. Este proyecto ya pagó varias veces el precio de dos implementaciones
del mismo criterio, una de las cuales se queda atrás en silencio; el test
`test_el_embudo_cuenta_lo_mismo_que_los_descartes` exige que las dos mitades sumen igual.

Y trata la ausencia como una respuesta: una comuna que no aparece en el embudo **no tiene
ninguna fila**, y eso se dice con todas las letras porque es el único diagnóstico que
ninguna cantidad de recolección de arriendo arregla.

gates: VERDE — 622 tests.

## 31-ago-2026 · T-047 · seis de los once avisos del #1 declaran "amoblado"

`cli comparables antofagasta/la-chimba --tipologia 1D1B --rango 35-50`, los 11 avisos que
sostenían el yield de 11,48% del primer lugar. Seis dicen **amoblado** o **semi amoblado** en
su propio título; uno además dice `gc incl`.

**Y sacarlos no mueve la mediana:** sigue en $660.000. Vale la pena decirlo porque si el
hallazgo se contara como "la mediana estaba inflada" sería falso y se caería a la primera
revisión.

**El problema es otro. La celda solo llega a los 8 comparables del §7.3 contando productos
que no son el mismo producto.** Sin los amoblados quedan 5. El umbral existe para que la
mediana no sea ruido, y once avisos de tres productos distintos son ruido con mejor
presentación que tres avisos de uno.

Medido sobre los 2.835 comparables de la copia local, la proporción de amoblados va de
**1,5% en San Miguel a 21,6% en Las Condes** (ñuñoa 13,8%, la celda de Antofagasta 64%).
**El sesgo no es parejo entre comunas**, así que un ranking cuya gracia es comparar comunas
estaba comparando mezclas distintas de dos productos.

**Por qué acá sí se filtra por palabra y en la cesión de promesa no.** En la promesa la
palabra era un proxy: 8 de 9 avisos que decían "promesa" publicaban el precio del
departamento, así que no identificaba el problema. Acá la palabra **es el hecho**: un aviso
que dice "amoblado" está declarando qué producto vende. No se infiere; se le cree.

La asimetría queda declarada en el módulo: que un aviso **no** diga amoblado no prueba que
esté pelado, así que la corrección va en una sola dirección y la mediana puede seguir sesgada
hacia arriba, solo que menos. No se compensa con un ajuste inventado (§3.2). `equipado` queda
fuera de la lista dura porque "cocina equipada" es estándar en un arriendo pelado: se marca
`?` para que un humano lo mire.

No hizo falta recolectar nada: el título viaja en el slug de `source_url`, que es una de las
seis columnas del §3.1 que toda fila ya tiene. Es el mismo dato que destapó la promesa.

**Y `cli embudo --fase 3` contestó lo de Concepción (T-048):** chiguayante, concepción,
hualpén y san-pedro-de-la-paz tienen **cero filas**. Nunca se recolectaron. De Gran
Concepción solo entró talcahuano — y de sus 232 unidades, 103 salen por `fuera_de_rango`
(más de 140 m² útiles), que en Talcahuano no es creíble.

gates: VERDE — 637 tests.

## 31-ago-2026 · T-048 · la venta publicada en pesos se tiraba a la basura

El colector **sí** había recolectado las ocho comunas de fase 3: la corrida reportó 3.812
avisos, que son 8 comunas × 5 páginas × 2 operaciones × 48. La pérdida estaba en la carga.

`cargar_avisos` tenía una rama que descartaba toda venta publicada en pesos, con un
`logging.info` como única huella. La razón era buena: `precio_uf` era la única columna de
precio y el §11 prohíbe que la capa de carga convierta, porque la UF del día vive en otra
tabla. Pero la consecuencia no se había medido.

La medí sobre el corpus de mayo, parseando los blobs crudos: **143 unidades, el 6,1% de las
ventas de la RM**. Y muy desparejo:

    las-condes    0,2%      nunoa       3,5%      macul       10,7%
    providencia   1,5%      san-miguel 11,8%      santiago    11,9%

**La proporción sube donde el stock es más barato** — que es exactamente el stock que este
inversionista puede comprar. En regiones, donde publicar en pesos es mucho más común que en
la RM, se llevó cuatro comunas completas.

El arreglo es el que el arriendo ya usaba: se guarda `precio_clp` como viene y la conversión
pasa al emparejamiento, con la UF **del día del aviso**. Sin esa UF la fila se descarta y se
cuenta (`sin_uf_del_dia`); no se convierte con la de hoy, que sería un precio de mayo
expresado en UF de agosto. El valor convertido queda `D`, no `V`.

**Un bug que casi meto yo, en el mismo cambio.** El INSERT de `_cargar_venta` indexaba una
tupla posicional de veinte columnas (`campos[4]`, `campos[2]`…). Al agregar `precio_clp` al
medio de `campos`, cada índice se corrió uno y los m² habrían entrado en la columna de
dormitorios **sin que nada fallara**: no revienta, ordena mal. Lo reescribí por nombre.

gates: VERDE — 641 tests.

## 31-ago-2026 · una anomalía que NO se explicó, y no se va a explicar adivinando

Comparando los dos `embudo --fase 3` del usuario, antes y después del cambio de `precio_clp`:

    antes:   talcahuano   103 fuera_de_rango · 129 sin_comparables · 0 rankea
             CERO: chiguayante, concepcion, hualpen, san-pedro-de-la-paz

    después: chiguayante  103 fuera_de_rango · 124 sin_comparables · 0 rankea
             CERO: concepcion, hualpen, san-pedro-de-la-paz, talcahuano

**Talcahuano y Chiguayante se intercambiaron, con el mismo 103.** Los cambios de las otras
tres comunas (la-serena 145→138, antofagasta 29→16, coquimbo 42→26) los explica el filtro de
amoblados, que sacó celdas de arriendo. Un intercambio de etiquetas entre dos comunas no.

Y al mismo tiempo `talcahuano/santiago` aparece con n=42 entre las celdas de ARRIENDO más
profundas. O sea que talcahuano existe en arriendo y no en venta.

**No lo voy a explicar por deducción.** Las hipótesis que se me ocurren —que `rebuild
--from-raw` corriera o no, que la etiqueta de comuna salga mal, que falte un `.meta.json` y
un comuna entera se caiga por `MetadatoAusente`— predicen cosas distintas y no tengo la base
del usuario para distinguirlas. Escribir la explicación más plausible en el RUNLOG y seguir
sería exactamente el error que este proyecto viene cazando toda la semana: una afirmación
que se lee bien y no se midió.

Lo que sí se hizo: `cli embudo --detalle` muestra, por comuna, los blobs crudos de los que
salieron sus unidades. El nombre del blob es `{operacion}_{comuna}_p{NN}`, o sea el filtro
con el que se pidió la página. Si la comuna de la fila no coincide con la del blob, la
etiqueta está mal puesta — y una etiqueta mal puesta manda toda la recolección dirigida a la
comuna equivocada. Con eso la afirmación "chiguayante tiene 103 unidades" pasa a ser
auditable en vez de creíble.

gates: VERDE — 641 tests.

## 31-ago-2026 · dos errores míos, corregidos con la evidencia

`embudo --fase 3 --detalle` echó abajo dos cosas que yo había afirmado.

**1. No hubo intercambio de etiquetas.** Las 232 unidades de Chiguayante salieron de
`venta_chiguayante_p01…p05`. La etiqueta es correcta y sale del filtro con el que se pidió la
página. Mi lectura de "talcahuano y chiguayante se intercambiaron" era una inferencia sobre
dos tablas de dos momentos distintos, no una medición.

**2. El precio en pesos NO era la causa de las comunas faltantes.** Las cuatro comunas de
regiones que sí están tienen **`0 con precio en pesos`**. En regiones se publica en UF igual
que en Santiago. Mi diagnóstico de T-048 —"en regiones publicar en pesos es mucho más común y
por eso se perdieron cuatro comunas"— era una hipótesis plausible que presenté como
conclusión, y es falsa.

El arreglo de `precio_clp` **se queda igual**, porque lo que sí está medido sigue en pie: en
la RM son 143 unidades, el 6,1% de las ventas, con 11,9% en Santiago y 11,8% en San Miguel.
Recupera dato real. Lo que no hace es explicar Gran Concepción.

**Lo que el output sí muestra, y es nuevo:** la mediana de m² de Chiguayante es **136 m²**,
contra 79 en Antofagasta, 70 en La Serena y 65 en Coquimbo. Ahí están sus 103
`fuera_de_rango`. Un departamento mediano de 136 m² en Chiguayante no es creíble: o el m² que
trae la tarjeta en esa comuna es superficie total y no útil, o el portal está sirviendo otro
producto cuando la comuna tiene poco stock de departamentos.

Se agregó `cli crudo` para separar las dos preguntas que se venían confundiendo y que llevan
a acciones opuestas: **¿el colector no lo trajo, o lo trajo y se perdió al cargar?** Si el
blob existe, se arregla con `rebuild --from-raw` sin pedirle nada al portal; si no existe,
hay que volver a recolectar. Yo venía respondiendo eso por aritmética —"3.812 avisos ≈ 8
comunas × 5 páginas × 2 operaciones × 48, luego las trajo todas"— que es justo el tipo de
razonamiento que no aguanta.

gates: VERDE — 641 tests.

## 31-ago-2026 · el blob existe, se parseó, y las filas no llegaron

`cli crudo` cerró la pregunta anterior:

    2026-08-31  portal_busqueda  40 blobs · 8 busquedas distintas
        venta_antofagasta · venta_chiguayante · venta_concepcion · venta_coquimbo
        venta_hualpen · venta_la-serena · venta_san-pedro-de-la-paz · venta_talcahuano

**Las ocho comunas están en disco**, cinco páginas cada una, y `rebuild --from-raw` las
parseó (12.884 filas de portal_busqueda). Cuatro no dejaron una sola unidad en la base.

Eso descarta de una vez las dos explicaciones que veníamos barajando: no es que el colector
no las trajera, y no es el precio en pesos. **El blob existe, se leyó, y la fila no llegó.**

`cli autopsia <parte-del-nombre>` abre los blobs y cuenta qué sobrevive a cada paso del
parseo: tarjetas encontradas, cuántas en UF, cuántas en CLP, cuántas con microzona, con
tipología y con m². No toca la base — solo lee la zona cruda.

La línea base, sobre San Miguel, que sí funciona:

    venta_san-miguel_p07..p10   48 tarjetas por página · 2% sin microzona · 1% sin tipología

Con eso, correrlo sobre `venta_concepcion` separa tres diagnósticos que llevan a acciones
distintas: **cero tarjetas** (el parser no entiende ese HTML y recolectar de nuevo no
arregla nada), **tarjetas sin microzona** (el texto de ubicación de regiones no trae barrio,
y sin barrio no hay microzona — §2.4), o **tarjetas completas** (el problema está en la
carga, no en el parseo).

Es la tercera herramienta de diagnóstico del día, y las tres nacieron de lo mismo: yo venía
contestando preguntas de hecho por deducción. `embudo` para "¿dónde se cayó?", `crudo` para
"¿se trajo?", `autopsia` para "¿se entendió?".

gates: VERDE — 641 tests.

## 31-ago-2026 · T-049 · una comuna contada cinco veces

`autopsia venta_concepcion` y `autopsia venta_talcahuano` dieron salidas **idénticas byte a
byte**: 513/512/514/512/524 KB, 47/48/47/47/48 tarjetas, mismo reparto UF/CLP.

Los blobs tienen nombres distintos y el mismo contenido. **El portal ignoró el filtro de
comuna y sirvió la misma página a las cinco comunas del Gran Concepción.** Al cargarlas todas
traen los mismos `MLC-`: la primera se lleva las filas, las otras cuatro quedan en cero. No
por falta de datos — porque son los mismos datos.

Y cuál gana depende del orden de carga. Ahí está la explicación del "intercambio" que yo
había leído mal: talcahuano antes del rebuild, chiguayante después. No hubo swap de
etiquetas; hubo una sola comuna contada cinco veces.

También explica la mediana de 136 m² de "chiguayante": no son departamentos de Chiguayante,
es lo que el portal devuelve cuando no aplica el filtro.

**Noveno check vacío, y es el que autorizó toda la corrida.** `probar-comunas` dijo *"8/8, 48
tarjetas cada una"*. Contaba el número correcto sobre el documento equivocado. Contar
resultados nunca podía detectar esto — sólo compararlos.

Ahora compara los `MLC-` entre comunas. Y `cli crudo` detecta blobs con el mismo
`sha_contenido` bajo búsquedas distintas: **ese sha estaba en cada `.meta.json` desde el
primer día** y nadie lo miraba.

gates: VERDE — 645 tests.

## 31-ago-2026 · T-050 · auditoría de código

Recorrido buscando el patrón de la semana: el check que no mide. Tres hallazgos.

**El selftest corría después de cargar.** `recolectar-portal` insertaba y *después*
verificaba, así que el detector de parser roto del §7.1 se enteraba con los datos ya adentro.
El §7.1 pone el selftest para que un colector roto no contamine; verificar después de
escribir lo convierte en un informe de daños. Ahora corre antes y en rojo no carga nada — los
blobs quedan en `data/raw/`, recuperables con `rebuild --from-raw`.

**`cobertura["precio"]` era `1.0 if tarjetas else 0.0`.** Toda `Tarjeta` tiene precio por
construcción, así que ese 100% no podía bajar nunca, ni con el selector de precio roto. Ahora
mide contra las tarjetas que hay en el HTML: **98,7%** sobre el corpus de mayo.

**El colector no detectaba lo de T-049 por sí mismo.** `probar-comunas` compara avisos entre
comunas, pero es un comando aparte que hay que acordarse de correr. `recolectar-portal` ahora
hace la comparación sobre lo que acaba de bajar, y se detiene antes de cargar.

**Un error mío dentro de la propia auditoría, que vale registrar.** Midiendo el punto 2 me
dio "cobertura real 49,4%" y estuve a un paso de reportar que el parser perdía la mitad de
los avisos. Estaba forzando `operacion="venta"` sobre blobs de arriendo, así que `plausible()`
descartaba los arriendos por caer fuera del rango de precio de venta. Con la operación sacada
de la URL real: 98,7%. **Una medición mal hecha se parece muchísimo a un hallazgo**, y es la
misma trampa del otro lado: antes creía checks que no medían, ahora casi creo una medición
que medía otra cosa.

gates: VERDE — 645 tests.

## 31-ago-2026 · T-051 · el ancla externa de venta nunca corrió

Buscando por qué la nueva primera del ranking marca 36,7 UF/m² en Santiago —contra una
referencia publicada de 80,9— salió que **ese gate no existía en la práctica**.

El §7.3 lo declara como FALLA: *"el UF/m² mediano de cada comuna se compara contra la tabla
Colliers; desviación >20% ⇒ falla el gate"*. `checks.correr()` acepta el argumento desde
siempre y `cli gates` nunca se lo pasó. **El gate más fuerte del lado de la venta, el único
que contrasta el pipeline contra un tercero, no se evaluó jamás.** Décimo caso.

**Y conectarlo tal cual habría sido peor que no tenerlo.** La tabla es explícitamente de
departamento **nuevo** y el 100% de la base es usado. El spread medido:

    ñuñoa −1% · macul −13% · las-condes −16% · san-miguel −17% · santiago −28%

Santiago habría fallado el gate por una razón real —su stock es más antiguo—, no por un error
del pipeline. Un gate que falla por algo estructural entrena a ignorarlo.

Es exactamente el error del amoblado del lado de la venta: **dos productos distintos bajo un
solo número.** Allá era arriendo pelado contra amoblado; acá, departamento nuevo contra usado.

Se conecta comparando lo comparable —el ancla mira stock nuevo— y el descuento del usado va
aparte como medición `MARCA`, que informa sin aprobar ni reprobar. El resultado inmediato es
"ninguna comuna tiene referencia con qué comparar", porque no hay una sola unidad nueva: es la
respuesta correcta, y vuelve a poner T-925 al frente de la fila.

Ese spread, además, no es ruido: ordena las comunas por cuánto pesa su stock antiguo, y el día
que entre la Capa 5 se cruza con transacciones reales.

gates: VERDE — 649 tests.

## 31-ago-2026 · T-052 · la herramienta de auditoría auditaba otro número

Los 12 comparables frescos de `santiago/san-diego · 1D1B · 25-35 m²` aguantan la mirada: 1D1B
reales de Santiago centro, entre $280.000 y $375.000, varios en edificios con nombre —
Eyzaguirre, Arturo Prat, Coquimbo—, dispersión chica. **La UF 8,68 del ranking es buena.**

Pero el comando que puse hoy para auditar esa mediana **mostró otro número**: $330.000 sobre
23 avisos, contra los $355.000 sobre 12 que usa el ranking. Los 11 de diferencia son de mayo,
que el §7.3 saca de la agregación — y `cli comparables` no aplicaba ese filtro.

**Es la misma enfermedad de la semana, y esta vez la introduje yo, hoy, en la herramienta
construida para detectarla.** Una herramienta de auditoría que filtra distinto del sistema que
audita no audita nada: confirma un número que nadie usó.

Ahora comparte el criterio —amoblado fuera, vencido fuera— y marca cada aviso con por qué
entra o no. Una celda sin comparables vigentes lo dice en vez de calcular una mediana con los
viejos, que sería exactamente el número que el ranking no usa.

El test que lo fija corre los dos filtros sobre los avisos reales de esa celda. Si alguien
cambia un lado, falla.

gates: VERDE — 650 tests.

## 31-ago-2026 · `cli buscar-en-crudo` — preguntarle al archivo en vez de moverlo

El ADR 008 quedó abierto en un punto concreto: si la ficha de Assetplan **renderizada con
navegador** trae `units_by_size` con m² y precio por unidad. Si los trae, Assetplan pasa de
"no sirve para lo que queríamos" a la mejor fuente de comparables del catálogo, y eso
justifica Playwright según el §5. Si no, queda como fuente de contexto.

El blob ya está en la máquina del usuario, en `data/raw/_explorar/`. Yo venía pidiéndole que
lo subiera al repo — 1,6 MB — cuando la pregunta no necesita el archivo, necesita saber qué
hay adentro.

`cli buscar-en-crudo <patron>` busca dentro de los blobs guardados y muestra el contexto de
cada hallazgo. Sin parser, sin red, sin mover nada. Y cuando no encuentra, dice **en cuántos
blobs miró**: "no está" sobre cero archivos no significa nada.

gates: VERDE — 650 tests.

## 31-ago-2026 · ADR 008 cerrado — Assetplan no es fuente de arriendo

`units_by_size` aparece **18 veces en la ficha renderizada y las 18 son código**:
`Object.values(this.localBuilding?.units_by_size || {})`. Es el JavaScript que dibujaría las
unidades; el `|| {}` de cada referencia es el plan B para cuando el objeto no está. Lo carga
Livewire por AJAX después de renderizar, y el render no lo esperó.

**Un "no aparece" no prueba nada solo**, así que se corrió un control: `min_ggcc`, que sabemos
que está en los datos, aparece 5 veces dentro del payload
(`"min_price":255000,"min_ggcc":60000`). El buscador encuentra datos
cuando los hay; `units_by_size` no está entre ellos.

Assetplan pasa de capa 4 a capa 6 en `fuentes.yml`, y **Playwright no queda justificado por
esta fuente**: renderizar no trae las unidades, y lo único que sí vale —las distancias a
Metro, que alimentarían el 10% del score que hoy está inerte— viaja en el HTML estático.

**Y un susto propio, medido a tiempo.** `min_ggcc` valida el supuesto `E` de gastos comunes,
y contra los m² medianos de nuestros avisos sale que `params.yml` está 30-40% alto en
Estación Central (2.200 vs 1.286-1.714 reales). Lo di por material antes de medirlo. Sobre
`MLC-4420580204` mueve el pie de flujo cero de **29,8% a 29,1%** — siete décimas.

La razón está en el §14 y el modelo ya la tenía bien: **los gastos comunes los paga el
arrendatario, salvo en vacancia**, así que solo se cargan el 8% del tiempo. $21.000 de
diferencia mensual entran al flujo como ~$1.680.

Es la segunda vez hoy que una aritmética de servilleta parecía un hallazgo y la medición lo
desarmó. La primera fue el "49,4% de avisos perdidos" que resultó ser 98,7%.

gates: VERDE.

## 31-ago-2026 · 13 cotizaciones reales desmienten dos supuestos, y `cli sensibilidad`

El usuario cotizó el crédito de la unidad real (UF 880, 30 años) en Santander y en
compara.cl. Descomponiendo cada dividendo contra la anualidad francesa pura sale la carga de
seguro implícita de cada banco. De 10 productos que la incluyen:

    rango 0,2264 – 0,3666 UF/mes · mediana 0,3190 · Santander directo 0,3400
    mi supuesto 0,6160 (+93%) · piso de mi rango 0,3960 (arriba del máximo observado)

**Once puntos independientes por debajo del piso del rango que yo mismo declaré.** El §3.2
pide que todo `E` venga con rango de sensibilidad; acá el rango era el problema.

**Y encontré que la medición que venía haciendo estaba mal enfocada.** El §8.4 habla de
mover *"el ranking en >10% de posiciones"* y yo venía midiendo el efecto sobre **una**
unidad. No es lo mismo: un supuesto puede mover poco cada fila y mucho **cuántas cruzan una
regla dura**. Hoy hay 567 unidades excluidas por el tope de déficit; abaratar el dividendo de
todas a la vez las mueve en bloque.

`cli sensibilidad <ruta> <valor>` corre el universo dos veces y reporta: cuántas entran,
cuántas salen, cuántas se mueven más del 10% de posiciones, y si cambia el top 5. Cambia una
copia en memoria — una medición que modifica lo que mide no sirve para decidir.

**Segundo hallazgo:** compara.cl da Santander 4,10% y el simulador de Santander da 4,65%.
Mismo banco, mismo día, 55 pb. Y BancoEstado 4,54% contra los 4,29% que el usuario midió
directo. Es tamizaje, no cotización — queda como T-056, y ninguna tasa de `params.yml` puede
salir de ahí.

gates: VERDE — 650 tests.

## 31-ago-2026 · `cli permanencia` — contar avisos no mide vacancia

El usuario fue a Portal Inmobiliario, dibujó un recuadro de **280 × 453 metros** sobre la
manzana del departamento y trajo los avisos de arriendo de ahí. Su pregunta: son muchos,
¿cuánta vacancia hay?

**Primero un error mío, corregido con la evidencia.** Leí que el barrio de esos avisos era
"Parque O'Higgins" y concluí que la búsqueda estaba en otra zona. Estaba mirando la etiqueta
en vez del mapa: la URL trae el recuadro exacto y son tres por cinco cuadras. Él confirmó
después que Google le daba mal la dirección y que Arturo Prat 324 sí está en San Diego.

**Y la pregunta de fondo es buena y no se contesta contando.** Un barrio con 30
publicaciones puede arrendarlas en dos semanas y otro con 10 puede tenerlas seis meses
colgadas. Lo que importa no es cuántas hay: es **cuánto duran**.

Eso sí se puede medir, y la zona cruda lo tenía guardado sin que nadie lo mirara: hay una
foto de mayo y otra de agosto. Un aviso que aparece en las dos estuvo cuatro meses en el
mercado; uno que estaba en mayo y ya no está, se arrendó.

`cli permanencia` cruza las dos fotos por microzona. Tres decisiones de diseño:

- **Lee del blob, no de la tabla.** `fact_arriendo_comp` guarda solo el último `fetched_at`,
  así que no distingue "visto en mayo y en agosto" de "visto solo en agosto". La zona cruda
  sí, y para eso existe (§3.6).
- **Parte por el hueco más grande entre fechas, no por la mitad de la lista.** Una
  recolección ocupa varios días seguidos —es una sola foto—, y partir por la mitad mezclaría
  el final de mayo con agosto: la ventana "nueva" tendría las dos campañas y la permanencia
  saldría inflada sin que nada avisara. Si el hueco máximo es menor a 21 días, se niega a
  medir en vez de devolver un número que no significa nada.
- **Dice lo que el número NO es**: los operadores republican con `MLC-` nuevo, así que la
  permanencia real es mayor que la medida; un aviso retirado se ve igual que uno arrendado.
  El sesgo es el mismo en todas las microzonas, así que la comparación vale aunque el nivel
  absoluto no.

Contexto que sí se pudo medir hoy: en avisos activos de 1D1B 25-35 m², `santiago/san-diego`
tiene 14 — a mitad de tabla, contra 30 de Santa Isabel y 28 del centro histórico.

gates: VERDE — 650 tests.

## 31-ago-2026 · el undécimo check vacío lo escribí yo, una hora antes

`cli permanencia` devolvió **0% en 61 de 63 microzonas**. Ni un aviso de mayo sobrevivió a
agosto, en ninguna parte. Eso no es un mercado que rota: es una medida rota.

**La causa:** el portal **expira y republica con código nuevo**. Los rangos ni se tocan —
mayo es `MLC-19xx/37-39xx`, agosto `MLC-20-22xx/43-44xx`. Y la prueba estaba a la vista
desde hace horas, en la salida de `cli comparables` que el usuario ya había pegado:

    $335.000  31 m²  2026-05-03  MLC-3776279058-edificio-coquimbo-vista-oriente-piso-6
    $335.000  31 m²  2026-08-31  MLC-2169758799-edificio-coquimbo-vista-oriente-piso-6

Mismo título, misma superficie, mismo precio, código distinto. Lo tuve delante y no lo vi.

**Lo que duele del caso** es que es exactamente la enfermedad que este proyecto lleva dos
días cazando, y la introduje yo, una hora antes, en una herramienta nueva. Once casos, y los
dos últimos son míos de hoy: primero `cli comparables` auditando otra población, ahora esto.
La disciplina no se aprende una vez.

**La llave que sí identifica:** `(microzona, título, m²)`. Medido sobre 2.807 avisos, el
**97% de los títulos aparece una sola vez** y la firma choca en 1,6%. El precio queda fuera a
propósito: un aviso que bajó de precio y sigue publicado es justo el que interesa.

Los títulos genéricos se descartan —"departamento en arriendo de 1 dorm en ñuñoa" sale 12
veces en una sola foto— con una regla dura: si una firma aparece más de una vez dentro de la
misma foto, no puede seguir a nadie y se saca de las dos. El comando reporta cuántos quedaron
fuera por eso, para que el denominador sea visible.

**Verificado antes de creerlo:** sobre dos días de mayo en Ñuñoa, la firma da 38
coincidencias y el `MLC-` da las mismas 38. En una ventana corta las dos llaves coinciden;
en cuatro meses solo sobrevive la firma. Eso es lo que hace creíble el arreglo.

gates: VERDE — 650 tests.

## 2026-08-31 · T-057 · 30 de los 100 puntos del score no se estaban midiendo

Buscando T-043 (`sospechoso` que nadie escribe) aparecio algo mas grande, en el score mismo.

Medido sobre las unidades emparejadas:

    descuento_vs_microzona   {'0': 25}      peso 5%   — nadie lo calcula nunca
    riesgo_microzona         {'0.5': 25}    peso 15%  — default del dataclass
    catalizador              {'0': 25}      peso 10%  — necesita distancia a Metro

Los tres son constantes. `_normalizar` con `hi == lo` devuelve 0,5 a todo el mundo, asi que
cada uno se convertia en una constante sumada identica a cada unidad: **no movia una sola
posicion del ranking**, pero inflaba todos los scores y aparecia en la ficha con un numero,
como si midiera. El ranking ordenaba con el 70% del §12 diciendo que ordenaba con el 100%.

Arreglo: `puntuar()` detecta los componentes que no varian, reparte su peso entre los que si,
y devuelve sus nombres. Viajan en `Evaluacion.score_inertes` hasta la API y la ficha. Repartir
en silencio habria sido el mismo error con otra cara.

El orden del ranking **no cambia**: quitar una constante y reescalar es una transformacion
afin positiva. Lo que cambia es que el score vuelve a tener 100 alcanzables y que se declara
sobre que se puntuo.

Autocritica (§7.6, hecha en linea): el detector encontro un quinto caso en el test que escribi
para probarlo — con `pie_exacto=False`, `pie_flujo_cero_real` es None en todas y el componente
del pie (20%) cae al mismo D(1) para todas. La API usa pie exacto; el atajo no.

Pendiente y anotado: `descuento_vs_microzona` es calculable HOY con lo que hay en la base
(UF/m2 de la unidad contra la mediana de su microzona). `catalizador` y `riesgo_microzona`
necesitan fuentes que no existen todavia (Metro, vacancia, stock entrando).

## 2026-09-01 · Auditoría integral pedida por el inversionista — código, cálculos y objetivo

Recorrido adversarial completo: motor financiero contra docs/02, capa de datos, score y docs.
**Nueve hallazgos, todos aplicados**, en serie con gates entre cada cambio de motor (§8.3):

1. **La detección de outliers marcaba el min y el max de CADA microzona** (percentiles
   interpolados: `min < p1` siempre). 161 "outliers" → 13 reales con cerca de Tukey
   3×IQR + piso ±10% de la mediana. ADR D-019.
2. **`sospechoso` no lo escribía nadie** (T-043): el filtro de la mediana de arriendo
   filtraba una columna vacía desde T-023. `quality/sospechosos.py` lo persiste en ambas
   tablas, misma cerca del gate, recalculado por corrida. Primer efecto: 2 avisos a 2–3×
   la banda de su zona salen de la mediana — el numerador del yield.
3. **`descuento_vs_microzona` (5% del §12) valía 0 en todas las unidades.** Ahora se
   calcula en `emparejar` contra la mediana de UF/m² de su microzona, sobre las MISMAS
   candidatas del ranking y sin sospechosos.
4. **El arriendo de equilibrio no equilibraba**: sin incobrabilidad y con opex congelado
   (4 líneas crecen con el arriendo). Medido en el caso real UF 1.100: cerrada $372.051,
   real $398.160 — **7% corto**. `arriendo_equilibrio_real()` por bisección + caso de oro
   "cobrando el equilibrio, flujo = 0 ± 0,02 UF".
5. **El impuesto a la renta gravaba el PGI** — arriendo que en vacancia no existe. Base
   corregida a `max(0, EGI − contribuciones)`; docs/02 además restaba el impuesto DOS
   veces (NOI y ATCF) — documento corregido al comportamiento del código.
6. **`con_fogaes=con_sub` acoplaba dos beneficios independientes**: el contraste
   sin_subsidio perdía además FOGAES y su pie mínimo saltaba a 20%. Desacoplado.
7. **`habilitación` estaba en docs/02 (CoC) y en ningún otro lado.** Declarada `E` en
   params (v: 0, rango [0, 60] UF), cableada a capital invertido y TIR t=0. Pendiente
   medirla: `cli sensibilidad gastos_de_cierre.habilitacion_inicial_uf=25`.
8. **Dos hoyos de frescura**: filas sin `fetched_at` pasaban el gate del §7.3 para
   siempre, en venta y en arriendo. Nuevo descarte `sin_fecha` en ambos.
9. **Dos mecanismos de componentes inertes** (uno hardcodeado, T-057 el otro): dos
   verdades. Unificado en `puntuar()`; y `sin_m2` no se anotaba en el embudo por comuna.

No aplicado, documentado: `break_even_occupancy` sigue la convención de libro (sobre PGI),
igual que docs/02. El gap lista→cierre (Capa 5) sigue sin fuente — el yield usa precio de
lista, como siempre, hasta que exista `factor_gap_lista_cierre`.

Suite completa tras el conjunto: 632 passed. Gates verdes en cada paso.

## 2026-09-01 · T-014 + T-014b · el Censo entra y riesgo_microzona despierta

Cadena completa, verificada contra los archivos reales en la maquina del inversionista:

- `ingerir-censo`: 197.032 manzanas-entidad (CSV oficial con '*' enmascarado → NULL, coma
  decimal, ID_ENTIDAD destruido por Excel EN el archivo oficial — se usa MANZENT).
  Geometria: la llave numerica del DBF viene TRUNCADA del origen (~7 cifras); la buena es
  la gemela textual `Mzent_TX`. 77.733 manzanas con poligono, cruce 65-72% por region
  (el resto: manzanas sin viviendas). Desocupacion censal RM: 5,2%.
- `recolectar-barrios`: classified_locations de MELI VIVO (a diferencia de /search, 403
  desde ADR 003): 196 requests, 158 barrios, 18/18 comunas, 107 microzonas con centro.
- `puente-censo` (nuevo): Voronoi manzana → barrio + riesgo por microzona (desocupacion,
  saturacion B2, profundidad de arriendo; pesos E en params). ADR 009 declara los limites
  de la aproximacion. Emparejar usa el riesgo medido y CUENTA cuantas unidades quedan en
  el 0.5 por defecto — el defecto no es un dato.

Pendiente de correr en la maquina real: `puente-censo` + `oportunidades` (activa el 15%
del §12) + `sensibilidad score.pesos.riesgo_microzona=0` para medir cuanto mueve.

## 2026-09-01 · T-014b corrido sobre la base real — riesgo_microzona activo

- Puente: 23.567 manzanas → 157 microzonas (54.166 quedan en comunas fuera del alcance,
  esperado: la cartografia es regional y los barrios solo del §10).
- `sensibilidad score.pesos.riesgo_microzona=0`: el componente mueve 4,1% de las
  posiciones (39 de 961) y cambia el top 5 — bajo el umbral del §8.4, activo y moderado.
- Validacion cruzada gratis: nunoa/estadio-nacional da 16,3% de desocupacion censal, y
  Tattersall ya la tenia marcada saturada por otra via. Dos fuentes, mismo lugar.
- Hallazgo de lectura (al ADR 009): la desocupacion censal COSTERA es segunda vivienda
  (avenida-del-mar 60,1%, guanaquero 61,6%) — riesgo real de estacionalidad para un
  arrendador, pero fenomeno distinto a la vacancia urbana; no comparar 1:1.
- El aviso de inertes quedo como el §12 manda: solo catalizador (10%), esperando Metro.

Duda abierta, preguntada al inversionista: entre las dos corridas de `oportunidades`
cambiaron medianas de arriendo (vicente-valdes paso de tenencia -22.341 a -16.872 y
sin_comparables bajo 28) sin que en el chat aparezca una recoleccion de por medio.
Si no corrio nada a mano, hay que buscar que lo movio.

## 2026-09-01 · T-922 · catalizador Metro construido

- `recolectar-metro`: una request Overpass (OSM, ODbL, json_publico §3.5) → dim_estacion_metro
  (Metro Santiago operativo + en construccion + Biotren). Fechas de construccion curadas con
  fuente en config/metro.yml (L7 2028, ext L6 2027): OSM trae geometria, no fechas, y una
  estacion en obra sin fecha creible no cataliza (§12) — se cuenta, no se le inventa.
- `puente-censo` ahora calcula tambien el catalizador por microzona: distancia del centro
  de barrio a la estacion elegible mas cercana, lineal entre dist_plena_m y dist_max_m
  (E declarados), factor_en_construccion para lo no inaugurado. NULL = sin medir (contado
  como defecto); 0 = medido y lejos, que es una afirmacion distinta.
- Con esto los 100 puntos del §12 tienen fuente: deficit/pie/TIR (motor), riesgo (censo+
  avisos), descuento (precios), catalizador (OSM+curaduria). Pendiente correr en la maquina
  real: recolectar-metro → puente-censo → oportunidades → sensibilidad catalizador=0.

## 2026-09-01 · dos cierres

- **Misterio de medianas resuelto**: agg_arriendo_microzona esta calculada 31-ago 22:29:25
  con 1.024 celdas; la corrida pegada en el chat mostro 1.005. Hubo una segunda
  agregar-arriendo esa noche tras mas avisos (la recoleccion dirigida de arriendo estaba
  en la lista de pendientes del inversionista). Nada movio datos por si solo.
- **habilitacion_inicial_uf: 0 → 25** por decision del inversionista, con la medicion
  previa de que no mueve el ranking (0 entradas/salidas/posiciones). CoC y TIR bajan a su
  nivel honesto: el modelo deja de asumir que amoblar la entrega cuesta $0.

## 2026-09-03 · T-925c en producción — el colector wp-json corre en vivo

- **Corrida completa contra socovesa.cl** (desde la máquina del inversionista): 98 requests,
  116 URLs de unidad en el sitemap, **16 proyectos y 51 modelos cargados** con precio
  "desde" (UF 2.330–6.990), todos `precio_es_desde=TRUE` y fuera del ranking por regla.
  Idempotencia verificada en vivo: segunda corrida = 0 filas nuevas, 9 refrescos.
- En el alcance del §10 cayeron **Ñuñoa (1), Macul (1) y La Florida (1)**; el resto es
  Socovesa Sur (Temuco, Puerto Montt, Chillán…) y casas fuera de alcance — consistente
  con el límite declarado en ADR 011: el valor del piloto es la RUTA, falta sumar dominios.
- Errores esperables y visibles, no silenciosos: 4× HTTP 401 (registros REST privados,
  borradores) y 3× "HTTP 200 pero HTML" (redirecciones de borrador). El primero de estos
  reventaba la corrida completa; el fix 31e1053 los degrada a error-por-proyecto.
- Dos bugs encontrados por la realidad en esta tarea: el upsert `ON CONFLICT DO UPDATE`
  sobre dim_proyecto viola la FK de DuckDB (ahora: congelada y CONTADA cuando ya hay fact
  referenciando), y el REST que responde HTML con 200.

## 2026-09-03 · Pilares en producción — el censo del grupo Socovesa completo

- **Corrida completa contra pilares.cl**: 126 requests, 99 URLs de unidad, 11 proyectos y
  21 modelos procesados (12 nuevos, 3 refrescos, 6 sin precio publicado — contados, no
  imputados). Con Socovesa, el censo wpjson queda en **66 modelos vigentes, UF 1.790–6.990**.
- **La RM del alcance por fin tiene oferta nueva censada**: La Florida 5 proyectos,
  Ñuñoa 2, Independencia 2, Santiago 2, Macul 1, La Cisterna 1, Estación Central 1.
  Pilares es exactamente el segmento del subsidio (deptos desde UF 1.790).
- Errores esperables: 12× HTTP 401 (registros REST privados — Pilares tiene más borradores
  que Socovesa) y la página de oficinas sin REST (uso comercial, irrelevante).
- Almagro descartado con dato (fuentes.yml + ADR 011 adenda): desde UF 10.590–16.790,
  todo sobre el tope UF 6.000.
- T-925c sigue `en_curso`: el criterio de ≥300 unidades/tipologías RM pide más dominios
  WP fuera del grupo Socovesa (candidatos para fuente-scout en la próxima ola), y la
  verificación adversarial (§7.6) queda para el cierre de la tarea.

## 2026-09-03 · Fundamenta e iarmas en producción — censo wp-json con 4 inmobiliarias

- **Corridas completas desde la máquina del inversionista**: Fundamenta 16 proyectos
  (11 modelos nuevos, 2 URLs del sitemap dan 404 — proyectos retirados, quedan contados),
  iarmas 10 proyectos y 54 bloques de planta (29 modelos con precio, 10 sin precio
  publicado — plantas agotadas, ND no imputado).
- **El censo de oferta nueva queda en 135 modelos vigentes, UF 990–6.990**, de 4
  inmobiliarias con 3 jerarquías web distintas. Comunas del alcance cubiertas:
  La Florida 10 proyectos, Santiago 5, Ñuñoa 5, Macul 3, Independencia 2,
  Estación Central 2, Lampa 2, La Cisterna 1, Cerrillos 1.
- Fundamenta aporta ademas lat/lon por proyecto (GeoCoordinates del JSON-LD) →
  dim_proyecto queda lista para el cruce con microzonas.
- La corrida semanal del domingo censa los cuatro dominios: desde ahora las BAJAS del
  "precio desde" de la oferta nueva se detectan solas (SCD), que es la señal de
  inmobiliaria apurada.
- T-925c sigue en_curso: para las ≥300 unidades/tipologías RM del criterio faltan
  dominios del scouting (ingevecinmobiliaria, iaconcagua, santolaya por descartar) y
  la verificación adversarial §7.6 al cierre.


## 2026-09-03 · D-018 (DFL2 probable) + revisión adversarial §7.6

- Instrucción del inversionista: evaluar CON DFL2 las usadas ≤140 m² sin escritura vista.
  Implementado como supuesto E declarado y MARCADO en toda superficie ("probable*").
- El verificador (§7.6) encontró 4 hallazgos materiales; todos corregidos en el mismo pase
  (detalle completo en docs/05-decisiones.md D-018): la marca faltaba en API y dashboard;
  el dashboard no aplicaba el gate de frescura (servía precios de mayo); la ventana de
  contribuciones se apilaba como segundo supuesto (docstring afirmaba 82% de antigüedad
  declarada — medido: 0%); cli sensibilidad no aceptaba booleanos; la nota del parámetro
  afirmaba mercado sin fuente.
- Medición §8.4 registrada: el supuesto CREA el ranking actual (0 → 4 unidades vivas; la
  #1 entra por $7.278/mes de margen contra el tope de liquidez). Deuda anotada en D-018.


## 2026-09-03 · T-931b (nuevas al "desde") + T-922b (obras OSM) + fix bitácora dirigida

- **T-931b**: el informe suma la sección "nuevas evaluadas al desde" (HIPOTÉTICO,
  separada del ranking de usadas). Microzona por lat/lon del proyecto (misma comuna,
  tope 2,5 km; en memoria — la FK de DuckDB impide persistir el update), motor real
  con tasa CON subsidio (primera venta) y arriendo de la celda n≥8. Descartes con
  motivo (sin_geo / sin_comparables / desde_fuera_de_rango). 2 tests nuevos.
- **T-922b**: la corrida real cosechó 0 estaciones en construcción porque la consulta
  Overpass exigía `station=subway` en las obras; el ciclo de vida de OSM lo etiqueta
  `railway=construction` + `construction=station` (+ `construction:station=subway`) o
  `construction:railway=station`. Consulta ampliada a los 4 patrones y filtro de red
  movido a `parsear` con contador `fuera_de_red` (tranvía/EFE no se cuelan). parser
  0.3.0. Confirmación pendiente en la corrida viva local (`recolectar-metro`).
- **Bitácora por modo**: la recolección dirigida comparaba su conteo contra la última
  corrida COMPLETA y saltaba el detector de -30% (falso positivo real del 03-sep:
  "conteo cayó 65,7%"). Ahora `portal:dirigida` compara contra su propia historia.
- **Deuda D-018**: test golden nuevo que ata los TRES 140 m² (params, modelo, doc) a
  una sola declaración.
- gates: VERDE (calidad de datos PARCIAL por cobertura, como venía).
