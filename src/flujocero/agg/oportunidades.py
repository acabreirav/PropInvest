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

from flujocero.agg.arriendo import (
    MIN_COMPARABLES,
    etiqueta_rango,
    percentil,
    serie_uf,
    uf_del_dia,
)
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
    # `comuna -> {motivo: n}` con `rankea` entre los motivos. El MISMO recorrido que arma el
    # ranking, contado por comuna: preguntar "¿por que no veo ninguna unidad de X?" con una
    # consulta aparte es como se producen las dos verdades que este proyecto ya pago varias
    # veces. Si el criterio cambia, cambia en un solo lugar y el embudo se entera solo.
    por_comuna: dict[str, dict[str, int]] = field(default_factory=dict)
    # `(unidad_key, razon)` de las filas que el §7.1 declara imposibles. Se listan y no solo
    # se cuentan: son pocas y cada una merece una mirada — la primera que aparecio era una
    # cesion de promesa encabezando el ranking.
    implausibles: list[tuple[str, str]] = field(default_factory=list)
    # T-014b · cuantas unidades rankeables llevan un riesgo de microzona MEDIDO (censo +
    # avisos, via agg_riesgo_microzona) y cuantas quedaron en el 0.5 por defecto. El
    # defecto no es un dato: si domina, el componente ordena poco y hay que decirlo.
    riesgo_medido: int = 0
    riesgo_por_defecto: int = 0
    catalizador_medido: int = 0
    catalizador_por_defecto: int = 0

    @property
    def total(self) -> int:
        return len(self.unidades) + sum(self.descartes.values())


