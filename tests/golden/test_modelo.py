"""Casos de oro del modelo completo — invariantes contables y reglas del régimen."""

from decimal import Decimal as D, getcontext

import pytest

from flujocero.config import cargar, ticket_maximo_uf
from flujocero.finance import core as f
from flujocero.finance.escenarios import construir_escenarios, escenario_base, evaluar_universo
from flujocero.finance.modelo import Escenario, Unidad, contribuciones_anuales_uf, evaluar

getcontext().prec = 34


@pytest.fixture(scope="module")
def cfg():
    return cargar("params"), cargar("inversionista")


def unidad(**kw) -> Unidad:
    base = dict(
        unidad_key="U-1", precio_uf=D(3000), m2_utiles=D(45), tipologia="2D1B",
        comuna_id="san-miguel", microzona_id="san-miguel/gran-avenida",
        arriendo_mensual_uf=D(10), arriendo_n_comparables=20, acogida_dfl2=True,
    )
    base.update(kw)
    return Unidad(**base)


def escenario(**kw) -> Escenario:
    base = dict(
        escenario_id="t", con_subsidio=True, pie_pct=D("0.10"), dfl2=True,
        vacancia=D("0.08"), tasa_anual=D("0.0330"),
    )
    base.update(kw)
    return Escenario(**base)


# 7 · identidad contable: BTCF*12 + servicio de deuda + opex = EGI
def test_identidad_contable(cfg) -> None:
    p, inv = cfg
    ev = evaluar(unidad(), escenario(), p, inv)
    izq = ev.btcf_mensual_uf * D(12) + ev.dividendo_total_uf * D(12) + ev.opex_anual_uf
    assert abs(izq - ev.egi_uf) < D("1e-9")


# 4 · DFL2 sube el NOI exactamente en (impuesto de renta evitado + 50% de contribuciones)
def test_delta_dfl2_exacto(cfg) -> None:
    p, inv = cfg
    u = unidad()
    con = evaluar(u, escenario(dfl2=True), p, inv)
    sin = evaluar(u, escenario(dfl2=False), p, inv)

    contrib_sin = contribuciones_anuales_uf(u.precio_uf, False, p)
    contrib_con = contribuciones_anuales_uf(u.precio_uf, True, p)
    renta_evitada = max(D(0), u.arriendo_mensual_uf * D(12) - contrib_sin) * p.d(
        "tributacion.igc_tasa_marginal_default"
    )
    esperado = renta_evitada + (contrib_sin - contrib_con)
    assert abs((con.noi_uf - sin.noi_uf) - esperado) < D("1e-9")
    assert con.noi_uf > sin.noi_uf


# los seguros NO se cuentan dos veces: van en el dividendo, no en el opex
def test_seguros_no_se_duplican(cfg) -> None:
    p, inv = cfg
    ev = evaluar(unidad(), escenario(), p, inv)
    assert ev.dividendo_total_uf > ev.dividendo_uf
    from flujocero.finance.modelo import construir_opex
    assert construir_opex(unidad(), escenario(), ev.egi_uf, p).seguro_incendio_sismo == D(0)


# exclusiones duras: excluyen, no restan puntos
@pytest.mark.parametrize(
    "kw,fragmento",
    [
        (dict(precio_uf=D(6500)), "sobre el tope"),
        (dict(m2_utiles=D(150)), "DFL2"),
        (dict(arriendo_n_comparables=3), "comparables"),
        (dict(microzona_saturada=True), "saturada"),
        (dict(evidence_precio="E"), "estimado"),
        (dict(acogida_dfl2=False), "DFL2"),
        (dict(es_vivienda_nueva=False), "usada"),
    ],
)
def test_exclusiones_duras(cfg, kw, fragmento) -> None:
    p, inv = cfg
    ev = evaluar(unidad(**kw), escenario(), p, inv)
    assert ev.excluido and fragmento in ev.motivo_exclusion
    assert ev.score == D(0)


# el escenario sin_subsidio SIEMPRE se calcula, aunque el inversionista califique
def test_escenario_sin_subsidio_siempre_presente(cfg) -> None:
    p, inv = cfg
    ids = {e.escenario_id for e in construir_escenarios(p, inv)}
    assert any(i.startswith("nosub_") for i in ids)
    assert any(i.startswith("sub_") for i in ids)


# el caso base del inversionista: califica al subsidio y exige DFL2
def test_escenario_base_refleja_el_perfil(cfg) -> None:
    p, inv = cfg
    e = escenario_base(p, inv)
    assert e.con_subsidio is True and e.dfl2 is True


# menor tasa => menor pie de equilibrio; mayor yield => menor pie de equilibrio
def test_monotonias(cfg) -> None:
    p, inv = cfg
    u = unidad()
    barata = evaluar(u, escenario(tasa_anual=D("0.0330")), p, inv)
    cara = evaluar(u, escenario(tasa_anual=D("0.0485")), p, inv)
    assert barata.pie_minimo_flujo_cero < cara.pie_minimo_flujo_cero
    mejor = evaluar(unidad(arriendo_mensual_uf=D(13)), escenario(), p, inv)
    assert mejor.pie_minimo_flujo_cero < barata.pie_minimo_flujo_cero


# el score reparte exactamente 100 puntos entre los seis componentes
def test_score_suma_pesos(cfg) -> None:
    p, inv = cfg
    us = [
        unidad(unidad_key="A", precio_uf=D(2800), arriendo_mensual_uf=D(11)),
        unidad(unidad_key="B", precio_uf=D(3400), arriendo_mensual_uf=D(10)),
        unidad(unidad_key="C", precio_uf=D(3000), arriendo_mensual_uf=D(9)),
    ]
    evals = evaluar_universo(us, escenario_base(p, inv), p, inv)
    assert all(not e.excluido for e in evals)
    assert max(e.score for e in evals) > 0
    for e in evals:
        assert abs(sum(e.score_desglose.values()) - e.score) < D("1e-9")
        assert D(0) <= e.score <= D(100)


# capacidad: la regla de carga financiera muerde cuando hay otras cuotas
def test_capacidad_carga_financiera(cfg) -> None:
    p, _ = cfg
    args = dict(
        tasa_anual=D("0.033"), plazo_anios=30, ltv=D("0.90"), uf_clp=D(40804),
        max_pct_ingreso=D("0.25"), max_carga_financiera=D("0.45"), tope_uf=D(6000),
    )
    limpio = ticket_maximo_uf(D(2_000_000), D(0), **args)
    endeudado = ticket_maximo_uf(D(2_000_000), D(500_000), **args)
    assert endeudado["ticket_max_uf"] < limpio["ticket_max_uf"]
    assert endeudado["restriccion_activa"] == D(1)


# el tope de UF 6.000 se respeta aunque la capacidad dé más
def test_tope_uf6000(cfg) -> None:
    r = ticket_maximo_uf(
        D(8_000_000), D(0), D("0.033"), 30, D("0.90"), D(40804), D("0.25"), D("0.45"), D(6000)
    )
    assert r["ticket_max_uf"] == D(6000)
