# Fixtures de Gael Cloud — procedencia

## `real/` — respuestas AUTÉNTICAS ✅

Grabadas por `cli ingest --fuente gael_indicadores` el **30-ago-2026 02:56 UTC**, desde una
máquina con IP chilena residencial. Son los bytes exactos que devolvió `api.gael.cloud`,
tal como los persistió la zona cruda (§3.6), con su `.meta.json` al lado.

| archivo | qué es |
|---|---|
| `uf_vigente.json.gz` | UF vigente: `"Valor": "40871,14"`, `"Fecha": "2026-08-29T22:00:03.403Z"` |
| `utm_vigente.json.gz` | UTM vigente: `"Valor": "68647,00"` |
| `robots.txt.json.gz` | el snapshot de robots que respalda el `robots_snapshot_sha` de cada fila |

Los valores **sí son dato de mercado real** y están verificados contra la CMF (abajo).

### Lo que estas fixtures dejaron probado, y no era obvio

**1. La fecha de Gael no está corrida en un día.** Gael publica `"2026-08-29T22:00:03.403Z"`
— la hora de su refresco diario, no una fecha de calendario limpia. Si esa marca
correspondiera al día siguiente, **toda conversión de pesos a UF quedaría corrida en un
día**. No lo está: la CMF fecha `40.871,14` el 2026-08-29 y Gael fecha ese mismo valor el
2026-08-29. Lo fija `test_las_dos_fuentes_reales_coinciden_al_peso`.

**2. Los dos formatos numéricos son distintos y los dos se leen bien.** La CMF manda
`"40.871,14"` (punto de miles + coma decimal); Gael manda `"40871,14"` (solo coma decimal).
Pasan por ramas distintas de `a_decimal_desambiguada` y llegan al mismo `Decimal`.

**3. El `robots.txt` de Gael trae una directiva malformada:** dice `Allow /general/public/*`
— sin los dos puntos. Según el RFC 9309 una línea malformada se ignora, así que en la
práctica solo rigen sus cuatro `Disallow:`, y ninguno cubre `/general/public/monedas`. El
veredicto `allowed` es correcto por los `Disallow`, **no** por ese `Allow` roto. Se deja
anotado porque si algún día Gael arregla el typo, el resultado no cambia — pero si alguien
lee el archivo a ojo puede creer que dependemos de una línea que el parser descarta.

## `../cmf/real/` — la contraparte

Las respuestas reales de la CMF viven en `tests/fixtures/cmf/real/` y llegaron en la misma
tanda. Ver `tests/fixtures/cmf/PROCEDENCIA.md`.
