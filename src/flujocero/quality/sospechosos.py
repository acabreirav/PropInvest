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
    grupos: dict[str, list[tuple[str, Decimal]]] = {}
    for clave, mz, m2, arr_uf, clp, visto in filas:
        if arr_uf is None:
            uf = uf_del_dia(serie, visto) if visto else None
            if uf is None:
                continue
            arr_uf = D(str(clp)) / uf
        grupos.setdefault(mz, []).append((clave, D(str(arr_uf)) / D(str(m2))))

    fuera = _marcas(grupos)
    conexion.execute("UPDATE fact_arriendo_comp SET sospechoso = FALSE WHERE activo")
    for clave in sorted(fuera):
        conexion.execute(
            "UPDATE fact_arriendo_comp SET sospechoso = TRUE WHERE comp_id = ?", (clave,)
        )
    return len(fuera), len(filas)
