"""Medición §8.4 del colapso de relistings (D-021): el ranking CON vs SIN colapso.

El verificador §7.6 demostró que el colapso NO es direccionalmente conservador: si la
firma repetida son unidades distintas reales bajo la mediana (plantas idénticas a precio
de lista), quitar sus copias SUBE el arriendo asignado — y con él el yield. Igual que en
T-949, la decisión no se cierra con un razonamiento sino con esta medición sobre la base
real. Correr y pegar el resultado en el RUNLOG / la conversación.

Uso:  uv run python scripts/medir_colapso_relistings.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from flujocero.agg import arriendo as agg  # noqa: E402
from flujocero.agg import oportunidades as op  # noqa: E402
from flujocero.alcance import desde_config  # noqa: E402
from flujocero.config import cargar  # noqa: E402
from flujocero.finance.escenarios import escenario_base, evaluar_universo  # noqa: E402

ahora = datetime.now(UTC)
p, inv = cargar("params"), cargar("inversionista")
alcance = desde_config(cargar("zonas"))
rangos = p.crudo("ingresos.rangos_m2")
con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)


def correr(colapsar: bool):
    """El mismo emparejamiento del ranking, con el colapso encendido o apagado."""
    original = op.comparables_desde_duckdb
    op.comparables_desde_duckdb = lambda c, a=None: agg.comparables_desde_duckdb(
        c, a, colapsar_relistings=colapsar
    )
    try:
        r = op.emparejar(con, rangos, alcance=alcance, ahora=ahora)
    finally:
        op.comparables_desde_duckdb = original
    return {u.unidad_key: u for u in r.unidades}, r


con_colapso, r_con = correr(True)
sin_colapso, r_sin = correr(False)

comunes = set(con_colapso) & set(sin_colapso)
solo_sin = set(sin_colapso) - set(con_colapso)  # el colapso las dejo bajo n=8 → ND
solo_con = set(con_colapso) - set(sin_colapso)  # raro, pero se reporta

suben = bajan = iguales = 0
mayores: list[tuple[Decimal, str, Decimal, Decimal]] = []
for k in comunes:
    a, b = sin_colapso[k].arriendo_mensual_uf, con_colapso[k].arriendo_mensual_uf
    if a is None or b is None or a == 0:
        continue
    delta = (b - a) / a
    if delta > 0:
        suben += 1
    elif delta < 0:
        bajan += 1
    else:
        iguales += 1
    if abs(delta) > Decimal("0.0001"):
        mayores.append((abs(delta), k, a, b))

print(f"== colapso de relistings: {len(comunes)} unidades comparables ==")
print(f"  arriendo SUBE con el colapso: {suben}")
print(f"  arriendo BAJA con el colapso: {bajan}")
print(f"  igual: {iguales}")
print(f"  pasan a ND por el colapso (pool fresco < 8): {len(solo_sin)}")
if solo_con:
    print(f"  rankean SOLO con colapso (revisar): {len(solo_con)}")
umbral = Decimal("0.10")
grandes = [m for m in mayores if m[0] > umbral]
print(f"  con cambio > 10%: {len(grandes)}  (gatillo §8.4 si mueve el ranking)")
print("\n  los 15 cambios mas grandes (|delta| arriendo UF, sin→con):")
for d, k, a, b in sorted(mayores, reverse=True)[:15]:
    print(f"    {k:<18} {a:>7.2f} → {b:>7.2f}  ({'+' if b > a else '-'}{d:.1%})")

# el efecto sobre el TOP: score con exclusiones, mismas dos corridas
for nombre, unidades in (("CON colapso", con_colapso), ("SIN colapso", sin_colapso)):
    evals = evaluar_universo(list(unidades.values()), escenario_base(p, inv), p, inv)
    vivos = sorted(
        (
            (ev.score, u.unidad_key)
            for u, ev in zip(unidades.values(), evals, strict=True)
            if not ev.excluido
        ),
        reverse=True,
    )
    print(f"\n  top 10 {nombre}: " + ", ".join(k for _, k in vivos[:10]))

con.close()
