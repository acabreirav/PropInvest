---
description: Corre todos los gates y produce el informe de estado del sistema
---

1. `make gates` completo.
2. Lanza en paralelo `auditor-datos` (checks de §7.3 sobre el estado actual de la base) y
   `verificador` (revisión adversarial de los últimos commits).
3. Consolida en una tabla: gate · resultado · magnitud · filas afectadas · acción.
4. Todo fallo abre una tarea en `state/BACKLOG.md`. Ningún fallo se cierra bajando un umbral sin
   justificación registrada en `docs/05-decisiones.md`.
5. Resume en `state/RUNLOG.md` y en la respuesta: qué está sano, qué está roto, qué falta.
