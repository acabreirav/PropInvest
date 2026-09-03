"""T-930 · el informe semanal: snapshots comparables y consultas de oferta nueva."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero import informe as inf

AHORA = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _fila(key: str, precio: float = 3000.0) -> inf.FilaTop:
    return inf.FilaTop(
        unidad_key=key,
        microzona_id="sm/el-llano",
        tipologia="2D2B",
        m2=56.0,
        precio_uf=precio,
        yield_bruto=0.06,
        tenencia_clp=120000,
        pie_pct=0.2,
        pie_cero="35%",
        score=71.2,
    )


def test_comparar_top_primera_corrida_y_cambios(tmp_path) -> None:
    # primera corrida: no hay con qué comparar, pero el snapshot queda
    c1 = inf.comparar_top(tmp_path, "2026-08-27", [_fila("A"), _fila("B", 2800)])
    assert c1.fecha_anterior is None
    assert (tmp_path / "top-2026-08-27.json").exists()

    # segunda corrida: A bajó de precio, B salió, C entró
    c2 = inf.comparar_top(tmp_path, "2026-09-03", [_fila("A", 2900.0), _fila("C")])
    assert c2.fecha_anterior == "2026-08-27"
    assert c2.entraron == ["C"]
    assert c2.salieron == ["B"]
    assert c2.bajas_precio == [("A", 3000.0, 2900.0)]

    # re-correr el MISMO día no se compara consigo mismo
    c3 = inf.comparar_top(tmp_path, "2026-09-03", [_fila("A", 2900.0), _fila("C")])
    assert c3.fecha_anterior == "2026-08-27"
    assert c3.entraron == ["C"] and c3.bajas_precio == [("A", 3000.0, 2900.0)]


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    c.execute("INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('nunoa', 'Ñuñoa', '')")
    c.execute(
        "INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id) "
        "VALUES ('wpjson-x-p1', 'Edificio Uno', 'nunoa')"
    )
    yield c
    c.close()


def _modelo(con, key, precio, valid_from, valid_to=None):
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, precio_uf, "
        "precio_es_desde, es_vivienda_nueva, evidence_level, valid_from, valid_to, "
        "fetched_at, dormitorios, m2_totales) "
        "VALUES (?, 'wpjson-x-p1', 'm1', ?, TRUE, TRUE, 'V', ?, ?, ?, 2, 55)",
        (key, D(str(precio)), valid_from, valid_to, valid_from),
    )


def test_bajas_oferta_nueva_solo_pares_version_cerrada_mas_barata(con) -> None:
    hace_3d = AHORA - timedelta(days=3)
    # baja real: versión cerrada hace 3 días, sucesora más barata
    _modelo(con, "K1", 3400, AHORA - timedelta(days=20), valid_to=hace_3d)
    _modelo(con, "K1", 3200, hace_3d)
    # subida: NO debe aparecer
    _modelo(con, "K2", 3000, AHORA - timedelta(days=20), valid_to=hace_3d)
    _modelo(con, "K2", 3100, hace_3d)
    bajas = inf.bajas_oferta_nueva(con, AHORA - timedelta(days=7))
    assert len(bajas) == 1
    assert bajas[0]["proyecto"] == "Edificio Uno"
    assert bajas[0]["antes"] == 3400.0 and bajas[0]["ahora"] == 3200.0
    assert bajas[0]["variacion"] == pytest.approx(-200 / 3400)

    # una baja mas vieja que el corte no es "de esta semana"
    assert inf.bajas_oferta_nueva(con, AHORA - timedelta(days=1)) == []


def test_menores_desde_solo_comunas_del_alcance(con) -> None:
    con.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('temuco', 'Temuco', '')"
    )
    con.execute(
        "INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id) "
        "VALUES ('wpjson-x-p2', 'Casa Lejos', 'temuco')"
    )
    _modelo(con, "K1", 2100, AHORA)
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, precio_uf, "
        "precio_es_desde, evidence_level, valid_from, fetched_at) "
        "VALUES ('K3', 'wpjson-x-p2', 'm1', 1500, TRUE, 'V', ?, ?)",
        (AHORA, AHORA),
    )
    filas = inf.menores_desde_en_alcance(con, frozenset({"nunoa"}))
    assert [f["proyecto"] for f in filas] == ["Edificio Uno"]  # temuco queda fuera
    assert filas[0]["precio_uf"] == 2100.0


def test_render_html_es_autocontenido() -> None:
    ficha = _fila("A")
    ficha.arriendo_clp = 294000
    ficha.n_comparables = 12
    ficha.tasa_pct = 0.0429
    ficha.flujo_clp = -46730
    ficha.drivers = ["déficit mensual bajo"]
    html = inf.render_html(
        "2026-09-03",
        "2026-08-27",
        [ficha],
        inf.CambiosTop(entraron=["A"], fecha_anterior="2026-08-27"),
        [],
        [],
        "delta de prueba",
        ["nota"],
    )
    assert "Flujo Cero" in html and "nueva en el top" in html
    # la ficha se explica sola: arriendo con su n, tasa con su caso, flujo con su signo
    assert "mediana de 12 arriendos reales" in html
    assert "sin subsidio (usada)" in html
    assert "−$46.730/mes" in html and "de tu bolsillo" in html
    assert "Por qué está arriba: déficit mensual bajo" in html
    assert "Sin bajas de precio en la oferta nueva" in html
    assert "delta de prueba" in html


# ------------------------------------------- T-931b · nuevas evaluadas al "desde"


def _proyecto_con_geo(c, pid="wpjson-x-geo", comuna="nunoa", lat=-33.456, lon=-70.60):
    c.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?, ?, '') "
        "ON CONFLICT (comuna_id) DO NOTHING",
        (comuna, comuna),
    )
    c.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, centro_lat, centro_lon) "
        "VALUES (?, ?, 'Barrio X', ?, ?) ON CONFLICT (microzona_id) DO NOTHING",
        (f"{comuna}/barrio-x", comuna, lat + 0.002, lon + 0.002),
    )
    c.execute(
        "INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id, lat, lon) "
        "VALUES (?, 'Edificio Geo', ?, ?, ?)",
        (pid, comuna, lat, lon),
    )


def test_microzonas_por_geo_asigna_en_la_misma_comuna_con_tope(con) -> None:
    _proyecto_con_geo(con)
    # otro proyecto SIN geo no aparece; uno a >2.5 km tampoco
    con.execute(
        "INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id, lat, lon) "
        "VALUES ('wpjson-x-lejos', 'Lejos', 'nunoa', -33.60, -70.60)"
    )
    mapa = inf.microzonas_por_geo(con)
    assert mapa == {"wpjson-x-geo": "nunoa/barrio-x"}


def test_nuevas_evaluadas_al_desde_pasa_por_el_motor_con_subsidio(con) -> None:
    from flujocero.config import cargar

    p, inv = cargar("params"), cargar("inversionista")
    _proyecto_con_geo(con)
    con.execute(
        "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, n, "
        "arriendo_uf_mediana, arriendo_uf_m2_mediana, calculado_en) "
        "VALUES ('nunoa/barrio-x', '2D2B', '50-70', 20, 12.5, 0.22, ?)",
        (AHORA,),
    )
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, precio_uf, "
        "m2_totales, dormitorios, banos, precio_es_desde, es_vivienda_nueva, evidence_level, "
        "valid_from, fetched_at) "
        "VALUES ('NG1', 'wpjson-x-geo', 'depto-a', 2900, 56, 2, 2, TRUE, TRUE, 'V', ?, ?)",
        (AHORA, AHORA),
    )
    # y una sin geo, para el contador
    con.execute(
        "INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id) "
        "VALUES ('wpjson-x-singeo', 'Sin Geo', 'nunoa')"
    )
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, precio_uf, "
        "m2_totales, dormitorios, banos, precio_es_desde, evidence_level, valid_from, "
        "fetched_at) VALUES ('NG2', 'wpjson-x-singeo', 'depto-b', 3000, 50, 2, 2, TRUE, "
        "'V', ?, ?)",
        (AHORA, AHORA),
    )
    rangos = p.crudo("ingresos.rangos_m2")
    filas, descartes = inf.nuevas_evaluadas_al_desde(con, p, inv, rangos)
    assert descartes["sin_geo"] == 1
    assert len(filas) == 1
    f = filas[0]
    assert f["proyecto"] == "Edificio Geo"
    assert f["microzona"] == "nunoa/barrio-x"
    # primera venta: el motor le APLICA el subsidio — el corazon de T-931b
    assert f["con_subsidio"] is True
    assert f["arriendo_clp"] > 0 and f["score"] >= 0
