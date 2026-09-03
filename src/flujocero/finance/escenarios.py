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
                # El escenario OFRECE FOGAES siempre; el motor decide si el inmueble
                # califica. FOGAES y subsidio a la tasa son beneficios INDEPENDIENTES —
                # el propio modelo lo advierte— y acoplarlos aqui (`con_fogaes=con_sub`)
                # le cargaba al contraste `sin_subsidio` un segundo castigo que la norma
                # no impone: ademas de la tasa, el pie minimo saltaba de 10% a 20%. El
                # mismo error de "confundir dos cosas" que el comentario de las tasas
                # de arriba dice evitar.
                con_fogaes=True,
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


def puntuar(unidades: list[Unidad], evals: list[Evaluacion], p: Config) -> list[str]:
    """Score 0–100, normalizado sobre el conjunto vivo. Cada componente queda auditable.

    Devuelve los componentes **inertes**: los que valen lo mismo en todas las unidades vivas.

    Un componente que no varia no ordena nada. Al normalizarlo, `_normalizar` le da 0,5 a
    todo el mundo y su peso se convierte en una constante que se le suma identica a cada
    unidad: no cambia una sola posicion del ranking, pero infla todos los scores y aparece
    en la ficha con un numero, como si midiera. Es la enfermedad de siempre — una casilla
    vacia leyendose como un resultado — y aca costaba **30 puntos de 100**: `riesgo_microzona`
    (15%) salia 0,5 fijo, `catalizador` (10%) salia 0 fijo y `descuento_vs_microzona` (5%)
    salia 0 fijo, porque nada los poblaba.

    Asi que sus pesos se redistribuyen entre los componentes que si varian, y sus nombres se
    devuelven para que quien muestre el score diga cuales no se midieron. Repartir en
    silencio seria el mismo error con otra cara: el score diria "sobre 100" midiendo 70.

    No se distingue —ni se puede desde aca— entre "nadie lo poblo" y "todas las unidades
    empatan de verdad". No hace falta: la consecuencia es la misma, el componente no
    discrimina, y gastarle peso es gastar escala en nada.
    """
    pesos = {k: D(str(v)) for k, v in p.crudo("score.pesos").items()}
    vivos = [(u, e) for u, e in zip(unidades, evals) if not e.excluido]
    if not vivos:
        return []

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
        # Indexado directo A PROPOSITO: una evaluacion no excluida siempre trae tir_real
        # (el fallo de calculo se guarda como -1, no como ausencia). Si alguien filtra
        # aca una evaluacion de calcular_tir=False, esto revienta en vez de puntuarla
        # en silencio como la peor TIR posible (verificador §7.6, 03-sep, F3).
        "tir_real_apalancada_10a": _normalizar([e.tir_real[10] for _, e in vivos], True),
        "riesgo_microzona": _normalizar([u.riesgo_microzona for u, _ in vivos], False),
        "catalizador": _normalizar([u.catalizador for u, _ in vivos], True),
        "descuento_vs_microzona": _normalizar([u.descuento_vs_microzona for u, _ in vivos], True),
    }
    # Con una sola unidad viva todo es constante por definicion; ahi no hay nada que
    # declarar inerte, simplemente no hay ranking.
    inertes = sorted(k for k, v in comps.items() if min(v) == max(v)) if len(vivos) > 1 else []
    activos = {k: w for k, w in pesos.items() if k not in inertes}
    total = sum(activos.values(), D(0))
    if total <= 0:
        # Ningun componente varia: el score no puede ordenar. Cero para todos, y que se note.
        for _, ev in vivos:
            ev.score_desglose, ev.score = {}, D(0)
        return sorted(pesos)
    for i, (_, ev) in enumerate(vivos):
        desglose = {k: comps[k][i] * (w / total) * D(100) for k, w in activos.items()}
        ev.score_desglose = desglose
        ev.score = sum(desglose.values(), D(0))
    return inertes


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
    inertes = tuple(puntuar(unidades, evals, p))
    for ev in evals:
        ev.score_inertes = inertes
    return evals
