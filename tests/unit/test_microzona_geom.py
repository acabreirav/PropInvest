"""T-928 · el cargador de geometría de microzonas.

Corre contra fixtures sintéticas: polígonos WKT chicos, nunca contra el GeoParquet real del
Censo (que solo vive en la máquina del usuario, ver `docs/adr/014-mapa-microzonas.md`).

La fixture cuelga un HECHO de cada microzona a propósito: la primera versión del cargador
hacía `UPDATE dim_microzona SET geom` y reventaba contra la base real con el veto de FK de
DuckDB — los tests no lo vieron porque sus microzonas no tenían hechos. No de nuevo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import duckdb
import pytest
from shapely import wkb, wkt

from flujocero import db
from flujocero.geo import microzona_geom as mg

AHORA = datetime(2026, 9, 6, tzinfo=UTC)


@pytest.fixture()
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    db.aplicar_esquema(c)
    c.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('san-miguel', 'San Miguel', 'RM')"
    )
    for i, mid in enumerate(("san-miguel/el-llano", "san-miguel/lo-vial")):
        c.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES (?, 'san-miguel', ?)",
            (mid, mid),
        )
        # el guardia del veto de FK: un comparable referenciando la microzona, como en
        # la base real (donde el UPDATE de la v1 murio con "still referenced").
        c.execute(
            "INSERT INTO fact_arriendo_comp (comp_id, microzona_id, arriendo_uf, "
            "evidence_level, fetched_at) VALUES (?, ?, ?, 'V', ?)",
            (f"G{i}", mid, D("8"), AHORA),
        )
    yield c
    c.close()


def _manzana(con, manzent, wkt_texto):
    geom = wkb.dumps(wkt.loads(wkt_texto)) if wkt_texto is not None else None
    con.execute(
        "INSERT INTO dim_manzana (manzent, comuna, geom_wkb, source_id, source_url, "
        "fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES (?, 'SAN MIGUEL', ?, 's', 'u', ?, 'v', 'p', 'x')",
        (manzent, geom, AHORA),
    )


def _asignar(con, manzent, microzona_id):
    con.execute(
        "INSERT INTO map_microzona_manzana (manzent, microzona_id, calculado_en) VALUES (?, ?, ?)",
        (manzent, microzona_id, AHORA),
    )


def test_con_las_tablas_vacias_no_inventa_nada_y_termina_limpio(con):
    res = mg.construir_geometria_microzonas(con, AHORA)
    assert (res.con_geometria, res.sin_geometria) == (0, 2)
    assert res.total_microzonas == 2
    assert res.sin_manzanas_asignadas == 2
    assert con.execute("SELECT count(*) FROM geo_microzona").fetchone()[0] == 0


def test_une_las_manzanas_asignadas_de_una_microzona(con):
    # Dos cuadrados adyacentes (comparten el borde x=1): la union es un rectangulo 2x1.
    _manzana(con, "M1", "POLYGON((0 0,0 1,1 1,1 0,0 0))")
    _manzana(con, "M2", "POLYGON((1 0,1 1,2 1,2 0,1 0))")
    _asignar(con, "M1", "san-miguel/el-llano")
    _asignar(con, "M2", "san-miguel/el-llano")

    res = mg.construir_geometria_microzonas(con, AHORA)
    assert (res.con_geometria, res.sin_geometria) == (1, 1)

    raw = con.execute(
        "SELECT geom_wkb FROM geo_microzona WHERE microzona_id = 'san-miguel/el-llano'"
    ).fetchone()[0]
    geom = wkb.loads(bytes(raw))
    assert geom.area == pytest.approx(2.0, rel=1e-6)
    assert geom.bounds == pytest.approx((0.0, 0.0, 2.0, 1.0))


def test_manzana_sin_poligono_censal_no_aporta_geometria(con):
    # `dim_manzana.geom_wkb` NULL: las 4 regiones sin cartografia del Censo (ver puente.py).
    _manzana(con, "M1", None)
    _asignar(con, "M1", "san-miguel/lo-vial")

    res = mg.construir_geometria_microzonas(con, AHORA)
    assert res.con_geometria == 0
    assert res.sin_geometria == 2
    # Pero SI tenia una fila en el puente: no es "sin manzanas asignadas".
    assert res.sin_manzanas_asignadas == 1


def test_es_un_derivado_que_se_puede_recorrer_muchas_veces(con):
    _manzana(con, "M1", "POLYGON((0 0,0 1,1 1,1 0,0 0))")
    _asignar(con, "M1", "san-miguel/el-llano")
    r1 = mg.construir_geometria_microzonas(con, AHORA)
    r2 = mg.construir_geometria_microzonas(con, AHORA)
    assert r1 == r2

    # Si el puente cambia (T-014b se re-corre y ya no le toca esa manzana), la geometria
    # vieja NO se queda pegada: se recalcula entera, igual que map_microzona_manzana.
    con.execute("DELETE FROM map_microzona_manzana")
    r3 = mg.construir_geometria_microzonas(con, AHORA)
    assert r3.con_geometria == 0
    assert con.execute("SELECT count(*) FROM geo_microzona").fetchone()[0] == 0
