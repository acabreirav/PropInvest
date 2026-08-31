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
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from flujocero.agg.arriendo import MIN_COMPARABLES, etiqueta_rango
from flujocero.alcance import Alcance
from flujocero.finance.modelo import Unidad
from flujocero.quality.checks import FRESCURA_MAX_DIAS
from flujocero.quality.plausibilidad import implausible

D = Decimal


@dataclass
class Emparejamiento:
    """El resultado del cruce, con lo que entró y lo que no."""

    unidades: list[Unidad] = field(default_factory=list)
    # De dónde salió el arriendo de cada unidad, para que la ficha lo pueda mostrar.
    procedencia_arriendo: dict[str, tuple[str, int, Decimal]] = field(default_factory=dict)
    # `unidad_key -> (m2 de la unidad - m2 mediana de su celda) / m2 mediana`. Negativo =
    # la unidad es mas chica que el depto tipico contra el que se la comparo, o sea que su
    # arriendo esta SOBREestimado.
    desvio_m2: dict[str, Decimal] = field(default_factory=dict)
    descartes: dict[str, int] = field(default_factory=dict)
    # `(unidad_key, razon)` de las filas que el §7.1 declara imposibles. Se listan y no solo
    # se cuentan: son pocas y cada una merece una mirada — la primera que aparecio era una
    # cesion de promesa encabezando el ranking.
    implausibles: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.unidades) + sum(self.descartes.values())


def celdas_de_arriendo(
    conexion: Any,
) -> dict[tuple[str, str, str], tuple[Decimal, int, Decimal | None]]:
    """`(microzona, tipología, rango)` -> `(mediana_uf, n, m2_mediana)`.

    `m2_mediana` viaja porque **una banda de m² no es homogénea**. Medido el 30-ago-2026
    sobre 1D1B en la banda `0-35`: el 60% de los comparables mide 31-35 m² y la mediana de
    la banda es $350.000, mientras que los de 22-26 m² rentan $300.000. Acreditarle la
    mediana de la banda a un depto de 22 m² le regala **+17% de arriendo**, y el arriendo es
    el numerador del yield.
    """
    return {
        (f[0], f[1], f[2]): (
            Decimal(str(f[3])),
            int(f[4]),
            Decimal(str(f[5])) if f[5] is not None else None,
        )
        for f in conexion.execute(
            "SELECT microzona_id, tipologia, rango_m2, arriendo_uf_mediana, n, m2_mediana "
            "FROM agg_arriendo_microzona WHERE n >= ?",
            (MIN_COMPARABLES,),
        ).fetchall()
    }


