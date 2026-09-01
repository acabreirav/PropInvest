"""T-014b · el puente Voronoi y el riesgo por microzona: asignacion, ND y redistribucion."""

from datetime import UTC, datetime

import duckdb
import pytest

from flujocero import db
from flujocero.config import cargar
from flujocero.geo import puente

AHORA = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture()
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    db.aplicar_esquema(c)
    c.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('san-miguel', 'San Miguel', 'RM')"
    )
    for mid, lat, lon in (
        ("san-miguel/el-llano", -33.480, -70.650),
        ("san-miguel/lo-vial", -33.500, -70.660),
    ):
        c.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
            "VALUES (?, 'san-miguel', ?, ?, ?)",
            (mid, mid, lat, lon),
        )
    yield c
    c.close()


def _manzana(con, manzent, lat, lon, desocup=5, ocup=95, arrend=40, hogares=100):
    con.execute(
        "INSERT INTO dim_manzana (manzent, comuna, lat, lon, n_viv_desocupadas, "
        "n_viv_ocupadas, n_hog_arrienda_contrato, n_hog_arrienda_sin_contrato, n_hogares, "
        "source_id, source_url, fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES (?, 'SAN MIGUEL', ?, ?, ?, ?, ?, 0, ?, 's', 'u', ?, 'v', 'p', 'x')",
        (manzent, lat, lon, desocup, ocup, arrend, hogares, AHORA),
    )


def test_cada_manzana_va_al_barrio_mas_cercano_de_su_comuna(con):
    _manzana(con, "M-CERCA-LLANO", -33.481, -70.651)
    _manzana(con, "M-CERCA-VIAL", -33.499, -70.659)
    res = puente.asignar_manzanas(con, AHORA)
    assert (res.manzanas_asignadas, res.microzonas_con_manzanas) == (2, 2)
    filas = dict(con.execute("SELECT manzent, microzona_id FROM map_microzona_manzana").fetchall())
    assert filas == {
        "M-CERCA-LLANO": "san-miguel/el-llano",
        "M-CERCA-VIAL": "san-miguel/lo-vial",
    }


def test_riesgo_combina_los_tres_insumos_y_mas_desocupacion_es_mas_riesgo(con):
    # el-llano: barrio sano (poca desocupacion, hondo). lo-vial: 30% desocupado y plano.
    _manzana(con, "M1", -33.481, -70.651, desocup=2, ocup=98, arrend=60, hogares=100)
    _manzana(con, "M2", -33.499, -70.659, desocup=30, ocup=70, arrend=10, hogares=100)
    puente.asignar_manzanas(con, AHORA)
    n = puente.calcular_riesgo(con, cargar("params"), AHORA)
    assert n == 2
    riesgos = dict(con.execute("SELECT microzona_id, riesgo FROM agg_riesgo_microzona").fetchall())
    assert riesgos["san-miguel/lo-vial"] > riesgos["san-miguel/el-llano"]
    d = con.execute(
        "SELECT desocupacion, profundidad_arriendo FROM agg_riesgo_microzona "
        "WHERE microzona_id = 'san-miguel/lo-vial'"
    ).fetchone()
    assert d == (0.30, 0.10), "los componentes son D: aritmetica exacta sobre el censo"


def test_los_null_censales_no_se_suman_como_cero(con):
    # Manzana con TODO enmascarado ('*' -> NULL): no aporta a ninguna suma, y la microzona
    # que solo la tiene a ella queda con componentes NULL y riesgo NULL — ND, no un 0.5
    # fabricado. En el emparejamiento esa microzona cae al defecto, contada como tal.
    con.execute(
        "INSERT INTO dim_manzana (manzent, comuna, lat, lon, source_id, source_url, "
        "fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES ('M-VELADA', 'SAN MIGUEL', -33.481, -70.651, 's', 'u', ?, 'v', 'p', 'x')",
        (AHORA,),
    )
    puente.asignar_manzanas(con, AHORA)
    puente.calcular_riesgo(con, cargar("params"), AHORA)
    fila = con.execute(
        "SELECT desocupacion, riesgo FROM agg_riesgo_microzona "
        "WHERE microzona_id = 'san-miguel/el-llano'"
    ).fetchone()
    assert fila == (None, None)


def test_emparejar_usa_el_riesgo_medido_y_cuenta_el_defecto(con):
    from decimal import Decimal as D

    from flujocero.agg import oportunidades as op

    _manzana(con, "M1", -33.481, -70.651, desocup=2, ocup=98)
    _manzana(con, "M2", -33.499, -70.659, desocup=30, ocup=70)
    puente.asignar_manzanas(con, AHORA)
    puente.calcular_riesgo(con, cargar("params"), AHORA)

    # una unidad en lo-vial (riesgo medido) con su celda de arriendo completa
    con.execute(
        "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, n, "
        "arriendo_uf_mediana, avisos_activos, calculado_en) "
        "VALUES ('san-miguel/lo-vial', '2D1B', '35-50', 9, 9.0, 9, ?)",
        (AHORA,),
    )
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, evidence_level, valid_from, source_id, source_url, fetched_at, "
        "parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES ('U1', 'san-miguel/lo-vial', '2D1B', 40, 2500, 'V', ?, 's', 'u', ?, 'v', 'p', 'x')",
        (AHORA, AHORA),
    )
    r = op.emparejar(con, [[25, 35], [35, 50]])
    assert (r.riesgo_medido, r.riesgo_por_defecto) == (1, 0)
    assert r.unidades[0].riesgo_microzona != D("0.5"), "medido, no el default"
