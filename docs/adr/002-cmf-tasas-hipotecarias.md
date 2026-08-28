# ADR-002 · Colector de tasas hipotecarias por banco

**Estado:** aceptado, fuente deshabilitada · **Fecha:** 2026-08-28 · **Tarea:** T-012

## Contexto

`config/params.yml` fija cuatro tasas puntuales con fuente citada. T-012 pedía reemplazarlas
por una serie por banco desde el XLS que la CMF publica en su portal de estadísticas.

## Lo que se encontró

**El archivo que esa URL sirve hoy es de mayo de 2006.** No es una sospecha: lo declara el
propio archivo.

```
Fecha de la consulta: 22 al 26 de mayo de 2006
Actualizado 06/06/2006
Fuente: Superintendencia de Bancos e Instituciones Financieras - SBIF
```

La SBIF se fusionó en la CMF en 2019. La planilla lista BankBoston, Banco del Desarrollo,
Banco Nova, Banco Paris y Citibank NA — todos desaparecidos del mercado chileno. Las tasas
van de 4,8% a 7,5%, propias de otro ciclo.

Dos metadatos más la hacen incomparable con nuestro escenario base aunque estuviera vigente:
**plazo de 20 años** (el modelo usa 30) y **crédito al 75% del valor de la propiedad** (el
modelo usa 90% con FOGAES).

## Decisión

**Se escribe el parser igual, y se deshabilita la fuente.**

El parser vale porque la estructura es real y verificada: lee las 117 filas, los 17 bancos,
los 3 montos y los 3 productos sin error. Si aparece una planilla vigente en el mismo
formato, funciona sin cambios.

**La detección de obsolescencia vive dentro del parser**, no en una nota al margen:
`parse()` lee la celda `Fecha de la consulta` y lanza `PlanillaObsoleta` si supera los 12
meses. El `selftest()` lo reporta como fallo de frescura. Es imposible usar este dato por
accidente.

`config/fuentes.yml` queda con `enabled: false` y la razón escrita, como manda el §7.1.
**El archivo no se borra**: se conserva como fixture de estructura, con un `PROCEDENCIA.md`
que prohíbe explícitamente usar sus números como dato de mercado.

## Decisiones de diseño que el archivo obligó

**Localización por etiqueta, nunca por índice de fila.** Entre la primera hoja y las
siguientes, todo el contenido se corre una fila. Un parser con índices fijos habría leído
la hoja 1 bien y las otras dos mal — en silencio. El parser busca `"Fecha de la consulta"`,
`"MONTO DEL CRÉDITO"`, `"Nombre de la institución"` y deriva las posiciones de ahí.

**`n/o` es `ND`, no cero.** Cuando un banco no ofrece un producto, la planilla escribe
`n/o`. Convertirlo a 0,0% habría hecho aparecer a ese banco como el más barato del mercado.
La fila simplemente no se emite (§3.2).

**Una tasa por banco al cargar, y es la mínima.** La planilla trae 9 combinaciones por banco
(3 productos × 3 montos). Se guarda la menor, que es la que el banco efectivamente ofrece en
su producto más barato. Es una decisión explícita y documentada, no un promedio silencioso.

## Consecuencia

`dim_tasa_banco` queda vacía. `params.yml` sigue con sus cuatro tasas fechadas de 2026, que
son peores que una serie pero infinitamente mejores que datos de 2006. Se abre **T-907** para
encontrar la fuente vigente, con cuatro pistas concretas.

## Fuentes

- Archivo analizado: `https://www.cmfchile.cl/portal/estadisticas/617/articles-46417_recurso_1.xls`,
  descargado el 28-ago-2026, conservado en `tests/fixtures/cmf_tasas/`
- Índice del portal: `https://www.cmfchile.cl/portal/estadisticas/617/w3-propertyvalue-29487.html`
