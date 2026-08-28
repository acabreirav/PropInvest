"""Producto cartesiano de escenarios y score. CLAUDE.md §12 y config/params.yml.

El escenario `sin_subsidio` se calcula siempre como contraste, aunque el inversionista califique.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import product

from flujocero.config import Config
from flujocero.finance.modelo import Escenario, Evaluacion, Unidad, evaluar

D = Decimal


def construir_escenarios(p: Config, inv: Config) -> list[Escenario]:
    pies = [D(str(x)) for x in p.crudo("financiamiento.pies_a_evaluar")]
    dfl2_posibles = [True] if inv.crudo("estrategia_dfl2").get("exigir_dfl2") else [True, False]
    vacancias = [
        p.d("vacancia_y_riesgo.vacancia_gestion_individual"),
        p.d("vacancia_y_riesgo.vacancia_gestion_profesional"),
    ]
    salida: list[Escenario] = []
    for con_sub, pie, dfl2, vac in product([True, False], pies, dfl2_posibles, vacancias):
        # Mejor caso con mejor caso, promedio con promedio: si no, la unidad que pierde el
        # subsidio carga ademas la diferencia entre bancos y el modelo confunde dos cosas.
        tasa = (
            p.d("financiamiento.tasa_mejor_caso_fogaes")
            if con_sub
            else p.d("financiamiento.tasa_anual_sin_subsidio")
        )
        caida = p.d("financiamiento.tasa_mejor_sin_subsidio") if con_sub else tasa
        gestion = "prof" if vac == vacancias[1] else "indiv"
        salida.append(
            Escenario(
                escenario_id=f"{'sub' if con_sub else 'nosub'}_pie{int(pie * 100)}_"
                f"{'dfl2' if dfl2 else 'nodfl2'}_{gestion}",
                con_subsidio=con_sub,
                pie_pct=pie,
                dfl2=dfl2,
                vacancia=vac,
                tasa_anual=tasa,
                tasa_sin_subsidio=caida,
            )
        )
    return salida


def escenario_base(p: Config, inv: Config) -> Escenario:
    """El caso base del inversionista: califica al subsidio, exige DFL2, pie objetivo."""
    pie = D(str(inv.crudo("restricciones.pie_objetivo_pct")))
    return Escenario(
        escenario_id="base",
        con_subsidio=bool(inv.crudo("elegibilidad.califica_subsidio_tasa")),
        pie_pct=pie,
        dfl2=bool(inv.crudo("estrategia_dfl2").get("exigir_dfl2")),
        vacancia=p.d("vacancia_y_riesgo.vacancia_gestion_individual"),
        tasa_anual=p.d("financiamiento.tasa_mejor_caso_fogaes"),
        tasa_sin_subsidio=p.d("financiamiento.tasa_mejor_sin_subsidio"),
    )


def _normalizar(valores: list[Decimal], mayor_es_mejor: bool) -> list[Decimal]:
    vivos = [v for v in valores if v is not None]
    lo, hi = min(vivos), max(vivos)
    if hi == lo:
        return [D("0.5")] * len(valores)
    return [((v - lo) / (hi - lo)) if mayor_es_mejor else ((hi - v) / (hi - lo)) for v in valores]


def puntuar(unidades: list[Unidad], evals: list[Evaluacion], p: Config) -> None:
    """Score 0–100, normalizado sobre el conjunto vivo. Cada componente queda auditable."""
    pesos = {k: D(str(v)) for k, v in p.crudo("score.pesos").items()}
    vivos = [(u, e) for u, e in zip(unidades, evals) if not e.excluido]
    if not vivos:
        return

    comps = {
        "costo_tenencia_mensual_uf": _normalizar(
            [e.costo_tenencia_mensual_uf for _, e in vivos], True
        ),
        "pie_minimo_flujo_cero": _normalizar([e.pie_minimo_flujo_cero for _, e in vivos], False),
        "tir_real_apalancada_10a": _normalizar([e.tir_real.get(10, D(-1)) for _, e in vivos], True),
        "riesgo_microzona": _normalizar([u.riesgo_microzona for u, _ in vivos], False),
        "catalizador": _normalizar([u.catalizador for u, _ in vivos], True),
        "descuento_vs_microzona": _normalizar([u.descuento_vs_microzona for u, _ in vivos], True),
    }
    for i, (_, ev) in enumerate(vivos):
        desglose = {k: comps[k][i] * pesos[k] * D(100) for k in pesos}
        ev.score_desglose = desglose
        ev.score = sum(desglose.values(), D(0))


def evaluar_universo(
    unidades: list[Unidad], escenario: Escenario, p: Config, inv: Config
) -> list[Evaluacion]:
    evals = [evaluar(u, escenario, p, inv) for u in unidades]
    puntuar(unidades, evals, p)
    return evals
