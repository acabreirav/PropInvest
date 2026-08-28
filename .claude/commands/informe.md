---
description: Genera el informe de oportunidades — ranking, export y resumen ejecutivo
argument-hint: "[pie objetivo, ej. 0.15]"
---

Con pie objetivo $1 (por defecto 0,15):

1. `make score` sobre el universo vigente.
2. Verifica cobertura: si <80% de las unidades tienen precio real y microzona, **marca el informe
   como parcial y dilo en la primera línea**.
3. Genera:
   - Top 20 por **menor déficit mensual en UF** al pie objetivo.
   - Top 10 por **menor pie mínimo para flujo cero**.
   - Top 10 por **TIR real apalancada a 10 años**.
   - Las tres listas con: proyecto, microzona, tipología, m², precio UF, arriendo estimado y su `n`,
     dividendo, déficit mensual, cap rate, pie de equilibrio y `evidence_level`.
4. Export XLSX y PDF de una página por unidad.
5. Resumen ejecutivo honesto, que incluya:
   - cuántas unidades quedaron **excluidas** y por qué (sobre UF 6.000, microzona saturada,
     comparables insuficientes, precio estimado);
   - el recordatorio de que **está en disputa si el subsidio exige comprador primerizo**, y qué
     cambia el ranking en el escenario `sin_subsidio`;
   - cupos de subsidio restantes y la fecha estimada de agotamiento.
