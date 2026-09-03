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
        # en construccion con linea CON fecha curada (l7) y apertura propia declarada
        {
            "id": 2,
            "lat": -33.4100,
            "lon": -70.6600,
            "tags": {
                "railway": "construction",
                "station": "subway",
                "name": "Futura L7",
                "ref": "L7",
                "start_date": "2028",
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
        # obra L7 con etiquetado de ciclo de vida REAL: sin `station=subway` — el subway
        # vive en `construction:station` (wiki OSM, Tag:railway=construction). Es el caso
        # que la consulta vieja dejaba en cero.
        {
            "id": 6,
            "lat": -33.4104,
            "lon": -70.6604,
            "tags": {
                "railway": "construction",
                "construction": "station",
                "construction:station": "subway",
                "name": "Huelén",
                "ref": "L7",
                "start_date": "2028",
            },
        },
        # obra que NO es Metro ni Biotren (tranvia): la cosecha ancha la trae, el
        # filtro de red la descarta y la cuenta
        {
            "id": 7,
            "lat": -33.36,
            "lon": -70.51,
            "tags": {"railway": "construction", "construction": "station", "name": "Tranvía X"},
        },
        # PROPUESTA de L9 calcada del blob real del 03-sep: sin `ref`, la linea vive en
        # `network`="Línea 9". No es obra — estado 'propuesta' — y como l9 no tiene fecha
        # en config/metro.yml, no cataliza
        {
            "id": 8,
            "lat": -33.61,
            "lon": -70.57,
            "tags": {
                "proposed:railway": "station",
                "proposed:public_transport": "stop_position",
                "network": "Línea 9",
                "operator": "Metro S.A.",
                "subway": "yes",
                "name": "Bajos de Mena",
                "start_date": "2033",
            },
        },
        # obra mapeada como WAY (el caso real de L7): `out center` da la geometria
        {
            "type": "way",
            "id": 9,
            "center": {"lat": -33.415, "lon": -70.665},
            "tags": {
                "railway": "construction",
                "construction": "station",
                "construction:station": "subway",
                "name": "Obra Way L7",
                "ref": "L7",
                "start_date": "2028",
            },
        },
        # el caso REAL de las estaciones de L7 (sonda_l7b): nodo de PARADA miembro de la
        # relation de ruta — railway=stop, la linea en network, y ref = NUMERO DE PARADA
        # (leer ref como linea inventariaria "l6")
        {
            "id": 10,
            "lat": -33.44,
            "lon": -70.70,
            "tags": {
                "railway": "stop",
                "proposed:railway": "stop",
                "public_transport": "stop_position",
                "subway": "yes",
                "network": "Línea 7",
                "ref": "6",
                "start_date": "2028",
                "name": "Radal",
            },
        },
        # la misma parada en el otro sentido: misma clave, se colapsa
        {
            "id": 13,
            "lat": -33.4401,
            "lon": -70.7001,
            "tags": {
                "railway": "stop",
                "proposed:railway": "stop",
                "public_transport": "stop_position",
                "subway": "yes",
                "network": "Línea 7",
                "ref": "6",
                "start_date": "2028",
                "name": "Radal",
            },
        },
        # tren EFE Alameda-Melipilla colado con station=subway y apertura FUTURA: el caso
        # real de las 5 "operativas" que abren 2027-2029 (sonda_l7 parte 1)
        {
            "id": 11,
            "lat": -33.60,
            "lon": -70.87,
            "tags": {
                "railway": "station",
                "station": "subway",
                "network": "Alameda - Melipilla",
                "train": "yes",
                "start_date": "2027",
                "name": "Malloco",
            },
        },
        # miembro de ruta de una linea OPERATIVA sin nada que lo clasifique: se omite
        {
            "id": 12,
            "lat": -33.437,
            "lon": -70.634,
            "tags": {
                "railway": "stop",
                "public_transport": "stop_position",
                "subway": "yes",
                "name": "Baquedano andén L1",
            },
        },
        # la relation de RUTA en si: solo aporta miembros, no es una estacion
        {
            "type": "relation",
            "id": 100,
            "tags": {"route": "subway", "ref": "L7", "name": "Línea 7: Dirección Brasil"},
            "members": [{"type": "node", "ref": 10, "role": "inactive"}],
        },
        # obra L6 SIN fecha del mapper (el caso Lo Errázuriz que enciende Cerrillos):
        # una obra FISICA con fecha curada en metro.yml no depende de un start_date OSM
        {
            "type": "way",
            "id": 14,
            "center": {"lat": -33.50, "lon": -70.75},
            "tags": {
                "railway": "construction",
                "construction": "station",
                "construction:station": "subway",
                "name": "Lo Errázuriz",
                "ref": "L6",
            },
        },
        # estacion EN SERVICIO con un tag de ciclo de vida NO estructural: sigue operativa
        # (hallazgo 3 del verificador — un construction:platform no la degrada)
        {
            "id": 15,
            "lat": -33.30,
            "lon": -70.72,
            "tags": {
                "railway": "station",
                "station": "subway",
                "name": "Los Héroes",
                "ref": "L1",
                "construction:platform": "yes",
            },
        },
        # estacion mapeada como RELATION (sin route): es una estacion, no se bota
        {
            "type": "relation",
            "id": 16,
            "center": {"lat": -33.46, "lon": -70.66},
            "tags": {
                "railway": "construction",
                "construction": "station",
                "construction:station": "subway",
                "name": "Obra Relation L7",
                "ref": "L7",
                "start_date": "2028",
            },
        },
        # miembro de una extension PROPUESTA que dice ser l7 pero sin fecha propia:
        # no puede heredar la fecha curada 2028 de la L7 real
        {
            "id": 17,
            "lat": -33.42,
            "lon": -70.75,
            "tags": {
                "proposed:railway": "station",
                "subway": "yes",
                "network": "Línea 7",
                "name": "Extensión Cerro Navia",
            },
        },
    ]
}


