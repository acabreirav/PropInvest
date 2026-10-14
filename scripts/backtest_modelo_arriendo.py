"""Backtest §8.4 del modelo hedónico de arriendo (T-958) sobre la base real.

Tres cosas, en orden:

  1. ENTRENAMIENTO: con qué se entrena (obs, celdas, grupos excluidos por temporada),
     la elasticidad β del tamaño y los efectos extremos de microzona — números que el
     usuario puede contrastar con lo que sabe del mercado.
  2. BACKTEST leave-one-cell-out sobre las celdas densas (n>=8): el error del modelo
     al predecir celdas cuya verdad SÍ conocemos, sin verlas. Global, por comuna y por
     tipología, con las 15 peores a la vista, y el veredicto contra los umbrales de
     `params.yml` — el mismo gate que decide si la sección 6 del informe se publica.
  3. COBERTURA: cuántas unidades hoy ND por `sin_comparables` el modelo puede estimar,
     cruzadas con la profundidad censal de arriendo (la tesis del usuario: celda rala
     con demanda honda = poca competencia; rala sin demanda = trampa).

Uso:  uv run python scripts/backtest_modelo_arriendo.py
Pegar la salida completa en la conversación / RUNLOG.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from flujocero.agg import modelo_arriendo as ma  # noqa: E402
from flujocero.agg import oportunidades as op  # noqa: E402
from flujocero.agg.arriendo import comparables_desde_duckdb, m2_amoblados_por_grupo  # noqa: E402
from flujocero.alcance import desde_config  # noqa: E402
from flujocero.config import cargar  # noqa: E402

ahora = datetime.now(UTC)
p = cargar("params")
alcance = desde_config(cargar("zonas"))
rangos = p.crudo("ingresos.rangos_m2")
tope = p.d("calidad.contaminacion_temporada_max")
k = float(p.d("modelo_arriendo.encogimiento_celda_k"))
con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)

comps, _ = comparables_desde_duckdb(con, ahora)
amoblados = m2_amoblados_por_grupo(con, ahora)

# ------------------------------------------------------------------- 1 · entrenamiento
print("== 1 · entrenamiento sobre los comparables limpios ==")
modelo = ma.entrenar(comps, rangos, amoblados, tope, k_encogimiento=k)
if modelo is None:
    raise SystemExit(
        "  el modelo no junta el minimo estructural "
        f"({ma.MIN_OBS_ENTRENAMIENTO} obs / {ma.MIN_CELDAS_ENTRENAMIENTO} celdas): ND"
    )
print(
    f"  obs={modelo.n_obs} · celdas={modelo.n_celdas} · "
    f"grupos excluidos por temporada={modelo.grupos_temporada_excluidos}"
)
print(f"  beta (elasticidad log-log del m²) = {modelo.beta:.3f}")
print("  (esperable: entre 0 y 1 — el arriendo sube con el tamaño, menos que proporcional)")
efectos = sorted(modelo.efecto_microzona.items(), key=lambda kv: kv[1])
print("  microzonas mas BARATAS ajustado por tamaño/tipologia:")
for mz, ef in efectos[:5]:
    print(f"    {mz:<40} {ef:+.3f} (x{2.718281828**ef:.2f}, n={modelo.n_microzona[mz]})")
print("  mas CARAS:")
for mz, ef in efectos[-5:]:
    print(f"    {mz:<40} {ef:+.3f} (x{2.718281828**ef:.2f}, n={modelo.n_microzona[mz]})")

# ------------------------------------------------------------------------ 2 · backtest
print("\n== 2 · backtest leave-one-cell-out sobre celdas densas (n>=8) ==")
bt = ma.backtest_loco(comps, rangos, amoblados, tope, k_encogimiento=k)
print(
    f"  celdas densas={bt.celdas_densas} · evaluadas={len(bt.errores)} · "
    f"no predecibles sin si mismas={bt.no_predecibles} · reentrenos sin minimo={bt.sin_modelo}"
)
if not bt.errores:
    raise SystemExit("  sin celdas evaluables: no hay veredicto")
print(f"  |error| mediano = {bt.error_abs_mediano:.1%} · p75 = {bt.error_abs_p75:.1%}")
sobre = sorted(e.error for e in bt.errores)
print(
    f"  sesgo (mediana del error CON signo) = {sobre[len(sobre) // 2]:+.1%}"
    "  (positivo = el modelo sobreestima, el lado que infla)"
)
for u in (0.10, 0.15, 0.20):
    n = sum(1 for e in bt.errores if abs(e.error) > u)
    print(f"  celdas con |error| > {u:.0%}: {n}  ({n / len(bt.errores):.0%})")
print("\n  por comuna (n celdas, |error| mediano):")
for comuna, (n, err) in bt.por_grupo("comuna").items():
    print(f"    {comuna:<24} n={n:<4} {err:.1%}")
print("  por tipologia:")
for tip, (n, err) in bt.por_grupo("tipologia").items():
    print(f"    {tip:<24} n={n:<4} {err:.1%}")
print("\n  las 15 peores celdas (modelo vs mediana real):")
for e in sorted(bt.errores, key=lambda e: -abs(e.error))[:15]:
    print(
        f"    {e.microzona_id} · {e.tipologia:<5} n={e.n:<3} "
        f"real={e.mediana_real_uf:>6.2f} UF → modelo={e.mediana_modelo_uf:>6.2f}  ({e.error:+.1%})"
    )

umbral_med = float(p.d("modelo_arriendo.error_mediano_max"))
umbral_p75 = float(p.d("modelo_arriendo.error_p75_max"))
min_celdas = int(p.d("modelo_arriendo.min_celdas_backtest"))
pasa = bt.pasa(umbral_med, umbral_p75, min_celdas)
print(
    f"\n  GATE (params modelo_arriendo.*): mediano<={umbral_med:.0%}, p75<={umbral_p75:.0%}, "
    f"celdas>={min_celdas} → {'PASA: la seccion 6 del informe se publica' if pasa else 'NO PASA: la seccion 6 lo dira sin publicar estimaciones'}"
)

# ------------------------------------------------------- 3 · cobertura y tesis censal
print("\n== 3 · cobertura: las ND por sin_comparables que el modelo puede estimar ==")
r = op.emparejar_con_params(con, p, alcance=alcance, ahora=ahora)
prof = {
    mid: float(v)
    for mid, v in con.execute(
        "SELECT microzona_id, profundidad_arriendo FROM agg_riesgo_microzona "
        "WHERE profundidad_arriendo IS NOT NULL"
    ).fetchall()
}
vp = sorted(prof.values())
prof_med = vp[len(vp) // 2] if vp else None
estimables = honda = baja = sin_censo = 0
vistos: set[tuple] = set()
top: list[tuple[float, float, str, str, str, float, int]] = []
for key, mz, tip, m2, precio in r.sin_comparables_detalle:
    firma = (mz, tip, m2, precio)
    if firma in vistos:
        continue
    vistos.add(firma)
    pred = ma.predecir(modelo, mz, tip, m2)
    if pred is None:
        continue
    estimables += 1
    pf = prof.get(mz)
    if pf is None:
        sin_censo += 1
    elif prof_med is not None and pf >= prof_med:
        honda += 1
    else:
        baja += 1
    y_p25 = float(pred.p25_uf) * 12 / float(precio)
    y = float(pred.arriendo_uf) * 12 / float(precio)
    top.append((y_p25, y, key, mz, tip, pf if pf is not None else -1.0, pred.n_celda))
print(
    f"  sin_comparables={r.descartes['sin_comparables']} · unicas={len(vistos)} · "
    f"estimables por el modelo={estimables}"
)
if prof_med is not None:
    print(
        f"  tesis censal (profundidad mediana del alcance {prof_med:.0%}): "
        f"demanda HONDA={honda} · demanda baja={baja} · sin censo={sin_censo}"
    )
print("  top 15 por yield del PISO del intervalo (p25 — castiga el optimismo):")
for y25, y, key, mz, tip, pf, n_c in sorted(top, reverse=True)[:15]:
    censal = f"prof {pf:.0%}" if pf >= 0 else "sin censo"
    print(
        f"    {key:<18} {mz} · {tip:<5} yield piso {y25:.2%} (central {y:.2%}) · "
        f"n_celda={n_c} · {censal}"
    )
print(
    "\n  OJO: nada de esto entra al ranking (§12). Es el radar de la seccion 6 del"
    "\n  informe, que solo se publica cuando el gate de arriba PASA."
)

con.close()
