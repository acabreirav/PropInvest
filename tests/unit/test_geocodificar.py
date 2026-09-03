"""T-931c · geocodificación Nominatim: consulta, validación de comuna, upsert, informe."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import httpx
import pytest

from flujocero import db
from flujocero import informe as inf
from flujocero.geo import geocodificar as geo

AHORA = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)

RESPUESTA_NUNOA = [
    {
        "lat": "-33.4569",
        "lon": "-70.6011",
        "display_name": "Edificio Geo, Avenida Irarrázaval 4400, Ñuñoa, "
        "Provincia de Santiago, Región Metropolitana de Santiago, Chile",
    }
]


def test_construir_consultas_direccion_primero_y_nombre_de_respaldo() -> None:
    assert geo.construir_consultas("Edificio Geo", "Irarrázaval 4400", "Ñuñoa") == [
        "Irarrázaval 4400, Ñuñoa, Chile",
        "Edificio Geo, Ñuñoa, Chile",
    ]
    # sin dirección publicada queda solo el nombre (medido: por nombre solo, 0 de 34)
    assert geo.construir_consultas("Edificio Geo", None, "Ñuñoa") == ["Edificio Geo, Ñuñoa, Chile"]


def test_parsear_exige_que_la_comuna_coincida_sin_acentos() -> None:
    lat, lon, display = geo.parsear(RESPUESTA_NUNOA, "Nunoa")  # sin tilde: igual calza
    assert (lat, lon) == (-33.4569, -70.6011) and "Ñuñoa" in display
    # una coordenada en OTRA comuna es peor que ninguna: ND (§3.2)
    assert geo.parsear(RESPUESTA_NUNOA, "Maipú") is None
    assert geo.parsear([], "Ñuñoa") is None


def test_la_comuna_como_slug_con_guion_tambien_coincide() -> None:
    """Bug vivo del 03-sep: dim_comuna guarda algunos nombres como slug
    ('la-cisterna') y la respuesta de Nominatim dice 'La Cisterna' — el guión
    rechazaba 4 aciertos como 'otra comuna'."""
    respuesta = [
        {
            "lat": "-33.532",
            "lon": "-70.665",
            "display_name": "Esmeralda 6548, La Cisterna, Provincia de Santiago, Chile",
        }
    ]
    assert geo.parsear(respuesta, "la-cisterna") is not None
    assert geo.parsear(respuesta, "estacion-central") is None  # otra comuna sigue fuera


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    c.execute("INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('nunoa', 'Ñuñoa', '')")
    c.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
        "VALUES ('nunoa/barrio-x', 'nunoa', 'Barrio X', -33.4575, -70.6020)"
    )
    # proyecto de oferta nueva SIN geo publicada
    c.execute(
        "INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id, direccion) "
        "VALUES ('wpjson-x-p1', 'Edificio Geo', 'nunoa', 'Irarrázaval 4400')"
    )
    c.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, precio_uf, "
        "precio_es_desde, evidence_level, valid_from, fetched_at) "
        "VALUES ('K1', 'wpjson-x-p1', 'm1', 3000, TRUE, 'V', ?, ?)",
        (AHORA, AHORA),
    )
    yield c
    c.close()


def test_geocodificar_escribe_con_procedencia_y_es_idempotente(con, tmp_path) -> None:
    vistos = []

    def responder(req: httpx.Request) -> httpx.Response:
        vistos.append(dict(req.url.params))
        assert "FlujoCero" in req.headers["user-agent"], "identificacion honesta, siempre"
        return httpx.Response(200, json=RESPUESTA_NUNOA)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    r = geo.geocodificar(cliente, con, ahora=AHORA, pausa_s=0, raiz=tmp_path)
    assert r.consultados == 1 and r.geocodificados == 1
    assert vistos[0]["q"] == "Irarrázaval 4400, Ñuñoa, Chile"
    assert vistos[0]["countrycodes"] == "cl"
    assert list(tmp_path.rglob("*.json.gz")), "raw primero (§3.6)"

    fila = con.execute(
        "SELECT lat, lon, source_id, source_url, fetched_at, parser_version, raw_blob_path, "
        "robots_snapshot_sha FROM geo_proyecto WHERE proyecto_id='wpjson-x-p1'"
    ).fetchone()
    assert fila[0] == pytest.approx(-33.4569)
    assert all(v is not None and v != "" for v in fila[2:]), "las seis columnas (§3.1)"

    # segunda corrida: el proyecto ya esta geocodificado, no se re-consulta
    r2 = geo.geocodificar(cliente, con, ahora=AHORA, pausa_s=0, raiz=tmp_path)
    assert r2.consultados == 0


def test_el_informe_usa_la_geo_geocodificada_via_coalesce(con, tmp_path) -> None:
    cliente = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=RESPUESTA_NUNOA))
    )
    geo.geocodificar(cliente, con, ahora=AHORA, pausa_s=0, raiz=tmp_path)
    mapa = inf.microzonas_por_geo(con)
    assert mapa == {"wpjson-x-p1": "nunoa/barrio-x"}


def test_direccion_de_proyecto_direccion_manda_y_el_nombre_es_respaldo(con, tmp_path) -> None:
    """El caso real: dim_proyecto.direccion vacia (dim congelada por la FK) pero la
    direccion capturada del JSON-LD vive en proyecto_direccion. Y si la direccion no
    resuelve, se intenta el nombre — dos requests, no una."""
    con.execute("UPDATE dim_proyecto SET direccion = NULL WHERE proyecto_id='wpjson-x-p1'")
    con.execute(
        "INSERT INTO proyecto_direccion (proyecto_id, direccion, source_id, source_url, "
        "fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES ('wpjson-x-p1', 'Irarrázaval 4400', 's', 'u', ?, 'v', 'r', 'sha')",
        (AHORA,),
    )
    consultas = []

    def responder(req: httpx.Request) -> httpx.Response:
        consultas.append(req.url.params["q"])
        # la direccion no resuelve (lista vacia); el nombre si
        if "Irarrázaval" in consultas[-1]:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=RESPUESTA_NUNOA)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    r = geo.geocodificar(cliente, con, ahora=AHORA, pausa_s=0, raiz=tmp_path)
    assert consultas == ["Irarrázaval 4400, Ñuñoa, Chile", "Edificio Geo, Ñuñoa, Chile"]
    assert r.geocodificados == 1


def test_comuna_equivocada_no_se_persiste(con, tmp_path) -> None:
    con.execute("UPDATE dim_comuna SET nombre='Maipú' WHERE comuna_id='nunoa'")
    cliente = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=RESPUESTA_NUNOA))
    )
    r = geo.geocodificar(cliente, con, ahora=AHORA, pausa_s=0, raiz=tmp_path)
    assert r.geocodificados == 0 and r.comuna_no_coincide == 1
    assert con.execute("SELECT count(*) FROM geo_proyecto").fetchone()[0] == 0
