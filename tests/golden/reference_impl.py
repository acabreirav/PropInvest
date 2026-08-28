"""Implementación de referencia INDEPENDIENTE del dividendo.

Existe para que dos lógicas distintas tengan que coincidir a 1e-6 (CLAUDE.md §7.2, caso 1).
Deliberadamente NO importa nada de flujocero.finance: si alguien "arregla" el motor con un
error, esta implementación no lo sigue.

Método: amortización mes a mes, buscando por bisección la cuota que deja saldo cero.
"""

from decimal import Decimal, getcontext

getcontext().prec = 40
D = Decimal


def saldo_final(credito: Decimal, tasa_anual: Decimal, plazo_anios: int, cuota: Decimal) -> Decimal:
    saldo = credito
    i = tasa_anual / D(12)
    for _ in range(plazo_anios * 12):
        saldo = saldo * (D(1) + i) - cuota
    return saldo


def dividendo_por_amortizacion(credito: Decimal, tasa_anual: Decimal, plazo_anios: int) -> Decimal:
    lo, hi = D(0), credito
    for _ in range(300):
        mid = (lo + hi) / D(2)
        if saldo_final(credito, tasa_anual, plazo_anios, mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / D(2)
