"""Cargador de geometría de microzonas — T-928.

La geometría nace de la UNIÓN de las manzanas censales que el puente Voronoi
(T-014b, `geo/puente.py::asignar_manzanas`) ya le asignó a cada microzona en
`map_microzona_manzana`, usando el polígono de cada manzana en `dim_manzana.geom_wkb`.
Sin puente (tabla vacía) o sin polígono censal (las 4 regiones con cartografía, igual que
en `puente.py`), la microzona queda **sin geometría** — nunca se dibuja un polígono
aproximado, exactamente la misma regla que el §2.4 ya aplica al riesgo por microzona.

## Por qué una tabla LATERAL (`geo_microzona`) y no la columna `dim_microzona.geom`

La primera versión hacía `UPDATE dim_microzona SET geom = ...` y **reventaba contra la
base real** con el veto de claves foráneas de DuckDB: cualquier UPDATE a una fila de
dimensión referenciada por un hecho falla, aunque no toque la PK (medido en vivo el
06-sep: `Violates foreign key constraint ... "talcahuano/santa-leonor" is still
referenced`). Los tests no lo vieron porque sus fixtures no tenían hechos colgando de la
microzona — ahora sí los tienen. Es el MISMO veto que ya obligó a `proyecto_direccion` y
`geo_proyecto`: el patrón del proyecto es tabla lateral con la misma PK, y el lector hace
el join. `dim_microzona.geom` queda como columna muerta del DDL original.

## Por qué el cálculo corre en shapely y el almacenamiento es WKB en BLOB

El §5 pide `duckdb spatial` para esto, pero la extensión se descarga de
`extensions.duckdb.org` la primera vez y el contenedor de desarrollo no tiene esa salida
(medido: HTTP 403). Para que el cargador dé el mismo resultado en las dos máquinas, la
unión y la simplificación corren siempre en `shapely` (ya es dependencia, §5) y el
polígono se guarda como **WKB en un BLOB**, legible con y sin la extensión — el mismo
formato de `dim_manzana.geom_wkb`. El lector (`api/servicio.py::geometria_microzonas`)
lo traduce a GeoJSON con shapely, nunca con `ST_AsGeoJSON`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shapely import wkb
from shapely.ops import unary_union

# Tolerancia de simplificación, en grados (el Censo viene en EPSG:4326, igual que
# `dim_manzana.lat/lon`). ~0,00035° ≈ 35-40 m en la latitud de Chile: bastante para que
# un polígono de decenas de manzanas sirva liviano al navegador y siga pareciendo el
# barrio, y muy por debajo de cualquier distancia que separe a dos microzonas vecinas.
# No es un supuesto de mercado (§3.2 no aplica): es una decisión de cuánto detalle
# sirve un mapa, y vive en código, no en `params.yml`.
TOLERANCIA_GRADOS = 0.00035


@dataclass(frozen=True)
class ResultadoGeometria:
    con_geometria: int
    sin_geometria: int
    total_microzonas: int
    # microzonas que ni siquiera tienen una fila en `map_microzona_manzana` (el puente
    # nunca corrió, o corrió y no le tocó ninguna manzana). Es el motivo más común de
    # `sin_geometria` y vale la pena distinguirlo de "tenía manzanas pero ninguna con
    # polígono censal".
    sin_manzanas_asignadas: int


def construir_geometria_microzonas(
    conexion: Any,
    ahora: datetime,
    tolerancia_grados: float = TOLERANCIA_GRADOS,
) -> ResultadoGeometria:
    """Reconstruye `geo_microzona` ENTERA desde `map_microzona_manzana` (es un derivado
    puro, igual que `map_microzona_manzana` mismo — se puede recorrer las veces que haga
    falta sin pedirle nada a nadie; `geo_microzona` no tiene hechos colgando, así que el
    DELETE total no choca con el veto de FK que mató a la versión sobre `dim_microzona`).

    Nunca inventa: una microzona sin manzanas asignadas o sin ninguna con polígono censal
    simplemente no tiene fila en `geo_microzona` y se cuenta en `sin_geometria` — no se
    aproxima con el centro de barrio ni con nada más.
    """
    total_microzonas = conexion.execute("SELECT count(*) FROM dim_microzona").fetchone()[0]
    con_manzanas = {
        r[0]
        for r in conexion.execute(
            "SELECT DISTINCT microzona_id FROM map_microzona_manzana"
        ).fetchall()
    }

    filas = conexion.execute(
        "SELECT m.microzona_id, array_agg(d.geom_wkb) "
        "FROM map_microzona_manzana m JOIN dim_manzana d USING (manzent) "
        "WHERE d.geom_wkb IS NOT NULL "
        "GROUP BY m.microzona_id"
    ).fetchall()

    conexion.execute("DELETE FROM geo_microzona")  # derivado puro: se recalcula entero
    con_geometria = 0
    for microzona_id, blobs in filas:
        poligonos = [wkb.loads(bytes(b)) for b in blobs if b is not None]
        if not poligonos:
            continue
        union = unary_union(poligonos)
        simplificado = union.simplify(tolerancia_grados, preserve_topology=True)
        if simplificado.is_empty:
            continue
        conexion.execute(
            "INSERT INTO geo_microzona (microzona_id, geom_wkb, calculado_en) VALUES (?, ?, ?)",
            (microzona_id, wkb.dumps(simplificado), ahora),
        )
        con_geometria += 1

    sin_manzanas_asignadas = total_microzonas - len(con_manzanas)
    return ResultadoGeometria(
        con_geometria=con_geometria,
        sin_geometria=total_microzonas - con_geometria,
        total_microzonas=total_microzonas,
        sin_manzanas_asignadas=max(sin_manzanas_asignadas, 0),
    )


__all__ = ["ResultadoGeometria", "construir_geometria_microzonas"]
