# Fixture de tasas hipotecarias — procedencia

`articles-46417_recurso_1_2006.xls` **es el archivo real** que la CMF sirve hoy en
`https://www.cmfchile.cl/portal/estadisticas/617/articles-46417_recurso_1.xls`,
descargado por el inversionista el 28-ago-2026 y adjuntado sin modificar.

**Su contenido es de mayo de 2006.** Lo declara su propia celda `Fecha de la consulta:
22 al 26 de mayo de 2006`, lo firma la SBIF —organismo que dejó de existir en 2019 al
fusionarse en la CMF— y lista instituciones disueltas: BankBoston, Banco del Desarrollo,
Banco Nova, Banco Paris, Citibank NA.

Sirve como fixture de **estructura**, que es real y verificada. **Sus tasas no deben
usarse jamás como dato de mercado**: van de 4,8% a 7,5% y corresponden a otro ciclo.

Dos metadatos que además impiden compararlas con nuestro escenario base sin ajustar:
el plazo de la planilla es de 20 años (el modelo usa 30) y el crédito equivale al 75% del
valor de la propiedad (el modelo usa 90% con FOGAES).

El test `test_el_archivo_real_de_la_cmf_es_de_2006_y_se_rechaza` fija este comportamiento:
el parser lo lee bien y luego lo rechaza por antigüedad.
