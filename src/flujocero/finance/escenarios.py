"""Producto cartesiano de escenarios y score. CLAUDE.md §12 y config/params.yml.

El escenario `sin_subsidio` se calcula siempre como contraste, aunque el inversionista califique.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import product

from flujocero.config import Config
from flujocero.finance.modelo import (
    Escenario,
    Evaluacion,
    Unidad,
    evaluar,
    pie_flujo_cero_real,
)

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
                # El escenario OFRECE FOGAES; el motor decide si el inmueble califica.
                # Es la misma regla que el subsidio: condicion del inmueble, no del deseo.
                con_fogaes=con_sub,
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
        con_fogaes=True,
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
        # El pie REAL cuando esta calculado, con la forma cerrada como respaldo. Rankear con
        # la cerrada ordenaria el 20% del score por una metrica que subestima 24-30 puntos, y
        # lo haria de forma desigual: subestima mas donde la vacancia y el opex pesan mas.
        # Un `None` —la unidad no llega a flujo cero ni con 95% de pie— es lo peor posible.
        "pie_minimo_flujo_cero": _normalizar(
            [
                e.pie_flujo_cero_real
                if e.pie_flujo_cero_real is not None
                else (
                    D(1)
                    if e.pie_flujo_cero_real is None and e.btcf_mensual_uf < 0
                    else e.pie_minimo_flujo_cero
                )
                for _, e in vivos
            ],
            False,
        ),
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
    unidades: list[Unidad],
    escenario: Escenario,
    p: Config,
    inv: Config,
    pie_exacto: bool = True,
    pie_cero_precalculado: dict[str, Decimal | None] | None = None,
) -> list[Evaluacion]:
    """`pie_exacto` busca por biseccion el pie de flujo cero sobre el modelo completo.

    Cuesta ~11 evaluaciones extra por unidad y vale cada una: la forma cerrada subestima el
    pie necesario en 24 a 30 puntos porcentuales, porque parte del yield bruto e ignora
    vacancia, incobrabilidad, erosion intra-anual y seguros.

    `pie_cero_precalculado` reusa biseciones ya hechas, por `unidad_key`. Existe porque el
    resultado **no depende del pie pedido**: la biseccion busca el pie donde el flujo cruza
    cero, asi que mover `escenario.pie_pct` no lo cambia. Sin esto, la API rehace 90 s de
    calculo cada vez que alguien mueve el control del pie, para llegar al mismo numero.

    Ojo con el resto del escenario: tasa, vacancia, plazo y DFL2 **si** lo cambian. Por eso
    quien pasa el diccionario es responsable de invalidarlo cuando cambie algo que no sea el
    pie; `api.servicio` lo hace cacheando por la firma del escenario sin el pie.
    """
    evals = [evaluar(u, escenario, p, inv) for u in unidades]
    if pie_exacto:
        cache = pie_cero_precalculado or {}
        for u, ev in zip(unidades, evals, strict=True):
            if ev.excluido:
                continue
            # `in` y no `.get()`: un `None` cacheado significa "ya se calculo y NO llega
            # nunca a flujo cero", que es informacion. Tratarlo como ausente rehace la
            # biseccion completa justo en las unidades mas caras de evaluar.
            ev.pie_flujo_cero_real = (
                cache[u.unidad_key]
                if u.unidad_key in cache
                else pie_flujo_cero_real(u, escenario, p, inv)
            )
    puntuar(unidades, evals, p)
    return evals