def test_recolectar_guarda_crudo_y_parsea(tmp_path):
    def responder(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OVERPASS)

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    cosecha = osm_metro.recolectar(cliente, ahora=AHORA, raiz=tmp_path)
    assert cosecha.error is None
    assert len(cosecha.estaciones) == 13 and cosecha.sin_nombre == 1
    assert cosecha.fuera_de_red == 1, "el tranvia se descarta y se cuenta, no se cuela"
    assert cosecha.omitidas == 1, "la parada operativa sin clasificar se omite y se cuenta"
    assert cosecha.duplicadas == 1, "la parada del otro sentido colapsa"
    assert list(tmp_path.rglob("estaciones_cl.json.gz")), "raw primero (§3.6)"
    por_id = {e.estacion_id: e for e in cosecha.estaciones}
    assert por_id["osm-2"].estado == "construccion" and por_id["osm-2"].linea == "l7"
    assert por_id["osm-4"].red == "biotren"
    # el etiquetado de ciclo de vida (sin station=subway) entra igual — era el hueco
    assert por_id["osm-6"].estado == "construccion" and por_id["osm-6"].linea == "l7"
    # la propuesta L9 real: estado propio y linea desde `network` — NO es "construccion"
    assert por_id["osm-8"].estado == "propuesta" and por_id["osm-8"].linea == "l9"
    # una obra mapeada como way entra con la geometria del `center`
    assert por_id["osm-way-9"].estado == "construccion" and por_id["osm-way-9"].lat == -33.415
    # la parada de L7: network manda sobre ref (que es el numero de parada, no la linea).
    # recolectar() pasa las lineas curadas de metro.yml, asi que la propuesta fechada de
    # una linea EN OBRA se guarda como construccion (T-922d): el resumen y el catalizador
    # dicen lo mismo
    assert por_id["osm-10"].linea == "l7" and por_id["osm-10"].anio_apertura == 2028
    assert por_id["osm-10"].estado == "construccion"
    # el tren EFE con apertura futura NO es operativa ni metro-santiago
    assert por_id["osm-11"].estado == "propuesta" and por_id["osm-11"].red == "efe"
    assert por_id["osm-11"].linea is None
    # un tag de ciclo de vida NO estructural no degrada una estacion en servicio
    assert por_id["osm-15"].estado == "operativa"
    # una estacion mapeada como relation (sin route) entra; la relation de RUTA no
    assert por_id["osm-relation-16"].estado == "construccion"
    assert "osm-relation-100" not in por_id
    # la obra sin start_date conserva anio None (la fecha creible es la curada)
    assert por_id["osm-way-14"].linea == "l6" and por_id["osm-way-14"].anio_apertura is None


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
    cosecha = osm_metro.parsear(OVERPASS, ahora=AHORA)
    osm_metro.cargar(con, cosecha, AHORA)
    res = puente.calcular_catalizador(con, cargar("params"), AHORA)
    assert res["microzonas"] == 2
    # elegibles: El Llano y Los Héroes (operativas), Concepcion (biotren), Futura L7,
    # Huelén, Obra Way L7, Obra Relation L7 y Radal (l7 con fecha curada 2028) y
    # Lo Errázuriz (obra l6: la fecha creible es la CURADA, no exige start_date OSM).
    # Fuera y contadas: "Misteriosa" (obra sin linea), "Bajos de Mena" (l9 sin fecha
    # curada) y "Extensión Cerro Navia" (propuesta que dice l7 pero sin fecha propia:
    # no hereda el 2028 de la L7 real). "Malloco" es EFE: el §12 pide Metro/Biotren.
    assert res["elegibles"] == 9 and res["construccion_sin_fecha"] == 3
    assert res["excluidas_efe"] == 1

    valores = dict(
        con.execute("SELECT microzona_id, catalizador FROM agg_riesgo_microzona").fetchall()
    )
    assert valores["san-miguel/el-llano"] == 1.0, "a ~200 m de una operativa: pleno"
    assert valores["san-miguel/lejos"] == 0.0, "medido y lejos: cero REAL, no ausencia"


