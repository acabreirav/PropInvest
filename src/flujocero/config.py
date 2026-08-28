"""Carga y valida config/*.yml. Fuente única de supuestos: ningún número mágico en el código.

Regla de CLAUDE.md §3.2: un valor marcado `E` (estimado) SIN `rango` de sensibilidad es un bug
y la carga falla. Es la forma barata de impedir que un supuesto se cuele sin declararse.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml

D = Decimal
Evidencia = Literal["V", "D", "E", "C", "ND"]
RAIZ = Path(__file__).resolve().parents[2]


class ErrorDeConfig(ValueError):
    """La configuración es inválida. Nunca se degrada en silencio."""


class Valor:
    """Un parámetro con su nivel de evidencia y, si es estimado, su rango de sensibilidad."""

    __slots__ = ("v", "evidence", "rango", "fuente", "nota", "ruta")

    def __init__(self, ruta: str, crudo: Any) -> None:
        self.ruta = ruta
        if isinstance(crudo, dict) and "v" in crudo:
            self.v = crudo["v"]
            self.evidence: Evidencia = crudo.get("evidence", "E")
            self.rango = crudo.get("rango")
            self.fuente = crudo.get("fuente")
            self.nota = crudo.get("nota")
        else:
            self.v, self.evidence, self.rango, self.fuente, self.nota = crudo, "V", None, None, None
        if self.evidence == "E" and self.rango is None:
            raise ErrorDeConfig(
                f"{ruta}: valor estimado sin `rango` de sensibilidad. "
                "Todo supuesto estimado debe declarar su rango (CLAUDE.md §3.2)."
            )

    def dec(self) -> Decimal:
        if self.v is None:
            raise ErrorDeConfig(f"{self.ruta}: valor nulo, no se puede usar en el modelo")
        return D(str(self.v))

    def __repr__(self) -> str:
        return f"Valor({self.ruta}={self.v!r}, {self.evidence})"


class Config:
    """Acceso por ruta con puntos: cfg['financiamiento.plazo_anios']."""

    def __init__(self, datos: dict[str, Any], origen: str) -> None:
        self._datos, self.origen, self._cache = datos, origen, {}

    def crudo(self, ruta: str) -> Any:
        nodo: Any = self._datos
        for parte in ruta.split("."):
            if not isinstance(nodo, dict) or parte not in nodo:
                raise ErrorDeConfig(f"{self.origen}: no existe la ruta `{ruta}`")
            nodo = nodo[parte]
        return nodo

    def __getitem__(self, ruta: str) -> Valor:
        if ruta not in self._cache:
            self._cache[ruta] = Valor(f"{self.origen}:{ruta}", self.crudo(ruta))
        return self._cache[ruta]

    def d(self, ruta: str) -> Decimal:
        return self[ruta].dec()

    def estimados(self) -> list[Valor]:
        """Todos los supuestos `E`. El análisis de sensibilidad recorre exactamente esta lista."""
        salida: list[Valor] = []

        def caminar(nodo: Any, ruta: str) -> None:
            if isinstance(nodo, dict):
                if "v" in nodo:
                    val = Valor(f"{self.origen}:{ruta}", nodo)
                    if val.evidence == "E":
                        salida.append(val)
                    return
                for k, v in nodo.items():
                    caminar(v, f"{ruta}.{k}" if ruta else k)

        caminar(self._datos, "")
        return salida


def cargar(nombre: str, raiz: Path | None = None) -> Config:
    ruta = (raiz or RAIZ) / "config" / f"{nombre}.yml"
    if not ruta.exists():
        raise ErrorDeConfig(f"falta {ruta}")
    return Config(yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}, nombre)


# --------------------------------------------------------------- capacidad de endeudamiento


def ticket_maximo_uf(
    renta_liquida_clp: Decimal,
    otras_cuotas_clp: Decimal,
    tasa_anual: Decimal,
    plazo_anios: int,
    ltv: Decimal,
    uf_clp: Decimal,
    max_pct_ingreso: Decimal,
    max_carga_financiera: Decimal,
    tope_uf: Decimal,
) -> dict[str, Decimal]:
    """Ticket máximo por capacidad de pago, con las dos reglas que aplica la banca chilena.

    Regla 1: dividendo <= 25% de la renta líquida.
    Regla 2: carga financiera total (dividendo + otras cuotas) <= 45% de la renta líquida.
    """
    from flujocero.finance.core import dividendo_frances

    por_dividendo = renta_liquida_clp * max_pct_ingreso
    por_carga = renta_liquida_clp * max_carga_financiera - otras_cuotas_clp
    dividendo_max_clp = min(por_dividendo, por_carga)
    if dividendo_max_clp <= 0:
        raise ErrorDeConfig("las otras cuotas ya consumen toda la carga financiera disponible")

    cuota_por_uf = dividendo_frances(D(1), tasa_anual, plazo_anios)
    credito_uf = (dividendo_max_clp / uf_clp) / cuota_por_uf
    return {
        "dividendo_max_clp": dividendo_max_clp,
        "credito_max_uf": credito_uf,
        "ticket_max_uf": min(credito_uf / ltv, tope_uf),
        "restriccion_activa": D(1) if por_carga < por_dividendo else D(0),
    }


def con_valor(base: Config, ruta: str, valor: Any, fuente: str) -> Config:
    """Copia de `base` con un valor reemplazado, marcado `V` y con su fuente.

    Es lo que permite que el motor siga siendo puro. El §11 le prohibe I/O, asi que no
    puede leer la UF de la base por su cuenta: alguien de afuera la lee, arma un `Config`
    con ella y se lo pasa. El valor viaja con su `evidence` y su `fuente`, no pelado.
    """
    import copy

    datos = copy.deepcopy(base._datos)  # noqa: SLF001 — copia deliberada, no acceso al estado
    nodo = datos
    partes = ruta.split(".")
    for parte in partes[:-1]:
        nodo = nodo.setdefault(parte, {})
    anterior = nodo.get(partes[-1])
    nuevo: dict[str, Any] = {"v": valor, "evidence": "V", "fuente": fuente}
    if isinstance(anterior, dict) and "rango" in anterior:
        nuevo["rango"] = anterior["rango"]
    nodo[partes[-1]] = nuevo
    return Config(datos, f"{base.origen}+{ruta}")


def uf_desde_la_base(conexion: Any, fecha: Any = None) -> tuple[Decimal, str] | None:
    """La UF mas reciente de `dim_tiempo_financiero`, con la fuente que la respalda.

    Devuelve `None` si no hay serie cargada, para que quien llame decida si cae al valor
    fijo de `params.yml` o se detiene. No imputa nada por su cuenta (§3.2).
    """
    if fecha is None:
        fila = conexion.execute(
            "SELECT valor, fecha, source_id, source_url FROM dim_tiempo_financiero "
            "WHERE serie = 'uf' ORDER BY fecha DESC LIMIT 1"
        ).fetchone()
    else:
        fila = conexion.execute(
            "SELECT valor, fecha, source_id, source_url FROM dim_tiempo_financiero "
            "WHERE serie = 'uf' AND fecha <= ? ORDER BY fecha DESC LIMIT 1",
            (fecha,),
        ).fetchone()
    if not fila or fila[0] is None:
        return None
    valor, dia, source_id, _url = fila
    return Decimal(str(valor)), f"{source_id} · dim_tiempo_financiero · {dia}"
