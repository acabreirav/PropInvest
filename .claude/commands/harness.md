---
description: Ejecuta una iteración completa del ciclo autónomo de construcción
argument-hint: "[fase] — opcional, ej. 'fase 1'"
---

Ejecuta **una iteración del harness** sobre `state/BACKLOG.md`. Alcance: $1 (si está vacío, la fase
más baja que tenga tareas pendientes).

1. Lee `CLAUDE.md`, `state/BACKLOG.md` y las últimas 50 líneas de `state/RUNLOG.md`.
2. Selecciona las tareas `pendiente` cuyas dependencias estén `hecha`.
3. **Agrúpalas en una ola paralela**: tareas que no tocan los mismos archivos salen en **una sola
   llamada con varios subagentes**. Nunca metas en la misma ola cambios de esquema, del motor
   financiero o de `config/params.yml` — esos van solos, en serie.
   Tamaño de ola: 4–6 subagentes. Más de 8 degrada la revisión.
4. Marca las tareas `en_curso`, lanza la ola, espera.
5. Corre `make gates`. **Si falla, la tarea NO se marca `hecha`**: vuelve a `pendiente` con el error
   pegado en su bloque.
6. Si la ola tocó el motor financiero, el score, o cerró una fase, lanza el subagente `verificador`
   con instrucción adversarial y pega su reporte en `state/RUNLOG.md`.
7. Escribe en `state/RUNLOG.md`: qué corrió, cuántas filas entraron, qué falló, qué se aprendió.
8. **Repón el backlog**: cada hallazgo nuevo (endpoint roto, fuente nueva, dato faltante, supuesto
   que resultó sensible) se convierte en una tarea con criterio de aceptación.
9. Commit por tarea: `T-NNN: <qué cambió> [gates: verde]`.

**Detente y escribe la pregunta en `docs/05-decisiones.md`** si aparece cualquiera de estos:
una fuente exige romper robots o T&C · hay que pagar por un dato · hay que enviar emails a terceros ·
un supuesto `E` mueve más del 10% de las posiciones del ranking · descubres que un hallazgo de
`CLAUDE.md §2` es falso.
