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

anchas: list[tuple[D, str, D, D, object]] = []  # (|desv|, key, mediana_angosta, asignado, unidad)
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
            anchas.append((abs((asignado - m20) / m20), u.unidad_key, m20, asignado, u))

# Firma S1 (verificador D-024, hallazgo 1): un nucleo cuyo m² tipico se corre >10%
# del m² de la unidad no es vara independiente — ancha y nucleo pueden estar sesgados
# juntos. Se cuenta ADEMAS de la desviacion de medianas.
s1 = 0
s1_keys: set[str] = set()
for u in base.unidades:
    m2 = u.m2_utiles
    grupo = grupos.get((u.microzona_id, u.tipologia), [])
    ventana20 = max(D(3), m2 * D("0.20"))
    m2s_nucleo = [m2c for m2c, _ in grupo if abs(m2c - m2) <= ventana20]
    if 3 <= len(m2s_nucleo) < op.MIN_COMPARABLES:  # rankeo en ancha, nucleo medible
        tipico = percentil(m2s_nucleo, D("0.5"))
        if abs(tipico - m2) > m2 * D("0.10"):
            s1 += 1
            s1_keys.add(u.unidad_key)
print(f"\n== 2 · unidades asignadas en ventana ANCHA con ±20% medible (n>=3): {len(anchas)} ==")
print(f"  firma S1 (nucleo con tipico corrido >10% del m² de la unidad): {s1}")
print("  (si es grande, la vara del nucleo no es independiente — T-957)")
if anchas:
    desvs = sorted(d for d, *_ in anchas)
    for umbral in (D("0.10"), D("0.15"), D("0.20")):
        n = sum(1 for d in desvs if d > umbral)
        print(f"  desviación > {umbral:.0%}: {n}  ({n / len(anchas):.0%} de las anchas)")
    print("  las 15 peores (asignado vs mediana de su ±20%):")
    for d, k, m20, asig, _u in sorted(anchas, key=lambda t: t[0], reverse=True)[:15]:
        print(
            f"    {k:<18} ±20%={m20:>7.2f} UF → asignado={asig:>7.2f}  ({'+' if asig > m20 else '-'}{d:.1%})"
        )

# 2d · T-957: la seccion 2 NO puede absolver a las firmas S1 — su punto es que nucleo
# y ancha pueden estar sesgados JUNTOS, asi que una desviacion chica entre ellos no
# prueba nada. La vara INDEPENDIENTE que T-957 pedia ("log-log arriendo~m² dentro de
# mz×tip") ya existe: el modelo hedonico de T-958, con elasticidad por tipologia.
# Se compara la asignacion de cada ancha contra la prediccion del modelo, separando
# S1 de no-S1. Matiz honesto: el modelo tampoco es del todo independiente (el ajuste
# de celda usa los mismos comps del grupo) y su propio error mediano es ~6% (backtest
# 14-oct), asi que divergencias bajo ~15% son ruido; lo que importa es si las S1
# divergen MAS que las no-S1 y cuantas superan el error propio del modelo.
print("\n== 2d · T-957: las anchas contra la vara independiente (modelo hedonico T-958) ==")
from flujocero.agg import modelo_arriendo as mamod  # noqa: E402
from flujocero.agg.arriendo import m2_amoblados_por_grupo  # noqa: E402

amo_g = m2_amoblados_por_grupo(con, ahora)
k_enc = float(p.d("modelo_arriendo.encogimiento_celda_k"))
modelo_h = mamod.entrenar(comps, rangos, amo_g, tmax, k_encogimiento=k_enc)
if modelo_h is None:
    print("  modelo ND (sin minimo estructural): la medicion queda pendiente")
