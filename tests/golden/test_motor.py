"""Casos de oro del motor financiero — CLAUDE.md §7.2."""

from decimal import Decimal as D
from decimal import getcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from flujocero.finance import core as f
from tests.golden.reference_impl import dividendo_por_amortizacion

getcontext().prec = 40


# 1 · doble implementación independiente
@pytest.mark.parametrize(
    "credito,tasa,plazo",
    [(D(4500), D("0.0340"), 30), (D(3000), D("0.0397"), 20), (D(5400), D("0.0485"), 30)],
)
def test_dividendo_doble_implementacion(credito: D, tasa: D, plazo: int) -> None:
    a = f.dividendo_frances(credito, tasa, plazo)
    b = dividendo_por_amortizacion(credito, tasa, plazo)
    assert abs(a - b) < D("1e-6")


# 2 · pie de equilibrio contra las anclas derivadas de la investigación
@pytest.mark.parametrize(
    "yield_bruto,tasa,lo,hi",
    [
        (D("0.040"), D("0.0410"), D("0.40"), D("0.43")),
        (D("0.036"), D("0.0485"), D("0.50"), D("0.53")),
        (D("0.045"), D("0.0410"), D("0.32"), D("0.36")),
    ],
)
def test_pie_minimo_flujo_cero(yield_bruto: D, tasa: D, lo: D, hi: D) -> None:
    pie = f.pie_minimo_flujo_cero(yield_bruto, tasa, 30, D("0.15"))
    assert lo <= pie <= hi, f"pie mínimo fuera de rango: {pie}"


# 3 · erosión intra-anual
def test_factor_erosion() -> None:
    assert abs(f.factor_erosion(D("0.03")) - D("0.985")) < D("0.001")


# 4 · factor de dividendo anual — anclas 5,798% y 6,332%
@pytest.mark.parametrize(
    "tasa,esperado", [(D("0.0410"), D("0.05798")), (D("0.0485"), D("0.06332"))]
)
def test_factor_dividendo_anual(tasa: D, esperado: D) -> None:
    assert abs(f.factor_dividendo_anual(tasa, 30) - esperado) < D("0.0005")


# 5 · TIR real de una operación sin flujo ni apreciación real = 0
def test_tir_neutra() -> None:
    flujos = [D(-1000)] + [D(0)] * 9 + [D(1000)]
    # §7.2 punto 5 pide 1e-9, no 1e-6. La diferencia importa: es la tolerancia que
    # distingue un cero real de un cero que quedo cerca por casualidad del solver.
    assert abs(f.tir(flujos)) < D("1e-9")


# 5b · anclas de FORMA CERRADA para la TIR (verificador §7.6, 03-sep, F4): la neutra
# de arriba tiene raiz 0 y no distingue un off-by-one en el descuento — estas si.
def test_tir_anclas_de_forma_cerrada() -> None:
    # -100 hoy, 110 en un anio: TIR = 10% exacto
    assert abs(f.tir([D(-100), D(110)]) - D("0.10")) < D("1e-9")
    # -100 hoy, 121 en DOS anios (121 = 100·1,1²): TIR = 10% exacto. Un descuento
    # corrido en un periodo daria otra raiz y este test lo caza.
    assert abs(f.tir([D(-100), D(0), D(121)]) - D("0.10")) < D("1e-9")
    # sin cambio de signo no hay TIR: fallo ruidoso, jamas un numero inventado
    with pytest.raises(ValueError):
        f.tir([D(-100), D(-10)])


# 5c · TIR no certificable => TirNoDefinida, jamas un numero (T-943, ADR 013)
def test_tir_multiples_cambios_de_signo_es_nd() -> None:
    # El caso del verificador F5: raices en 10% y 20% — la biseccion elegiria una
    # sin avisar. Verificacion independiente de las dos raices, a mano:
    #   VAN(10%) = -100 + 230/1,1 - 132/1,21 = -100 + 209,0909 - 109,0909 = 0
    #   VAN(20%) = -100 + 230/1,2 - 132/1,44 = -100 + 191,6667 -  91,6667 = 0
    with pytest.raises(f.TirNoDefinida, match="no es única"):
        f.tir([D(-100), D(230), D(-132)])
    # cero cambios de signo (todo positivo): la TIR no existe
    with pytest.raises(f.TirNoDefinida, match="no existe"):
        f.tir([D(100), D(10)])
    # y el conteo ignora los ceros: [-100, 0, 121] sigue siendo UN cambio => 10%
    assert f.cambios_de_signo([D(-100), D(0), D(121)]) == 1
    assert f.cambios_de_signo([D(-100), D(230), D(-132)]) == 2


