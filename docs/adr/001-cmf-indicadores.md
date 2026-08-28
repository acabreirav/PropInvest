# ADR-001 · Colector CMF de indicadores (UF, UTM, IPC)

**Estado:** aceptado · **Fecha:** 2026-08-28 · **Tarea:** T-010 · **Capa:** 6

---

## Contexto

El motor financiero corre en UF. Sin una serie de UF trazable, ninguna conversión a pesos
puede llevar `evidence_level: V`, y hoy `config/params.yml` tiene un único valor puntual
(`valor_uf_clp: 40804`, 28-ago-2026) que envejece cada día.

## Decisión

Se construye `sources/cmf_indicadores.py` contra la API `api-sbifv3` de la Comisión para el
Mercado Financiero.

**`legal_tier: api_oficial`** — el nivel más alto del §3.5. Es una API pública documentada,
con apikey bajo registro gratuito. No hay scraping, no hay robots.txt que sortear, no hay
términos de servicio que tensionar.

### Endpoints

| Uso | Ruta |
|---|---|
| Valor de hoy | `/uf?apikey=&formato=json` |
| Rango de años | `/uf/periodo/{a1}/{a2}?apikey=&formato=json` |
| Rango de meses | `/uf/periodo/{a1}/{m1}/{a2}/{m2}?apikey=&formato=json` |

`formato=json` es obligatorio: el default del servicio es XML.

### Forma de la respuesta

```json
{"UFs": [{"Fecha": "2010-01-01", "Valor": "20.939,49"}]}
```

El envoltorio cambia por serie: `UFs`, `UTMs`, `IPCs`. **El valor viene como texto en
formato chileno** — punto de miles, coma decimal. Leer `"20.939,49"` con un parser de
locale inglés da `20.93` en vez de `20939.49`: un error de mil veces sobre el número que
convierte todo el modelo a pesos. Por eso la conversión vive en una función pura y aislada,
`a_decimal()`, con ocho casos de prueba.

## Consecuencias

### Cambio de esquema

`dim_tiempo_financiero` estaba en formato ancho (`fecha` como clave, con `uf_clp`, `utm_clp`,
`ipc_var_m`, `tpm` como columnas) y **sin ninguna columna de procedencia**. Eso es
incompatible con el §3.1: esas cuatro series vienen de endpoints distintos, y un solo juego
de seis columnas por fila no puede describir cuatro orígenes.

Se pasa a formato largo, `(fecha, serie)` como clave, con las seis columnas de procedencia y
`evidence_level` por fila. Se agrega la vista `v_tiempo_financiero` que reconstruye la forma
ancha para el motor y el dashboard, así el cambio no se propaga a quien sólo quiere leer.

De paso se completó `dim_tasa_banco`, que tenía 2 de las 6 columnas de procedencia.

### Identificación de serie por el cuerpo, no por la URL

El parser deduce qué serie está leyendo desde la clave de nivel superior del JSON, no desde
la ruta que pidió. Si la CMF renombra un envoltorio, el resultado es un error visible y no
una fila bien formada con la etiqueta equivocada.

### La apikey no se persiste

`source_url` guarda la URL con `apikey=OCULTA`. La credencial no entra a la base, ni al
nombre de los archivos de la zona cruda, ni a los logs.

---

## Limitación conocida, y por qué se acepta

**La forma de la respuesta no ha sido verificada contra la API viva.** El entorno donde se
escribió este colector tiene bloqueado el egreso hacia `api.cmfchile.cl` por el proxy de red
—no es el bloqueo geográfico de los portales inmobiliarios, es una pared anterior—, así que
no fue posible grabar una respuesta real.

Lo que sí se hizo:

- la estructura se tomó de la **documentación oficial** de la CMF, no de una suposición;
- la fixture en `tests/fixtures/cmf/` está **marcada explícitamente como derivada de la
  documentación**, con sus valores numéricos declarados sintéticos y prohibidos como dato
  de mercado (ver `tests/fixtures/cmf/PROCEDENCIA.md`);
- `selftest()` **distingue los dos casos**: reporta `forma_verificada: false` mientras no
  haya visto una muestra viva, en vez de afirmar una verificación que no ocurrió.

**Qué falta para cerrar esto:** ejecutar `uv run python -m flujocero.cli ingest` desde una
máquina con salida a internet. Ese primer run confirma la forma, y su respuesta reemplaza la
fixture derivada de documentación por una grabada. Hasta entonces la tarea T-010 **no se
marca `hecha`**: queda `en_curso`, porque el §7.1 exige que el `selftest` corra también
contra muestra viva.

## Alternativas descartadas

- **Gael Cloud como fuente primaria.** Queda como fallback, según `config/fuentes.yml`. Su
  límite duro —más de 9 peticiones en 10 segundos y la IP queda baneada una hora— lo hace
  mal candidato para la carga histórica inicial, que pide varios años de serie.
- **Fijar la UF en `params.yml` y olvidarse.** Es lo que hay hoy y es exactamente el problema:
  un número con fecha de vencimiento silenciosa.

## Fuentes

- Documentación oficial de la API: `https://api.cmfchile.cl/documentacion/UF.html`,
  `.../UTM.html`, `.../IPC.html`
- Registro para la apikey: `https://api.cmfchile.cl`
