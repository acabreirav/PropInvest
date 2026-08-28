"""Evaluación de una unidad bajo un escenario. Funciones puras: sin I/O, sin now(), sin azar.

Convención: TODO en UF, términos reales. Ver docs/02-modelo-financiero.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from flujocero.config import Config
from flujocero.finance import core as f

D = Decimal


@dataclass(frozen=True)
class Unidad:
    unidad_key: str
    precio_uf: Decimal
    m2_utiles: Decimal
    tipologia: str
    comuna_id: str
    microzona_id: str
    arriendo_mensual_uf: Decimal
    arriendo_n_comparables: int
    acogida_dfl2: bool
    es_vivienda_nueva: bool = True
    evidence_precio: str = "V"
    microzona_saturada: bool = False
    riesgo_microzona: Decimal = D("0.5")  # 0 = sin riesgo, 1 = máximo
    catalizador: Decimal = D("0")  # 0..1, Metro con fecha creíble <= 3 años
    descuento_vs_microzona: Decimal = D("0")


@dataclass(frozen=True)
class Escenario:
    escenario_id: str
    con_subsidio: bool
    pie_pct: Decimal
    dfl2: bool
    vacancia: Decimal
    tasa_anual: Decimal


@dataclass
class Evaluacion:
    unidad_key: str
    escenario_id: str
    credito_uf: Decimal = D(0)
    dividendo_uf: Decimal = D(0)
    dividendo_total_uf: Decimal = D(0)
    pgi_uf: Decimal = D(0)
    egi_uf: Decimal = D(0)
    noi_uf: Decimal = D(0)
    opex_anual_uf: Decimal = D(0)
    rentabilidad_bruta: Decimal = D(0)
    cap_rate: Decimal = D(0)
    grm: Decimal = D(0)
    dscr: Decimal = D(0)
    btcf_mensual_uf: Decimal = D(0)
    atcf_mensual_uf: Decimal = D(0)
    # Descomposición del déficit: cuánto es gasto y cuánto es compra de patrimonio.
    amortizacion_mensual_uf: Decimal = D(0)
    costo_tenencia_mensual_uf: Decimal = D(0)
    fraccion_deficit_que_es_ahorro: Decimal = D(0)
    cash_on_cash: Decimal = D(0)
    capital_invertido_uf: Decimal = D(0)
    arriendo_equilibrio_uf: Decimal = D(0)
    pie_minimo_flujo_cero: Decimal = D(0)
    break_even_occupancy: Decimal = D(0)
    tir_real: dict[int, Decimal] = field(default_factory=dict)
    van_uf: Decimal = D(0)
    excluido: bool = False
    motivo_exclusion: str | None = None
    score: Decimal = D(0)
    score_desglose: dict[str, Decimal] = field(default_factory=dict)


def deficit_caja_max_uf(params: Config, inv: Config) -> Decimal | None:
    """Techo de deficit mensual de caja, en UF. `None` = sin filtro.

    Sale de `inversionista.yml`, no de `params.yml`: es una restriccion de la persona,
    no un supuesto del modelo. D-012 lo usa como EXCLUSION dura, no como penalizacion:
    el score ordena por costo economico y este filtro protege la liquidez por separado.
    """
    if not params.crudo("score.exclusiones_duras").get("aplicar_deficit_caja_max"):
        return None
    tope = inv.crudo("restricciones").get("deficit_mensual_tolerado_clp")
    if tope is None:
        return None
    return D(str(tope)) / params.d("macro.valor_uf_clp")


# ----------------------------------------------------------------------- exclusiones duras


def evaluar_exclusiones(u: Unidad, params: Config, inv: Config) -> str | None:
    """Las exclusiones EXCLUYEN, no restan puntos (CLAUDE.md §12)."""
    ex = params.crudo("score.exclusiones_duras")
    if u.precio_uf > D(str(ex["precio_max_uf"])):
        return f"precio UF {u.precio_uf} sobre el tope de UF {ex['precio_max_uf']}"
    if ex.get("solo_vivienda_nueva") and not u.es_vivienda_nueva:
        return "vivienda usada: no aplica el subsidio a la tasa"
    if u.m2_utiles > D(str(ex["m2_utiles_max"])):
        return f"{u.m2_utiles} m² útiles: sobre 140 se pierde el régimen DFL2 completo"
    if u.arriendo_n_comparables < int(ex["min_comparables_arriendo"]):
        return f"solo {u.arriendo_n_comparables} comparables de arriendo (mínimo {ex['min_comparables_arriendo']})"
    if ex.get("excluir_microzonas_saturadas") and u.microzona_saturada:
        return f"microzona {u.microzona_id} marcada como saturada"
    if ex.get("excluir_precio_estimado") and u.evidence_precio not in ("V", "D"):
        return f"precio con evidencia `{u.evidence_precio}`: no se rankea un precio estimado"
    if inv.crudo("estrategia_dfl2").get("exigir_dfl2") and not u.acogida_dfl2:
        return "no acogida a DFL2, y el perfil exige DFL2"
    return None


# ------------------------------------------------------------------------------ componentes


def contribuciones_anuales_uf(precio_uf: Decimal, dfl2: bool, p: Config) -> Decimal:
    """Impuesto territorial. Se calcula en pesos sobre el avalúo fiscal y se lleva a UF.

    El ratio avalúo/mercado es un supuesto `E` con rango [0,40; 0,70]: es de los parámetros
    a los que más conviene hacerle sensibilidad.
    """
    uf = p.d("macro.valor_uf_clp")
    avaluo = precio_uf * uf * p.d("gastos_operativos.ratio_avaluo_fiscal_sobre_mercado")
    base = max(D(0), avaluo - p.d("gastos_operativos.avaluo_exento_clp"))
    corte = p.d("gastos_operativos.contribuciones_avaluo_corte_clp")
    t1 = p.d("gastos_operativos.contribuciones_tasa_anual")
    t2 = p.d("gastos_operativos.contribuciones_tasa_tramo_alto")
    clp = (
        base * t1
        if avaluo <= corte
        else (corte - min(corte, p.d("gastos_operativos.avaluo_exento_clp"))) * t1
        + (avaluo - corte) * t2
    )
    if dfl2:
        clp *= D(1) - p.d("gastos_operativos.rebaja_dfl2_contribuciones")
    return clp / uf


def gastos_comunes_mensuales_clp(u: Unidad, p: Config) -> Decimal:
    tabla = p.crudo("gastos_operativos.gastos_comunes_clp_m2_mes")
    por_m2 = D(str(tabla.get("por_comuna", {}).get(u.comuna_id, tabla["default"]["v"])))
    return por_m2 * u.m2_utiles


def construir_opex(u: Unidad, e: Escenario, egi_uf: Decimal, p: Config) -> f.Opex:
    """Gastos operativos anuales. Los SEGUROS no van acá: el banco los cobra con el dividendo."""
    uf = p.d("macro.valor_uf_clp")
    contrib = contribuciones_anuales_uf(u.precio_uf, e.dfl2, p)
    renta = D(0)
    if not e.dfl2:
        base = max(D(0), u.arriendo_mensual_uf * D(12) - contrib)
        renta = base * p.d("tributacion.igc_tasa_marginal_default")
    return f.Opex(
        contribuciones=contrib,
        gastos_comunes_vacancia=gastos_comunes_mensuales_clp(u, p) * D(12) * e.vacancia / uf,
        seguro_incendio_sismo=D(0),
        administracion=egi_uf * p.d("comisiones.administracion_pct_arriendo"),
        corretaje_amortizado=u.arriendo_mensual_uf
        * p.d("comisiones.corretaje_arriendo_efectivo_meses")
        / p.d("vacancia_y_riesgo.permanencia_arrendatario_anios"),
        mantencion=f.pgi(u.arriendo_mensual_uf) * p.d("gastos_operativos.mantencion_pct_pgi"),
        impuesto_renta=renta,
    )


def gastos_de_cierre_uf(precio_uf: Decimal, credito_uf: Decimal, p: Config) -> Decimal:
    uf = p.d("macro.valor_uf_clp")
    return (
        credito_uf * p.d("gastos_de_cierre.impuesto_timbres_pct_credito")
        + p.d("gastos_de_cierre.tasacion_uf")
        + p.d("gastos_de_cierre.estudio_titulos_uf")
        + p.d("gastos_de_cierre.notaria_escritura_cv_uf")
        + p.d("gastos_de_cierre.notaria_escritura_mutuo_uf")
        + (p.d("gastos_de_cierre.inscripcion_cbr_clp") + p.d("gastos_de_cierre.certificados_clp"))
        / uf
    )


# -------------------------------------------------------------------------------- evaluación


def evaluar(u: Unidad, e: Escenario, p: Config, inv: Config) -> Evaluacion:
    ev = Evaluacion(unidad_key=u.unidad_key, escenario_id=e.escenario_id)

    motivo = evaluar_exclusiones(u, p, inv)
    if motivo:
        ev.excluido, ev.motivo_exclusion = True, motivo
        return ev

    pi = p.d("macro.inflacion_anual_esperada")
    plazo = int(p.d("financiamiento.plazo_anios"))

    ev.credito_uf = u.precio_uf * (D(1) - e.pie_pct)
    ev.dividendo_uf = f.dividendo_frances(ev.credito_uf, e.tasa_anual, plazo)
    seguros_mensuales = ev.credito_uf * p.d(
        "gastos_operativos.seguro_desgravamen_pct_mensual_saldo"
    ) + u.precio_uf * p.d("gastos_operativos.seguro_incendio_sismo_pct_mensual_tasacion")
    ev.dividendo_total_uf = ev.dividendo_uf + seguros_mensuales

    ev.pgi_uf = f.pgi(u.arriendo_mensual_uf)
    ev.egi_uf = f.egi(
        u.arriendo_mensual_uf, e.vacancia, p.d("vacancia_y_riesgo.incobrabilidad"), pi
    )
    opex = construir_opex(u, e, ev.egi_uf, p)
    ev.opex_anual_uf = opex.total()
    ev.noi_uf = f.noi(ev.egi_uf, opex)

    cierre = gastos_de_cierre_uf(u.precio_uf, ev.credito_uf, p)
    servicio_anual = ev.dividendo_total_uf * D(12)

    ev.rentabilidad_bruta = f.rentabilidad_bruta(u.arriendo_mensual_uf, u.precio_uf)
    ev.cap_rate = f.cap_rate(ev.noi_uf, u.precio_uf, cierre)
    ev.grm = u.precio_uf / ev.pgi_uf
    ev.dscr = f.dscr(ev.noi_uf, servicio_anual)
    ev.btcf_mensual_uf = f.btcf_mensual(ev.noi_uf, ev.dividendo_total_uf)
    ev.atcf_mensual_uf = ev.btcf_mensual_uf  # el impuesto ya está dentro del NOI

    ev.amortizacion_mensual_uf = f.amortizacion_mensual_promedio(
        ev.credito_uf, e.tasa_anual, plazo, anio=1
    )
    ev.costo_tenencia_mensual_uf = f.costo_tenencia_mensual(
        ev.btcf_mensual_uf, ev.amortizacion_mensual_uf
    )
    if ev.btcf_mensual_uf < 0:
        # Qué fracción del egreso mensual es, en realidad, ahorro forzoso.
        ev.fraccion_deficit_que_es_ahorro = min(
            D(1), ev.amortizacion_mensual_uf / -ev.btcf_mensual_uf
        )

    ev.capital_invertido_uf = u.precio_uf * e.pie_pct + cierre
    ev.cash_on_cash = ev.btcf_mensual_uf * D(12) / ev.capital_invertido_uf
    ev.arriendo_equilibrio_uf = f.arriendo_equilibrio_uf(
        servicio_anual, ev.opex_anual_uf, e.vacancia, pi
    )
    ev.pie_minimo_flujo_cero = f.pie_minimo_flujo_cero(
        ev.rentabilidad_bruta, e.tasa_anual, plazo, ev.opex_anual_uf / ev.pgi_uf
    )
    ev.break_even_occupancy = f.break_even_occupancy(ev.opex_anual_uf, servicio_anual, ev.pgi_uf)

    g = p.d("activo.plusvalia_real_anual")
    r = p.d("macro.tasa_descuento_real")
    com_venta = p.d("comisiones.corretaje_venta_pct") * D("1.19")
    exencion = p.d("tributacion.ganancia_capital_exencion_uf")
    tasa_gc = p.d("tributacion.ganancia_capital_tasa_unica")

    for n in p.crudo("indicadores_objetivo.horizontes_tir_anios"):
        n = int(n)
        flujos = [-ev.capital_invertido_uf] + [ev.atcf_mensual_uf * D(12)] * n
        venta = u.precio_uf * (D(1) + g) ** n
        ganancia = max(D(0), venta - u.precio_uf - exencion)
        flujos[n] += (
            venta * (D(1) - com_venta)
            - f.saldo_insoluto(ev.credito_uf, e.tasa_anual, plazo, n * 12)
            - ganancia * tasa_gc
        )
        try:
            ev.tir_real[n] = f.tir(flujos)
        except ValueError:
            ev.tir_real[n] = D("-1")
        if n == 10:
            ev.van_uf = f.van(flujos, r)

    # D-012 · filtro de liquidez, DESPUES de calcular: la unidad se excluye del ranking
    # pero conserva todas sus metricas, para que el informe pueda mostrar por que se cayo.
    tope = deficit_caja_max_uf(p, inv)
    if tope is not None and -ev.btcf_mensual_uf > tope:
        ev.excluido = True
        uf = p.d("macro.valor_uf_clp")
        ev.motivo_exclusion = (
            f"deficit de caja {-ev.btcf_mensual_uf * uf:,.0f} CLP/mes sobre el tope "
            f"tolerado de {tope * uf:,.0f} CLP/mes"
        )
    return ev