# 6 · el saldo insoluto llega a cero al final del plazo
def test_saldo_insoluto_final() -> None:
    s = f.saldo_insoluto(D(4500), D("0.034"), 30, 360)
    assert abs(s) < D("1e-6")


# 7 · invariantes
@settings(max_examples=2000, deadline=None)
@given(
    arriendo=st.decimals(min_value=D(3), max_value=D(60), places=3),
    vacancia=st.decimals(min_value=D(0), max_value=D("0.3"), places=3),
    incob=st.decimals(min_value=D(0), max_value=D("0.1"), places=3),
)
def test_egi_nunca_supera_pgi(arriendo: D, vacancia: D, incob: D) -> None:
    e = f.egi(arriendo, vacancia, incob, D("0.03"))
    assert D(0) <= e <= f.pgi(arriendo)


# ------------------------------------------------------------- amortización y costo real


def test_amortizacion_del_primer_anio_es_la_diferencia_de_saldos() -> None:
    """Identidad contable: lo amortizado en 12 meses = saldo(0) - saldo(12)."""
    credito, tasa, plazo = D(3000), D("0.033"), 30
    esperado = f.saldo_insoluto(credito, tasa, plazo, 0) - f.saldo_insoluto(
        credito, tasa, plazo, 12
    )
    assert f.amortizacion_periodo(credito, tasa, plazo, 0, 12) == esperado
    assert f.amortizacion_mensual_promedio(credito, tasa, plazo, 1) == esperado / D(12)


def test_la_amortizacion_mas_el_interes_es_exactamente_el_dividendo() -> None:
    """El dividendo francés se parte en dos y no sobra nada: capital + interés."""
    credito, tasa, plazo = D(2500), D("0.033"), 30
    div = f.dividendo_frances(credito, tasa, plazo)
    i = f.tasa_mensual(tasa)
    interes_mes_1 = credito * i
    amort_mes_1 = f.amortizacion_periodo(credito, tasa, plazo, 0, 1)
    assert abs((interes_mes_1 + amort_mes_1) - div) < D("1e-18")


def test_la_amortizacion_crece_con_los_anios() -> None:
    """En el sistema francés la parte de capital sube y la de interés baja."""
    credito, tasa, plazo = D(3000), D("0.033"), 30
    a1 = f.amortizacion_mensual_promedio(credito, tasa, plazo, 1)
    a10 = f.amortizacion_mensual_promedio(credito, tasa, plazo, 10)
    a30 = f.amortizacion_mensual_promedio(credito, tasa, plazo, 30)
    assert D(0) < a1 < a10 < a30


def test_el_costo_de_tenencia_es_el_deficit_neto_de_amortizacion() -> None:
    """Un déficit de caja de 5 UF con 3 UF de amortización cuesta 2 UF, no 5."""
    assert f.costo_tenencia_mensual(D("-5"), D("3")) == D("-2")
    # Si la amortización supera el déficit, la tenencia construye patrimonio neto.
    assert f.costo_tenencia_mensual(D("-2"), D("3")) == D("1")


def test_la_amortizacion_nunca_supera_al_dividendo() -> None:
    """Invariante: si lo hiciera, el interés sería negativo."""
    for tasa in (D("0.025"), D("0.033"), D("0.05")):
        credito, plazo = D(3000), 30
        div = f.dividendo_frances(credito, tasa, plazo)
        for anio in (1, 15, 30):
            amort = f.amortizacion_mensual_promedio(credito, tasa, plazo, anio)
            assert D(0) < amort <= div


def test_amortizacion_con_rango_invertido_es_error() -> None:
    with pytest.raises(ValueError, match="posterior"):
        f.amortizacion_periodo(D(1000), D("0.03"), 30, 12, 12)
