"""T-925c · el colector wp-json de inmobiliarias, contra las fixtures de la corrida viva."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import duckdb
import pytest

from flujocero import db
from flujocero.sources import wpjson_inmobiliarias as wp

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "wpjson"
URL_PROYECTO = "https://www.socovesa.cl/nuestros-proyectos/portal-del-libertador-ix/"
AHORA = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------------------------- parseo


def test_uf_de_formatos_chilenos() -> None:
    assert wp.uf_de("3.390 UF") == D("3390")
    assert wp.uf_de("UF 6.390") == D("6390")
    assert wp.uf_de("3.390,5 UF") == D("3390.5")
    assert wp.uf_de("62") == D("62")
    assert wp.uf_de("sin numeros") is None


def test_rest_id_y_slug_de_url() -> None:
    html = (FIXTURES / "proyecto.html").read_text(encoding="utf-8")
    assert wp.rest_id_de(html) == 854913
    assert wp.proyecto_slug_de(URL_PROYECTO) == "portal-del-libertador-ix"
    assert wp.proyecto_slug_de("https://otro.cl/x/") is None


def test_modelos_de_html_extrae_los_propios_e_ignora_promos() -> None:
    html = (FIXTURES / "proyecto.html").read_text(encoding="utf-8")
    modelos = wp.modelos_de_html(html, URL_PROYECTO)
    # dos bloques planta; la card_proyecto de Nueva Toledo (UF 6.390) NO debe aparecer
    assert len(modelos) == 2
    assert all(m["precio_desde_uf"] != D("6390") for m in modelos)

    primero = modelos[0]
    assert primero["modelo_slug"] == "casa-62-2"
    assert primero["precio_desde_uf"] == D("3390")
    assert primero["m2_totales"] == D("62")
    assert primero["dormitorios"] == 3
    assert primero["banos"] == 2
    assert primero["proyecto_slug"] == "portal-del-libertador-ix"

    segundo = modelos[1]
    assert segundo["modelo_slug"] == "casa-73"
    assert segundo["precio_desde_uf"] == D("3890")
    assert segundo["m2_totales"] == D("73")


def test_meta_de_rest_lee_class_list() -> None:
    rest = json.loads((FIXTURES / "proyecto_rest.json").read_text(encoding="utf-8"))
    meta = wp.meta_de_rest(rest)
    assert meta["slug"] == "portal-del-libertador-ix"
    assert meta["nombre"] == "Portal del Libertador IX"
    assert meta["link"] == URL_PROYECTO
    assert meta["comuna_slug"] == "chillan"
    assert meta["estado"] == "venta-en-blanco"
    assert meta["tipo_bien"] == "casa"
    assert meta["disponibilidad"] is None  # el fixture real no trae la clase: ND


def test_modelo_pilares_extrae_precio_y_atributos() -> None:
    html = (FIXTURES / "pilares_modelo.html").read_text(encoding="utf-8")
    m = wp.modelo_de_html_pilares(html, "https://www.pilares.cl/x/depto-a1/")
    assert m["precio_desde_uf"] == D("2990")
    assert m["m2_totales"] == D("30.5")
    assert m["dormitorios"] == 1
    assert m["banos"] == 1


def test_meta_pilares_lee_comuna_estado_y_tags() -> None:
    rest = json.loads((FIXTURES / "pilares_modelo_rest.json").read_text(encoding="utf-8"))
    meta = wp.meta_de_rest(rest)
    assert meta["comuna_slug"] == "la-florida"
    assert meta["estado"] == "entrega-inmediata"
    assert meta["tipo_bien"] == "departamentos"
    assert meta["disponibilidad"] == "disponible-planta"
    assert meta["dormitorios"] == 1
    assert meta["banos"] == 1
    assert meta["parent"] == 126752


def test_selftest_fixture_verde() -> None:
    ok, fallas = wp.selftest_fixture(FIXTURES)
    assert ok, fallas


# -------------------------------------------------------------------------------- carga


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    yield c
    c.close()


def _cosecha(precio: str = "3390", cuando: datetime = AHORA) -> wp.Cosecha:
    comun = {
        "dominio": "socovesa.cl",
        "proyecto_slug": "portal-del-libertador-ix",
        "fetched_at": cuando,
        "raw_blob_path": "data/raw/wpjson_inmobiliarias/2026/09/03/x.json.gz",
        "robots_snapshot_sha": "abc123",
    }
    return wp.Cosecha(
        proyectos=[
            wp.ProyectoWp(
                nombre="Portal del Libertador IX",
                comuna_slug="chillan",
                estado="venta-en-blanco",
                tipo_bien="casa",
                url="https://www.socovesa.cl/wp-json/wp/v2/proyecto/854913",
                **comun,
            )
        ],
        modelos=[
            wp.ModeloWp(
                modelo_slug="casa-62-2",
                precio_desde_uf=D(precio),
                m2_totales=D("62"),
                dormitorios=3,
                banos=2,
                url=URL_PROYECTO,
                **comun,
            )
        ],
    )


def test_cargar_inserta_marcado_como_desde(con) -> None:
    contadores = wp.cargar(con, _cosecha())
    assert contadores["proyectos"] == 1
    assert contadores["modelos_nuevos"] == 1
    fila = con.execute(
        "SELECT proyecto_id, tipologia, precio_uf, precio_es_desde, es_vivienda_nueva, "
        "evidence_level, disponible FROM fact_unidad_venta WHERE valid_to IS NULL"
    ).fetchone()
    assert fila == (
        "wpjson-socovesa.cl-portal-del-libertador-ix",
        "3D2B",
        D("3390.00"),
        True,
        True,
        "V",
        None,
    )
    proyecto = con.execute(
        "SELECT nombre, comuna_id, estado FROM dim_proyecto WHERE proyecto_id LIKE 'wpjson-%'"
    ).fetchone()
    assert proyecto == ("Portal del Libertador IX", "chillan", "venta-en-blanco")


def test_cargar_es_idempotente_y_versiona_cambios_de_precio(con) -> None:
    wp.cargar(con, _cosecha())
    # misma corrida otra vez: refresco, no fila nueva
    contadores = wp.cargar(con, _cosecha())
    assert contadores["refrescos"] == 1
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1

    # el precio baja una semana despues: version cerrada + version nueva (señal de compra)
    despues = AHORA + timedelta(days=7)
    contadores = wp.cargar(con, _cosecha(precio="3290", cuando=despues))
    assert contadores["versiones_nuevas"] == 1
    filas = con.execute(
        "SELECT precio_uf, valid_to FROM fact_unidad_venta ORDER BY valid_from"
    ).fetchall()
    assert filas[0] == (D("3390.00"), despues)
    assert filas[1] == (D("3290.00"), None)

    # una captura MAS VIEJA que la vigente no reescribe el presente
    contadores = wp.cargar(con, _cosecha(precio="9999", cuando=AHORA - timedelta(days=1)))
    assert contadores["fuera_de_orden"] == 1
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 2


def test_cargar_sin_precio_no_inserta_ni_inventa(con) -> None:
    cosecha = _cosecha()
    sin_precio = wp.ModeloWp(
        dominio="socovesa.cl",
        proyecto_slug="portal-del-libertador-ix",
        modelo_slug="casa-84",
        precio_desde_uf=None,
        m2_totales=D("84"),
        dormitorios=4,
        banos=2,
        url=URL_PROYECTO,
        fetched_at=AHORA,
        raw_blob_path="data/raw/wpjson_inmobiliarias/2026/09/03/x.json.gz",
        robots_snapshot_sha="abc123",
    )
    cosecha.modelos.append(sin_precio)
    contadores = wp.cargar(con, cosecha)
    assert contadores["sin_precio"] == 1
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1
