# ADR 007 · API y tablero sin dependencias externas

- **Estado:** aceptado
- **Fecha:** 30-ago-2026
- **Tarea:** T-027
- **Módulos:** `src/flujocero/api/{servicio,app}.py` · `src/flujocero/api/static/index.html`

---

## 1. Tres decisiones, y la única que se desvía del contrato

### 1.1 El tablero no carga ninguna librería externa — desviación del §5

El §5 del contrato dice *"HTML único + Alpine.js + MapLibre GL + Chart.js"*. **No se usó
ninguna.** La página es HTML, CSS y JavaScript plano, sin un solo `<script src>` externo.

Tres razones, en orden de peso:

1. **El gate E2E del §7.5 corre en un contenedor sin salida a internet.** Un tablero que
   depende de un CDN no se puede testear ahí, y un gate que no puede correr no es un gate:
   se salta en silencio y todos siguen creyendo que está verde.
2. **Un tablero de decisión financiera que se rompe cuando falla un CDN ajeno es peor que
   uno que no se rompe.** Este archivo abre sin red.
3. **MapLibre no tenía nada que dibujar de todos modos** (ver §2).

Lo que se pierde: reactividad declarativa y gráficos vistosos. El desglose del score se
dibuja con barras de CSS en vez de con Chart.js — cumple la función, se ve peor.
Lo que se gana: el archivo funciona solo, y el gate del §7.5 puede correr de verdad.

Hay un test que fija esto en las dos capas: `test_el_tablero_no_depende_de_ningun_cdn`
revisa el HTML, y `test_la_pagina_no_pide_ningun_recurso_externo` escucha las peticiones
reales del navegador durante el E2E. Si alguien agrega un `<script src>` externo mañana, se
entera antes de que el gate deje de poder correr.

**Cuándo revisar esta decisión:** cuando entre la geometría del Censo y haya un mapa de
verdad que dibujar. Ahí se evalúa vendorizar MapLibre —copiarlo al repo, no traerlo por
CDN— y se escribe el ADR que corresponda.

### 1.2 El pie de flujo cero se cachea; el resto se recalcula

Calcular el ranking cuesta **~90 s sobre mil unidades**, casi todo en la bisección de T-923.
Servir eso por petición es imposible con el gate de 3 s.

Lo que lo arregla es una propiedad del cálculo, no un truco: **la bisección busca el pie
donde el flujo cruza cero, así que no depende del pie pedido**. Se cachea por unidad y mover
el control del pie deja de costar 90 s.

Pero **sí depende del resto**: tasa, vacancia, plazo, DFL2, y los supuestos de `params.yml`.
Por eso la caché se indexa por una firma que incluye los campos del escenario *sin el pie*
**más el hash de `params.yml` e `inversionista.yml`**. Editar un supuesto invalida la caché
sola, en vez de servir un número viejo — que es peor que servirlo lento.

Dos trampas que costaron tiempo y quedan fijadas por test:

- **`escenario_id` no puede entrar en la firma.** Se construye como `pie20`, `pie40`… o sea
  que *codifica el pie*. Meterlo daría una firma por cada pie y anularía la caché entera
  **sin que nada fallara**: solo estaría lenta, para siempre, sin síntoma.
- **La primera carga de la página no debe mandar un pie.** El servidor precalcula la foto
  del pie del perfil; si la página manda el suyo, la descarta y re-evalúa el universo
  entero. Medido con 10.000 unidades: **8,1 s contra 0,3 s**. Lo encontró el E2E, no una
  revisión de código.

### 1.3 Ningún número sale sin su nivel de evidencia, y el nivel es el PEOR de sus entradas

El §7.5 pide que ningún número aparezca sin su `evidence_level`. Se cumple con una sola
función, `cifra()`, que envuelve valor y nivel: no hay otra forma de escribir un número en la
respuesta, así que no se puede olvidar por descuido.

La parte que importa es `nivel_derivado()`: **un cálculo hereda el peor nivel de sus
entradas**. `V + V → D`, pero `V + E → E`. Si un supuesto entra en la fórmula, el resultado
es un supuesto, por muy determinística que sea la aritmética.