def _anotar(r: Emparejamiento, comuna: str | None, motivo: str) -> None:
    """Suma uno al embudo de esa comuna. `None` cuando la fila ni siquiera dice donde esta."""
    clave = comuna or "(sin microzona)"
    r.por_comuna.setdefault(clave, {})
    r.por_comuna[clave][motivo] = r.por_comuna[clave].get(motivo, 0) + 1


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
    # T-014b · el riesgo por microzona, si el puente ya corrio (`cli puente-censo`).
    # Tabla vacia = dict vacio = todas las unidades al 0.5 por defecto, contado y dicho.
    riesgos: dict[str, Decimal] = {
        mid: Decimal(str(v))
        for mid, v in conexion.execute(
            "SELECT microzona_id, riesgo FROM agg_riesgo_microzona WHERE riesgo IS NOT NULL"
        ).fetchall()
    }
    # T-922 · idem para el catalizador Metro. NULL = sin medir (sin estaciones o sin
    # centro de barrio): la unidad queda en el 0 por defecto del dataclass, contada.
    catalizadores: dict[str, Decimal] = {
        mid: Decimal(str(v))
        for mid, v in conexion.execute(
            "SELECT microzona_id, catalizador FROM agg_riesgo_microzona "
            "WHERE catalizador IS NOT NULL"
        ).fetchall()
    }
    r = Emparejamiento(
        descartes=dict.fromkeys(
            (
                "sin_microzona",
                "fuera_de_alcance",
                "microzona_saturada",
                "sin_tipologia",
                "sin_m2",
                "sin_uf_del_dia",
                "desactualizada",
                "sin_fecha",
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
        "antiguedad_anios, evidence_level, fetched_at, precio_clp, "
        "coalesce(sospechoso, FALSE) FROM fact_unidad_venta "
        "WHERE valid_to IS NULL AND coalesce(precio_uf, precio_clp) IS NOT NULL "
        "AND evidence_level = 'V' "
        # T-925c: un "Precio desde" por modelo es el piso, no el precio de una unidad —
        # no puede competir en el ranking contra precios reales (B1).
        "AND coalesce(precio_es_desde, FALSE) = FALSE"
    ).fetchall()
    # La UF de CADA dia, no la de hoy: un aviso publicado en pesos el 4 de mayo vale lo que
    # valia la UF ese dia. Es la misma conversion que el arriendo ya hacia; lo unico nuevo es
    # que la venta en pesos dejo de tirarse a la basura.
    serie = serie_uf(conexion)
    limite = ahora - timedelta(days=FRESCURA_MAX_DIAS) if ahora is not None else None

    # Primera pasada: filtros DE FILA. Lo que sobrevive es candidata, y sobre las candidatas
    # se calcula la mediana de UF/m² de cada microzona — el denominador de
    # `descuento_vs_microzona`, que hasta hoy era un peso del §12 que nadie calculaba nunca.
    # La mediana sale de esta misma poblacion y no de una consulta aparte a proposito:
    # dos criterios de filtrado distintos son dos verdades, y ya pagamos ese error.
    candidatas: list[tuple[str, str, str, Decimal, Decimal, Any, Any, bool, bool]] = []
    for key, mz, tip, m2, precio, nueva, antiguedad, _ev, visto, clp, sospechoso in filas:
        comuna = mz.split("/")[0] if mz else None
        if limite is not None:
            if visto is None:
                # §3.1 declara `fetched_at` obligatorio; una fila sin fecha no puede probar
                # que cumple los 21 dias del §7.3, y ANTES pasaba el gate para siempre: el
                # `visto is not None` del filtro la saltaba en vez de retenerla.
                r.descartes["sin_fecha"] += 1
                _anotar(r, comuna, "sin_fecha")
                continue
            if visto < limite:
                # §7.3, y se descarta ANTES que nada mas: una unidad cuyo precio es de hace
                # cuatro meses no es una oportunidad peor, es una oportunidad que no sabemos
                # si existe. Sigue en la base como linea base para medir que bajo de precio.
                r.descartes["desactualizada"] += 1
                _anotar(r, comuna, "desactualizada")
                continue
        precio_en_pesos = precio is None
        if precio_en_pesos:
            uf = uf_del_dia(serie, visto) if visto else None
            if uf is None:
                # Sin la UF de su dia la fila no se convierte con la de hoy: seria un precio
                # de mayo expresado en UF de agosto. Se descarta y se cuenta (§3.2).
                r.descartes["sin_uf_del_dia"] += 1
                _anotar(r, comuna, "sin_uf_del_dia")
                continue
            precio = Decimal(str(clp)) / uf
        if not mz:
            r.descartes["sin_microzona"] += 1
            _anotar(r, comuna, "sin_microzona")
            continue
        if alcance is not None:
            if alcance.saturada(mz):
                # §12: exclusion dura. Se descarta ACA y no en el motor porque una unidad
                # que no puede rankear tampoco tiene que consumir una celda de arriendo ni
                # aparecer como "desbloqueable" en el diagnostico de huecos.
                r.descartes["microzona_saturada"] += 1
                _anotar(r, comuna, "microzona_saturada")
                continue
            if not alcance.en_alcance(mz.split("/")[0]):
                r.descartes["fuera_de_alcance"] += 1
                _anotar(r, comuna, "fuera_de_alcance")
                continue
        if not tip:
            r.descartes["sin_tipologia"] += 1
            _anotar(r, comuna, "sin_tipologia")
            continue
        if not m2:
            r.descartes["sin_m2"] += 1
            _anotar(r, comuna, "sin_m2")
            continue
        razon_implausible = implausible(Decimal(str(precio)), Decimal(str(m2)))
        if razon_implausible is not None:
            # §7.1 aplicado a la tabla, no a una muestra de 5 documentos. Agarra la fila cuyo
            # precio y superficie son cada uno plausibles pero no hablan de la misma cosa: la
            # cesion de promesa que encabezo el ranking del 31-ago con yield 17,58%.
            # Un ranking por yield ordena por precio bajo, asi que esa fila no queda perdida
            # en el medio: flota sola hasta el primer lugar. Ver `quality/plausibilidad.py`.
            r.descartes["precio_implausible"] += 1
            _anotar(r, comuna, "precio_implausible")
            r.implausibles.append((key, razon_implausible))
            continue
        candidatas.append(
            (
                key,
                mz,
                tip,
                Decimal(str(m2)),
                Decimal(str(precio)),
                nueva,
                antiguedad,
                precio_en_pesos,
                bool(sospechoso),
            )
        )

    # La mediana de UF/m² de cada microzona, SIN los sospechosos: el §7.3 los marca
    # exactamente para esto — se conservan, compiten, pero no definen el punto de referencia
    # contra el que se mide al resto. Con una sola candidata la mediana es ella misma y su
    # descuento es 0, que no es imputacion: la unidad ES el mercado observable de su zona.
    uf_m2_zona: dict[str, list[Decimal]] = {}
    for _key, mz, _tip, m2, precio, _n, _a, _pep, sospechoso in candidatas:
        if not sospechoso:
            uf_m2_zona.setdefault(mz, []).append(precio / m2)
    mediana_zona = {mz: percentil(v, D("0.5")) for mz, v in uf_m2_zona.items()}

    # Segunda pasada: el cruce con la celda de arriendo y el colapso de duplicados.
    for key, mz, tip, m2, precio, nueva, antiguedad, precio_en_pesos, sospechoso in candidatas:
        comuna = mz.split("/")[0]
        rango = etiqueta_rango(m2, rangos)
        if rango is None:
            # Sobre 140 m² se pierde el DFL2 y la unidad no compite (§12).
            r.descartes["fuera_de_rango"] += 1
            _anotar(r, comuna, "fuera_de_rango")
            continue
        celda = celdas.get((mz, tip, rango))
        if celda is None:
            # SIN caída a comuna, a proposito. Ver el docstring del módulo.
            r.descartes["sin_comparables"] += 1
            _anotar(r, comuna, "sin_comparables")
            continue

        firma = (mz, tip, m2, precio)
        if firma in vistos:
            r.descartes["duplicado"] += 1
            _anotar(r, comuna, "duplicado")
            continue
        vistos.add(firma)
        _anotar(r, comuna, "rankea")

        arriendo, n, m2_celda = celda
        med = mediana_zona.get(mz)
        riesgo = riesgos.get(mz)
        if riesgo is None:
            r.riesgo_por_defecto += 1
        else:
            r.riesgo_medido += 1
        catalizador = catalizadores.get(mz)
        if catalizador is None:
            r.catalizador_por_defecto += 1
        else:
            r.catalizador_medido += 1
        r.unidades.append(
            Unidad(
                unidad_key=key,
                precio_uf=precio,
                m2_utiles=m2,
                tipologia=tip,
                comuna_id=mz.split("/")[0],
                microzona_id=mz,
                arriendo_mensual_uf=arriendo,
                arriendo_n_comparables=n,
                # El portal no declara DFL2 (16 de 5.870 avisos). `None` = por verificar en la
                # escritura: compite, pero sin cobrar el beneficio (T-917).
                acogida_dfl2=None,
                # Un precio convertido de pesos es `D`, no `V`: sale de un calculo
                # deterministico sobre dos valores `V` —el peso publicado y la UF de su dia—.
                # El §12 excluye del ranking los `E`, no los `D`, asi que compite; pero la
                # ficha tiene que poder decir que este numero no se leyo, se calculo.
                evidence_precio="D" if precio_en_pesos else "V",
                es_vivienda_nueva=bool(nueva) if nueva is not None else False,
                antiguedad_anios=int(antiguedad) if antiguedad is not None else None,
                # Se pobla aunque las saturadas ya se hayan descartado arriba: si algun dia
                # el filtro de arriba cambia, el motor sigue teniendo con que aplicar el §12.
                microzona_saturada=alcance.saturada(mz) if alcance else False,
                # Positivo = mas barata por m² que la mediana de su microzona. Es `D` puro:
                # dos precios publicados y una division. Era el 5% del §12 que valia 0 en
                # todas las unidades — un peso del score que nadie calculaba nunca.
                descuento_vs_microzona=(med - precio / m2) / med if med else D(0),
                # T-014b · medido desde el Censo y los avisos cuando el puente corrio;
                # 0.5 (el default historico del dataclass) cuando no hay medicion. El
                # conteo medido/por-defecto viaja en el Emparejamiento y se muestra.
                riesgo_microzona=riesgo if riesgo is not None else D("0.5"),
                catalizador=catalizador if catalizador is not None else D(0),
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


def peso_inerte(inertes: list[str] | tuple[str, ...], p: Any) -> Decimal:
    """Cuanto peso del §12 quedo fuera del score por no variar.

    La deteccion vive en `finance.escenarios.puntuar`, que ademas redistribuye ese peso y
    deja los nombres en `Evaluacion.score_inertes`. Aqui hubo una segunda deteccion,
    hardcodeada a `riesgo_microzona` y `catalizador`: dos mecanismos midiendo lo mismo con
    listas distintas — dos verdades. Se elimino; este helper solo suma pesos.
    """
    pesos = p.crudo("score.pesos")
    return sum((Decimal(str(pesos.get(k, 0))) for k in inertes), D(0))
