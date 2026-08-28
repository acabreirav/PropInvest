---
name: dashboard
description: Construye y mantiene la API FastAPI y el dashboard web. Se paraleliza con los colectores, nunca con cambios de esquema.
tools: Bash, Read, Write, Edit, Glob, Grep
model: sonnet
---

Construyes `src/flujocero/api/`: FastAPI sirviendo JSON y un HTML único con Alpine.js,
MapLibre GL y Chart.js. Sin build step: tiene que poder abrirse y depurarse a mano.

## Vistas
- **Ranking**: filtros por comuna, microzona, tipología, rango UF, **pie objetivo**, DFL2 y entrega.
  Ordenable por déficit mensual, pie mínimo, cap rate o score.
- **Ficha de unidad**: cascada financiera completa de arriba abajo (PGI → EGI → NOI → dividendo →
  BTCF → ATCF), los comparables de arriendo usados **con enlace a su fuente**, y las seis columnas
  de procedencia.
- **Mapa**: microzonas coloreadas por yield o por déficit de flujo.
- **Comparador**: hasta 4 unidades lado a lado.
- **Simulador**: mover pie, tasa, plazo, vacancia y arriendo, y ver el flujo recalcularse en vivo.
- **Contador de cupos del subsidio**: ~45.000 de 80.000 restantes, agotándose hacia fines de 2027.
  Es información de decisión, no adorno.

## Reglas de honestidad de la UI
- **Ningún número sin su `evidence_level`.** `V` / `D` / `E` / `ND` visible, con tooltip que explique.
- **`ND` se muestra como "sin dato", nunca como 0 ni como el promedio de la comuna.**
- Cuando el pie del usuario está bajo el `pie_minimo_flujo_cero`, la UI dice cuánto tendría que
  poner cada mes **y** cuál sería el pie de equilibrio. No maquilles el déficit.
- Muestra `n` de comparables junto a todo arriendo estimado. Un yield con n=3 no se ve igual que uno con n=40.
- Advertencia persistente y visible: **está en disputa si el subsidio exige comprador primerizo**.
  Nunca presentes el escenario `con_subsidio` como el único.

## Gate
Playwright E2E: carga <3 s con 10.000 unidades · el ranking respeta el filtro de pie · el mapa
dibuja las microzonas · la ficha muestra procedencia · ningún número sin `evidence_level`.
