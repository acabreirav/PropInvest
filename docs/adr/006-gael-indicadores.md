# ADR 006 · Gael Cloud como segunda fuente de UF y UTM

- **Estado:** aceptado
- **Fecha:** 29-ago-2026
- **Tarea:** T-908
- **Fuente:** `https://api.gael.cloud/general/public/monedas[/{codigo}]`
- **`legal_tier`:** `api_oficial` — endpoint público documentado, sin autenticación, sin scraping.
- **Módulo:** `src/flujocero/sources/gael_indicadores.py`

---

## Contexto

Sin el valor de la UF no se convierte ni un arriendo publicado en pesos, y el 83% de los
avisos de arriendo se publican en pesos. O sea: la serie de UF es el único dato del que
depende, literalmente, todo lo demás.

Hoy esa serie tiene **una sola fuente**, la CMF, y esa fuente está medida como inestable.
Del propio módulo `cmf_indicadores`, medido con `cli probe` el 28-ago-2026 contra la API
real: el servidor **corta la conexión al azar** (`RemoteProtocolError: Server disconnected
without sending a response`), sin relación con el tamaño del rango pedido — la misma URL de
32 meses falló y minutos después devolvió 974 registros.

Los reintentos con backoff absorben el corte la mayoría de las veces. Lo que no absorben es
un día en que la CMF simplemente no esté.

## Decisión

Se agrega Gael Cloud como **fuente de respaldo**, no como fuente alternativa. Cuatro
decisiones concretas, y las cuatro tienen consecuencias en el código:

### 1. El respaldo NUNCA pisa a la fuente primaria

`gael_indicadores.cargar_en_duckdb` hace `ON CONFLICT DO NOTHING`, mientras que el de la
CMF hace `ON CONFLICT DO UPDATE`. Es deliberado y es el punto más importante de este ADR.

Una fuente de respaldo que sobrescribe a la primaria convierte **una caída pasajera de la
CMF en un cambio permanente de los datos**, sin que nadie lo pida y sin que quede rastro.

Efecto lateral que vale la pena: como el respaldo solo inserta si falta y la primaria
sobrescribe siempre, **la CMF gana venga en el orden que venga**. Eso hace que
`make rebuild --from-raw` sea determinista sin tener que ordenar las fuentes, y hay un test
que lo fija (`test_la_fuente_primaria_gana_venga_en_el_orden_que_venga`).

### 2. Una discrepancia entre fuentes se reporta, no se resuelve

Cuando las dos fuentes tienen el mismo `(fecha, serie)` y no coinciden más allá del
redondeo (tolerancia 0,01% — la CMF publica 2 decimales y la columna guarda 6), la carga
devuelve una `Discrepancia` y el comando la imprime.

Dos fuentes oficiales que dicen cosas distintas del mismo día es un **hallazgo de calidad
de datos**, no algo que un cargador deba decidir solo.

### 3. El cupo se respeta del lado del cliente, con margen, y un 429 no se reintenta

El límite duro de Gael es **>9 peticiones en 10 s ⇒ IP baneada una hora**
(`docs/04-legal.md`). Dos consecuencias:

- `Limitador` es un token bucket que frena **antes** de pedir, con cupo 6 y no 9: no
  sabemos si el servidor cuenta la ventana igual que nosotros, y el castigo por equivocarse
  no es un 429 pasajero sino una hora sin fuente de respaldo.
- Un **429 corta de inmediato** y no entra en la lista de reintentables. Es la diferencia
  central con la CMF, donde el corte sí es transitorio y sí se reintenta. Reintentar un
  baneo solo lo prolonga.

El reloj y la espera entran por argumento, así que los tests miden el comportamiento del
limitador sin dormir de verdad.

### 4. Gael NO reemplaza a la CMF para el histórico

El endpoint público no toma fechas: entrega el **valor vigente**. Así que este respaldo
cubre *"hoy la CMF no responde y necesito la UF de hoy"*, no el backfill de 32 meses.

`collect()` **falla con un mensaje explícito** si se le pide un período, en vez de devolver
un día y dejar creer que devolvió treinta. Un hoyo silencioso en la serie histórica es peor
que un error.

---

## Verificación viva — 30-ago-2026

**Resuelto.** Corrida de `cli ingest --fuente gael_indicadores` desde la máquina del usuario
(IP chilena residencial). Los cinco checks del §7.1 en verde y **`forma_verificada=true`**:

