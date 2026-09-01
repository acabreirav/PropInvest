"""Casos de oro del modelo completo — invariantes contables y reglas del régimen."""

from dataclasses import replace
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
    gastos_de_cierre_uf,
    pie_flujo_cero_real,
    tasa_aplicable,
    ventana_dfl2_abierta,
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
    # Sobre el EGI —renta efectivamente percibida—, no el PGI: el mes de vacancia no
    # tributa. `egi_uf` es igual en ambos escenarios porque comparten vacancia.
    assert con.egi_uf == sin.egi_uf
    renta_evitada = max(D(0), con.egi_uf - contrib_sin) * p.d(
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


def test_sin_subsidio_NI_fogaes_el_usado_y_el_nuevo_son_identicos(cfg) -> None:
    """La version anterior de este caso exigia que fueran identicos con solo quitar el
    subsidio. Era falso: sin subsidio el nuevo TODAVIA accede a FOGAES y el usado no, asi que
    uno financia el 90% y el otro el 80%. Quitados los dos beneficios, ser usado no debe
    cambiar nada por si solo — si cambia, se colo una penalizacion encubierta en vez de un
    supuesto declarado."""
    p, inv = cfg
    e = escenario(
        con_subsidio=False,
        con_fogaes=False,
        tasa_anual=p.d("financiamiento.tasa_anual_sin_subsidio"),
        pie_pct=D("0.20"),
    )
    nuevo_ = evaluar(unidad(es_vivienda_nueva=True), e, p, inv)
    usado = evaluar(unidad(es_vivienda_nueva=False), e, p, inv)
    assert usado.dividendo_uf == nuevo_.dividendo_uf
    assert usado.pie_efectivo == nuevo_.pie_efectivo
    assert usado.pie_minimo_flujo_cero == nuevo_.pie_minimo_flujo_cero


def test_el_usado_no_accede_a_FOGAES_y_por_eso_su_pie_minimo_se_duplica(cfg) -> None:
    """La respuesta que mas movio el modelo (29-ago-2026): el FOGAES tradicional cubre solo
    primera venta. No es un detalle de tasa — es el doble de plata sobre la mesa."""
    p, inv = cfg
    e = escenario(con_subsidio=True, con_fogaes=True, pie_pct=D("0.10"))
    nuevo_ = evaluar(unidad(es_vivienda_nueva=True), e, p, inv)
    usado = evaluar(unidad(es_vivienda_nueva=False), e, p, inv)

    assert nuevo_.fogaes_aplicado and nuevo_.pie_efectivo == D("0.10")
    assert not usado.fogaes_aplicado
    assert "primera venta" in usado.motivo_sin_fogaes
    assert usado.pie_efectivo == D("0.20"), "el banco exige 20% sin garantia estatal"
    assert usado.capital_invertido_uf > nuevo_.capital_invertido_uf


def test_el_pie_deseado_manda_cuando_supera_al_exigido(cfg) -> None:
    """Pedir 30% de pie sobre una unidad que solo exige 10% no se recorta al minimo."""
    p, inv = cfg
    ev = evaluar(unidad(), escenario(pie_pct=D("0.30")), p, inv)
    assert ev.pie_efectivo == D("0.30")


def test_el_cash_on_cash_se_calcula_sobre_el_pie_que_de_verdad_se_pone(cfg) -> None:
    """Con el pie deseado en vez del exigido, el retorno de un usado saldria inflado al doble:
    se dividiria el flujo por la mitad del capital que el banco obliga a poner."""
    p, inv = cfg
    ev = evaluar(unidad(es_vivienda_nueva=False), escenario(pie_pct=D("0.10")), p, inv)
    cierre = gastos_de_cierre_uf(D(3000), ev.credito_uf, p)
    # pie + cierre + habilitacion: la plata que sale del bolsillo el dia uno, completa.
    habilitacion = p.d("gastos_de_cierre.habilitacion_inicial_uf")
    assert ev.capital_invertido_uf == D(3000) * D("0.20") + cierre + habilitacion


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


# ------------------------------------------------ DFL2 tri-estado y ventana (T-917, T-911)


def test_un_DFL2_sin_confirmar_compite_pero_no_cobra_el_beneficio(cfg) -> None:
    """T-917. Medido sobre 5.870 avisos reales: **16 mencionan DFL2, el 0,3%** — y no porque
    no lo sean, sino porque el aviso no lo dice. Con un booleano, `exigir_dfl2` vaciaba el
    ranking entero. Un ND tratado como False es imputar en silencio (§3.2).

    La asimetria es deliberada: compite, pero se evalua SIN el beneficio. Nunca se muestra una
    oportunidad mejor de lo que se puede probar; si despues resulta DFL2, solo mejora.
    """
    p, inv = cfg
    ev = evaluar(unidad(acogida_dfl2=None), escenario(dfl2=True), p, inv)
    assert not ev.excluido, "compite: el aviso callarselo no prueba que no lo sea"
    assert not ev.dfl2_aplicado
    assert "sin confirmar" in ev.motivo_sin_dfl2
    assert "escritura" in ev.motivo_sin_dfl2, "dice donde se verifica de verdad (§2.5)"


def test_solo_se_excluye_lo_que_se_sabe_que_NO_es_DFL2(cfg) -> None:
    p, inv = cfg
    assert evaluar(unidad(acogida_dfl2=False), escenario(), p, inv).excluido
    assert not evaluar(unidad(acogida_dfl2=None), escenario(), p, inv).excluido


def test_un_DFL2_sin_confirmar_nunca_rinde_mas_que_uno_confirmado(cfg) -> None:
    """El sentido de la asimetria, en plata."""
    p, inv = cfg
    e = escenario(dfl2=True)
    confirmado = evaluar(unidad(acogida_dfl2=True), e, p, inv)
    dudoso = evaluar(unidad(acogida_dfl2=None), e, p, inv)
    assert dudoso.noi_uf < confirmado.noi_uf


def test_la_ventana_de_contribuciones_se_agota_con_la_antiguedad(cfg) -> None:
    """T-911. La rebaja del 50% no es perpetua: corre desde la recepcion municipal. El motor
    se la aplicaba a todos, que es un supuesto optimista justo sobre el beneficio que el §2.5
    declara de mayor valor presente."""
    p, inv = cfg
    e = escenario(dfl2=True)
    nueva = evaluar(unidad(acogida_dfl2=True, m2_utiles=D(55), antiguedad_anios=3), e, p, inv)
    vieja = evaluar(unidad(acogida_dfl2=True, m2_utiles=D(55), antiguedad_anios=25), e, p, inv)
    assert nueva.ventana_contribuciones_abierta
    assert not vieja.ventana_contribuciones_abierta
    assert vieja.opex_anual_uf > nueva.opex_anual_uf, "la vieja paga contribuciones completas"


@pytest.mark.parametrize(
    "m2,antiguedad,abierta",
    [
        ("55", 19, True),  # <=70 m2: 20 anios
        ("55", 20, False),
        ("85", 14, True),  # <=100 m2: 15 anios
        ("85", 15, False),
        ("120", 9, True),  # <=140 m2: 10 anios
        ("120", 10, False),
    ],
)
def test_la_ventana_dura_mas_mientras_mas_chica_la_vivienda(cfg, m2, antiguedad, abierta) -> None:
    p, _ = cfg
    u = unidad(m2_utiles=D(m2), antiguedad_anios=antiguedad, acogida_dfl2=True)
    assert ventana_dfl2_abierta(u, p) is abierta


def test_sin_dato_de_antiguedad_la_ventana_se_asume_abierta(cfg) -> None:
    """Es donde falta el dato —obra nueva— y es tambien donde la ventana recien empieza."""
    p, _ = cfg
    assert ventana_dfl2_abierta(unidad(antiguedad_anios=None), p) is True


# ----------------------------------------------- el pie de flujo cero REAL vs la forma cerrada


def test_la_forma_cerrada_subestima_el_pie_y_por_eso_existe_la_busqueda(cfg) -> None:
    """La forma cerrada `1 - (1-opex)·yield/factor` parte del yield BRUTO: ignora vacancia,
    incobrabilidad, la erosion intra-anual del §3.3 y los seguros que el banco cobra con el
    dividendo. Todo eso empeora el flujo, asi que **subestima sistematicamente**.

    Se vio en el primer ranking real: una unidad con forma cerrada en 18% seguia costando
    plata a 35% de pie. Dos metricas contradiciendose en la misma fila, y la optimista era la
    que el contrato llama "la metrica honesta"."""
    p, inv = cfg
    e = escenario_base(p, inv)
    u = unidad(
        precio_uf=D(2110),
        m2_utiles=D(58),
        arriendo_mensual_uf=D("13.70"),
        es_vivienda_nueva=False,
        acogida_dfl2=None,
    )
    cerrada = evaluar(u, e, p, inv, saltar_exclusiones=True).pie_minimo_flujo_cero
    real = pie_flujo_cero_real(u, e, p, inv)
    assert real is not None
    assert real > cerrada, "la cerrada es optimista, nunca al reves"
    assert real - cerrada > D("0.10"), "y la diferencia es de decenas de puntos, no de redondeo"


def test_el_pie_hallado_de_verdad_da_flujo_cero(cfg) -> None:
    """La prueba de que la busqueda hace lo que dice: al pie que devuelve, el flujo del
    modelo completo cruza cero."""
    p, inv = cfg
    e = escenario_base(p, inv)
    u = unidad(
        precio_uf=D(2110),
        m2_utiles=D(58),
        arriendo_mensual_uf=D("13.70"),
        es_vivienda_nueva=False,
        acogida_dfl2=None,
    )
    pie = pie_flujo_cero_real(u, e, p, inv)
    justo = evaluar(u, replace(e, pie_pct=pie), p, inv, saltar_exclusiones=True)
    apenas_menos = evaluar(u, replace(e, pie_pct=pie - D("0.01")), p, inv, saltar_exclusiones=True)
    assert justo.btcf_mensual_uf >= 0
    assert apenas_menos.btcf_mensual_uf < 0


def test_una_unidad_que_nunca_se_paga_sola_devuelve_None(cfg) -> None:
    """`None` no es un error: es la respuesta correcta a "ni con 95% de pie". Rankearla con
    un numero cualquiera la haria competir contra unidades que si llegan."""
    p, inv = cfg
    mala = unidad(
        precio_uf=D(6000),
        m2_utiles=D(40),
        arriendo_mensual_uf=D("3"),
        es_vivienda_nueva=False,
        acogida_dfl2=None,
    )
    assert pie_flujo_cero_real(mala, escenario_base(p, inv), p, inv) is None


def test_el_DFL2_sin_confirmar_es_lo_que_mas_encarece_el_pie(cfg) -> None:
    """Medido sobre una unidad real del ranking: sin DFL2 confirmado el arriendo paga
    impuesto a la renta, y eso mueve el pie de flujo cero de 0% a mas del 40%. El §2.5 dice
    que el DFL2 vale mas que el subsidio en valor presente; esto lo cuantifica."""
    p, inv = cfg
    e = escenario_base(p, inv)
    base = dict(
        precio_uf=D(2110), m2_utiles=D(58), arriendo_mensual_uf=D("13.70"), es_vivienda_nueva=False
    )
    sin = pie_flujo_cero_real(unidad(**base, acogida_dfl2=None), e, p, inv)
    con = pie_flujo_cero_real(unidad(**base, acogida_dfl2=True, antiguedad_anios=5), e, p, inv)
    assert sin is not None and con is not None
    assert sin - con > D("0.30"), "verificar el DFL2 vale mas de 30 puntos de pie"


# --------------------------------------------------------------- 8 · componentes inertes del score


def test_score_declara_los_componentes_que_no_miden(cfg):
    """Un componente constante no ordena nada: no debe gastar peso ni fingir que midio.

    `riesgo_microzona`, `catalizador` y `descuento_vs_microzona` salen con el mismo valor en
    todas las unidades porque nada los pobla — 30 de los 100 puntos del §12. Antes se sumaban
    identicos a cada score, inflandolos, y aparecian en la ficha con un numero.
    """
    p, inv = cfg
    us = [
        unidad(unidad_key="A", precio_uf=D(2500), arriendo_mensual_uf=D(12)),
        unidad(unidad_key="B", precio_uf=D(3500), arriendo_mensual_uf=D(9)),
        unidad(unidad_key="C", precio_uf=D(3000), arriendo_mensual_uf=D(11)),
    ]
    # `pie_exacto=True` no es decoracion del test: con la biseccion apagada,
    # `pie_flujo_cero_real` es None en todas y el componente cae al mismo D(1) para todas —
    # o sea, un QUINTO componente inerte, otro 20% del score apagado en silencio. Lo detecto
    # este mismo detector la primera vez que corrio. La API usa pie exacto; el atajo no.
    evals = evaluar_universo(us, escenario_base(p, inv), p, inv, pie_exacto=True)
    vivos = [e for e in evals if not e.excluido]
    assert vivos, "el caso necesita unidades vivas para tener algo que puntuar"

    inertes = set(vivos[0].score_inertes)
    assert inertes == {"riesgo_microzona", "catalizador", "descuento_vs_microzona"}

    # Ninguno aparece en el desglose: no se muestra un numero de algo que no se midio.
    for ev in vivos:
        assert not inertes & set(ev.score_desglose)
        # Y el desglose sigue sumando el score completo: los pesos se repartieron, no se
        # perdieron. Un score "sobre 100" que suma 70 seria el mismo error con otra cara.
        assert abs(sum(ev.score_desglose.values()) - ev.score) < D("1e-9")

    # El maximo alcanzable vuelve a ser 100: con los tres inertes dentro, ninguna unidad
    # podia pasar de 70 + las tres constantes, y el tope real quedaba escondido.
    assert max(e.score for e in vivos) <= D(100)


def test_score_con_una_sola_unidad_no_declara_nada_inerte(cfg):
    """Con una unidad todo es constante por definicion. Declararlo todo inerte seria ruido."""
    p, inv = cfg
    evals = evaluar_universo([unidad()], escenario_base(p, inv), p, inv, pie_exacto=True)
    vivos = [e for e in evals if not e.excluido]
    if vivos:
        assert vivos[0].score_inertes == ()


# ------------------------------------------------------------- 9 · arriendo de equilibrio


def test_el_arriendo_de_equilibrio_real_equilibra_de_verdad(cfg):
    """Cobrando el equilibrio real, el flujo mensual queda en cero (± la tolerancia).

    Es la definicion de la metrica, y la version anterior no la cumplia por dos lados:
    la forma cerrada no descontaba incobrabilidad y congelaba el opex, cuando 4 de sus
    lineas crecen con el arriendo. El mismo defecto del par de pies, con la misma cura.
    """
    from dataclasses import replace as reemplazar

    from flujocero.finance.modelo import arriendo_equilibrio_real, evaluar

    p, inv = cfg
    u = unidad(arriendo_mensual_uf=D(8))  # deficitaria: el equilibrio esta por encima
    e = escenario()
    eq = arriendo_equilibrio_real(u, e, p, inv)
    assert eq is not None and eq > D(8)

    ev = evaluar(reemplazar(u, arriendo_mensual_uf=eq), e, p, inv, saltar_exclusiones=True)
    assert abs(ev.btcf_mensual_uf) < D("0.02"), (
        f"cobrando el 'equilibrio' el flujo da {ev.btcf_mensual_uf} UF/mes, no cero"
    )

    # Y la forma cerrada queda por DEBAJO, como su docstring declara: si algun dia la
    # supera, una de las dos cambio de significado y hay que mirar.
    assert ev.arriendo_equilibrio_uf <= eq + D("0.02")


def test_la_forma_cerrada_descuenta_incobrabilidad(cfg):
    """Con incobrabilidad i, el denominador lleva (1-i): un equilibrio que al cobrarse pasa
    por (1-i) y no lo descuenta, no equilibra — quedaba corto exactamente en esa fraccion."""
    from flujocero.finance import core as f

    con_i = f.arriendo_equilibrio_uf(D(100), D(20), D("0.08"), D("0.02"), D("0.03"))
    sin_i = f.arriendo_equilibrio_uf(D(100), D(20), D("0.08"), D(0), D("0.03"))
    assert abs(con_i - sin_i / (D(1) - D("0.02"))) < D("1e-12")
