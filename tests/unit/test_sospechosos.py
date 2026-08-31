"""T-043 · el flag `sospechoso` se escribe de verdad y con la misma cerca del gate."""

from datetime import UTC, datetime
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.agg.arriendo import comparables_desde_duckdb
from flujocero.quality import sospechosos

AHORA = datetime(2026, 8, 31, tzinfo=UTC)


@pytest.fixture()
def con(tmp_path):
    conexion = duckdb.connect(str(tmp_path / "t.duckdb"))
    conexion.execute(db.DDL if hasattr(db, "DDL") else open("schema/schema.sql").read())
    conexion.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('san-miguel', 'San Miguel', 'RM')"
    )
    conexion.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES ('san-miguel/el-llano', 'san-miguel', 'El Llano')"
    )
    yield conexion
    conexion.close()


def _arriendo(con, comp_id, clp, m2=40, mz="san-miguel/el-llano"):
    con.execute(
        "INSERT INTO fact_arriendo_comp (comp_id, microzona_id, tipologia, m2_utiles, "
        "arriendo_clp, arriendo_uf, activo, source_id, source_url, fetched_at, "
        "parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES (?, ?, '2D1B', ?, ?, ?, TRUE, 's', 'u', ?, 'v1', 'p', 'sha')",
        (comp_id, mz, m2, clp, D(str(clp)) / D(39000), AHORA),
    )


def test_marca_el_aviso_absurdo_y_lo_conserva(con):
    """Un arriendo de $3.500.000 entre veinte de ~$350.000 es un cero de mas, no un dato.

    Antes de T-043 ese aviso ENTRABA a la mediana: el filtro `sospechoso = FALSE` de la
    consulta filtraba una columna que nadie escribia.
    """
    for i in range(20):
        _arriendo(con, f"C{i}", 330_000 + i * 3_000)
    _arriendo(con, "ABSURDO", 3_500_000)

    marcados, evaluados = sospechosos.marcar_arriendo(con)
    assert (marcados, evaluados) == (1, 21)
    fila = con.execute(
        "SELECT sospechoso FROM fact_arriendo_comp WHERE comp_id = 'ABSURDO'"
    ).fetchone()
    assert fila[0] is True
    assert con.execute("SELECT count(*) FROM fact_arriendo_comp").fetchone()[0] == 21

    # Y la consulta de la mediana por fin lo excluye de verdad.
    comps, _ = comparables_desde_duckdb(con, ahora=None)
    assert len(comps) == 20


def test_es_idempotente_y_se_desmarca_si_la_cerca_cambia(con):
    """El flag es un derivado: re-correr no acumula, y un dato nuevo puede desmarcar."""
    for i in range(6):
        _arriendo(con, f"C{i}", 330_000)
    _arriendo(con, "ALTO", 700_000)
    assert sospechosos.marcar_arriendo(con)[0] == 1
    assert sospechosos.marcar_arriendo(con)[0] == 1  # idempotente

    # Llegan avisos que legitiman el precio alto: la cerca se mueve y ALTO se desmarca.
    for i in range(6):
        _arriendo(con, f"N{i}", 550_000 + i * 40_000)
    sospechosos.marcar_arriendo(con)
    fila = con.execute(
        "SELECT sospechoso FROM fact_arriendo_comp WHERE comp_id = 'ALTO'"
    ).fetchone()
    assert fila[0] is False


def test_venta_marca_por_uf_m2_contra_su_microzona(con):
    for i in range(10):
        con.execute(
            "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
            "precio_uf, evidence_level, valid_from, source_id, source_url, fetched_at, "
            "parser_version, raw_blob_path, robots_snapshot_sha) "
            "VALUES (?, 'san-miguel/el-llano', '2D1B', 40, ?, 'V', ?, 's', 'u', ?, 'v1', 'p', 'x')",
            (f"U{i}", 2400 + i * 40, AHORA, AHORA),
        )
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, evidence_level, valid_from, source_id, source_url, fetched_at, "
        "parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES ('CARO', 'san-miguel/el-llano', '2D1B', 40, 9000, 'V', ?, 's', 'u', ?, 'v1', 'p', 'x')",
        (AHORA, AHORA),
    )
    marcados, evaluados = sospechosos.marcar_venta(con)
    assert (marcados, evaluados) == (1, 11)
    assert con.execute("SELECT unidad_key FROM fact_unidad_venta WHERE sospechoso").fetchall() == [
        ("CARO",)
    ]