La consecuencia concreta: **`pie_flujo_cero_real` se declara `E`, no `D`**. Sale de una
bisección sobre el modelo completo, que incluye vacancia, opex e inflación — los tres
supuestos de `params.yml`. Declararlo `D` lo presentaría como un cálculo sobre datos
verificados, y la métrica insignia del producto no lo es.

Los montos viajan como **texto**, no como `float`: convertirlos metería error de coma
flotante en el último paso, justo después de que el motor los cuidó con `Decimal` (§11).

---

## 2. El gate §7.5, criterio por criterio

| criterio | estado |
|---|---|
| carga en <3 s con 10.000 unidades | ✅ medido en E2E con 10.000 unidades sintéticas |
| el ranking respeta el filtro de pie | ✅ medido en E2E, y el filtro tiene que *morder* |
| la ficha muestra las seis columnas de procedencia | ✅ medido en E2E sobre el DOM |
| ningún número sin `evidence_level` | ✅ medido en la API y en el DOM renderizado |
| **el mapa dibuja las microzonas** | ❌ **no se puede** |

### Por qué no hay mapa, y por qué no se dibuja uno aproximado

`dim_microzona.geom` está **vacío en las 165 microzonas** y `fact_unidad_venta` no guarda
coordenadas. No hay nada que dibujar.

La tentación es poner puntos aproximados —el centroide de la comuna, un geocoding por
nombre— y que se vea completo. **No se hizo, y la razón es del §2.4**: la microzona *es* la
unidad de análisis de este producto. Todo el argumento se apoya en que dentro de Estación
Central el mismo producto renta $300.000 en Santa Isabel y $350.000 a pocas cuadras. Un mapa
que ubique mal una microzona no es un mapa incompleto: es un mapa que contradice la tesis
del producto mientras aparenta confirmarla.

En su lugar, `capacidades.mapa` viene en `False` con su razón, y el tablero la muestra. Hay
un endpoint `/api/microzonas` que responde la misma pregunta —dónde están las
oportunidades— con una tabla ordenada por el pie de flujo cero más bajo.

**Se destraba con T-014** (Censo 2024 por manzanas del INE). El test
`test_el_tablero_dice_por_que_no_hay_mapa` está escrito para **fallar** cuando entre la
geometría, y ahí hay que reemplazarlo por uno que verifique que el mapa se dibuja.

---

## 3. Lo que el tablero muestra y no es obvio que deba mostrar

- **Lo PEDIDO y lo APLICADO por separado.** El escenario pide 10% de pie con subsidio, pero a
  un usado el motor le niega el subsidio y el FOGAES y le exige 20%. Un encabezado que
  anuncia "pie 10%" sobre números calculados al 20% miente sobre la plata que hay que poner.
- **Por qué el motor negó cada beneficio**, unidad por unidad, con el motivo textual.
- **Qué parte del score está inerte.** Hoy el 25%: riesgo de microzona y catalizador no
  tienen fuente, reparten el mismo puntaje y no mueven una posición.
- **El aviso de micro-unidades del §13.3** cuando un tercio o más del top está bajo 35 m².
- **De dónde salió el arriendo**: celda, número de comparables y mediana. El §2.4 exige
  emparejar por microzona × tipología × rango, nunca por comuna.

---

## 4. Alternativas descartadas

- **Persistir las evaluaciones en `fact_evaluacion` y que la API solo lea.** Es la
  arquitectura que el esquema anticipa y probablemente sea lo correcto a futuro. No se hizo
  ahora porque obliga a fijar de antemano el conjunto de pies calculados, y el control de pie
  continuo es justo lo que hace útil al tablero. Queda anotado.
- **Calcular por petición sin caché.** 90 s por request. Descartado sin más.
- **Precalcular al arrancar el proceso.** `make serve` tardaría 90 s en responder al primer
  `curl`. La caché perezosa da lo mismo sin bloquear el arranque, y `/api/salud` responde
  mientras tanto.
