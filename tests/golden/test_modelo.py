"""Casos de oro del modelo completo — invariantes contables y reglas del régimen."""

from decimal import Decimal as D
from decimal import getcontext

import pytest

from flujocero.config import cargar, ticket_maximo_uf
from flujocero.finance.escenarios import construir_escenarios, escenario_base, evaluar_universo
from flujocero.finance.modelo import (
    Escenario,
    Unidad,
    contribuciones_anuales_uf,
    evaluar,
    tasa_aplicable,
)

getcontext().prec = 34


@pytest.fixture(scope="module")
def cfg():
    return cargar("params"), cargar("inversionista")


def unidad(**kw) -> Unidad:
    base = dict(
        unidad_key="U-1",
        precio_uf=D(3000),
        m2_utiles=D(45),
        tipologia="2D1B",
        comuna_id="san-miguel",
        microzona_id="san-miguel/gran-avenida",
        arriendo_mensual_uf=D(10),
        arriendo_n_comparables=20,
        acogida_dfl2=True,
    )
    base.update(kw)
    return Unidad(**base)


def escenario(**kw) -> Escenario:
    base = dict(
        escenario_id="t",
        con_subsidio=True,
        pie_pct=D("0.10"),
        dfl2=True,
        vacancia=D("0.08"),
        tasa_anual=D("0.0330"),
        tasa_sin_subsidio=D("0.0429"),
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
        tasa_anual=D("0.033"),
        plazo_anios=30,
        ltv=D("0.90"),
        uf_clp=D(40804),
        max_pct_ingreso=D("0.25"),
        max_carga_financiera=D("0.45"),
        tope_uf=D(6000),
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


# --------------------------------------------------------- usado: escenario, no exclusion (D-015)


def test_el_usado_entra_al_ranking_pero_sin_el_subsidio(cfg) -> None:
    """D-015: el stock usado compite. Lo que NO hereda es el subsidio a la tasa.

    El Decreto 180 art. 3 lo ata a la *primera venta del inmueble*: es condicion de la
    propiedad, no del escenario. Un escenario `con_subsidio` no se la puede regalar.
    """
    p, inv = cfg
    ev = evaluar(unidad(es_vivienda_nueva=False), escenario(con_subsidio=True), p, inv)
    assert not ev.excluido, "el usado ya no se excluye: compite"
    assert not ev.subsidio_aplicado
    assert "primera venta" in ev.motivo_sin_subsidio
    assert ev.tasa_aplicada == D("0.0429"), "cae a la tasa que el escenario declaro"


def test_un_usado_paga_mas_dividendo_que_el_mismo_depto_nuevo(cfg) -> None:
    """La consecuencia en plata de lo anterior, sobre la MISMA unidad y el mismo escenario."""
    p, inv = cfg
    e = escenario(con_subsidio=True)
    nuevo = evaluar(unidad(es_vivienda_nueva=True), e, p, inv)
    usado = evaluar(unidad(es_vivienda_nueva=False), e, p, inv)
    assert usado.dividendo_uf > nuevo.dividendo_uf
    assert nuevo.subsidio_aplicado and not usado.subsidio_aplicado


def test_la_tasa_negada_manda_en_TODO_el_calculo_no_solo_en_el_dividendo(cfg) -> None:
    """El bug facil: bajar el dividendo y dejar amortizacion, pie de equilibrio y TIR a la
    tasa vieja. El modelo quedaria incoherente consigo mismo y el error no se veria."""
    p, inv = cfg
    e = escenario(con_subsidio=True)
    nuevo = evaluar(unidad(es_vivienda_nueva=True), e, p, inv)
    usado = evaluar(unidad(es_vivienda_nueva=False), e, p, inv)
    # A mayor tasa: se amortiza menos capital y hace falta mas pie para llegar a flujo cero.
    assert usado.amortizacion_mensual_uf < nuevo.amortizacion_mensual_uf
    assert usado.pie_minimo_flujo_cero > nuevo.pie_minimo_flujo_cero


def test_sin_subsidio_en_el_escenario_el_usado_y_el_nuevo_son_identicos(cfg) -> None:
    """Sin subsidio de por medio, ser usado no debe cambiar NADA por si solo. Si cambia,
    es que se colo una penalizacion encubierta en vez de un supuesto declarado."""
    p, inv = cfg
    e = escenario(con_subsidio=False, tasa_anual=p.d("financiamiento.tasa_anual_sin_subsidio"))
    nuevo = evaluar(unidad(es_vivienda_nueva=True), e, p, inv)
    usado = evaluar(unidad(es_vivienda_nueva=False), e, p, inv)
    assert usado.dividendo_uf == nuevo.dividendo_uf
    assert usado.pie_minimo_flujo_cero == nuevo.pie_minimo_flujo_cero


def test_el_subsidio_tampoco_se_aplica_sobre_el_tope_de_uf6000(cfg) -> None:
    """Misma regla, otra condicion del inmueble. Se prueba en el limite exacto."""
    p, inv = cfg
    tope = p.d("subsidio_ley_21748.tope_valor_vivienda_uf")
    justo = evaluar(unidad(precio_uf=tope, arriendo_mensual_uf=D(20)), escenario(), p, inv)
    assert justo.subsidio_aplicado, "en el tope exacto todavia califica"


def test_el_ds1_tramo4000_esta_declarado_y_marcado_como_no_aplicable(cfg) -> None:
    """Es el instrumento que SI admite usadas, y el que no podemos usar: obliga a habitar
    la vivienda y prohibe arrendarla 5 anos. Queda escrito para no re-descubrirlo."""
    p, _ = cfg
    t4 = p.crudo("subsidio_ds1_tramo4")
    assert t4["admite_vivienda_usada"]["v"] is True
    assert t4["aplicable_a_este_inversionista"]["v"] is False
    assert "arrendar" in t4["razon_no_aplicable"]


def test_perder_el_subsidio_cuesta_exactamente_la_brecha_medida(cfg) -> None:
    """Que cuesta perder el subsidio, medido y no supuesto.

    Version anterior de este test: "no puede costar mas de 60 pb", porque el Decreto 180 son
    60 pb. **Era falso**, y ademas pasaba por la razon equivocada: comparaba contra un
    `tasa_sin_subsidio` fijo en el fixture en vez de contra la configuracion real.

    Los simuladores de los propios bancos, mismo dia y mismas condiciones (depto nuevo
    UF 3.999, pie 10%, 30 anos), dan brechas de **99 pb (BancoEstado)** y **146 pb
    (Santander)** — no 60. Y eso confirma el §2.1 del contrato en vez de contradecirlo: el
    subsidio son 60 pb y **el resto es el efecto FOGAES sobre el spread del banco**. Son dos
    beneficios sumados, y quien no califica pierde los dos.
    """
    p, inv = cfg
    e = escenario_base(p, inv)
    usado = evaluar(unidad(es_vivienda_nueva=False), e, p, inv)
    nuevo_ = evaluar(unidad(es_vivienda_nueva=True), e, p, inv)

    assert usado.tasa_aplicada == p.d("financiamiento.tasa_mejor_sin_subsidio")
    assert nuevo_.tasa_aplicada == p.d("financiamiento.tasa_mejor_caso_fogaes")

    brecha_pb = (usado.tasa_aplicada - nuevo_.tasa_aplicada) * D(10000)
    assert brecha_pb == D(99), "la brecha pareada de BancoEstado, medida el 28-ago-2026"
    assert brecha_pb > p.d("financiamiento.subsidio_tasa_pb"), (
        "la brecha DEBE superar los 60 pb del Decreto 180: incluye el efecto FOGAES"
    )


def test_el_par_de_tasas_del_motor_viene_del_mismo_banco_y_dia(cfg) -> None:
    """T-914: una resta entre tasas de bancos o fechas distintas no mide nada."""
    p, _ = cfg
    par = p.crudo("financiamiento.tasas_pareadas_simulador")["bancoestado"]
    assert p.d("financiamiento.tasa_mejor_caso_fogaes") == D(str(par["con_subsidio"]["v"]))
    assert p.d("financiamiento.tasa_mejor_sin_subsidio") == D(str(par["sin_subsidio"]["v"]))


def test_los_escenarios_construidos_emparejan_mejor_caso_con_mejor_caso(cfg) -> None:
    p, inv = cfg
    for e in construir_escenarios(p, inv):
        if e.con_subsidio:
            assert e.tasa_sin_subsidio == p.d("financiamiento.tasa_mejor_sin_subsidio")
        else:
            assert e.tasa_sin_subsidio == e.tasa_anual, "sin subsidio no hay nada que perder"


def test_el_escenario_base_tambien_declara_su_caida(cfg) -> None:
    p, inv = cfg
    assert escenario_base(p, inv).tasa_sin_subsidio is not None


def test_sobre_el_tope_el_subsidio_se_niega_aunque_el_ranking_lo_admitiera(cfg) -> None:
    """Se prueba la funcion pura: hoy la exclusion dura tapa este caso, pero si el tope del
    ranking y el de la norma se separan, la regla tiene que seguir de pie sola."""
    p, _ = cfg
    tope = p.d("subsidio_ley_21748.tope_valor_vivienda_uf")
    tasa, aplicado, motivo = tasa_aplicable(
        unidad(precio_uf=tope + D(1)), escenario(con_subsidio=True), p
    )
    assert not aplicado and "tope" in motivo
    assert tasa == D("0.0429")
