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
    assert abs(f.tir(flujos)) < D("1e-6")


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
