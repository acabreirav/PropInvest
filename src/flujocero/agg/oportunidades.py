"""El puente: cruza cada unidad en venta con el arriendo de su microzona — T-029.

Es el eslabón que faltaba. Estaban las dos puntas —2.696 unidades con precio y microzona, y
la mediana de arriendo por celda— y no había nada que las uniera, así que el motor financiero
solo había corrido sobre departamentos inventados.

**La regla de emparejamiento es la clave `(microzona, tipología, rango_m2)` del §2.4**, la
misma con la que se agregó el arriendo. No hay caída a comuna: si una unidad no tiene su celda
con suficientes comparables, **no se rankea**. Prestarle la mediana de la comuna sería
exactamente lo que el §2.4 prohíbe — dentro de una comuna hay 17% de brecha a pocas cuadras, y
esa diferencia es mayor que la que separa a dos comunas distintas.

Las unidades que quedan fuera se cuentan por motivo. Un universo que se achica sin explicación
es indistinguible de un filtro roto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from flujocero.agg.arriendo import MIN_COMPARABLES, etiqueta_rango
from flujocero.finance.modelo import Unidad

D = Decimal


@dataclass
class Emparejamiento:
    """El resultado del cruce, con lo que entró y lo que no."""

    unidades: list[Unidad] = field(default_factory=list)
    # De dónde salió el arriendo de cada unidad, para que la ficha lo pueda mostrar.
    procedencia_arriendo: dict[str, tuple[str, int, Decimal]] = field(default_factory=dict)
    descartes: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.unidades) + sum(self.descartes.values())


def celdas_de_arriendo(conexion: Any) -> dict[tuple[str, str, str], tuple[Decimal, int]]:
    """`(microzona, tipología, rango)` -> `(mediana_uf, n)`, solo celdas que pueden rankear."""
    return {
        (f[0], f[1], f[2]): (Decimal(str(f[3])), int(f[4]))
        for f in conexion.execute(
            "SELECT microzona_id, tipologia, rango_m2, arriendo_uf_mediana, n "
            "FROM agg_arriendo_microzona WHERE n >= ?",
            (MIN_COMPARABLES,),
        ).fetchall()
    }


def emparejar(conexion: Any, rangos: list[list[int]]) -> Emparejamiento:
    """Cruza `fact_unidad_venta` vigente contra `agg_arriendo_microzona`.

    Solo entran unidades con precio de evidencia `V`: el §12 excluye del ranking todo precio
    estimado, y un "desde UF X" de proyecto es precisamente eso.
    """
    celdas = celdas_de_arriendo(conexion)
    r = Emparejamiento(
        descartes=dict.fromkeys(
            ("sin_microzona", "sin_tipologia", "sin_m2", "fuera_de_rango", "sin_comparables"), 0
        )
    )

    filas = conexion.execute(
        "SELECT unidad_key, microzona_id, tipologia, m2_utiles, precio_uf, es_vivienda_nueva, "
        "antiguedad_anios, evidence_level FROM fact_unidad_venta "
        "WHERE valid_to IS NULL AND precio_uf IS NOT NULL AND evidence_level = 'V'"
    ).fetchall()

    for key, mz, tip, m2, precio, nueva, antiguedad, _ev in filas:
        if not mz:
            r.descartes["sin_microzona"] += 1
            continue
        if not tip:
            r.descartes["sin_tipologia"] += 1
            continue
        if not m2:
            r.descartes["sin_m2"] += 1
            continue
        rango = etiqueta_rango(Decimal(str(m2)), rangos)
        if rango is None:
            # Sobre 140 m² se pierde el DFL2 y la unidad no compite (§12).
            r.descartes["fuera_de_rango"] += 1
            continue
        celda = celdas.get((mz, tip, rango))
        if celda is None:
            # SIN caída a comuna, a proposito. Ver el docstring del módulo.
            r.descartes["sin_comparables"] += 1
            continue

        arriendo, n = celda
        r.unidades.append(
            Unidad(
                unidad_key=key,
                precio_uf=Decimal(str(precio)),
                m2_utiles=Decimal(str(m2)),
                tipologia=tip,
                comuna_id=mz.split("/")[0],
                microzona_id=mz,
                arriendo_mensual_uf=arriendo,
                arriendo_n_comparables=n,
                # El portal no declara DFL2 (16 de 5.870 avisos). `None` = por verificar en la
                # escritura: compite, pero sin cobrar el beneficio (T-917).
                acogida_dfl2=None,
                es_vivienda_nueva=bool(nueva) if nueva is not None else False,
                antiguedad_anios=int(antiguedad) if antiguedad is not None else None,
            )
        )
        r.procedencia_arriendo[key] = (f"{mz} · {tip} · {rango} m²", n, arriendo)
    return r


# --------------------------------------------------------- que parte del score esta viva


COMPONENTES_SIN_DATO = ("riesgo_microzona", "catalizador")


def componentes_inertes(unidades: list[Unidad]) -> list[str]:
    """Qué componentes del score no diferencian nada porque todos valen igual.

    Importa decirlo: `riesgo_microzona` y `catalizador` suman **25% del score** y hoy no
    tienen fuente —faltan el Censo 2024 y las distancias a Metro (T-014)—. Al quedar todos
    con el mismo valor, la normalización los vuelve una constante: reparten el mismo puntaje
    a cada unidad y no mueven una sola posición del ranking.

    No es un error, pero un score que se presenta como completo cuando un cuarto de su peso
    está inerte es un score que miente por omisión.
    """
    inertes = []
    for nombre in COMPONENTES_SIN_DATO:
        valores = {getattr(u, nombre) for u in unidades}
        if len(valores) <= 1:
            inertes.append(nombre)
    return inertes


def peso_inerte(inertes: list[str], p: Any) -> Decimal:
    pesos = p.crudo("score.pesos")
    return sum((Decimal(str(pesos.get(k, 0))) for k in inertes), D(0))
