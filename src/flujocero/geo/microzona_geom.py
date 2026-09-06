"""Cargador de geometría de microzonas — T-928.

`dim_microzona.geom` nace de la UNIÓN de las manzanas censales que el puente Voronoi
(T-014b, `geo/puente.py::asignar_manzanas`) ya le asignó en `map_microzona_manzana`, usando
el polígono de cada manzana en `dim_manzana.geom_wkb`. Sin puente (tabla vacía) o sin
polígono censal (las 4 regiones con cartografía, igual que en `puente.py`), la microzona
queda **sin geometría** — nunca se dibuja un polígono aproximado, exactamente la misma regla
que el §2.4 ya aplica al riesgo por microzona.

## Por qué la unión y la simplificación corren en shapely y no en SQL de DuckDB

El §5 pide `duckdb spatial` para esto (`ST_Union`, `ST_Simplify`) y es la primera opción.
Pero la extensión se descarga de `extensions.duckdb.org` la primera vez, y este contenedor
de desarrollo **no tiene esa salida** (medido: `INSTALL spatial` devuelve HTTP 403 vía el
proxy, y `~/.duckdb/extensions/` está vacío). El usuario sí la tendrá en su máquina. Para que
el cargador funcione en los dos sitios con el mismo resultado, la geometría se calcula
siempre con `shapely` (ya es dependencia del proyecto, §5) y solo se decide, mirando el tipo
de columna real de `dim_microzona.geom`, CÓMO se escribe:

- Si `aplicar_esquema` consiguió cargar `spatial` (columna `GEOMETRY`), se escribe con
  `ST_GeomFromWKB(?)` — el mismo WKB que produjo shapely, ahora tipado como geometría nativa
  de DuckDB, para que `ST_AsGeoJSON`/`ST_AsWKB` funcionen en el resto del sistema.
- Si no (columna degradada a `BLOB`, igual que `dim_manzana.geom_wkb` — "legible con y sin
  la extensión", ver `schema.sql`), se escribe el WKB tal cual: un `BLOB` no necesita casteo.

Las dos rutas producen el mismo polígono; la única diferencia es el tipo de columna, no la
geometría. `flujocero/api/servicio.py::Servicio.geometria_microzonas` lee con el mismo
criterio a la inversa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shapely import wkb
from shapely.ops import unary_union

# Tolerancia de `ST_Simplify`/`shapely.simplify`, en grados (el Censo viene en EPSG:4326,
# igual que `dim_manzana.lat/lon`). ~0,00035° ≈ 35-40 m en la latitud de Chile: bastante para
# que un polígono de decenas de manzanas sirva liviano al navegador y siga pareciendo el
# barrio, y muy por debajo de cualquier distancia que separe a dos microzonas vecinas. No es
# un supuesto de mercado (§3.2 no aplica): es una decisión de cuánto detalle sirve un mapa,
# y vive en código, no en `params.yml`.
TOLERANCIA_GRADOS = 0.00035


@dataclass(frozen=True)
class ResultadoGeometria:
    con_geometria: int
    sin_geometria: int
    total_microzonas: int
    # microzonas que ni siquiera tienen una fila en `map_microzona_manzana` (el puente nunca
    # corrió, o corrió y no le tocó ninguna manzana). Es el motivo más común de `sin_geometria`
    # y vale la pena distinguirlo de "tenía manzanas pero ninguna con polígono censal".
    sin_manzanas_asignadas: int


def columna_geom_es_espacial(conexion: Any) -> bool:
    """True si `dim_microzona.geom` quedó como `GEOMETRY` (la extensión `spatial` cargó).

    `aplicar_esquema` ya hizo esa decisión una vez (degrada a `BLOB` si `INSTALL spatial`
    falla); esto solo la lee de vuelta para saber qué SQL de escritura/lectura usar.
    """
    fila = conexion.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'dim_microzona' AND column_name = 'geom'"
    ).fetchone()
    return fila is not None and fila[0].upper() != "BLOB"


def construir_geometria_microzonas(
    conexion: Any,
    ahora: datetime,  # noqa: ARG001 — se recibe por simetría con el resto de `geo/` (§11:
    # nada de fechas del sistema adentro), aunque este cálculo no la necesita: es un
    # derivado geométrico puro, sin componente temporal.
    tolerancia_grados: float = TOLERANCIA_GRADOS,
) -> ResultadoGeometria:
    """Reconstruye `dim_microzona.geom` ENTERO desde `map_microzona_manzana` (es un derivado
    puro, igual que `map_microzona_manzana` mismo — se puede recorrer las veces que haga
    falta sin pedirle nada a nadie).

    Nunca inventa: una microzona sin manzanas asignadas o sin ninguna con polígono censal se
    queda con `geom = NULL` y se cuenta en `sin_geometria`, no se aproxima con el centro de
    barrio ni con nada más.
    """
    espacial = columna_geom_es_espacial(conexion)

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

    conexion.execute("UPDATE dim_microzona SET geom = NULL")  # es un derivado: se recalcula
    con_geometria = 0
    for microzona_id, blobs in filas:
        poligonos = [wkb.loads(bytes(b)) for b in blobs if b is not None]
        if not poligonos:
            continue
        union = unary_union(poligonos)
        simplificado = union.simplify(tolerancia_grados, preserve_topology=True)
        if simplificado.is_empty:
            continue
        wkb_bytes = wkb.dumps(simplificado)
        if espacial:
            conexion.execute(
                "UPDATE dim_microzona SET geom = ST_GeomFromWKB(?) WHERE microzona_id = ?",
                (wkb_bytes, microzona_id),
            )
        else:
            conexion.execute(
                "UPDATE dim_microzona SET geom = ? WHERE microzona_id = ?",
                (wkb_bytes, microzona_id),
            )
        con_geometria += 1

    sin_manzanas_asignadas = total_microzonas - len(con_manzanas)
    return ResultadoGeometria(
        con_geometria=con_geometria,
        sin_geometria=total_microzonas - con_geometria,
        total_microzonas=total_microzonas,
        sin_manzanas_asignadas=max(sin_manzanas_asignadas, 0),
    )


__all__ = ["ResultadoGeometria", "columna_geom_es_espacial", "construir_geometria_microzonas"]
