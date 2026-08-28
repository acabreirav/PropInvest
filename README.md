# Flujo Cero

Sistema de inteligencia de inversión inmobiliaria residencial en Chile.
Encuentra departamentos **nuevos** elegibles para el subsidio a la tasa (Ley 21.748 ampliada,
hasta UF 6.000) y evalúa cuáles llegan a flujo de caja no negativo, con cada número trazable
hasta su fuente.

## Empezar

```bash
make setup            # uv sync + playwright chromium
cp .env.example .env  # credenciales de MELI, CMF apikey, etc.
make test             # motor financiero y gates offline
claude                # y luego:  /harness fase 0
```

## Leer, en este orden

1. **`CLAUDE.md`** — el contrato operativo. Los agentes lo leen antes de tocar nada.
2. `docs/PRD.md` — qué se está construyendo y con qué criterios de aceptación.
3. `docs/00-hallazgos.md` — la investigación de mercado que fundamenta las decisiones.
4. `docs/01-fuentes.md` — dónde están los datos y cómo llegar a ellos legalmente.
5. `docs/02-modelo-financiero.md` — las fórmulas.
6. `state/BACKLOG.md` — qué falta.

## Lo que este proyecto no te va a decir

Que con 10–20% de pie vas a tener flujo positivo en un departamento nuevo del Gran Santiago.
No lo vas a tener: el pie de equilibrio hoy está entre 34% y 47%.
Lo que sí hace es **cuantificar exactamente cuánto pondrías de tu bolsillo cada mes**, mostrarte
**qué pie necesitarías** para no poner nada, y señalarte dónde esa cuenta sí cierra.

## Comandos de agente

| Comando | Qué hace |
|---|---|
| `/harness [fase]` | Una iteración del ciclo autónomo: elegir, paralelizar, validar, registrar |
| `/ola [T-001 ...]` | Lanza una ola de subagentes en paralelo |
| `/validar` | Todos los gates + auditoría de datos + revisión adversarial |
| `/nueva-fuente <url>` | Investiga, autoriza y construye un colector |
| `/informe [pie]` | Ranking, export XLSX/PDF y resumen ejecutivo |
