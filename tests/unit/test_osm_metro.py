"""T-922 · estaciones OSM y el catalizador: elegibilidad por fecha, distancia, ND."""

from datetime import UTC, datetime

import duckdb
import httpx
import pytest

from flujocero import db
from flujocero.config import cargar
from flujocero.geo import puente
from flujocero.sources import osm_metro

AHORA = datetime(2026, 9, 1, tzinfo=UTC)

OVERPASS = {
    "elements": [
        # operativa en San Miguel (L2 El Llano aprox)
        {
            "id": 1,
            "lat": -33.4795,
            "lon": -70.6519,
            "tags": {"railway": "station", "station": "subway", "name": "El Llano"},
        },
        # en construccion con linea CON fecha curada (l7)
        {
            "id": 2,
            "lat": -33.4100,
            "lon": -70.6600,
            "tags": {
                "railway": "construction",
                "station": "subway",
                "name": "Futura L7",
                "ref": "L7",
            },
        },
        # en construccion SIN linea: no cataliza, se cuenta
        {
            "id": 3,
            "lat": -33.42,
            "lon": -70.67,
            "tags": {"railway": "construction", "station": "subway", "name": "Misteriosa"},
        },
        # biotren operativa
        {
            "id": 4,
            "lat": -36.82,
            "lon": -73.05,
            "tags": {"railway": "station", "network": "Biotrén", "name": "Concepcion"},
        },
        # nodo sin nombre: fuera
        {"id": 5, "lat": -33.0, "lon": -70.0, "tags": {"railway": "station", "station": "subway"}},
    ]
}


def test_recolectar_guarda_crudo_y_parsea(tmp_path):
    def responder(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OVERPASS)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    cosecha = osm_metro.recolectar(cliente, ahora=AHORA, raiz=tmp_path)
    assert cosecha.error is None
    assert len(cosecha.estaciones) == 4 and cosecha.sin_nombre == 1
    assert list(tmp_path.rglob("estaciones_cl.json.gz")), "raw primero (§3.6)"
    por_id = {e.estacion_id: e for e in cosecha.estaciones}
    assert por_id["osm-2"].estado == "construccion" and por_id["osm-2"].linea == "l7"
    assert por_id["osm-4"].red == "biotren"


@pytest.fixture()
def con():
    c = duckdb.connect()
    db.aplicar_esquema(c)
    c.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('san-miguel', 'SM', 'RM')"
    )
    # centro a ~200 m de El Llano operativa
    c.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
        "VALUES ('san-miguel/el-llano', 'san-miguel', 'El Llano', -33.4810, -70.6525)"
    )
    # centro lejos de todo (>1200 m)
    c.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
        "VALUES ('san-miguel/lejos', 'san-miguel', 'Lejos', -33.53, -70.70)"
    )
    yield c
    c.close()


def test_catalizador_por_distancia_y_fecha(con, tmp_path):
    cosecha = osm_metro.parsear(OVERPASS)
    osm_metro.cargar(con, cosecha, AHORA)
    res = puente.calcular_catalizador(con, cargar("params"), AHORA)
    assert res["microzonas"] == 2
    # elegibles: El Llano (operativa), Futura L7 (fecha 2028 <= 3 anios), Concepcion
    # (biotren operativa). "Misteriosa" queda fuera y contada.
    assert res["elegibles"] == 3 and res["construccion_sin_fecha"] == 1

    valores = dict(
        con.execute("SELECT microzona_id, catalizador FROM agg_riesgo_microzona").fetchall()
    )
    assert valores["san-miguel/el-llano"] == 1.0, "a ~200 m de una operativa: pleno"
    assert valores["san-miguel/lejos"] == 0.0, "medido y lejos: cero REAL, no ausencia"


def test_sin_estaciones_no_se_escribe_nada(con):
    res = puente.calcular_catalizador(con, cargar("params"), AHORA)
    assert res == {"microzonas": 0, "construccion_sin_fecha": 0, "elegibles": 0}
    assert con.execute("SELECT count(*) FROM agg_riesgo_microzona").fetchone()[0] == 0, (
        "catalizador NULL = sin medir; un 0 escrito diria 'medimos y no hay Metro'"
    )


def test_construccion_con_fecha_vale_menos_que_operativa(con):
    # dos microzonas equidistantes: una junto a operativa, otra junto a la L7 en obra
    con.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
        "VALUES ('san-miguel/junto-l7', 'san-miguel', 'JL7', -33.4102, -70.6602)"
    )
    osm_metro.cargar(con, osm_metro.parsear(OVERPASS), AHORA)
    puente.calcular_catalizador(con, cargar("params"), AHORA)
    v = dict(con.execute("SELECT microzona_id, catalizador FROM agg_riesgo_microzona").fetchall())
    factor = float(cargar("params").d("catalizador.factor_en_construccion"))
    assert abs(v["san-miguel/junto-l7"] - factor) < 1e-9, (
        "pegado a una estacion EN CONSTRUCCION vale el factor E, no 1.0"
    )


def test_si_el_endpoint_principal_rechaza_se_usa_el_espejo(tmp_path):
    """El caso real: overpass-api.de devolvio 406 (cliente sin User-Agent identificable).
    Con identificacion puesta y espejos de respaldo, un rechazo no mata la recoleccion."""
    vistos = []

    def responder(req: httpx.Request) -> httpx.Response:
        vistos.append(req.url.host)
        assert "FlujoCero" in req.headers["user-agent"], "identificacion honesta, siempre"
        if req.url.host == "overpass-api.de":
            return httpx.Response(406, text="Not Acceptable")
        return httpx.Response(200, json=OVERPASS)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    cosecha = osm_metro.recolectar(cliente, ahora=AHORA, raiz=tmp_path)
    assert cosecha.error is None and len(cosecha.estaciones) == 4
    assert vistos == ["overpass-api.de", "overpass.kumi.systems"]
