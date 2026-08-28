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
