"""Persistencia del flag `sospechoso` — cierra T-043.

La consulta que arma la mediana de arriendo filtra `coalesce(sospechoso, FALSE) = FALSE`
desde T-023, y hasta hoy esa columna **no la escribia nadie, en ninguna de las dos tablas**:
`marcar_outliers` mutaba diccionarios en memoria que morian con el proceso del gate. El
filtro se leia bien y no filtraba nada — la enfermedad de siempre.

Este modulo escribe el flag de verdad, con dos decisiones deliberadas:

1. **La misma cerca que el gate** (`checks.limites_outlier`). Dos definiciones de outlier
   serian dos verdades: el gate reportando una cosa y la mediana excluyendo otra.
   Arreglar la cerca ANTES de persistir no fue casualidad: la version interpolada marcaba
   el min y el max de cada zona, y persistida habria echado dos comparables buenos por
   microzona justo donde el umbral n>=8 del §7.3 muerde. Ver D-019.

2. **Se recalcula desde cero en cada corrida** (reset a FALSE y re-marca). El flag es un
   derivado del conjunto vigente, no un historico: si un dato nuevo mueve la cerca, un
   aviso antes sospechoso puede dejar de serlo, y un flag pegado para siempre seria
   exactamente el drift que el §3.6 prohibe. `make rebuild` lo reproduce identico.

La regla del §7.3 se mantiene intacta: **se marca y se conserva, jamas se borra**; queda
fuera de las medianas, no del ranking ni de la base.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from flujocero.quality.checks import limites_outlier

D = Decimal


def _marcas(grupos: dict[str, list[tuple[str, Decimal]]]) -> set[str]:
    """Ids fuera de la cerca de su grupo. Bajo 3 valores no hay cerca que valga."""
    fuera: set[str] = set()
    for pares in grupos.values():
        if len(pares) < 3:
            continue
        lo, hi = limites_outlier([v for _, v in pares])
        fuera |= {clave for clave, v in pares if v < lo or v > hi}
    return fuera


# Cluster promocional: el MISMO precio repetido >=3 veces en la microzona, con un UF/m²
# muy por debajo de la mediana del grupo. Caso medido (06-sep, auditoria del top 1 en
# san-alberto-hurtado): DIEZ avisos a $150.000 exactos por 25-30 m² que eran "precio
# primer mes" — el arriendo real era $260.000, confirmado abriendo el aviso. La cerca de
# Tukey no los ve porque diez valores identicos CORREN la cerca hacia ellos. La firma es
# inequivoca: repeticion exacta + nivel imposible. 0,75 y el minimo de 3 son constantes
# de la regla (como la cerca misma, D-019), no supuestos de mercado.
FACTOR_PROMO = D("0.75")
MIN_CLUSTER_PROMO = 3


def _clusters_promocionales(
    grupos: dict[str, list[tuple[str, Decimal, Decimal | None, Decimal]]],
) -> set[str]:
    """Ids cuyos precios EXACTOS se repiten >=3 veces bajo 0,75x la referencia UF/m².

    La referencia es la mediana UF/m² de los comparables de TAMANO SIMILAR (±25% de m²)
    que no son parte del cluster — no la mezcla de toda la microzona. La primera version
    comparaba contra la mediana global del grupo y el cluster real de san-alberto-hurtado
    se escapo (medido 06-sep en `medir_celda_vs_vecinos`): las unidades grandes de la
    microzona arrastran la mediana UF/m² hacia abajo y el promo de 25 m² queda a un pelo
    del umbral. Contra sus vecinos de tamano, la firma es inequivoca. Si hay menos de 5
    vecinos de tamano, cae a la mediana del grupo entero, que es mejor que nada.
    """
    fuera: set[str] = set()
    for triples in grupos.values():
        if len(triples) < MIN_CLUSTER_PROMO:
            continue
        mediana_grupo = sorted(v for _, v, _, _ in triples)[len(triples) // 2]
        por_precio: dict[Decimal, list[tuple[str, Decimal, Decimal]]] = {}
        for clave, v, clp, m2 in triples:
            if clp is not None:
                por_precio.setdefault(clp, []).append((clave, v, m2))
        for precio, miembros in por_precio.items():
            if len(miembros) < MIN_CLUSTER_PROMO:
                continue
            m2_cluster = sorted(m for _, _, m in miembros)[len(miembros) // 2]
            pares = [
                v
                for _, v, clp, m2 in triples
                if clp != precio and abs(m2 - m2_cluster) <= m2_cluster * D("0.25")
            ]
            referencia = sorted(pares)[len(pares) // 2] if len(pares) >= 5 else mediana_grupo
            ufm2 = sorted(v for _, v, _ in miembros)[len(miembros) // 2]
            if ufm2 < referencia * FACTOR_PROMO:
                fuera |= {clave for clave, _, _ in miembros}
    return fuera


def marcar_venta(conexion: Any) -> tuple[int, int]:
    """Marca `sospechoso` en `fact_unidad_venta` vigente, por UF/m² contra su microzona.

    Devuelve `(marcadas, evaluadas)`. Las filas en pesos se convierten con la UF del dia
    del aviso — la misma conversion del emparejamiento, por la misma razon (§3.3).
    """
    from flujocero.agg.arriendo import serie_uf, uf_del_dia

    serie = serie_uf(conexion)
    filas = conexion.execute(
        "SELECT unidad_key, microzona_id, m2_utiles, precio_uf, precio_clp, fetched_at "
        "FROM fact_unidad_venta WHERE valid_to IS NULL "
        "AND microzona_id IS NOT NULL AND m2_utiles IS NOT NULL AND m2_utiles > 0 "
        "AND coalesce(precio_uf, precio_clp) IS NOT NULL"
    ).fetchall()
    grupos: dict[str, list[tuple[str, Decimal]]] = {}
    for clave, mz, m2, precio_uf, clp, visto in filas:
        if precio_uf is None:
            uf = uf_del_dia(serie, visto) if visto else None
            if uf is None:
                continue  # sin la UF de su dia no hay UF/m² honesto; la fila no se evalua
            precio_uf = D(str(clp)) / uf
        grupos.setdefault(mz, []).append((clave, D(str(precio_uf)) / D(str(m2))))

    fuera = _marcas(grupos)
    conexion.execute("UPDATE fact_unidad_venta SET sospechoso = FALSE WHERE valid_to IS NULL")
    for clave in sorted(fuera):
        conexion.execute(
            "UPDATE fact_unidad_venta SET sospechoso = TRUE "
            "WHERE unidad_key = ? AND valid_to IS NULL",
            (clave,),
        )
    return len(fuera), len(filas)


def marcar_arriendo(conexion: Any) -> tuple[int, int]:
    """Marca `sospechoso` en `fact_arriendo_comp` activo, por arriendo UF/m² contra su microzona.

    Es la mitad que hacia vacio el filtro de la mediana: el arriendo es el numerador del
    yield y un aviso mal parseado ($3.500.000 en vez de $350.000) entraba a la mediana
    como cualquier otro.
    """
    from flujocero.agg.arriendo import serie_uf, uf_del_dia

    serie = serie_uf(conexion)
    filas = conexion.execute(
        "SELECT comp_id, microzona_id, m2_utiles, arriendo_uf, arriendo_clp, fetched_at "
        "FROM fact_arriendo_comp WHERE activo "
        "AND microzona_id IS NOT NULL AND m2_utiles IS NOT NULL AND m2_utiles > 0 "
        "AND coalesce(arriendo_uf, arriendo_clp) IS NOT NULL"
    ).fetchall()
    grupos: dict[str, list[tuple[str, Decimal, Decimal | None, Decimal]]] = {}
    for clave, mz, m2, arr_uf, clp, visto in filas:
        if arr_uf is None:
            uf = uf_del_dia(serie, visto) if visto else None
            if uf is None:
                continue
            arr_uf = D(str(clp)) / uf
        grupos.setdefault(mz, []).append(
            (
                clave,
                D(str(arr_uf)) / D(str(m2)),
                D(str(clp)) if clp is not None else None,
                D(str(m2)),
            )
        )

    # Primero los clusters promocionales (que la cerca de Tukey no puede ver: la corren
    # ellos mismos), y la cerca despues, sobre el grupo ya limpio.
    promos = _clusters_promocionales(grupos)
    limpios = {
        mz: [(clave, v) for clave, v, _, _ in triples if clave not in promos]
        for mz, triples in grupos.items()
    }
    fuera = promos | _marcas(limpios)
    conexion.execute("UPDATE fact_arriendo_comp SET sospechoso = FALSE WHERE activo")
    for clave in sorted(fuera):
        conexion.execute(
            "UPDATE fact_arriendo_comp SET sospechoso = TRUE WHERE comp_id = ?", (clave,)
        )
    return len(fuera), len(filas)
