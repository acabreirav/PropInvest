"""Qué falta recolectar, ordenado por cuántas unidades desbloquea — T-935.

## El hallazgo que lo justifica

Medido el 30-ago-2026: de **2.380 unidades de venta con precio verificado**, 2.043 —el
**86%**— se caen en el emparejamiento por `sin_comparables`. No por falta de avisos de venta,
sino porque **su celda de arriendo no llega a los 8 comparables que exige el §7.3**.

(El 14% restante *sobrevive al emparejamiento*; cuántas de esas llegan al ranking es otra
cosa, porque después vienen las exclusiones duras del §12. Este módulo mide solo el primer
filtro, que es el que se puede destrabar recolectando.)

Y el desbalance está concentrado de una forma que se puede explotar:

    san-miguel/el-llano · 2D2B  ->  108 unidades en venta,  2 comparables de arriendo
    nunoa/metro-nunoa   · 2D2B  ->   60 unidades en venta,  1 comparable
    san-miguel/lo-vial  · 2D2B  ->   37 unidades en venta,  0 comparables

**Seis avisos de arriendo en una sola celda desbloquean 108 unidades.** Recolectar "más
arriendo" a ciegas reparte ese esfuerzo entre celdas que ya sirven y celdas que no le
importan a nadie; recolectar dirigido lo concentra donde paga.

## Lo que este módulo NO hace

No baja el umbral de 8 comparables. Ese número es del §7.3 y protege contra la mediana de
tres avisos, que es ruido con cara de dato. La respuesta correcta a "faltan comparables" es
conseguirlos, no dejar de exigirlos.

Tampoco propone caer a la comuna. El §2.4 lo prohíbe con evidencia: 17% de brecha
intracomunal, más que entre comunas.

Módulo puro salvo la consulta: entra una conexión, sale una lista ordenada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from flujocero.agg.arriendo import MIN_COMPARABLES, etiqueta_rango
from flujocero.alcance import Alcance
from flujocero.quality.checks import FRESCURA_MAX_DIAS

D = Decimal


@dataclass(frozen=True)
class Hueco:
    """Una celda que tiene unidades esperando y no tiene con qué evaluarlas."""

    microzona_id: str
    tipologia: str
    rango_m2: str
    unidades_bloqueadas: int
    comparables_actuales: int

    @property
    def faltan(self) -> int:
        return max(0, MIN_COMPARABLES - self.comparables_actuales)

    @property
    def palanca(self) -> Decimal:
        """Unidades desbloqueadas por cada aviso de arriendo que haya que conseguir.

        Es el número que ordena la lista y el punto entero del módulo. Una celda con 108
        unidades a la que le faltan 6 comparables rinde 18 unidades por aviso; una con 12
        unidades a la que le falta 1 rinde 12. La primera va antes, aunque la segunda parezca
        más fácil por necesitar un solo aviso.

        Es lo que convierte "recolectar más arriendo" —que reparte el esfuerzo entre celdas
        que ya sirven y celdas que no le importan a nadie— en un plan.
        """
        return D(self.unidades_bloqueadas) / D(self.faltan) if self.faltan else D(0)

    @property
    def comuna_id(self) -> str:
        return self.microzona_id.split("/")[0]


@dataclass
class Diagnostico:
    huecos: list[Hueco]
    unidades_rankeables_hoy: int
    unidades_con_precio: int

    @property
    def desbloqueables(self) -> int:
        return sum(h.unidades_bloqueadas for h in self.huecos)

    @property
    def avisos_necesarios(self) -> int:
        return sum(h.faltan for h in self.huecos)

    def top(self, n: int) -> list[Hueco]:
        return self.huecos[:n]

    def por_comuna(self) -> dict[str, tuple[int, int]]:
        """`comuna -> (unidades desbloqueables, avisos que hay que conseguir)`.

        Es la vista que sirve para planificar una corrida: el colector recorre por comuna,
        no por celda.
        """
        salida: dict[str, tuple[int, int]] = {}
        for h in self.huecos:
            u, a = salida.get(h.comuna_id, (0, 0))
            salida[h.comuna_id] = (u + h.unidades_bloqueadas, a + h.faltan)
        return dict(sorted(salida.items(), key=lambda kv: -kv[1][0]))


CONSULTA = """
SELECT v.microzona_id, v.tipologia, v.m2_utiles, v.fetched_at
FROM fact_unidad_venta v
WHERE v.valid_to IS NULL AND v.precio_uf IS NOT NULL AND v.evidence_level = 'V'
  AND v.microzona_id IS NOT NULL AND v.tipologia IS NOT NULL AND v.m2_utiles IS NOT NULL
