---
description: Investiga, autoriza y construye una fuente de datos nueva
argument-hint: "<url o nombre de la fuente>"
---

Para la fuente **$1**:

1. Lanza `fuente-scout`. Produce el ADR en `docs/adr/`.
2. **Punto de decisión.** Si el `legal_tier` resulta `html_prohibido`, **para acá** y escala:
   escribe la pregunta en `docs/05-decisiones.md` y no construyas nada.
3. Si está autorizada, agrega la entrada a `config/fuentes.yml` con `enabled: true`.
4. Lanza `colector` para construir el módulo.
5. Corre `selftest()` contra fixture y contra una muestra viva de ≤5 documentos.
6. Corre `make gates`.
7. Si aporta comparables de arriendo, lanza `analista-arriendo` para reconciliar contra las anclas
   de `docs/00-hallazgos.md §2`.
