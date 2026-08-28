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
