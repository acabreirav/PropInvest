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


def test_el_cluster_promocional_se_marca_aunque_corra_la_cerca(con):
    """Caso medido 06-sep (auditoria del top 1): DIEZ avisos a $150.000 exactos por
    25-30 m² que eran "precio primer mes" (arriendo real $260.000). Tukey no los ve
    porque diez valores identicos corren la cerca hacia ellos; la firma del promo es
    repeticion exacta + nivel bajo 0,75x la mediana del grupo."""
    for i in range(12):
        _arriendo(con, f"C{i}", 330_000 + i * 3_000)
    for i in range(10):
        _arriendo(con, f"PROMO{i}", 150_000, m2=28)

    marcados, _ = sospechosos.marcar_arriendo(con)
    assert marcados == 10
    filas = con.execute(
        "SELECT comp_id FROM fact_arriendo_comp WHERE sospechoso ORDER BY comp_id"
    ).fetchall()
    assert all(f[0].startswith("PROMO") for f in filas)


def test_precio_repetido_a_nivel_de_mercado_no_es_promo(con):
    """Un multifamily publicando 6 unidades identicas al precio de mercado es oferta
    real, no promocion: la repeticion sola no marca nada."""
    for i in range(10):
        _arriendo(con, f"C{i}", 320_000 + i * 5_000)
    for i in range(6):
        _arriendo(con, f"MF{i}", 330_000)

    marcados, _ = sospechosos.marcar_arriendo(con)
    assert marcados == 0


def test_dos_repetidos_baratos_no_bastan_para_cluster(con):
    """Bajo 3 repeticiones no hay firma de promo: puede ser coincidencia. En un grupo
    disperso (cerca de Tukey holgada), dos repetidos baratos quedan DENTRO de la cerca
    y sin cluster: no se marcan por ninguna de las dos reglas."""
    # dispersion real de mercado: $200k a $500k -> la cerca queda lejisimos de $240k
    for i in range(12):
        _arriendo(con, f"C{i}", 200_000 + i * 27_000)
    _arriendo(con, "B1", 240_000)  # bajo 0,75x la mediana, pero solo DOS veces
    _arriendo(con, "B2", 240_000)

    sospechosos.marcar_arriendo(con)
    baratos = con.execute(
        "SELECT count(*) FROM fact_arriendo_comp WHERE sospechoso AND comp_id LIKE 'B%'"
    ).fetchone()[0]
    assert baratos == 0
