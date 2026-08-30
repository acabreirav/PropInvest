# ADR 008 · Assetplan no es la fuente de arriendo efectivo que creíamos

- **Estado:** aceptado — con una decisión pendiente de una medición
- **Fecha:** 30-ago-2026
- **Tarea:** T-022
- **Fuente:** `https://www.assetplan.cl/edificios.xml` + fichas de edificio
- **`legal_tier`:** `html_permitido`
- **Evidencia:** exploración real del 30-ago-2026, `tests/fixtures/assetplan/real/`

---

## 1. Lo que decía el catálogo, y lo que devuelve la página

`docs/01-fuentes.md` la describe como *"mejor proxy de arriendo real y vacancia"* y el §4 del
contrato la pone como la Capa 4, el **arriendo efectivo** que es el numerador del yield.

Se exploró con `cli explorar` desde una IP chilena y se miraron los bytes. **La ficha de
edificio no entrega arriendo efectivo ni vacancia.**

Lo que sí entrega, dentro de un `x-data="buildingPage(JSON.parse('…'))"` de 35 KB —Livewire
+ Alpine, sin JSON-LD útil: el único bloque `ld+json` es un `BreadcrumbList`—:

| campo | valor de ejemplo | qué sirve |
|---|---|---|
| `latlng` | `-33.453163,-70.69313` | **coordenadas reales**, que hoy no tenemos de nada |
| `nearby_transport[].distance_meters` | `134` a `San Alberto Hurtado`, `subway_station` | **distancia a Metro medida**, vía Google Places |
| `min_ggcc` por tipología | Estudio $45.000 · 1D $60.000 · 2D $90.000 | gastos comunes **reales por edificio** |
| `commune`, `address`, `multifamily` | Estación Central, Conde del Maule 4160 | ubicación dura |
| `min_price` por tipología | Estudio $231.000 · 1D $255.000 · 2D $308.000 | ⚠️ **"desde", no efectivo** |

Y lo que **no** entrega:

- **Nada por unidad.** No hay m², ni precio por departamento, ni número de unidad. El
  componente `units_by_size` aparece referenciado en el JavaScript pero **su contenido no
  está en el HTML**: lo carga Livewire por AJAX después de renderizar.
- **Nada de vacancia.** Ni unidades disponibles sobre total, ni tasa de ocupación.

## 2. Por qué `min_price` no puede usarse como comparable

Es un **"desde"**. El §12 excluye del ranking todo precio con `evidence_level = E`, y un
"desde UF X" es el ejemplo canónico de eso — es la misma razón por la que se descartan los
avisos de proyecto en el portal.

Usarlo como comparable de arriendo sería peor que no tenerlo: **sesgaría la mediana hacia
abajo de forma sistemática**, porque el mínimo de un edificio no es su arriendo típico. Y
como el arriendo es el numerador del yield, un sesgo a la baja ahí se traduce en yields
subestimados en todas las unidades de esa microzona.

## 3. Lo que sí vale, y no es poco

Dos cosas que hoy están **estimadas o muertas** en el modelo:

**`distance_meters` a estación de Metro.** El catalizador es el 10% del score y hoy está
inerte: no tiene fuente, reparte el mismo puntaje a todas las unidades y no mueve una
posición. Acá viene medido por Google Places, con el nombre de la estación y el tipo
(`subway_station`), para 176 edificios con coordenadas.

**`min_ggcc` por tipología.** Hoy los gastos comunes son un supuesto `E` en `params.yml`:
`3.000 CLP/m²/mes` con rango declarado [2.000, 5.000], afinado a mano por comuna. Acá hay
valores reales por edificio y tipología. Sin m² no se convierten a CLP/m² directamente, pero
son un ancla externa para validar el supuesto — y validar un `E` contra dato real es
exactamente lo que el §3.2 pide de un `E`.

**`latlng`.** No resuelve el mapa —son 176 puntos de edificios multifamily, no la geometría
de las 165 microzonas (T-928)— pero es la primera coordenada real que entra al sistema.

## 4. La decisión que queda pendiente, y de qué depende

`units_by_size` existe: el JavaScript lo usa. Si al renderizar con navegador aparece **con
m² y precio por unidad**, Assetplan pasa de "no sirve para lo que queríamos" a **la mejor
fuente de comparables del catálogo**: precio por unidad con superficie, de un operador
profesional, en territorio que su `robots.txt` permite explícitamente.

Eso justificaría Playwright, que el §5 permite *"solo cuando esté justificado en el ADR de la
fuente"*. Esta sería esa justificación — pero **solo si la medición la sostiene**. Por eso el
ADR queda abierto en este punto en vez de decidirlo por adelantado.

La medición es una línea:

```
uv run python -m flujocero.cli explorar <url-de-una-ficha> --render
```

- **Si aparecen unidades con m² y precio** → se escribe el colector con `js_render: true`
  justificado acá, y Assetplan vuelve a ser Capa 4.
- **Si no aparecen** → Assetplan queda como fuente de **contexto** (Metro, gastos comunes,
  coordenadas), no de arriendo. `config/fuentes.yml` cambia de capa 4 a capa 6 y el catálogo
  se corrige.

## 5. Nota legal

Su `robots.txt` permite explícitamente `ClaudeBot` y `Claude-User`, y la ruta que usamos no
está cubierta por ningún `Disallow` — el veredicto lo dijo así: *"ninguna regla del grupo
calza con la ruta"*.

Pero trae `Disallow: /arriendo/departamento/*/edificio/`, **con comodín**. Hasta T-926 el
verificador usaba el `RobotFileParser` de la librería estándar, que no implementa comodines y
habría dado esa ruta por permitida. El arreglo de T-926 protege este colector directamente:
sin él, el primer scraper de Assetplan habría entrado a territorio prohibido creyendo lo
contrario.

## 6. Corrección al catálogo

`docs/01-fuentes.md` y `config/fuentes.yml` describían Assetplan como *"mejor proxy de
arriendo efectivo y vacancia"*. **Sobre la página estática no es ninguna de las dos.** Se
corrigen los dos archivos citando este ADR; la afirmación original venía de investigación
secundaria y no de haber mirado una respuesta.
