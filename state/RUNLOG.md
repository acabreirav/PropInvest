# Runlog
Append-only. Una entrada por iteración del harness.

Formato:
```
## YYYY-MM-DD HH:MM · iteración N
tareas: T-0xx (hecha), T-0yy (falló)
gates: verde | rojo — detalle
filas: fuente → insertadas / actualizadas
hallazgos:
aprendizajes:
tareas nuevas abiertas:
```

---

## 2026-08-28 · iteración 0 — bootstrap
tareas: ninguna ejecutada
gates: n/a
notas: repositorio inicializado con CLAUDE.md, PRD, catálogo de fuentes, modelo financiero,
params, zonas, esquema, agentes, comandos y backlog. Investigación de mercado consolidada en
`docs/00-hallazgos.md`. Siguiente paso: `/harness fase 0`.


## 2026-08-28 · iteración 1 — FASE 0 COMPLETA
tareas: T-001, T-002, T-003, T-004, T-005 → hechas
gates: **VERDE** · `pytest`: **28 passed**

qué se construyó:
- `src/flujocero/config.py` — carga de params/inversionista con validación de evidencia
- `src/flujocero/finance/core.py` — dividendo, saldo insoluto, erosión, NOI, TIR, pie de equilibrio
- `src/flujocero/finance/modelo.py` — evaluación de unidad × escenario, opex, exclusiones duras
- `src/flujocero/finance/escenarios.py` — producto cartesiano de escenarios + score auditable
- `src/flujocero/db.py` — esquema DuckDB aplicado (13 tablas)
- `src/flujocero/cli.py` — `build`, `rebuild`, `capacidad`, `demo`, `gates`
- `tests/golden/` — 28 casos: doble implementación del dividendo, anclas del pie de equilibrio,
  identidad contable, delta DFL2 exacto, exclusiones duras, monotonías, score

hallazgos:
1. **El gate de evidencia encontró un bug real de configuración**: 6 supuestos marcados `E` en
   `params.yml` no declaraban rango de sensibilidad. Corregidos. Hoy hay 11 estimados, todos
   con rango — que es exactamente la lista que debe recorrer el análisis de sensibilidad.
2. **Doble conteo de seguros en `docs/02-modelo-financiero.md`**: el NOI restaba el seguro de
   incendio/sismo y `dividendo_total` lo sumaba otra vez. En Chile el banco los cobra con el
   dividendo, así que van solo ahí. Documento corregido y test que lo fija.
3. El motor reproduce el hallazgo central de la investigación sin que se le imponga: con pie de
   10% y tasa 3,30%, el pie de equilibrio sale 36–37% en la RM y **27% en Concepción**.

aprendizajes: el escenario `sin_subsidio` se construye siempre, aunque el inversionista califique.

siguiente: T-010 a T-012 (CMF, OAuth de MercadoLibre, tasas por banco) — se paralelizan.
Requiere credenciales en `.env` y, para los colectores, IP chilena.
