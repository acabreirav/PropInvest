"""Medición §8.4 de los guardias de ventana (T-955/D-023) sobre la base real.

Tras D-024 (guardia de desplazamiento ASIMETRICO, solo el alza veta), este script
mide sobre la base real lo que el verificador de D-024 dejo pendiente: la firma S1
(nucleo cargado validando una ancha cargada: ambos sesgados en la misma direccion),
las unidades cuyo VALOR cambia entre guardia activo y apagado (invisibles para una
comparacion de conjuntos), y el barrido del umbral:

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
print("== 1 · barrido de calidad.desvio_ventana_ancha_max ==")
resultados = {}
for etiqueta, umbral in (
    ("0.10", D("0.10")),
    ("0.15 (actual)", D("0.15")),
    ("0.20", D("0.20")),
    ("apagado", D(99)),
):
    r = op.emparejar(
        con, rangos, alcance=alcance, ahora=ahora, temporada_max=tmax, desvio_ancha_max=umbral
    )
    resultados[etiqueta] = r
    print(
        f"  {etiqueta:<14} rankean={len(r.unidades):<5} "
        f"desviadas={r.descartes['ventana_desviada']:<4} "
        f"sin_comparables={r.descartes['sin_comparables']:<4} "
        f"temporada={r.descartes['mercado_temporada']}"
    )
base = resultados["0.15 (actual)"]
apagado = resultados["apagado"]
solo_sin_guardia = {u.unidad_key for u in apagado.unidades} - {u.unidad_key for u in base.unidades}
print(f"  rankean SOLO sin guardia (las que el 0.15 apaga): {len(solo_sin_guardia)}")

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

# Firma S1 (verificador D-024, hallazgo 1): un nucleo cuyo m² tipico se corre >10%
# del m² de la unidad no es vara independiente — ancha y nucleo pueden estar sesgados
# juntos. Se cuenta ADEMAS de la desviacion de medianas.
s1 = 0
for u in base.unidades:
    m2 = u.m2_utiles
    grupo = grupos.get((u.microzona_id, u.tipologia), [])
    ventana20 = max(D(3), m2 * D("0.20"))
    m2s_nucleo = [m2c for m2c, _ in grupo if abs(m2c - m2) <= ventana20]
    if 3 <= len(m2s_nucleo) < op.MIN_COMPARABLES:  # rankeo en ancha, nucleo medible
        tipico = percentil(m2s_nucleo, D("0.5"))
        if abs(tipico - m2) > m2 * D("0.10"):
            s1 += 1
print(f"\n== 2 · unidades asignadas en ventana ANCHA con ±20% medible (n>=3): {len(anchas)} ==")
print(f"  firma S1 (nucleo con tipico corrido >10% del m² de la unidad): {s1}")
print("  (si es grande, la vara del nucleo no es independiente — T-957)")
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

# El número que faltaba para la decisión (corrida 13-oct): la sección 2 mide solo las
# anchas que PASARON el guardia. Acá se mide el daño de las que el guardia APAGA: con
# el guardia desactivado, ¿cuánto se desvía su asignación de su propio núcleo ±20%?
# Si estas desviaciones también son chicas, el guardia de conteo se reemplaza por el
# de desplazamiento de mediana (candidato 3 de T-955) y esas unidades vuelven honestas.
bloqueadas: list[tuple[D, str, D, D]] = []
sin_nucleo = 0
for u in apagado.unidades:
    if u.unidad_key not in solo_sin_guardia:
        continue
    m2, asignado = u.m2_utiles, u.arriendo_mensual_uf
    grupo = grupos.get((u.microzona_id, u.tipologia), [])
    ventana20 = max(D(3), m2 * D("0.20"))
    pool20 = [a for m2c, a in grupo if abs(m2c - m2) <= ventana20]
    if len(pool20) >= 3 and asignado:
        m20 = percentil(pool20, D("0.5"))
        if m20:
            bloqueadas.append((abs((asignado - m20) / m20), u.unidad_key, m20, asignado))
            continue
    sin_nucleo += 1

print(f"\n== 2b · las {len(solo_sin_guardia)} que el guardia 0.15 apaga: su daño SIN guardia ==")
if bloqueadas:
    for umbral in (D("0.10"), D("0.15"), D("0.20")):
        n = sum(1 for d, *_ in bloqueadas if d > umbral)
        print(f"  desviación > {umbral:.0%}: {n}  ({n / len(bloqueadas):.0%} de las medibles)")
    print(f"  sin núcleo ±20% medible (n<3): {sin_nucleo}")
    print("  las 15 peores (asignado vs mediana de su ±20%):")
    for d, k, m20, asig in sorted(bloqueadas, reverse=True)[:15]:
        print(
            f"    {k:<18} ±20%={m20:>7.2f} UF → asignado={asig:>7.2f}  "
            f"({'+' if asig > m20 else '-'}{d:.1%})"
        )
else:
    print(f"  ninguna medible (sin núcleo ±20% con n>=3: {sin_nucleo})")

# Hallazgo 2 del verificador D-024: comparar conjuntos de llaves esconde a las que
# rankean en ambas corridas pero con OTRO arriendo (la ±30% vetada -> ±40% distinta).
por_llave_base = {u.unidad_key: u.arriendo_mensual_uf for u in base.unidades}
cambiadas = [
    (
        abs((por_llave_base[u.unidad_key] - u.arriendo_mensual_uf) / u.arriendo_mensual_uf),
        u.unidad_key,
        u.arriendo_mensual_uf,
        por_llave_base[u.unidad_key],
    )
    for u in apagado.unidades
    if u.unidad_key in por_llave_base
    and u.arriendo_mensual_uf
    and por_llave_base[u.unidad_key] != u.arriendo_mensual_uf
]
print(f"\n== 2c · rankean en ambas corridas pero con OTRO arriendo: {len(cambiadas)} ==")
for d, k, sin_g, con_g in sorted(cambiadas, reverse=True)[:10]:
    print(f"    {k:<18} sin guardia={sin_g:>7.2f} → con guardia={con_g:>7.2f}  ({d:.1%})")

print(
    f"\n== 3 · unidades rankeadas en ±20% con un lado >70% del pool: {veinte_cargadas} de {veinte_total} =="
)
print("  (hallazgo 2 del verificador: hoy SIN guardia — si el número es grande, el")
print("   arreglo definitivo tiene que cubrir también la ±20%, no solo las anchas)")

con.close()