def emparejar(
    conexion: Any,
    rangos: list[list[int]],
    alcance: Alcance | None = None,
    ahora: datetime | None = None,
) -> Emparejamiento:
    """Cruza `fact_unidad_venta` vigente contra `agg_arriendo_microzona`.

    Solo entran unidades con precio de evidencia `V`: el §12 excluye del ranking todo precio
    estimado, y un "desde UF X" de proyecto es precisamente eso.

    `alcance` decide dos cosas que ANTES NO SE DECIDIAN AQUI, y una era grave:

    - **`microzona_saturada` se puebla.** `params.yml` declara
      `excluir_microzonas_saturadas: true` y `modelo.py` implementa la regla, pero este
      emparejamiento —el unico camino de las unidades reales— dejaba el campo en su default
      `False`, asi que la exclusion dura del §12 **no se disparaba nunca**. Solo funcionaba
      en `demo`, sobre unidades inventadas.
    - **Las comunas fuera del alcance se descartan y se cuentan.** El §10 define el alcance
      por fases; una comuna que el colector trajo de pasada no entra al ranking porque si.

    Con `alcance=None` se conserva el comportamiento anterior. Se pasa `None` solo donde no
    hay configuracion a mano; el camino normal SIEMPRE lo pasa.

    `ahora` aplica el gate de frescura del §7.3 —*"ninguna fila usada en el ranking puede
    tener `fetched_at` > 21 dias"*—. **Antes no lo aplicaba nadie.** El check de calidad
    contaba las filas viejas y anunciaba que "quedan FUERA del ranking", pero esta consulta
    no miraba `fetched_at`: las 2.696 filas del corpus de mayo entraban igual. La segunda del
    ranking del 31-ago-2026 tenia precio del **4 de mayo**, cuatro meses viejo, en un mercado
    donde eso significa llamar y que ya se vendio.

    Entra por argumento y no del reloj del sistema (§11). Con `ahora=None` no se filtra:
    es lo que necesitan los tests para hablar de otra cosa sin tener que inventar fechas.
    """
    celdas = celdas_de_arriendo(conexion)
    r = Emparejamiento(
        descartes=dict.fromkeys(
            (
                "sin_microzona",
                "fuera_de_alcance",
                "microzona_saturada",
                "sin_tipologia",
                "sin_m2",
                "desactualizada",
                "precio_implausible",
                "fuera_de_rango",
                "sin_comparables",
                "duplicado",
            ),
            0,
        )
    )
    # El mismo departamento publicado por dos corredores tiene dos `MLC-`, asi que la clave
    # natural del §7.3 —(proyecto_id, numero_unidad)— no lo agarra: ninguno de los dos campos
    # existe en un aviso de portal. Se vio en el primer ranking real, con dos avisos identicos
    # en UF 1.200 y 57,1 UF/m2 ocupando dos lugares del top. La firma que si los junta es la
    # que el §7.3 ya usa para arriendo: mismo barrio, misma tipologia, mismos m2, mismo precio.
    # Se colapsa para el RANKING; en la tabla siguen los dos, porque el dato crudo no se toca.
    vistos: set[tuple[Any, ...]] = set()

    filas = conexion.execute(
        "SELECT unidad_key, microzona_id, tipologia, m2_utiles, precio_uf, es_vivienda_nueva, "
        "antiguedad_anios, evidence_level, fetched_at FROM fact_unidad_venta "
        "WHERE valid_to IS NULL AND precio_uf IS NOT NULL AND evidence_level = 'V'"
    ).fetchall()
    limite = ahora - timedelta(days=FRESCURA_MAX_DIAS) if ahora is not None else None

    for key, mz, tip, m2, precio, nueva, antiguedad, _ev, visto in filas:
        if limite is not None and visto is not None and visto < limite:
            # §7.3, y se descarta ANTES que nada mas: una unidad cuyo precio es de hace
            # cuatro meses no es una oportunidad peor, es una oportunidad que no sabemos si
            # existe. Sigue en la base como linea base para medir que bajo de precio.
            r.descartes["desactualizada"] += 1
            continue
        if not mz:
            r.descartes["sin_microzona"] += 1
            continue
        if alcance is not None:
            if alcance.saturada(mz):
                # §12: exclusion dura. Se descarta ACA y no en el motor porque una unidad
                # que no puede rankear tampoco tiene que consumir una celda de arriendo ni
                # aparecer como "desbloqueable" en el diagnostico de huecos.
                r.descartes["microzona_saturada"] += 1
                continue
            if not alcance.en_alcance(mz.split("/")[0]):
                r.descartes["fuera_de_alcance"] += 1
                continue
        if not tip:
            r.descartes["sin_tipologia"] += 1
            continue
        if not m2:
            r.descartes["sin_m2"] += 1
            continue
        razon_implausible = implausible(Decimal(str(precio)), Decimal(str(m2)))
        if razon_implausible is not None:
            # §7.1 aplicado a la tabla, no a una muestra de 5 documentos. Agarra la fila cuyo
            # precio y superficie son cada uno plausibles pero no hablan de la misma cosa: la
            # cesion de promesa que encabezo el ranking del 31-ago con yield 17,58%.
            # Un ranking por yield ordena por precio bajo, asi que esa fila no queda perdida
            # en el medio: flota sola hasta el primer lugar. Ver `quality/plausibilidad.py`.
            r.descartes["precio_implausible"] += 1
            r.implausibles.append((key, razon_implausible))
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

        firma = (mz, tip, Decimal(str(m2)), Decimal(str(precio)))
        if firma in vistos:
            r.descartes["duplicado"] += 1
            continue
        vistos.add(firma)

        arriendo, n, m2_celda = celda
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
                # Se pobla aunque las saturadas ya se hayan descartado arriba: si algun dia
                # el filtro de arriba cambia, el motor sigue teniendo con que aplicar el §12.
                microzona_saturada=alcance.saturada(mz) if alcance else False,
            )
        )
        r.procedencia_arriendo[key] = (f"{mz} · {tip} · {rango} m²", n, arriendo)
        # Cuanto se aleja esta unidad del depto TIPICO de su celda. No corrige el arriendo
        # —eso seria imputar (§3.2)— pero deja medido el sesgo para que la ficha lo muestre
        # y para poder decidir con numeros si las bandas hay que angostarlas.
        if m2_celda:
            r.desvio_m2[key] = (Decimal(str(m2)) - m2_celda) / m2_celda
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
