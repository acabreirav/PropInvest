"""Agregación de arriendo por microzona × tipología × rango de m² — T-023.

Es el **numerador de todo el análisis**: el yield bruto sale de
`arriendo_mediano × 12 / precio_venta`, y ese arriendo mediano se calcula acá.

Tres decisiones que gobiernan el módulo:

1. **La clave es `(microzona, tipología, rango_m2)`, nunca la comuna.** El §2.4 lo fija con
   evidencia: dentro de Estación Central el mismo producto renta ~$300.000 en una calle y
   ~$350.000 a pocas cuadras — 17% de brecha *intracomunal*, más que la diferencia entre
   comunas. Agregar por comuna promedia dos mercados distintos y produce un yield que no
   existe en ninguna de las dos calles.

2. **La conversión a UF usa la UF del día de cada aviso, no la de hoy.** Un arriendo publicado
   en mayo se convierte con la UF de mayo. Usar la de hoy mezclaría el movimiento de la UF con
   el del mercado, que es justo lo que el §3.3 manda separar trabajando en términos reales.
   Si falta la UF de ese día, la fila **no se convierte y no se usa**: el §3.2 prohíbe imputar.

3. **La mediana, no el promedio.** Un aviso mal parseado o un departamento atípico mueve un
   promedio y no mueve una mediana. Se reportan además p25 y p75, que es lo que permite ver
   si la microzona es homogénea o si el rango esconde dos mercados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

D = Decimal


@dataclass(frozen=True)
class Comparable:
    """Un aviso de arriendo, ya normalizado a UF. Entrada pura de la agregación."""

    microzona_id: str
    tipologia: str
    m2_utiles: Decimal
    arriendo_uf: Decimal

    @property
    def arriendo_uf_m2(self) -> Decimal:
        return self.arriendo_uf / self.m2_utiles if self.m2_utiles else D(0)


@dataclass(frozen=True)
class Agregado:
    microzona_id: str
    tipologia: str
    rango_m2: str
    n: int
    p25: Decimal
    mediana: Decimal
    p75: Decimal
    uf_m2_mediana: Decimal
    m2_mediana: Decimal = D(0)

    @property
    def suficiente(self) -> bool:
        """§7.3: bajo 8 comparables la mediana no se usa para rankear."""
        return self.n >= MIN_COMPARABLES

    @property
    def dispersion(self) -> Decimal:
        """`(p75 - p25) / mediana`. Alta = el rango esconde dos mercados distintos."""
        return (self.p75 - self.p25) / self.mediana if self.mediana else D(0)


MIN_COMPARABLES = 8


# ------------------------------------------------------------------------ funciones puras


def etiqueta_rango(m2: Decimal, rangos: list[list[int]]) -> str | None:
    """`50` con rangos `[[35,50],[50,70]]` -> `'50-70'`. Cerrado abajo, abierto arriba.

    Devuelve `None` fuera de todo rango: sobre 140 m² se pierde el DFL2 y la unidad no compite
    (§12), así que su arriendo tampoco sirve de comparable para las que sí.
    """
    for lo, hi in rangos:
        if D(lo) <= m2 < D(hi):
            return f"{lo}-{hi}"
    return None


def percentil(valores: list[Decimal], p: Decimal) -> Decimal:
    """Percentil por interpolación lineal. Determinista y sin dependencias.

    `statistics.median` no sirve acá: haría falta una implementación distinta por percentil y
    se perdería el control sobre el redondeo, que en `Decimal` importa.
    """
    if not valores:
        return D(0)
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    pos = (D(len(orden)) - 1) * p
    bajo = int(pos)
    alto = min(bajo + 1, len(orden) - 1)
    return orden[bajo] + (orden[alto] - orden[bajo]) * (pos - D(bajo))


def agregar(comparables: list[Comparable], rangos: list[list[int]]) -> list[Agregado]:
    """Función pura: agrupa por `(microzona, tipología, rango_m2)` y calcula los percentiles.

    Sin I/O, sin reloj, sin red. Es lo que la hace testeable contra casos a mano (§11).
    """
    grupos: dict[tuple[str, str, str], list[Comparable]] = {}
    for c in comparables:
        rango = etiqueta_rango(c.m2_utiles, rangos)
        if rango is None:
            continue
        grupos.setdefault((c.microzona_id, c.tipologia, rango), []).append(c)

    salida: list[Agregado] = []
    for (mz, tip, rango), items in sorted(grupos.items()):
        arriendos = [c.arriendo_uf for c in items]
        por_m2 = [c.arriendo_uf_m2 for c in items]
        salida.append(
            Agregado(
                microzona_id=mz,
                tipologia=tip,
                rango_m2=rango,
                n=len(items),
                p25=percentil(arriendos, D("0.25")),
                mediana=percentil(arriendos, D("0.5")),
                p75=percentil(arriendos, D("0.75")),
                uf_m2_mediana=percentil(por_m2, D("0.5")),
                # La superficie tipica de la celda. Un rango de m2 NO es homogeneo: en
                # `0-35` el 60% de los comparables mide 31-35, asi que la mediana de
                # arriendo describe a un depto grande de la banda y no al chico.
                m2_mediana=percentil([c.m2_utiles for c in items], D("0.5")),
            )
        )
    return salida


# ------------------------------------------------------------------- conversión y carga


class SinSerieUF(RuntimeError):
    """No hay UF cargada para convertir. Se detiene en vez de inventar un tipo de cambio."""


@dataclass(frozen=True)
class EstadoSerie:
    """Qué tan cargada está la serie de UF. Sin esto, "4.099 descartados" no dice por qué."""

    n: int
    desde: date | None
    hasta: date | None

    def __str__(self) -> str:
        if not self.n:
            return "serie UF: VACÍA"
        return f"serie UF: {self.n} días, {self.desde} → {self.hasta}"


def estado_serie(conexion: Any) -> EstadoSerie:
    fila = conexion.execute(
        "SELECT count(*), min(fecha), max(fecha) FROM dim_tiempo_financiero "
        "WHERE serie = 'uf' AND valor IS NOT NULL"
    ).fetchone()
    return EstadoSerie(int(fila[0] or 0), fila[1], fila[2])


def serie_uf(conexion: Any) -> dict[date, Decimal]:
    """La serie completa de UF, para convertir cada aviso con la UF de SU día."""
    return {
        f[0]: Decimal(str(f[1]))
        for f in conexion.execute(
            "SELECT fecha, valor FROM dim_tiempo_financiero WHERE serie = 'uf' AND valor IS NOT NULL"
        ).fetchall()
    }


def uf_del_dia(serie: dict[date, Decimal], momento: datetime) -> Decimal | None:
    """La UF de ese día, o la del día hábil anterior más cercano dentro de una semana.

    La UF se publica todos los días, pero una serie puede tener huecos. Se retrocede hasta
    siete días y no más: más allá, la conversión deja de ser del día del aviso y se prefiere
    perder la fila antes que convertirla con un valor que no le corresponde.
    """
    dia = momento.date()
    for atras in range(8):
        valor = serie.get(date.fromordinal(dia.toordinal() - atras))
        if valor:
            return valor
    return None


def comparables_desde_duckdb(conexion: Any) -> tuple[list[Comparable], dict[str, int]]:
    """Lee `fact_arriendo_comp` y normaliza a UF. Devuelve `(comparables, descartes)`.

    Los descartes se cuentan por motivo y se devuelven: una fila que no entra a la mediana
    tiene que poder explicarse, no desaparecer.
    """
    serie = serie_uf(conexion)
    filas = conexion.execute(
        "SELECT microzona_id, tipologia, m2_utiles, arriendo_uf, arriendo_clp, fetched_at "
        "FROM fact_arriendo_comp "
        "WHERE activo AND coalesce(sospechoso, FALSE) = FALSE"
    ).fetchall()

    comparables: list[Comparable] = []
    descartes = {"sin_microzona": 0, "sin_tipologia": 0, "sin_m2": 0, "sin_uf_del_dia": 0}
    for mz, tip, m2, arr_uf, arr_clp, momento in filas:
        if not mz:
            descartes["sin_microzona"] += 1
            continue
        if not tip:
            descartes["sin_tipologia"] += 1
            continue
        if not m2:
            descartes["sin_m2"] += 1
            continue

        if arr_uf is not None:
            en_uf = Decimal(str(arr_uf))
        else:
            uf = uf_del_dia(serie, momento) if momento else None
            if uf is None:
                descartes["sin_uf_del_dia"] += 1
                continue
            en_uf = Decimal(str(arr_clp)) / uf

        comparables.append(
            Comparable(
                microzona_id=mz, tipologia=tip, m2_utiles=Decimal(str(m2)), arriendo_uf=en_uf
            )
        )
    return comparables, descartes


def cargar_en_duckdb(conexion: Any, agregados: list[Agregado], ahora: datetime) -> int:
    """Reemplaza la tabla entera: es un derivado, no un histórico.

    `fact_arriendo_comp` guarda la historia; recalcular la agregación sobre datos nuevos tiene
    que dar el estado actual, no acumularse encima del anterior.
    """
    conexion.execute("DELETE FROM agg_arriendo_microzona")
    for a in agregados:
        conexion.execute(
            "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, n, "
            "arriendo_uf_p25, arriendo_uf_mediana, arriendo_uf_p75, arriendo_uf_m2_mediana, "
            "m2_mediana, avisos_activos, calculado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                a.microzona_id,
                a.tipologia,
                a.rango_m2,
                a.n,
                a.p25,
                a.mediana,
                a.p75,
                a.uf_m2_mediana,
                a.m2_mediana,
                a.n,
                ahora,
            ),
        )
    return len(agregados)
