"""Motor financiero. Funciones PURAS: sin I/O, sin now(), sin números mágicos.

Todas las fórmulas están en docs/02-modelo-financiero.md. Si el código y el documento
divergen, el documento manda y el código es el bug.

Convención: TODO en UF, términos reales.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

D = Decimal


# --------------------------------------------------------------------------- crédito


def tasa_mensual(tasa_anual: Decimal, capitalizacion: str = "simple") -> Decimal:
    """Convierte tasa anual a mensual.

    'simple' = tasa/12 (convención bancaria chilena habitual).
    'compuesta' = (1+t)^(1/12) - 1. Declara cuál usas al comparar con el banco.
    """
    if capitalizacion == "compuesta":
        return (D(1) + tasa_anual) ** (D(1) / D(12)) - D(1)
    return tasa_anual / D(12)


def dividendo_frances(credito_uf: Decimal, tasa_anual: Decimal, plazo_anios: int) -> Decimal:
    """Cuota mensual del sistema francés, en UF."""
    i = tasa_mensual(tasa_anual)
    n = plazo_anios * 12
    if i == 0:
        return credito_uf / D(n)
    factor = (D(1) + i) ** n
    return credito_uf * (i * factor) / (factor - D(1))


def factor_dividendo_anual(tasa_anual: Decimal, plazo_anios: int) -> Decimal:
    """Servicio de deuda anual como fracción del crédito.

    Anclas de test: 0,05798 al 4,10%/30a · 0,06332 al 4,85%/30a.
    """
    return dividendo_frances(D(1), tasa_anual, plazo_anios) * D(12)


def saldo_insoluto(
    credito_uf: Decimal, tasa_anual: Decimal, plazo_anios: int, meses_pagados: int
) -> Decimal:
    """Capital pendiente tras `meses_pagados` cuotas."""
    i = tasa_mensual(tasa_anual)
    n = plazo_anios * 12
    if i == 0:
        return credito_uf * D(n - meses_pagados) / D(n)
    return credito_uf * ((D(1) + i) ** n - (D(1) + i) ** meses_pagados) / ((D(1) + i) ** n - D(1))


# --------------------------------------------------------------------------- ingresos


def factor_erosion(inflacion_anual: Decimal) -> Decimal:
    """Erosión intra-anual del arriendo medido en UF.

    El arriendo se reajusta 1 vez al año; la UF sube todos los días. Con pi=3% el factor
    es 0,985: se pierde ~1,5% de renta real cada año, permanentemente.
    Omitir esto sobreestima el flujo. Ver docs/02-modelo-financiero.md §1.1.
    """
    return D(1) / (D(1) + inflacion_anual / D(2))


def pgi(arriendo_mensual_uf: Decimal) -> Decimal:
    return arriendo_mensual_uf * D(12)


def egi(
    arriendo_mensual_uf: Decimal,
    vacancia: Decimal,
    incobrabilidad: Decimal,
    inflacion_anual: Decimal,
) -> Decimal:
    return (
        pgi(arriendo_mensual_uf)
        * (D(1) - vacancia)
        * (D(1) - incobrabilidad)
        * factor_erosion(inflacion_anual)
    )


# --------------------------------------------------------------------------- resultado


@dataclass(frozen=True)
class Opex:
    """Gastos operativos anuales del arrendador, en UF. El NOI chileno EXCLUYE la deuda."""

    contribuciones: Decimal
    gastos_comunes_vacancia: Decimal
    seguro_incendio_sismo: Decimal
    administracion: Decimal
    corretaje_amortizado: Decimal
    mantencion: Decimal
    impuesto_renta: Decimal  # 0 si DFL2 dentro de las 2 primeras viviendas

    def total(self) -> Decimal:
        return (
            self.contribuciones
            + self.gastos_comunes_vacancia
            + self.seguro_incendio_sismo
            + self.administracion
            + self.corretaje_amortizado
            + self.mantencion
            + self.impuesto_renta
        )


def noi(egi_uf: Decimal, opex: Opex) -> Decimal:
    return egi_uf - opex.total()


def cap_rate(noi_uf: Decimal, precio_uf: Decimal, gastos_cierre_uf: Decimal) -> Decimal:
    """Sobre inversión total. Declara siempre el denominador que usas."""
    return noi_uf / (precio_uf + gastos_cierre_uf)


def rentabilidad_bruta(arriendo_mensual_uf: Decimal, precio_uf: Decimal) -> Decimal:
    return pgi(arriendo_mensual_uf) / precio_uf


def dscr(noi_uf: Decimal, servicio_deuda_anual_uf: Decimal) -> Decimal:
    return noi_uf / servicio_deuda_anual_uf


def btcf_mensual(noi_uf: Decimal, dividendo_total_mensual_uf: Decimal) -> Decimal:
    return noi_uf / D(12) - dividendo_total_mensual_uf


# ------------------------------------------------------------------- puntos de equilibrio


def pie_minimo_flujo_cero(
    yield_bruto: Decimal, tasa_anual: Decimal, plazo_anios: int, opex_pct: Decimal
) -> Decimal:
    """Fracción del precio que hay que poner para que el flujo mensual sea >= 0.

    LA métrica insignia del producto. Anclas de test (docs/00-hallazgos.md §6):
      yield 4,0% @ 4,10% -> ~0,414   ·   yield 3,6% @ 4,85% -> ~0,517
    """
    f = factor_dividendo_anual(tasa_anual, plazo_anios)
    return D(1) - (D(1) - opex_pct) * yield_bruto / f


def arriendo_equilibrio_uf(
    servicio_deuda_anual_uf: Decimal,
    opex_anual_uf: Decimal,
    vacancia: Decimal,
    inflacion_anual: Decimal,
) -> Decimal:
    """Arriendo mensual mínimo, en UF, para flujo cero."""
    denom = D(12) * (D(1) - vacancia) * factor_erosion(inflacion_anual)
    return (servicio_deuda_anual_uf + opex_anual_uf) / denom


def break_even_occupancy(
    opex_anual_uf: Decimal, servicio_deuda_anual_uf: Decimal, pgi_uf: Decimal
) -> Decimal:
    return (opex_anual_uf + servicio_deuda_anual_uf) / pgi_uf


# --------------------------------------------------------------------------- retorno


def tir(flujos: Sequence[Decimal], tol: Decimal = D("1e-10"), max_iter: int = 300) -> Decimal:
    """TIR por bisección sobre [-0,9999; 10]. Flujos en UF => la TIR resultante es REAL.

    Para compararla con un depósito a plazo nominal, súmale la inflación esperada.
    """

    def van(r: Decimal) -> Decimal:
        return sum((f / (D(1) + r) ** t for t, f in enumerate(flujos)), D(0))

    lo, hi = D("-0.9999"), D(10)
    if van(lo) * van(hi) > 0:
        raise ValueError("TIR sin cambio de signo en el intervalo")
    for _ in range(max_iter):
        mid = (lo + hi) / D(2)
        v = van(mid)
        if abs(v) < tol:
            return mid
        if van(lo) * v < 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / D(2)


def van(flujos: Sequence[Decimal], tasa_descuento_real: Decimal) -> Decimal:
    return sum((f / (D(1) + tasa_descuento_real) ** t for t, f in enumerate(flujos)), D(0))
