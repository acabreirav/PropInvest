"""Auditoría de una celda de arriendo: ¿de dónde salió la mediana que usa el ranking?

Vuelca TODOS los comparables de una microzona con su detalle fila a fila (m², tipología,
GGCC, señales de no-comparable, frescura, aviso) y la mediana por celda (tipología ×
tramo de m²), para contrastar contra lo que se ve en terreno. No toca la red.

Uso:  uv run python scripts/auditar_celda_arriendo.py [patron-de-microzona]
      (por defecto: alberto-hurtado)
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flujocero.quality.comparabilidad import dudoso, no_comparable  # noqa: E402

PATRON = sys.argv[1] if len(sys.argv) > 1 else "alberto-hurtado"
RAIZ = Path(__file__).resolve().parents[1]

con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)
filas = con.execute(
    """
    SELECT microzona_id, tipologia, m2_utiles, arriendo_clp, arriendo_uf,
           gastos_comunes_clp, activo, sospechoso, publicado_desde, visto_primera_vez,
           fetched_at, source_url, comp_id
    FROM fact_arriendo_comp
    WHERE microzona_id LIKE '%' || ? || '%'
    ORDER BY tipologia, m2_utiles
    """,
    (PATRON,),
).fetchall()

if not filas:
    zonas = con.execute(
        "SELECT DISTINCT microzona_id FROM fact_arriendo_comp "
        "WHERE microzona_id LIKE '%estacion%' ORDER BY 1"
    ).fetchall()
    raise SystemExit(
        f"sin comparables para '{PATRON}'. Microzonas de Estación Central en la base: "
        + ", ".join(z[0] for z in zonas)
    )

print(f"== {len(filas)} comparables en microzonas ~ '{PATRON}' ==\n")
print(f"{'tipo':<6}{'m²':>6}{'arriendo':>12}{'GGCC':>10}  {'señales':<28}{'ultima vista':<13}aviso")

TRAMOS = ((0, 25, "<25"), (25, 35, "25-35"), (35, 50, "35-50"), (50, 70, "50-70"), (70, 9e9, "70+"))
celdas: dict[tuple[str, str], list[int]] = defaultdict(list)
usados = descartados = 0
for mz, tip, m2, clp, uf, ggcc, activo, sosp, pub_desde, visto, fetched, url, cid in filas:
    señales = []
    if no_comparable(url):
        señales.append("AMOBLADO/temporada")
    if dudoso(url):
        señales.append("dudoso(gc-incl?)")
    if sosp:
        señales.append("outlier-marcado")
    if not activo:
        señales.append("inactivo")
    mlc = m.group(1) if (m := re.search(r"(MLC-?\d+)", url or cid or "")) else (cid or "?")
    monto = f"${clp:,.0f}".replace(",", ".") if clp else (f"UF {uf}" if uf else "?")
    ggcc_txt = f"${ggcc:,.0f}".replace(",", ".") if ggcc else "ND"
    print(
        f"{tip or 'ND':<6}{(f'{m2:.0f}' if m2 else 'ND'):>6}{monto:>12}{ggcc_txt:>10}  "
        f"{('; '.join(señales) or '-'):<28}{str(fetched.date() if fetched else 'ND'):<13}{mlc}"
    )
    comparable = clp and m2 and tip and not no_comparable(url) and not sosp
    if comparable:
        usados += 1
        tramo = next(t for lo, hi, t in TRAMOS if lo <= m2 < hi)
        celdas[(tip, tramo)].append(int(clp))
    else:
        descartados += 1

print(f"\n== medianas por celda (tipologia × tramo m²) — {usados} usados, {descartados} fuera ==")
for (tip, tramo), montos in sorted(celdas.items()):
    med = statistics.median(montos)
    print(
        f"  {tip:<6}{tramo:<7} n={len(montos):<4} mediana=${med:,.0f}".replace(",", ".")
        + ("   <- n<8: la celda NO rankea" if len(montos) < 8 else "")
    )

activos = sum(1 for f in filas if f[6])
print(
    f"\nsaturacion (proxy B2): {activos} avisos 'activos' en la microzona — OJO: hoy nada"
    "\napaga un aviso (T-945 pendiente), asi que este conteo incluye avisos ya arrendados;"
    "\nes una COTA SUPERIOR de la oferta disponible real."
)