else:
    por_clase: dict[str, list[D]] = {"S1": [], "no-S1": []}
    detalle_2d: list[tuple[D, str, str, D, D]] = []  # (|ratio|, key, clase, asignado, modelo)
    for _d, key, _m20, asignado, u in anchas:
        pred = mamod.predecir(modelo_h, u.microzona_id, u.tipologia, u.m2_utiles)
        if pred is None or not pred.arriendo_uf:
            continue
        ratio = (asignado - pred.arriendo_uf) / pred.arriendo_uf
        clase = "S1" if key in s1_keys else "no-S1"
        por_clase[clase].append(abs(ratio))
        detalle_2d.append((abs(ratio), key, clase, asignado, pred.arriendo_uf))
    for clase, vals in por_clase.items():
        if not vals:
            print(f"  {clase}: sin unidades medibles")
            continue
        med = percentil(sorted(vals), D("0.5"))
        print(
            f"  {clase:<6} n={len(vals):<4} |asignado vs modelo| mediano={med:.1%} · "
            f">15%: {sum(1 for v in vals if v > D('0.15'))} · "
            f">20%: {sum(1 for v in vals if v > D('0.20'))}"
        )
    print("  las 10 mayores divergencias (positivo = la ventana esta SOBRE el modelo):")
    for r, key, clase, asig, pm in sorted(detalle_2d, key=lambda t: t[0], reverse=True)[:10]:
        signo = "+" if asig > pm else "-"
        print(
            f"    {key:<18} [{clase:<5}] ventana={asig:>7.2f} UF vs modelo={pm:>7.2f}  ({signo}{r:.1%})"
        )
    print("  (si las S1 divergen como las no-S1 y pocas superan el error propio del")
    print("   modelo, T-957 se cierra como 'marca, no motor'; si divergen mas y hacia")
    print("   ARRIBA, la vara del nucleo necesita el ajuste por tamanio en el motor)")

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

# 5 · pregunta del usuario (14-oct): ¿m² como variable CONTINUA? El emparejamiento ya
# es continuo en la SELECCION (ventana alrededor del m² propio), pero la ASIGNACION es
# la mediana cruda del pool: si la unidad queda descentrada DENTRO de la ventana (hasta
# ±20%, que el guardia de descentrado permite), hereda el arriendo del tamanio tipico
# del pool, no del suyo. Con beta~0,45, un corrimiento de +17% de m² (el 60 vs 70 del
# usuario) son ~+7% de arriendo. Aqui se mide cuanto corrimiento REAL hay en los pools
# aceptados de ±20% y cuanto arriendo implica, ANTES de decidir si la asignacion misma
# se ajusta por tamanio (candidato T-959 — mover el numerador de TODOS los yields es
# decision 8.4 con medicion, no un commit).
print("\n== 5 · corrimiento de m² DENTRO de la ventana ±20% aceptada (asignacion cruda) ==")
BETA_REF = D("0.45")  # el respaldo E calidad.elasticidad_m2_vara (beta global 0,446)
factores: list[tuple[D, str, D, D]] = []  # (|factor-1|, key, m2, tipico)
for u in base.unidades:
    m2 = u.m2_utiles
    grupo = grupos.get((u.microzona_id, u.tipologia), [])
    ventana20 = max(D(3), m2 * D("0.20"))
    pool20m = [m2c for m2c, _ in grupo if abs(m2c - m2) <= ventana20]
    if len(pool20m) < op.MIN_COMPARABLES:
        continue  # asignada en ancha: su vara ya se ajusta por D-026
    tipico = percentil(pool20m, D("0.5"))
    if not tipico:
        continue
    factor = D(str((float(m2) / float(tipico)) ** float(BETA_REF)))
    factores.append((abs(factor - 1), u.unidad_key, m2, tipico))
if factores:
    vals = sorted(f for f, *_ in factores)
    mediana_f = percentil(vals, D("0.5"))
    p90_f = percentil(vals, D("0.9"))
    print(f"  unidades asignadas en ±20%: {len(factores)}")
    print(
        f"  correccion de arriendo implicada |(m2/tipico)^0.45 - 1|: mediana {mediana_f:.1%} · p90 {p90_f:.1%}"
    )
    for umbral in (D("0.03"), D("0.05"), D("0.08")):
        n = sum(1 for v in vals if v > umbral)
        print(f"  unidades con correccion implicada > {umbral:.0%}: {n}  ({n / len(vals):.0%})")
    print("  las 10 mas corridas (su arriendo hereda el del tamanio tipico del pool):")
    for f, k, m2v, tipv in sorted(factores, key=lambda t: t[0], reverse=True)[:10]:
        lado = "chica vs pool" if m2v < tipv else "grande vs pool"
        print(f"    {k:<18} {m2v:>5.0f} m² vs tipico {tipv:>5.0f}  ({lado}, correccion {f:+.1%})")
    print("  (mediana y p90 chicas => la asignacion cruda basta y T-959 no se abre;")
    print("   una cola gorda sobre 5-8% => medir el ajuste de asignacion por tamanio)")
else:
    print("  sin unidades medibles")

con.close()
