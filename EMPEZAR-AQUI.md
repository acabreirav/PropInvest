# Empezar aquí

## 1 · Súbelo a GitHub (una vez)

```bash
tar xzf flujo-cero.tar.gz && cd flujo-cero
gh repo create flujo-cero --private --source=. --push
```
Ya trae dos commits hechos. **Privado**, porque `config/inversionista.yml` va a llevar tu renta.

## 2 · Comprueba que todo está sano

```bash
make setup
make test        # → 28 passed
uv run python -m flujocero.cli demo
```

`demo` te muestra el motor funcionando sobre unidades de ejemplo. Esto es lo que verás:

```
Escenario base: pie 10% · tasa 3.30% · con subsidio · DFL2 True · vacancia 8.0%

unidad         UF  arr UF   yield   div UF  déficit/mes  pie eq.  TIR 10a  score
CO-1D-40     2761    10.5   4.56%    12.53     -4.87 UF    27.0%    7.72%   81.5
SM-1D-35     2600     8.6   3.97%    11.80     -5.53 UF    36.5%    6.04%   55.4
LF-2D-50     3700    12.5   4.05%    16.79     -7.84 UF    36.2%    6.18%   23.9
NU-2D-55     4900    16.5   4.04%    22.23    -10.60 UF    37.2%    6.05%    8.9
EC-SAT      EXCLUIDA — microzona estacion-central/santa-isabel marcada como saturada
```

Lee esa tabla así: **Concepción necesita 27% de pie para flujo cero; Santiago, 36–37%.**
Con 10% de pie, un 1D1B en San Miguel te cuesta ~5,5 UF al mes de tu bolsillo (unos $226.000).
No es un error del modelo: es el mercado. Y por eso el ranking ordena por *cuánto duele menos*.

## 3 · Tu perfil

```bash
uv run python -m flujocero.cli capacidad
```
Va a pedirte que completes `config/inversionista.yml`. Cuatro campos: renta líquida mensual,
ahorro para el pie, cuotas de otros créditos, y el pie objetivo (déjalo en `0.10`).

## 4 · Abre Claude Code y sigue

```bash
claude
```

Y pega esto como primer mensaje:

> Lee CLAUDE.md, state/BACKLOG.md y state/RUNLOG.md. La fase 0 está hecha y los gates están en
> verde. Quiero avanzar la fase 1. Explícame en dos líneas qué vas a hacer, qué necesitas de mí
> (credenciales, decisiones) y lánzalo. Antes de marcar cualquier tarea como hecha, corre `make gates`.

De ahí en adelante conversas normal. `/harness fase 1`, `/validar` e `/informe 0.10` también
funcionan: son comandos que trae el repo en `.claude/commands/`.

---

**Lo único que necesita salir de tu computador con IP chilena** son los colectores de la fase 1
en adelante. Todo lo demás —motor, escenarios, score, dashboard— corre en cualquier parte.