def test_sin_estaciones_no_se_escribe_nada(con):
    res = puente.calcular_catalizador(con, cargar("params"), AHORA)
    assert res == {
        "microzonas": 0,
        "construccion_sin_fecha": 0,
        "elegibles": 0,
        "excluidas_efe": 0,
    }
    assert con.execute("SELECT count(*) FROM agg_riesgo_microzona").fetchone()[0] == 0, (
        "catalizador NULL = sin medir; un 0 escrito diria 'medimos y no hay Metro'"
    )


def test_construccion_con_fecha_vale_menos_que_operativa(con):
    # dos microzonas equidistantes: una junto a operativa, otra junto a la L7 en obra
    con.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
        "VALUES ('san-miguel/junto-l7', 'san-miguel', 'JL7', -33.4102, -70.6602)"
    )
    osm_metro.cargar(con, osm_metro.parsear(OVERPASS, ahora=AHORA), AHORA)
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
    assert cosecha.error is None and len(cosecha.estaciones) == 13
    assert vistos == ["overpass-api.de", "overpass.kumi.systems"]


def _nodo(nid, lat, lon, **tags):
    return {"id": nid, "lat": lat, "lon": lon, "tags": tags}


L7_STOP = {
    "railway": "stop",
    "proposed:railway": "stop",
    "subway": "yes",
    "network": "Línea 7",
    "name": "Radal",
}


def test_dedupe_prefiere_el_gemelo_con_fecha_y_respeta_homonimas_lejanas():
    # el gemelo SIN fecha llega primero: igual debe sobrevivir el que la declara,
    # porque de esa fecha depende la elegibilidad y el orden de Overpass no es estable
    cuerpo = {
        "elements": [
            _nodo(1, -33.44, -70.70, **L7_STOP),
            _nodo(2, -33.4401, -70.7001, **L7_STOP, start_date="2028"),
        ]
    }
    cosecha = osm_metro.parsear(cuerpo, ahora=AHORA)
    assert len(cosecha.estaciones) == 1 and cosecha.duplicadas == 1
    assert cosecha.estaciones[0].anio_apertura == 2028

    # dos estaciones DISTINTAS con el mismo nombre a kilometros: no se colapsan
    cuerpo = {
        "elements": [
            _nodo(3, -33.44, -70.70, **L7_STOP, start_date="2028"),
            _nodo(4, -33.40, -70.60, **L7_STOP, start_date="2028"),
        ]
    }
    cosecha = osm_metro.parsear(cuerpo, ahora=AHORA)
    assert len(cosecha.estaciones) == 2 and cosecha.duplicadas == 0


def test_linea_curada_en_obra_reclasifica_la_propuesta_fechada_a_construccion():
    """T-922d: OSM tagea las paradas de L7 como proposed aunque la linea este en obra.
    Con la linea curada en metro.yml Y fecha propia del nodo → construccion; sin fecha
    propia sigue propuesta (la "Propuesta de Extension L7" no se cuela)."""
    con_fecha = _nodo(1, -33.44, -70.70, **L7_STOP, start_date="2028")
    sin_fecha = _nodo(2, -33.42, -70.75, **{**L7_STOP, "name": "Extensión Cerro Navia"})
    cosecha = osm_metro.parsear(
        {"elements": [con_fecha, sin_fecha]}, ahora=AHORA, lineas_en_obra=frozenset({"l7"})
    )
    por_nombre = {e.nombre: e for e in cosecha.estaciones}
    assert por_nombre["Radal"].estado == "construccion"
    assert por_nombre["Extensión Cerro Navia"].estado == "propuesta"


def test_apertura_con_fecha_completa_del_mismo_anio_no_es_operativa():
    # start_date=2026-12-20 evaluado el 01-sep-2026: aun no abre. Comparar solo el
    # anio la habria vendido como abierta (verificador 03-sep, hallazgo 8)
    cuerpo = {
        "elements": [
            _nodo(
                1,
                -33.4,
                -70.6,
                **{
                    "railway": "station",
                    "station": "subway",
                    "name": "Casi Lista",
                    "start_date": "2026-12-20",
                },
            )
        ]
    }
    cosecha = osm_metro.parsear(cuerpo, ahora=AHORA)
    assert cosecha.estaciones[0].estado == "propuesta"


def test_estaciones_cargadas_pero_cero_elegibles_no_escribe_ceros(con):
    # solo una propuesta l9 sin fecha curada: "no se pudo medir", no "no hay Metro"
    cuerpo = {
        "elements": [
            _nodo(
                1,
                -33.4795,
                -70.6519,
                **{
                    "proposed:railway": "station",
                    "subway": "yes",
                    "network": "Línea 9",
                    "name": "Bajos de Mena",
                    "start_date": "2033",
                },
            )
        ]
    }
    osm_metro.cargar(con, osm_metro.parsear(cuerpo, ahora=AHORA), AHORA)
    res = puente.calcular_catalizador(con, cargar("params"), AHORA)
    assert res["microzonas"] == 0 and res["elegibles"] == 0
    assert con.execute("SELECT count(*) FROM agg_riesgo_microzona").fetchone()[0] == 0, (
        "catalizador 0.0 escrito con cero elegibles afirmaria 'medimos y no hay Metro'"
    )
