---
description: Lanza una ola de subagentes en paralelo sobre tareas independientes del backlog
argument-hint: "[T-001 T-002 ...] — opcional, si no se dan se eligen del backlog"
---

Lanza una ola paralela sobre: $ARGUMENTS (si está vacío, elige del backlog las `pendiente` con
dependencias resueltas).

**Antes de lanzar, verifica las tres reglas de paralelización:**
1. Ninguna tarea de la ola toca el mismo archivo que otra. Si dos lo hacen, la tarea está mal
   cortada — arréglala antes de lanzar.
2. Ninguna toca el esquema de la base, el motor financiero ni `config/params.yml`. Esos van solos.
3. La ola tiene entre 2 y 6 tareas.

Emite **todas las llamadas a subagentes en un solo mensaje** para que corran de verdad en paralelo.
Cada subagente recibe: su bloque del backlog verbatim, su criterio de aceptación, y la instrucción
de no marcar nada como hecho sin gate verde.

Al volver: consolida, corre `make gates`, actualiza el backlog y el runlog.
