# ADR-005 · Colector de Portal Inmobiliario por la ruta permitida

**Estado:** aceptado · **Fecha:** 2026-08-29 · **Tarea:** T-920

## Contexto

Con MercadoLibre devolviendo 403 en `/sites/MLC/search` (ADR-003), la oferta y el arriendo de
la Fase 1 se quedaron sin fuente. El proyecto anterior del usuario sí tenía un scraper de
Portal Inmobiliario, pero scrapeaba **fichas `/MLC-...`**, que el `robots.txt` del portal
bloquea, y lo hacía autenticado y con evasión de detección (ADR-004, hallazgo H6).

## La decisión

**Se recolecta solo por las rutas `_Desde_`, que el `robots.txt` permite.**

El §13.6 del contrato dice que el portal bloquea `/propiedades/` y permite `/*_Desde_`.
Verificado contra las 130 páginas de listado del corpus real: **6.076 tarjetas, de las cuales
5.608 son unidades individuales** con precio exacto, dormitorios, baños, m² útiles y barrio.

| Campo | Cobertura sobre las páginas reales |
|---|---|
| microzona (barrio) | **99,8%** |
| m² útiles (sobre unidades) | **99,3%** |
| dormitorios | **98,9%** |

Todo lo que el motor necesita para rankear stock usado está en territorio permitido. **La
aprobación D-016 queda de respaldo y no de vía principal**, que es el orden que manda el §3.5.

## Tres detalles que no son cosméticos

### La página 1 también se pide con `_Desde_1`

El portal sirve la primera página sin sufijo, pero esa forma no calza con el patrón
`/*_Desde_` y quedaría fuera de lo permitido. `_Desde_1` devuelve lo mismo. Elegir la URL
permitida cuando existe una equivalente no cuesta nada y evita tener que discutir después si
el colector estaba autorizado.

### Identidad honesta, y el riesgo real no es el que parece

El colector rechaza en el constructor cualquier `User-Agent` que contenga `Mozilla` — es
decir, se niega a disfrazarse de navegador. No hay `--disable-blink-features`, no hay
Playwright, no hay sesión.

Lo que el scraper anterior arriesgaba **no era una IP: era la cuenta de MercadoLibre del
usuario**, la misma con la que compra. D-016 es explícita: *"la aprobación cubre recolectar,
no cubre esquivar"*. Si el portal responde 403 a un cliente honesto, el colector levanta
`Bloqueado` y se detiene. No reintenta de otra forma.

### El proyecto no es una unidad

De cada 48 tarjetas, unas 10 son proyectos: publican `"Desde UF 2.680"`, `"1 a 2 dormitorios"`
y `"35 - 61 m² útiles"`. El §B1 exige el precio **real por unidad**, así que:

- los rangos quedan en `ND` (`a_decimal` devuelve `None` ante más de un número, tras el bug
  que convertía `"35 - 61"` en 3.561 m²);
- la fila se carga con `evidence_level = 'E'`, y el §12 ya excluye del ranking todo precio
  estimado. La regla que existe hace el trabajo sin código nuevo.

## Lo que queda por verificar en la máquina del usuario

**Si el listado se sirve renderizado o necesita JavaScript.** Las 130 páginas del corpus
fueron capturadas con Playwright, así que no prueban que un `GET` simple alcance. El colector
usa `httpx` —lo mínimo, según el §5— y la primera corrida real lo dirá. Si vuelve una cáscara
sin tarjetas, el `selftest` falla con "ninguna tarjeta parseó" y ahí se justifica Playwright
en este mismo ADR, no antes.

**Si el portal acepta a un cliente honesto desde una IP residencial chilena.** No se puede
medir desde el contenedor: no tiene IP chilena y el portal ya devolvió 403 a datacenter.

## Consecuencias

- La Fase 1 recupera su fuente de oferta y de comparables sin depender de MercadoLibre.
- El cargador SCD tipo 2 es **compartido** con el colector histórico (`portal_comun`), así que
  la primera corrida cruza contra la foto de mayo-2026 y produce el delta de precios de T-919
  sin código adicional: la unidad que bajó de precio abre versión nueva y la anterior se cierra.
- `legal_tier: html_permitido`, sin necesidad de invocar D-016.