```
✓ selftest: {'parseo': True, 'campos_requeridos': True, 'rangos_plausibles': True,
             'conteo_estable': True, 'robots': True, 'forma_verificada': True}
✓ 1 insertadas · 1 ya estaban
```

Dos hallazgos, y el segundo no estaba planificado:

1. **La forma documentada resultó ser la real.** El parser defensivo no tuvo que rechazar
   nada: ni ambigüedad de miles, ni fecha ambigua, ni campos duplicados. Que se haya
   escrito para fallar ruidosamente sigue valiendo — es lo que lo hace seguro cuando Gael
   cambie el formato— pero hoy no hizo falta.

2. **Las dos fuentes coinciden.** Del día que se solapaba con la CMF no salió ninguna
   `Discrepancia`, o sea que los dos valores están dentro del 0,01%. Es una **validación
   externa que no existía**: la UF que usa el modelo la confirman dos fuentes oficiales
   independientes, no una sola API inestable.

Queda pendiente convertir el blob de esa corrida en la fixture de los tests, que hoy siguen
corriendo contra una respuesta reconstruida (misma deuda que T-909 tiene con la CMF).

## Lo que este ADR no podía afirmar antes de esa corrida

**La forma de la respuesta no estaba verificada contra una respuesta viva.** El entorno donde
se escribió el módulo tiene bloqueado el egreso hacia `api.gael.cloud` (comprobado:
`EGRESS_BLOCKED`). La forma viene de `docs/01-fuentes.md`, que a su vez viene de la
documentación de Gael.

Es la misma situación del ADR 001 con la CMF, y se maneja con la misma disciplina — con una
vuelta de tuerca más, porque acá los dos campos que importan son justamente los dos más
fáciles de leer mal:

| Riesgo | Cómo lo maneja el parser |
|---|---|
| Nombres de campo distintos | Los busca sin distinguir mayúsculas entre candidatos declarados, por niveles de preferencia. Cero coincidencias = error. Dos coincidencias **dentro del mismo nivel** = error, porque ahí sí son sinónimos y elegir sería adivinar. |
| **Formato de miles** | `"40.804"` es cuarenta mil ochocientos cuatro en chileno y 40,8 en inglés: un **error de mil veces** sobre el número que convierte todo el modelo a pesos. Se resuelve por rango de plausibilidad; si **las dos** lecturas caen dentro del rango, se levanta `ErrorDeFuente` en vez de elegir. |
| **Formato de fecha** | `05-08-2026` es 5 de agosto en Chile y 8 de mayo en formato gringo. Una UF con tres meses de error corrompe toda conversión de ese día y no se nota mirando la tabla. Se aceptan ISO siempre y `DD-MM-AAAA` **solo cuando el primer componente es >12**; lo ambiguo se rechaza. |
| Serie equivocada | La serie se deduce del **cuerpo** del registro, no de la URL pedida: si se pidió UF y Gael devuelve UTM, queremos notarlo. |

`selftest()` deja `forma_verificada=False` mientras no vea una respuesta real, igual que el
módulo de la CMF.

**Cómo se cierra esta advertencia:** una corrida de
`uv run python -m flujocero.cli ingest --fuente gael_indicadores` desde una máquina con
salida a internet deja el primer blob real en `data/raw/gael_indicadores/`. De ahí sale la
fixture. Si el parser falla contra la respuesta real, el blob ya quedó escrito (§3.6: se
persiste **antes** de parsear) y el arreglo no necesita volver a pedirle nada a Gael — que
es precisamente el motivo de esa regla.

## Alternativas descartadas

- **Gael como fuente primaria.** No: la CMF es el organismo que publica la UF. Gael es un
  intermediario. La procedencia de una fila importa tanto como su valor (§3.1).
- **`mindicador.cl`.** `docs/01-fuentes.md` ya lo registra como *observado caído*. Un
  respaldo que se cae no es un respaldo.
- **Banco Central (API BDE).** Es una buena tercera fuente y tiene serie histórica, que es
  justo lo que a Gael le falta. No se hizo ahora porque los IDs de serie están sin
  verificar (`docs/01-fuentes.md` los marca con ❓) y eso es una investigación aparte.
  → queda como tarea.

## Consecuencias

- Un día de caída de la CMF ya no deja al modelo sin UF **de hoy**.
- Un día de caída de la CMF **sí** sigue dejando sin backfill histórico. No se disimula.
- Aparece una capacidad nueva que no existía: **contraste entre dos fuentes oficiales**.
  Si algún día discrepan, el sistema lo dice en vez de promediarlas.
