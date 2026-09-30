"""Evalúa UN aviso del portal por el pipeline completo — la ficha de una unidad a pedido.

No calcula nada a mano: corre el MISMO emparejamiento (ventana de vecinos por m²,
filtros §7.3, alcance §10) y el MISMO motor/score del informe, y muestra dónde queda
la unidad en el ranking real de hoy, con sus comparables a la vista para auditarla.

Uso:  uv run python scripts/evaluar_aviso.py MLC-4418530726
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
from flujocero.agg.arriendo import comparables_desde_duckdb  # noqa: E402
from flujocero.alcance import desde_config  # noqa: E402
from flujocero.config import cargar  # noqa: E402
from flujocero.finance.escenarios import escenario_base, evaluar_universo  # noqa: E402
from flujocero.finance.modelo import arriendo_equilibrio_real  # noqa: E402

if len(sys.argv) != 2:
    raise SystemExit("uso: uv run python scripts/evaluar_aviso.py MLC-XXXXXXXXXX")
clave = sys.argv[1].upper()
if not clave.startswith("MLC-"):
    clave = clave.replace("MLC", "MLC-", 1)

ahora = datetime.now(UTC)
p, inv = cargar("params"), cargar("inversionista")
uf = p.d("macro.valor_uf_clp")
alcance = desde_config(cargar("zonas"))
con = duckdb.connect(str(RAIZ / "data" / "flujocero.duckdb"), read_only=True)

# ---------------------------------------------------------------- la fila y su historia
versiones = con.execute(
    "SELECT valid_from, valid_to, precio_uf, precio_clp, m2_utiles, tipologia, "
    "microzona_id, evidence_level, coalesce(sospechoso, FALSE), fetched_at, source_url "
    "FROM fact_unidad_venta WHERE unidad_key = ? ORDER BY valid_from",
    (clave,),
).fetchall()
if not versiones:
    raise SystemExit(
        f"{clave} no está en la base. O la comuna no se ha recolectado, o el aviso no\n"
        "aparece en los listados permitidos (_Desde_). Corre la recolección de su comuna\n"
        "y reintenta — la ficha directa /MLC- está prohibida por robots (§13.6)."
    )

*_, vigente = versiones
(v_from, _v_to, precio_uf, precio_clp, m2, tip, mz, ev_nivel, sosp, visto, url) = vigente
print(
    f"== {clave} · {tip or 'ND'} · {f'{m2:.0f} m²' if m2 else 'sin m²'} · {mz or 'sin microzona'} =="
)
precio_txt = (
    f"UF {precio_uf:,.0f}".replace(",", ".")
    if precio_uf is not None
    else f"${precio_clp:,.0f} (en pesos)".replace(",", ".")
)
print(f"  precio vigente : {precio_txt} · evidencia {ev_nivel}{' · SOSPECHOSO' if sosp else ''}")
print(f"  visto          : primera vez {versiones[0][0]:%d-%m-%Y} · última {visto:%d-%m-%Y}")
if len(versiones) > 1:
    print(f"  historial      : {len(versiones)} versiones de precio —")
    for vv in versiones:
        pr = (
            f"UF {vv[2]:,.0f}".replace(",", ".")
            if vv[2] is not None
            else f"${vv[3]:,.0f}".replace(",", ".")
        )
        print(f"      {vv[0]:%d-%m-%Y}  {pr}{'  <- vigente' if vv[1] is None else ''}")
    print("      (una baja de precio es señal de compra, §11)")

# --------------------------------------------------- el pipeline completo, no un atajo
r = op.emparejar(con, p.crudo("ingresos.rangos_m2"), alcance=alcance, ahora=ahora)
evals = evaluar_universo(r.unidades, escenario_base(p, inv), p, inv) if r.unidades else []
vivos = sorted(
    ((u, e) for u, e in zip(r.unidades, evals) if not e.excluido), key=lambda x: -x[1].score
)
por_clave = {u.unidad_key: (u, e) for u, e in zip(r.unidades, evals)}

if clave not in por_clave:
    print("\n  NO RANKEA. Diagnóstico (informativo — la verdad es emparejar()):")
    motivo_imp = dict(r.implausibles).get(clave)
    if motivo_imp:
        print(f"    · precio implausible: {motivo_imp}")
    if visto < ahora.replace(tzinfo=UTC) and (ahora - visto).days > 21:
        print(f"    · frescura: última vista hace {(ahora - visto).days} días (>21, §7.3)")
    if ev_nivel != "V":
        print(f"    · evidencia de precio '{ev_nivel}' (el §12 exige V)")
    if mz and alcance.saturada(mz):
        print(f"    · microzona {mz} marcada saturada (§12)")
    if mz and not alcance.en_alcance(mz.split("/")[0]):
        print(f"    · comuna {mz.split('/')[0]} fuera del alcance (§10)")
    if not (mz and tip and m2):
        print("    · le falta microzona, tipología o m²")
    print("    · o su ventana de vecinos no junta n>=8 (ver comparables abajo)")
else:
    u, e = por_clave[clave]
    puesto = next((i for i, (x, _) in enumerate(vivos, 1) if x.unidad_key == clave), None)
    proc, n_comp, arr_uf = r.procedencia_arriendo.get(clave, ("?", 0, D(0)))
    print(f"\n  EVALUACIÓN (escenario base, pie {e.pie_efectivo:.0%}):")
    if e.excluido:
        print(f"    EXCLUIDA del ranking: {e.motivo_exclusion}")
    elif puesto:
        print(f"    puesto #{puesto} de {len(vivos)} · score {e.score:.0f}")
    arr_txt = f"${arr_uf * uf:,.0f}".replace(",", ".")
    print(f"    arriendo asignado : {arr_txt}/mes  [{proc}, n={n_comp}]")
    eq = arriendo_equilibrio_real(u, escenario_base(p, inv), p, inv)
    if eq is not None and arr_uf:
        colchon = (arr_uf - eq) / arr_uf
        print(
            f"    arriendo equilibrio: ${eq * uf:,.0f}/mes  colchón {colchon:+.0%}".replace(
                ",", "."
            )
            + ("  <- SIN margen: el estimado ya está bajo el equilibrio" if colchon < 0 else "")
        )
    print(f"    yield bruto       : {e.rentabilidad_bruta:.2%} · cap rate neto {e.cap_rate:.2%}")
    print(
        f"    flujo mensual     : ${e.btcf_mensual_uf * uf:+,.0f} (dividendo ${e.dividendo_total_uf * uf:,.0f})".replace(
            ",", "."
        )
    )
    pie_cero = (
        "positivo al pie mínimo"
        if e.pie_flujo_cero_real == 0
        else (f"{e.pie_flujo_cero_real:.0%}" if e.pie_flujo_cero_real is not None else "nunca")
    )
    print(f"    pie de flujo cero : {pie_cero}")
    if e.tir_real.get(10) is not None:
        print(
            f"    TIR real 10a      : {e.tir_real[10]:.2%} · VAN {e.van_uf:,.0f} UF".replace(
                ",", "."
            )
        )
    tasa = (
        "con subsidio"
        if e.subsidio_aplicado
        else f"sin subsidio ({e.motivo_sin_subsidio or 'usada'})"
    )
    print(f"    tasa aplicada     : {e.tasa_aplicada:.2%} {tasa}")
    dfl2 = (
        ("probable, verificar en escritura" if e.dfl2_es_supuesto else "sí")
        if e.dfl2_aplicado
        else "no"
    )
    print(f"    DFL2              : {dfl2}")
    print(f"    riesgo microzona  : {u.riesgo_microzona} · catalizador {u.catalizador}")

# ------------------------------------------- los comparables que sostienen el arriendo
if mz and tip and m2:
    comps, _ = comparables_desde_duckdb(con, ahora)
    grupo = sorted(
        (
            (abs(c.m2_utiles - D(str(m2))), c.m2_utiles, c.arriendo_uf)
            for c in comps
            if c.microzona_id == mz and c.tipologia == tip
        ),
        key=lambda t: t[0],
    )
    print(f"\n  VECINOS {tip} en {mz} (frescos, sin sospechosos ni amoblados): {len(grupo)}")
    for factor in op.VENTANAS_M2_REL:
        v = max(op.VENTANA_M2_MIN, D(str(m2)) * factor)
        dentro = [g for g in grupo if g[0] <= v]
        print(f"    ventana ±{v:.0f} m² ({factor:.0%}): n={len(dentro)}")
    print("    los 12 más cercanos por m²:")
    for _d, m2c, arr in grupo[:12]:
        print(f"      {m2c:>5.0f} m²  ${arr * uf:>10,.0f}/mes".replace(",", "."))
    activos = con.execute(
        "SELECT count(*) FROM fact_arriendo_comp WHERE microzona_id = ? AND activo", (mz,)
    ).fetchone()[0]
    print(f"    saturación: {activos} avisos de arriendo 'activos' en la microzona")
    print("    (cota superior: nada apaga un aviso todavía, T-945)")

con.close()
