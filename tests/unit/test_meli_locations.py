"""T-014b · la cascada de barrios MELI: raw primero, cruce por slug, ND sin centro."""

from datetime import UTC, datetime

import duckdb
import httpx

from flujocero import db
from flujocero.sources import meli_locations as ml
from flujocero.sources.meli import Meli

MOMENTO = datetime(2026, 9, 1, tzinfo=UTC)

RESPUESTAS = {
    "/classified_locations/countries/CL": {"states": [{"id": "TUxDUE1FVEE", "name": "RM"}]},
    "/classified_locations/states/TUxDUE1FVEE": {
        "cities": [
            {"id": "SM01", "name": "San Miguel"},
            {"id": "LC01", "name": "Las Condes"},  # fuera del alcance: NO debe pedirse
        ]
    },
    "/classified_locations/cities/SM01": {
        "neighborhoods": [
            {"id": "B-LLANO", "name": "El Llano"},
            {"id": "B-NUEVO", "name": "Barrio Nuevo"},
        ]
    },
    "/classified_locations/neighborhoods/B-LLANO": {
        "geo_information": {"location": {"latitude": -33.4901, "longitude": -70.6511}}
    },
    "/classified_locations/neighborhoods/B-NUEVO": {},  # sin geo_information: ND
}


def _cliente(pedidas: list[str]) -> Meli:
    def responder(req: httpx.Request) -> httpx.Response:
        pedidas.append(req.url.path)
        cuerpo = RESPUESTAS.get(req.url.path)
        if cuerpo is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=cuerpo)

    return Meli("tok", "test-ua", cliente=httpx.Client(transport=httpx.MockTransport(responder)))


def test_camina_solo_el_alcance_y_guarda_cada_respuesta_en_crudo(tmp_path):
    pedidas: list[str] = []
    cosecha = ml.recolectar(
        _cliente(pedidas), frozenset({"san-miguel"}), ahora=MOMENTO, raiz=tmp_path, pausa=0
    )
    assert "/classified_locations/cities/LC01" not in pedidas, (
        "Las Condes esta fuera del §10: su ciudad no se pide"
    )
    assert cosecha.requests == 5 and not cosecha.errores

    crudos = sorted(p.name for p in tmp_path.rglob("*.json.gz"))
    assert "pais_CL.json.gz" in crudos and "barrio_san-miguel_el-llano.json.gz" in crudos
    assert len(crudos) == 5, "cada respuesta a la zona cruda ANTES de leerla (§3.6)"

    por_slug = {b.barrio_slug: b for b in cosecha.barrios}
    assert por_slug["el-llano"].lat == -33.4901
    assert por_slug["barrio-nuevo"].lat is None, "sin geo_information es ND, no un cero"


def test_cargar_cruza_por_slug_e_inserta_los_barrios_nuevos(tmp_path):
    pedidas: list[str] = []
    cosecha = ml.recolectar(
        _cliente(pedidas), frozenset({"san-miguel"}), ahora=MOMENTO, raiz=tmp_path, pausa=0
    )
    con = duckdb.connect()
    db.aplicar_esquema(con)
    con.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('san-miguel', 'San Miguel', 'RM')"
    )
    con.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) "
        "VALUES ('san-miguel/el-llano', 'san-miguel', 'El Llano')"
    )
    contadores = ml.cargar(con, cosecha, MOMENTO)
    assert contadores == {"actualizadas": 1, "insertadas": 1, "sin_centro": 1}

    fila = con.execute(
        "SELECT meli_neighborhood_id, centro_lat FROM dim_microzona "
        "WHERE microzona_id = 'san-miguel/el-llano'"
    ).fetchone()
    assert fila == ("B-LLANO", -33.4901)
    nuevo = con.execute(
        "SELECT centro_lat FROM dim_microzona WHERE microzona_id = 'san-miguel/barrio-nuevo'"
    ).fetchone()
    assert nuevo == (None,), "el barrio sin geo queda con centro NULL, no inventado"


def test_un_403_no_bota_la_cosecha(tmp_path):
    def responder(req: httpx.Request) -> httpx.Response:
        if "neighborhoods" in req.url.path:
            return httpx.Response(403, json={"message": "forbidden"})
        cuerpo = RESPUESTAS.get(req.url.path)
        return httpx.Response(200, json=cuerpo) if cuerpo else httpx.Response(404)

    cliente = Meli("tok", "ua", cliente=httpx.Client(transport=httpx.MockTransport(responder)))
    cosecha = ml.recolectar(
        cliente, frozenset({"san-miguel"}), ahora=MOMENTO, raiz=tmp_path, pausa=0
    )
    assert len(cosecha.errores) == 2 and all("403" in e for e in cosecha.errores)
    assert len(cosecha.barrios) == 2, "los barrios existen aunque su detalle este 403"
    assert all(b.lat is None for b in cosecha.barrios)
