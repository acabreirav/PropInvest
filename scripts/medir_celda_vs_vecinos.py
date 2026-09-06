"""Medición §8.4 · ¿cuánto cambia el arriendo del top si la celda fuera por m² vecinos?

Caso que la motiva (06-sep, auditoría del top 1): un 2D1B de 36 m² tomó la mediana de la
celda 2D1B × 35-50, cuyos comparables se concentran en 42-48 m² — el tramo de 15 m² de
ancho le regaló arriendo a la unidad chica. La alternativa a medir: mediana de los k=8
comparables MÁS CERCANOS en m² dentro de (microzona, tipología), con los mismos filtros
del §7.3 más la limpieza de clusters promocionales.

Este script SOLO MIDE (no cambia el ranking): imprime, para cada unidad del último
snapshot del top, el arriendo de celda contra el de vecinos, el ancho de ventana que
necesitó, y el resumen de cuántas posiciones se moverían. La decisión de cambiar el
emparejamiento es §8.4 — se toma mirando esta salida.

Uso:  uv run python scripts/medir_celda_vs_vecinos.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from flujocero.quality.comparabilidad import NO_COMPARABLE  # noqa: E402
from flujocero.quality.sospechosos import _clusters_promocionales  # noqa: E402

K = 8

snaps = sorted((RAIZ / "data" / "informes").glob("top-*.json"))
if not snaps:
    raise SystemExit("sin snapshots en data/informes — corre `cli informe-semanal` primero")
top = json.loads(snaps[-1].read_text(encoding="utf-8"))
print(f"snapshot: {snaps[-1].name} ({len(top)} filas)\n")

con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)
filas = con.execute(
    "SELECT comp_id, microzona_id, tipologia, m2_utiles, arriendo_clp "
    "FROM fact_arriendo_comp WHERE activo AND NOT COALESCE(sospechoso, FALSE) "
    "AND arriendo_clp IS NOT NULL AND m2_utiles > 0 AND tipologia IS NOT NULL "
    "AND NOT regexp_matches(lower(COALESCE(source_url, '')), ?)",
    (NO_COMPARABLE.pattern,),
).fetchall()

# limpieza promocional en memoria (la base puede no tener corrida la marca nueva)
from decimal import Decimal as D  # noqa: E402

grupos: dict[str, list[tuple[str, D, D | None, D]]] = {}
for cid, mz, tip, m2, clp in filas:
    grupos.setdefault(mz, []).append((cid, D(str(clp)) / D(str(m2)), D(str(clp)), D(str(m2))))
promos = _clusters_promocionales(grupos)
limpias = [(cid, mz, tip, m2, clp) for cid, mz, tip, m2, clp in filas if cid not in promos]
print(f"comparables limpios: {len(limpias)} ({len(promos)} descartados como cluster promocional)\n")

print(
    f"{'#':<3}{'microzona':<28}{'tip':<6}{'m²':>5}{'celda':>11}{'vecinos':>11}"
    f"{'delta':>8}{'ventana':>9}"
)
deltas = []
for i, f in enumerate(top, 1):
    mz, tip, m2, celda = f["microzona_id"], f["tipologia"], f["m2"], f["arriendo_clp"]
    pool = sorted((abs(c[3] - m2), c[4]) for c in limpias if c[1] == mz and c[2] == tip)[:K]
    if len(pool) < K:
        print(f"{i:<3}{mz:<28}{tip:<6}{m2:>5.0f}{celda:>11,}{'n<8':>11}{'—':>8}{'—':>9}")
        continue
    vecinos = statistics.median(p for _, p in pool)
    ventana = pool[-1][0]
    delta = (vecinos - celda) / celda if celda else 0.0
    deltas.append(delta)
    aviso = " <- ventana ancha" if ventana > 8 else ""
    print(
        f"{i:<3}{mz:<28}{tip:<6}{m2:>5.0f}{celda:>11,}{round(vecinos):>11,}"
        f"{delta:>8.1%}{ventana:>7.0f}m²{aviso}".replace(",", ".")
    )

if deltas:
    print(
        f"\nresumen: mediana |delta| = {statistics.median(abs(d) for d in deltas):.1%}"
        f" · {sum(1 for d in deltas if abs(d) > 0.10)} de {len(deltas)} filas se mueven >10%"
        "\nSi varias filas del top se mueven >10%, el cambio de celda ES material (§8.4):"
        "\nse decide con esta salida a la vista, no se aplica solo."
    )
