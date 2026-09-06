"""Imprime el último snapshot del top con las columnas que deciden: arriendo asignado,
equilibrio con colchón, flujo y score. Complemento de consola del informe HTML.

Uso:  uv run python scripts/ver_top.py
"""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
snaps = sorted((RAIZ / "data" / "informes").glob("top-*.json"))
if not snaps:
    raise SystemExit("sin snapshots en data/informes")
top = json.loads(snaps[-1].read_text(encoding="utf-8"))
print(f"{snaps[-1].name} · {len(top)} filas\n")
print(
    f"{'#':<3}{'microzona':<38}{'tip':<6}{'m²':>4}{'arriendo':>10}{'equilib.':>10}"
    f"{'colchón':>9}{'flujo':>10}{'score':>7}"
)
for i, f in enumerate(top, 1):
    arr, eq = f.get("arriendo_clp", 0), f.get("equilibrio_clp", 0)
    colchon = f"{(arr - eq) / arr:+.0%}" if arr and eq else "ND"
    eq_txt = f"${eq:,.0f}" if eq else "ND"
    print(
        f"{i:<3}{f['microzona_id']:<38}{f['tipologia']:<6}{f['m2']:>4.0f}"
        f"{'$' + format(arr, ','):>10}{eq_txt:>10}{colchon:>9}"
        f"{'$' + format(f.get('flujo_clp', 0), ','):>10}{f['score']:>7.0f}".replace(",", ".")
    )
