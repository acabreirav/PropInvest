# ADR-003 · MercadoLibre como fuente de oferta y arriendo

**Estado:** parcial — G1 y G4 respondidas, G2/G3 bloqueadas por HTTP 403 · **Fecha:** 2026-08-28 · **Tarea:** T-011

## Contexto

`config/fuentes.yml` declaraba tres fuentes sobre la API de MercadoLibre:
`meli_locations` (capa 2, el diccionario de barrios), `meli_venta` (capa 3) y `meli_arriendo`
(capa 4). Las dos últimas son el núcleo de la Fase 1: sin ellas no hay universo de unidades
ni comparables de arriendo.

Esa elección no fue casual. El §13.6 del contrato prohíbe scrapear Portal Inmobiliario en HTML
—su `robots.txt` bloquea `/propiedades/` y hay WAF— y da como alternativa exactamente esto:

> *"Usa la API oficial de MercadoLibre (site MLC). Es la misma data, por la puerta."*

El §G de `docs/01-fuentes.md` dejó cuatro brechas abiertas para medir antes de comprometer
arquitectura. `cli medir-meli` las mide. El usuario lo ejecutó el 28-ago-2026 a las 21:57 UTC
desde su máquina, con IP residencial chilena.

## Lo que se midió

### G1 · Categoría — respondida [V]

```
MLC1459 = Inmuebles
hijos: MLC50623 Agrícolas · MLC50564 Bodegas · MLC1466 Casas · MLC1472 Departamentos
       MLC50620 Estacionamientos · MLC50617 Industriales · MLC50610 Locales · MLC1493 Loteos
```

`fuentes.yml` traía `MLC1459` como "la categoría". No es falso, es el nodo equivocado del
árbol: es la **raíz** Inmuebles. La categoría que los colectores necesitan es
**`MLC1472` · Departamentos**. Corregido en `fuentes.yml` como `categoria_raiz` + `categoria`.

### G2 · ¿Exige token? — **bloqueada** [ND]

```
GET /sites/MLC/search?q=departamento&limit=1
  con token: HTTP 403 · sin token: HTTP 403
```

### G3 · Tope de resultados — **bloqueada** [ND]

```
HTTP 403
```

### G4 · Rate limit — respondida [D]

12 peticiones en 3,3 s sin 429. La API **no publica cabeceras** `X-RateLimit-*`, así que el
valor queda `D` (derivado de una observación), no `V`: 12 peticiones sin castigo no son un
límite medido, solo una cota inferior.

## El hallazgo que importa

**`/sites/MLC/search` devuelve 403 con token válido y sin token.** El mismo token, en la misma
corrida y contra el mismo host, leyó `/sites/MLC/categories` y `/categories/MLC1459` sin
problema. Eso descarta las tres explicaciones cómodas:

| Hipótesis | Descartada porque |
|---|---|
| La app está bloqueada | G1 funcionó con ese mismo token |
| El token venció o le faltan scopes | El canje devolvió 200 y G1 leyó datos autenticados |
| IP de datacenter | Corrió en la máquina del usuario, IP residencial chilena |

Queda una hipótesis viva: **MercadoLibre cerró el recurso de búsqueda abierta**. La evidencia
que la respalda es secundaria y hay que decirlo así:

- El servidor MCP `lumile/mercadolibre-mcp` documenta haber retirado su herramienta de
  búsqueda: *"due to changes in MercadoLibre's API policies, it is no longer possible to
  access their search API"*, sin fecha declarada.
  <https://github.com/lumile/mercadolibre-mcp>
- Desarrolladores brasileños reportan el **mismo 403 en `/sites/MLB/search`**, el equivalente
  de MLB, en reclamos públicos contra Mercado Livre.
- La documentación oficial sigue describiendo formas *acotadas* de búsqueda
  (`?seller_id=`, `/users/{id}/items/search`), lo que es consistente con un cierre de la
  búsqueda **abierta** y no de todo el recurso.

**No pude verificarlo contra la documentación oficial:** `developers.mercadolibre.com.ar`,
`developers.mercadolivre.com.br` y `global-selling.mercadolibre.com` están bloqueados por el
proxy de egreso del contenedor donde corre el agente. Por el §3.2, esto es hipótesis, no hecho.

## Decisión

1. **`meli_venta` y `meli_arriendo` quedan `enabled: false`** en `fuentes.yml`, con la razón
   escrita. No se borra nada: el día que la ruta vuelva, el módulo está.
2. **`meli_locations` sigue habilitada.** Pega contra `/classified_locations/`, que es otro
   recurso y no fue tocado por el 403. T-013 (microzonas) no está bloqueada por esto.
3. **Antes de replantear arquitectura, se mide.** Se agregó la brecha **G5** a `cli medir-meli`:
   prueba una por una las formas que la documentación todavía describe —`category=`,
   `category=`+`search_type=scan`, `seller_id=`, `/highlights/`, `/trends/`— y, si alguna
   devuelve IDs, verifica con el multiget `/items?ids=` si de ahí sale el **detalle**
   (una lista de IDs sin precio ni m² no alimenta ninguna tabla).
4. **La medición ahora captura el cuerpo del rechazo, no solo el código.** La primera versión
   registraba `HTTP 403` y tiraba el cuerpo: un 403 pelado no distingue "el recurso murió"
   de "te falta un scope", y MercadoLibre manda esa diferencia en `message`/`error`/`cause`.
   Fue un defecto de instrumentación propio y costó una corrida.

## Lo que esto pone en juego

Si G5 confirma que no queda ruta, se cae la premisa del §13.6: la puerta oficial que
justificaba **no** scrapear Portal Inmobiliario. Eso es una decisión del §8.4 —afecta un
hallazgo del contrato— y va a `docs/05-decisiones.md` como **D-014**, no se resuelve en un ADR.

Lo que **no** se hace, pase lo que pase: scrapear el HTML de Portal Inmobiliario. Que la
alternativa oficial se haya cerrado no convierte en permitido lo que su `robots.txt` prohíbe.

## Consecuencias

- Fase 1 pierde, por ahora, su fuente de oferta y de comparables de arriendo vía MELI.
- `assetplan_arriendo` (capa 4, `robots.txt` permite explícitamente ClaudeBot) pasa a ser la
  fuente **primaria** de arriendo, no el complemento. Sube la prioridad de T-022.
- Para capa 3 quedan `planok_cotizador`, `inmobiliarias_wpjson`, `pabellon` y
  `enlace_inmobiliario` — todas `json_publico` o `html_permitido`, ninguna prohibida.
  Son, además, mejor dato: precio **por unidad** en vez de precio de aviso.
- El rate limit (G4) queda sin cerrar; se retomará cuando haya una ruta que valga la pena
  paginar.
