"""Gate de fuente — CLAUDE.md §7.1.

Verifica dos cosas distintas y las reporta por separado:

1. que el módulo implemente el protocolo `Source` (métodos y atributos);
2. que las filas que produce lleven las seis columnas de procedencia del §3.1
   y un `evidence_level` legal.

Lo segundo es lo que de verdad importa: un colector puede tener la forma correcta
y aun así insertar filas sin procedencia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from flujocero.sources.base import COLUMNAS_PROCEDENCIA, LegalTier

TIERS_VALIDOS: tuple[str, ...] = (
    "api_oficial",
    "json_publico",
    "html_permitido",
    "html_prohibido",
)
NIVELES_EVIDENCIA: tuple[str, ...] = ("V", "D", "E", "ND")
METODOS = ("robots_ok", "collect", "parse", "selftest")


@dataclass
class ReporteContrato:
    source_id: str
    ok: bool = True
    fallos: list[str] = field(default_factory=list)

    def fallar(self, msg: str) -> None:
        self.ok = False
        self.fallos.append(msg)

    def __str__(self) -> str:
        if self.ok:
            return f"✓ {self.source_id}: cumple el contrato de fuente"
        detalle = "\n".join(f"    - {f}" for f in self.fallos)
        return f"✗ {self.source_id}:\n{detalle}"


def verificar_protocolo(fuente: Any) -> ReporteContrato:
    """Comprueba atributos y métodos exigidos por el §7.1."""
    sid = getattr(fuente, "id", None) or fuente.__class__.__name__
    rep = ReporteContrato(source_id=str(sid))

    if not getattr(fuente, "id", ""):
        rep.fallar("falta el atributo `id` (slug estable)")
    tier: LegalTier | None = getattr(fuente, "legal_tier", None)
    if tier not in TIERS_VALIDOS:
        rep.fallar(f"`legal_tier` inválido: {tier!r}; esperado uno de {TIERS_VALIDOS}")
    if not getattr(fuente, "parser_version", ""):
        rep.fallar("falta `parser_version`: sin él no se puede versionar el parseo (§3.1)")
    for metodo in METODOS:
        if not callable(getattr(fuente, metodo, None)):
            rep.fallar(f"falta el método `{metodo}()`")
    return rep


def verificar_filas(source_id: str, filas: list[Any]) -> ReporteContrato:
    """Regla dura del §3.1: sin las seis columnas, la fila no puede existir."""
    rep = ReporteContrato(source_id=source_id)
    if not filas:
        rep.fallar("el parser no produjo ninguna fila")
        return rep

    for i, fila in enumerate(filas):
        for col in COLUMNAS_PROCEDENCIA:
            valor = getattr(fila, col, None)
            if valor in (None, ""):
                rep.fallar(f"fila {i}: `{col}` vacío — CLAUDE.md §3.1")
        fecha = getattr(fila, "fetched_at", None)
        if isinstance(fecha, datetime) and fecha.tzinfo is None:
            rep.fallar(f"fila {i}: `fetched_at` sin tzinfo; la base guarda UTC (§11)")
        nivel = getattr(fila, "evidence_level", None)
        if nivel is not None and nivel not in NIVELES_EVIDENCIA:
            rep.fallar(f"fila {i}: `evidence_level` inválido: {nivel!r}")
        if rep.fallos and i >= 2:  # no inundar el reporte
            rep.fallar(f"... y {len(filas) - i - 1} filas más sin revisar")
            break
    return rep


def verificar(fuente: Any, filas: list[Any] | None = None) -> ReporteContrato:
    """Corre ambas verificaciones y devuelve un único reporte."""
    rep = verificar_protocolo(fuente)
    if filas is not None:
        de_filas = verificar_filas(rep.source_id, filas)
        if not de_filas.ok:
            rep.ok = False
            rep.fallos.extend(de_filas.fallos)
    return rep
