"""Medición §8.4 del catalizador (auditoría 14-oct H3 / T-963) sobre la base real.

La cota extrema ya se midió con `cli sensibilidad score.pesos.catalizador=0`: mueve el
16,2% del ranking y cambia el top 5 — decisión humana obligatoria. Pero apagar el PESO
mata también a las estaciones EN CONSTRUCCIÓN (Cerrillos L6, Recoleta L7), que son el
catalizador real: lo que aún no está en el precio. La variante fina es escalar solo lo
que vale una estación OPERATIVA (`factor_operativa`), que hoy vale 1,0 y la auditoría
mostró como "bono RM" doblemente contado (una estación de 2006 ya vive en el precio y
el arriendo de su microzona).

Este script recalcula el catalizador EN MEMORIA (sin escribir nada) con factor_operativa
en 1,0 (hoy) / 0,5 / 0,25 / 0,0 y re-puntúa el universo completo con cada variante:
posiciones movidas, top 10, y el catalizador medio RM vs regiones (el "bono" a la vista).

Uso:  uv run python scripts/medir_catalizador.py
Pegar la salida completa en la conversación / RUNLOG. Con esa salida se decide (§8.4)
si nace el parámetro E `catalizador.factor_operativa` y con qué valor.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from flujocero.agg import oportunidades as op  # noqa: E402
from flujocero.alcance import desde_config  # noqa: E402
from flujocero.config import cargar  # noqa: E402
from flujocero.finance.escenarios import escenario_base, evaluar_universo  # noqa: E402
from flujocero.geo.puente import catalizadores_en_memoria  # noqa: E402

ahora = datetime.now(UTC)
p, inv = cargar("params"), cargar("inversionista")
alcance = desde_config(cargar("zonas"))
con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)

r = op.emparejar_con_params(con, p, alcance=alcance, ahora=ahora)
if not r.unidades:
    raise SystemExit("sin unidades rankeables: nada que medir")
esc = escenario_base(p, inv)


def _ranking(unidades):
    evals = evaluar_universo(unidades, esc, p, inv)
    vivos = sorted(
        ((u, e) for u, e in zip(unidades, evals, strict=True) if not e.excluido),
        key=lambda x: -x[1].score,
    )
    return [u.unidad_key for u, _ in vivos]


base = _ranking(r.unidades)
pos_base = {k: i for i, k in enumerate(base)}
umbral = max(1, int(len(base) * 0.10))
print(f"== medicion catalizador.factor_operativa (base: {len(base)} rankeadas) ==")
print(f"  hoy (1.0): top 10 = {' '.join(base[:10])}\n")

for factor in (0.5, 0.25, 0.0):
    valores, stats = catalizadores_en_memoria(con, p, ahora, factor_operativa=factor)
    if not valores:
        print(f"  factor {factor}: sin estaciones elegibles — no medible")
        continue
    unidades_v = [
        replace(u, catalizador=D(str(valores[u.microzona_id][1])))
        if u.microzona_id in valores
        else u
        for u in r.unidades
    ]
    rank_v = _ranking(unidades_v)
    pos_v = {k: i for i, k in enumerate(rank_v)}
    movidas = sum(1 for k, i in pos_base.items() if k in pos_v and abs(pos_v[k] - i) > umbral)
    # el "bono RM" a la vista: catalizador medio de las rankeadas, RM vs regiones
    rm = [
        float(x.catalizador) for x in unidades_v if alcance.region(x.comuna_id) == "metropolitana"
    ]
    reg = [
        float(x.catalizador) for x in unidades_v if alcance.region(x.comuna_id) != "metropolitana"
    ]
    media_rm = sum(rm) / len(rm) if rm else 0.0
    media_reg = sum(reg) / len(reg) if reg else 0.0
    print(
        f"  factor {factor:<4} movidas >10%: {movidas:>4} de {len(base)} "
        f"({movidas / len(base):.1%}) · catalizador medio RM={media_rm:.2f} "
        f"regiones={media_reg:.2f} · elegibles={stats['elegibles']}"
    )
    if rank_v[:10] != base[:10]:
        print(f"    top 10 -> {' '.join(rank_v[:10])}")
    else:
        print("    top 10 identico al de hoy")

print(
    "\n  LECTURA: el factor que deja el 'bono RM' cerca del catalizador de regiones sin"
    "\n  romper el top honesto es el candidato para el E catalizador.factor_operativa."
    "\n  Las EN CONSTRUCCION con fecha creible no se tocan en ninguna variante."
)
con.close()
