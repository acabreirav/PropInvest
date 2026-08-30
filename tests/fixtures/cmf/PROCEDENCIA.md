# Fixtures de la CMF — procedencia

## `real/` — respuestas AUTÉNTICAS ✅  (T-909, cerrada el 30-ago-2026)

`real/uf_2024-01_2024-12.json.gz`, `real/uf_2025-01_2025-12.json.gz` y
`real/uf_2026-01_2026-08.json.gz` son los bytes exactos que devolvió `api.cmfchile.cl`,
grabados por el colector el 28-ago-2026 desde una máquina con IP chilena, con su
`.meta.json` al lado. **La apikey no aparece**: `base.ocultar_secreto` la reemplaza por
`apikey=OCULTA` antes de persistir, así que el `source_url` guardado es publicable.

243 registros solo en el tramo 2026. La forma documentada resultó ser la real: envoltorio
`UFs`, campos `Fecha` (ISO) y `Valor` en formato chileno `"40.871,14"`.

Estos valores **sí son dato de mercado real**, y están contrastados contra una segunda
fuente oficial independiente: Gael Cloud da `40871,14` para el 2026-08-29, el mismo valor
al peso. Ver `tests/fixtures/gael/PROCEDENCIA.md`.

---

## Las fixtures sintéticas que quedan, y por qué

`uf_periodo_2026_08.json`, `utm_2026_08.json` y `envoltorio_desconocido.json` **no son
respuestas grabadas**. Se conservan a propósito: ejercitan casos que una respuesta real no
contiene —un envoltorio desconocido, un registro sin `Valor`— y que el parser tiene que
rechazar. Sus valores numéricos son sintéticos y **no deben usarse como dato de mercado**.

Antes decían ser la única evidencia de la forma de la API. Ya no lo son.

---

## Texto original, conservado como registro de la deuda que existió

# Fixtures de la CMF — procedencia

`uf_periodo_2026_08.json` **no es una respuesta grabada de la API.**

Es una fixture de *forma*, construida a partir de la estructura publicada en la
documentación oficial de la CMF (https://api.cmfchile.cl/documentacion/UF.html), que
define el envoltorio `UFs` y los campos `Fecha` y `Valor` en formato chileno.

Los valores numéricos que contiene son **sintéticos y no deben usarse como dato de
mercado bajo ninguna circunstancia**. Existen sólo para ejercitar el parser: la conversión
de `"20.939,49"` a `Decimal("20939.49")`, el rechazo de registros incompletos y la
detección de un envoltorio desconocido.

Se construyó así porque el entorno donde se escribió el colector tiene bloqueado el egreso
hacia `api.cmfchile.cl` y no fue posible grabar una respuesta real. Por eso
`CmfIndicadores.selftest()` reporta `forma_verificada: false` mientras no reciba una
muestra viva.

**Al ejecutar el colector por primera vez contra la API real, reemplazar este archivo por
la respuesta grabada** y borrar esta advertencia. Ver `docs/adr/001-cmf-indicadores.md`.
