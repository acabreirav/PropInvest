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