"""


def diagnosticar(
    conexion: Any,
    rangos: list[list[int]],
    minimo: int = MIN_COMPARABLES,
    alcance: Alcance | None = None,
    ahora: datetime | None = None,
) -> Diagnostico:
    """Qué celdas bloquean cuántas unidades, ordenadas por palanca.

    `alcance` saca de la cuenta lo que **no se desbloquea con comparables de arriendo**: una
    unidad en una comuna excluida del §10, o en una microzona marcada saturada, se descarta
    por regla dura después, así que contarla como "desbloqueable" infla el objetivo y manda
    la recolección al lugar equivocado. Pasó: `--dirigida 3` eligió Providencia por volumen,
    y Providencia está en `excluidas`.

    El rango de m² se calcula con la MISMA función que usa la agregación de arriendo. Si acá
    se calculara de otra forma, el diagnóstico apuntaría a celdas que el emparejamiento nunca
    va a mirar — y sería peor que no tener diagnóstico, porque daría una lista de tareas
    falsas con cara de plan.
    """
    celdas: dict[tuple[str, str, str], int] = {
        (f[0], f[1], f[2]): int(f[3])
        for f in conexion.execute(
            "SELECT microzona_id, tipologia, rango_m2, n FROM agg_arriendo_microzona"
        ).fetchall()
    }

    bloqueadas: dict[tuple[str, str, str], int] = {}
    rankeables = 0
    total = 0
    # El MISMO criterio de frescura que `emparejar`, y por la misma razon por la que este
    # modulo ya comparte `unidad_rankeable` con el: una unidad que el ranking no va a tomar
    # tampoco se "desbloquea" recolectando arriendo. Contarla infla el objetivo y manda el
    # esfuerzo a la comuna equivocada.
    limite = ahora - timedelta(days=FRESCURA_MAX_DIAS) if ahora is not None else None
    for mz, tip, m2, visto in conexion.execute(CONSULTA).fetchall():
        if limite is not None and visto is not None and visto < limite:
            continue
        if alcance is not None and not alcance.unidad_rankeable(mz)[0]:
            continue
        rango = etiqueta_rango(D(str(m2)), rangos)
        if rango is None:
            # Sobre 140 m² pierde el DFL2 y no compite (§12). No es un hueco de datos:
            # ningún comparable de arriendo la va a rescatar.
            continue
        total += 1
        clave = (mz, tip, rango)
        if celdas.get(clave, 0) >= minimo:
            rankeables += 1
        else:
            bloqueadas[clave] = bloqueadas.get(clave, 0) + 1

    huecos = [
        Hueco(
            microzona_id=mz,
            tipologia=tip,
            rango_m2=rango,
            unidades_bloqueadas=n,
            comparables_actuales=celdas.get((mz, tip, rango), 0),
        )
        for (mz, tip, rango), n in bloqueadas.items()
    ]
    # Por palanca, y a igual palanca por volumen: entre dos celdas que rinden lo mismo por
    # aviso conviene la que desbloquea más, porque una corrida trae varios avisos de una.
    huecos.sort(key=lambda h: (-h.palanca, -h.unidades_bloqueadas))
    return Diagnostico(huecos=huecos, unidades_rankeables_hoy=rankeables, unidades_con_precio=total)


__all__ = ["CONSULTA", "Diagnostico", "Hueco", "diagnosticar"]
