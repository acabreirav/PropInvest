"""Qué significa el número que reporta `cargar_avisos`.

El contador es la métrica con la que uno decide si vale la pena volver a recolectar. Si
cuenta confirmaciones como filas nuevas, una corrida que no aportó nada se ve productiva.

Pasó de verdad: la misma recolección de fase 3 corrida dos veces seguidas sobre exactamente
los mismos 3.812 avisos anunció **1.911 filas nuevas o versionadas** la segunda vez. Los
datos estaban bien —`comp_id` es clave primaria— pero `_cargar_arriendo` devolvía 1 aunque
el `ON CONFLICT DO UPDATE` solo hubiera actualizado una fila que ya existía.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.sources.portal_comun import cargar_avisos

HOY = datetime(2026, 8, 29, tzinfo=UTC)
MANANA = datetime(2026, 8, 30, tzinfo=UTC)


class AvisoArriendo:
    """Lo mínimo que el cargador compartido necesita para un comparable de arriendo."""

    def __init__(self, pid: str, clp: int, fecha: datetime = HOY):
        self.portal_id, self.operacion, self.url = pid, "arriendo", f"https://x/{pid}"
        self.fetched_at = fecha
        self.comuna_id, self.comuna_nombre = "san-miguel", "San Miguel"
        self.microzona_id, self.microzona_nombre = "san-miguel/el-llano", "San Miguel - El Llano"
        self.precio_uf = None
        self.arriendo_clp, self.arriendo_uf = clp, D(clp) / D("40871.14")
        self.m2_utiles, self.dormitorios, self.banos = D(58), 2, 2
        self.tipologia, self.es_proyecto = "2D2B", False
        self.gastos_comunes_clp, self.estacionamientos, self.bodegas = 60000, 1, 0
        self.raw_blob_path, self.robots_snapshot_sha = "b", "s"


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    yield c
    c.close()


def test_recolectar_dos_veces_lo_mismo_reporta_cero_la_segunda(con) -> None:
    avisos = [AvisoArriendo("MLC-A1", 450000), AvisoArriendo("MLC-A2", 520000)]
    assert cargar_avisos(con, avisos, "portal_busqueda", "v1") == 2
    assert cargar_avisos(con, avisos, "portal_busqueda", "v1") == 0, (
        "la segunda corrida no agregó nada: el contador no puede decir que sí"
    )
    assert con.execute("SELECT count(*) FROM fact_arriendo_comp").fetchone()[0] == 2


def test_el_precio_nuevo_si_se_guarda_aunque_la_fila_no_cuente(con) -> None:
    """No contar la fila no es no actualizarla. El dato de hoy manda; el contador solo
    deja de mentir sobre cuántas filas son nuevas."""
    cargar_avisos(con, [AvisoArriendo("MLC-A1", 450000)], "portal_busqueda", "v1")
    assert (
        cargar_avisos(con, [AvisoArriendo("MLC-A1", 500000, MANANA)], "portal_busqueda", "v1") == 0
    )
    clp, visto = con.execute(
        "SELECT arriendo_clp, fetched_at FROM fact_arriendo_comp WHERE comp_id = 'MLC-A1'"
    ).fetchone()
    assert clp == 500000
    assert visto.date() == MANANA.date()


def test_un_comparable_nuevo_entre_confirmados_si_cuenta(con) -> None:
    cargar_avisos(con, [AvisoArriendo("MLC-A1", 450000)], "portal_busqueda", "v1")
    n = cargar_avisos(
        con,
        [AvisoArriendo("MLC-A1", 450000), AvisoArriendo("MLC-A3", 610000)],
        "portal_busqueda",
        "v1",
    )
    assert n == 1, "solo MLC-A3 es fila nueva"
