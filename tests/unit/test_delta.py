"""Delta de precios — T-919. El SCD tipo 2 escrito como pregunta."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.quality import delta
from flujocero.sources.portal_comun import cargar_avisos

MAYO = datetime(2026, 5, 4, tzinfo=UTC)
HOY = datetime(2026, 8, 29, tzinfo=UTC)


class Aviso:
    """Lo mínimo que el cargador compartido necesita."""

    def __init__(self, pid: str, precio: str, fecha: datetime, mz: str = "san-miguel/el-llano"):
        self.portal_id, self.operacion, self.url = pid, "venta", f"https://x/{pid}"
        self.fetched_at = fecha
        self.comuna_id, self.comuna_nombre = "san-miguel", "San Miguel"
        self.microzona_id, self.microzona_nombre = mz, "San Miguel - El Llano"
        self.precio_uf = D(precio)
        self.arriendo_clp = self.arriendo_uf = None
        self.m2_utiles, self.dormitorios, self.banos = D(58), 2, 2
        self.tipologia, self.es_proyecto, self.es_vivienda_nueva = "2D2B", False, False
        self.raw_blob_path, self.robots_snapshot_sha = "b", "s"


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    yield c
    c.close()


def test_las_cuatro_categorias_del_cruce(con) -> None:
    cargar_avisos(
        con,
        [Aviso("MLC-1", "4000", MAYO), Aviso("MLC-2", "3500", MAYO), Aviso("MLC-3", "5000", MAYO)],
        "legado",
        "v1",
    )
    cargar_avisos(
        con,
        [Aviso("MLC-1", "3600", HOY), Aviso("MLC-2", "3500", HOY), Aviso("MLC-9", "2800", HOY)],
        "portal_busqueda",
        "v1",
    )
    r = delta.comparar(con, HOY)
    assert len(r.bajaron) == 1 and r.bajaron[0].unidad_key == "MLC-1"
    assert r.sin_cambio == 1
    assert r.desaparecidas == 1, "MLC-3 ya no aparece: un aviso desaparece cuando se vende"
    assert r.nuevas == 1, "solo MLC-9"


def test_la_que_bajo_de_precio_no_se_cuenta_tambien_como_nueva(con) -> None:
    """Su version vigente nace hoy, igual que la de un aviso nuevo. Lo que las separa es que
    la primera tiene una version cerrada detras. Sin ese filtro, el universo se infla con
    unidades que ya estaban."""
    cargar_avisos(con, [Aviso("MLC-1", "4000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3600", HOY)], "portal_busqueda", "v1")
    r = delta.comparar(con, HOY)
    assert r.nuevas == 0
    assert len(r.bajaron) == 1


def test_la_variacion_se_calcula_sobre_el_precio_viejo(con) -> None:
    cargar_avisos(con, [Aviso("MLC-1", "4000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3600", HOY)], "portal_busqueda", "v1")
    assert delta.comparar(con, HOY).bajaron[0].variacion == D("-0.1")


def test_una_que_subio_no_aparece_entre_las_que_bajaron(con) -> None:
    cargar_avisos(con, [Aviso("MLC-1", "3000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3300", HOY)], "portal_busqueda", "v1")
    r = delta.comparar(con, HOY)
    assert not r.bajaron
    assert len(r.subieron) == 1 and r.subieron[0].variacion == D("0.1")


def test_confirmar_una_unidad_actualiza_su_procedencia_pero_no_su_valid_from(con) -> None:
    """Dejar la procedencia apuntando al blob de mayo diria que la evidencia de esta fila es
    un documento viejo, cuando la evidencia es la captura de hoy. `valid_from` conserva
    cuando se vio por primera vez, que es otra pregunta."""
    cargar_avisos(con, [Aviso("MLC-2", "3500", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-2", "3500", HOY)], "portal_busqueda", "v1")
    fila = con.execute(
        "SELECT valid_from, fetched_at, source_id FROM fact_unidad_venta WHERE unidad_key='MLC-2'"
    ).fetchone()
    assert fila[0] == MAYO, "se vio por primera vez en mayo"
    assert fila[1] == HOY, "se confirmo hoy"
    assert fila[2] == "portal_busqueda", "la evidencia vigente es la captura de hoy"
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1


def test_la_microzona_viaja_a_la_unidad_de_venta(con) -> None:
    """Sin microzona en `fact_unidad_venta` no hay yield: el arriendo comparable esta indexado
    por microzona y no habria por donde cruzarlos."""
    cargar_avisos(con, [Aviso("MLC-5", "3000", HOY, mz="nunoa/plaza-egana")], "x", "v1")
    assert (
        con.execute("SELECT microzona_id FROM fact_unidad_venta").fetchone()[0]
        == "nunoa/plaza-egana"
    )
