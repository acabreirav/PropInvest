"""Medición §8.4 de los guardias de ventana (T-955/D-023) sobre la base real.

El verificador de D-023 demostró que el balance de lados cuenta cabezas y no mide el
DAÑO (la mediana ancha puede quedar inflada con 9/13), y que la ±20% exenta puede
cargarse entera a un lado sin que ningún guardia salte (el descentrado es vacuo ahí:
su límite es igual al ancho de la ventana). Este script mide ambas cosas donde
corresponde — la base real — para elegir el arreglo definitivo con datos:

  1. BARRIDO del umbral de balance (0.60 / 0.70 actual / 0.80 / apagado): cuántas
     unidades rankean, cuántas caen por `ventana_desbalanceada`, cómo cambia el top.
  2. DAÑO OBSERVADO en ventanas anchas: para cada unidad asignada en ±30/±40, la
     desviación de su arriendo vs la mediana de su propia ventana ±20% (n>=3) — el
     tercer candidato de T-955, medido antes de implementarlo.
  3. HALLAZGO 2: cuántas unidades rankeadas en ±20% tienen un lado con >70% del pool
     (hoy sin guardia) y cuánto se desvía su arriendo del segmento de su propio lado.

Uso:  uv run python scripts/medir_guardias_ventana.py
Pegar la salida completa en la conversación / RUNLOG.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from flujocero.agg import oportunidades as op  # noqa: E402
from flujocero.agg.arriendo import comparables_desde_duckdb, percentil  # noqa: E402
from flujocero.alcance import desde_config  # noqa: E402
from flujocero.config import cargar  # noqa: E402

ahora = datetime.now(UTC)
p, inv = cargar("params"), cargar("inversionista")
alcance = desde_config(cargar("zonas"))
rangos = p.crudo("ingresos.rangos_m2")
tmax = p.d("calidad.contaminacion_temporada_max")
con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)

# ---------------------------------------------------- 1 · barrido del umbral de balance
print("== 1 · barrido de calidad.ventana_balance_lado_max ==")
resultados = {}
for etiqueta, umbral in (
    ("0.60", D("0.60")),
    ("0.70 (actual)", D("0.70")),
    ("0.80", D("0.80")),
    ("apagado", D(1)),
):
    r = op.emparejar(
        con, rangos, alcance=alcance, ahora=ahora, temporada_max=tmax, balance_lado_max=umbral
    )
    resultados[etiqueta] = r
    print(
        f"  {etiqueta:<14} rankean={len(r.unidades):<5} "
        f"desbalanceadas={r.descartes['ventana_desbalanceada']:<4} "
        f"sin_comparables={r.descartes['sin_comparables']:<4} "
        f"temporada={r.descartes['mercado_temporada']}"
    )
base = resultados["0.70 (actual)"]
apagado = resultados["apagado"]
solo_sin_guardia = {u.unidad_key for u in apagado.unidades} - {u.unidad_key for u in base.unidades}
print(f"  rankean SOLO sin guardia (las que el 0.70 apaga): {len(solo_sin_guardia)}")

# ------------------------------------- 2 y 3 · daño observado, con la corrida actual
comps, _ = comparables_desde_duckdb(con, ahora)
grupos: dict[tuple[str, str], list[tuple[D, D]]] = {}
for c in comps:
    grupos.setdefault((c.microzona_id, c.tipologia), []).append((c.m2_utiles, c.arriendo_uf))

anchas: list[tuple[D, str, D, D]] = []  # (|desv|, key, mediana_angosta, asignado)
veinte_cargadas = 0
veinte_total = 0
for u in base.unidades:
    m2, asignado = u.m2_utiles, u.arriendo_mensual_uf
    grupo = grupos.get((u.microzona_id, u.tipologia), [])
    ventana20 = max(D(3), m2 * D("0.20"))
    pool20 = [(m2c, a) for m2c, a in grupo if abs(m2c - m2) <= ventana20]
    if len(pool20) >= op.MIN_COMPARABLES:
        # asignada en ±20%: medir carga de lados (hallazgo 2, hoy sin guardia)
        veinte_total += 1
        chico = sum(1 for m2c, _ in pool20 if m2c < m2)
        grande = sum(1 for m2c, _ in pool20 if m2c > m2)
        if max(chico, grande) > len(pool20) * D("0.70"):
            veinte_cargadas += 1
    elif len(pool20) >= 3 and asignado:
        # asignada en ventana ancha: desviación vs la mediana de SU ±20% (candidato 3)
        m20 = percentil([a for _, a in pool20], D("0.5"))
        if m20:
            anchas.append((abs((asignado - m20) / m20), u.unidad_key, m20, asignado))

print(f"\n== 2 · unidades asignadas en ventana ANCHA con ±20% medible (n>=3): {len(anchas)} ==")
if anchas:
    desvs = sorted(d for d, *_ in anchas)
    for umbral in (D("0.10"), D("0.15"), D("0.20")):
        n = sum(1 for d in desvs if d > umbral)
        print(f"  desviación > {umbral:.0%}: {n}  ({n / len(anchas):.0%} de las anchas)")
    print("  las 15 peores (asignado vs mediana de su ±20%):")
    for d, k, m20, asig in sorted(anchas, reverse=True)[:15]:
        print(
            f"    {k:<18} ±20%={m20:>7.2f} UF → asignado={asig:>7.2f}  ({'+' if asig > m20 else '-'}{d:.1%})"
        )

print(
    f"\n== 3 · unidades rankeadas en ±20% con un lado >70% del pool: {veinte_cargadas} de {veinte_total} =="
)
print("  (hallazgo 2 del verificador: hoy SIN guardia — si el número es grande, el")
print("   arreglo definitivo tiene que cubrir también la ±20%, no solo las anchas)")

con.close()
