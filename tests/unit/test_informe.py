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
    # el monto del credito a la vista: UF 3.000 con pie 20% → UF 2.400
    assert "Crédito (80%)" in html and "UF 2.400" in html
    # una clave que no es del portal sale como codigo plano, sin link
    assert "<span class='codigo'>A</span>" in html
    # D-022: con procedencia real, la ficha la muestra (alertas incluidas) en vez de la
    # frase generica; sin ella (snapshots viejos), cae a la frase de siempre
    ficha.arriendo_metodo = "vecinos ±15 m² de 77 (típico 76) · ⚠ $/m² sobre el de los más chicos"
    html_m = inf.render_html("2026-09-03", "2026-08-27", [ficha], inf.CambiosTop(), [], [], "", [])
    assert "vecinos ±15 m² de 77" in html_m and "⚠ $/m²" in html_m
    assert "mediana de 12 arriendos reales en su microzona" not in html_m


def test_render_html_codigo_ml_con_link_al_aviso() -> None:
    # pedido del 07-oct-2026: el codigo ML en cada ficha, para traer la ficha completa
    # con evaluar_aviso.py sin ir a buscarlo a la URL del aviso
    html = inf.render_html(
        "2026-10-07",
        "2026-09-30",
        [_fila("MLC-4418530726")],
        inf.CambiosTop(),
        [],
        [],
        "",
        [],
    )
    assert "href='https://www.portalinmobiliario.com/MLC-4418530726'" in html
    assert ">MLC-4418530726</a>" in html
    assert "evaluar_aviso.py" in html


def test_render_html_todo_el_top_como_ficha_y_alerta_de_credito_chico() -> None:
    # 7 filas: TODAS salen como ficha (la tabla del "resto del top" murio el 07-oct-2026,
    # porque escondia justo el detalle que decide la conversacion con el banco)
    filas = [_fila(f"U{i}", 1000.0 + i) for i in range(7)]
    html = inf.render_html(
        "2026-10-07",
        "2026-09-30",
        filas,
        inf.CambiosTop(),
        [],
        [],
        "",
        [],
        credito_minimo_uf=1500.0,
    )
    assert "El top 7" in html
    assert "El resto del top" not in html
    for i in range(1, 8):
        assert f"#{i} · " in html
    # UF 1.000 con pie 20% → credito UF 800, bajo el umbral E de UF 1.500 → alerta
    assert html.count("bajo las UF 1.500 que los bancos priorizan") == 7

    # sin umbral (default 0) no hay alerta; con credito sobre el umbral tampoco
    grande = _fila("G", 3000.0)  # credito UF 2.400 > 1.500
    html2 = inf.render_html(
        "2026-10-07",
        "2026-09-30",
        [grande],
        inf.CambiosTop(),
        [],
        [],
        "",
        [],
        credito_minimo_uf=1500.0,
    )
    assert "bancos priorizan" not in html2
    html3 = inf.render_html(
        "2026-10-07", "2026-09-30", [_fila("C", 1000.0)], inf.CambiosTop(), [], [], "", []
    )
    assert "bancos priorizan" not in html3


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


# ------------------------------------------- T-958 · arriendo por modelo (sección 6)


def _mercado_sintetico(n_mz=8, n_por_celda=9, saltar=()):
    """48 celdas densas con estructura log-log conocida: suficiente para que el gate
    `min_celdas_backtest` (40) sea alcanzable y el error del backtest, ~0."""
    import math

    from flujocero.agg.arriendo import Comparable

    tips = {"1D1B": -0.1, "2D1B": 0.0, "2D2B": 0.05, "3D2B": 0.12, "4D2B": 0.2, "1D2B": -0.05}
    m2_tipico = {"1D1B": 30, "2D1B": 45, "2D2B": 58, "3D2B": 80, "4D2B": 100, "1D2B": 38}
    ruido = (0.03, -0.03, 0.015, -0.015, 0.0)
    comps = []
    for j in range(n_mz):
        mz = f"com{j % 4}/mz{j}"
        for tip, t in tips.items():
            if (mz, tip) in saltar:
                continue
            for i in range(n_por_celda):
                m2 = m2_tipico[tip] + (i - n_por_celda / 2) * 1.5
                y = -0.2 + 0.6 * math.log(m2) + t + 0.03 * j + ruido[i % 5]
                comps.append(Comparable(mz, tip, D(str(m2)), D(str(round(math.exp(y), 6)))))
    return comps


def test_arriendos_por_modelo_publica_solo_si_el_backtest_pasa(con) -> None:
    from flujocero.config import cargar

    p = cargar("params")
    # profundidad censal: com0/mz0 honda, com1/mz1 baja (mediana entre medio)
    for mid, prof in (("com0/mz0", 0.45), ("com1/mz1", 0.10), ("com2/mz2", 0.30)):
        con.execute(
            "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?, ?, '') "
            "ON CONFLICT DO NOTHING",
            (mid.split("/")[0], mid.split("/")[0]),
        )
        con.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES (?, ?, '') "
            "ON CONFLICT DO NOTHING",
            (mid, mid.split("/")[0]),
        )
        con.execute(
            "INSERT INTO agg_riesgo_microzona (microzona_id, profundidad_arriendo) VALUES (?, ?)",
            (mid, prof),
        )
    comps = _mercado_sintetico(saltar={("com0/mz0", "1D1B")})
    detalle = [
        ("MLC-1", "com0/mz0", "1D1B", D(30), D(900), False),  # rala estimable, honda
        ("MLC-2", "com0/mz0", "1D1B", D(30), D(900), False),  # misma firma: colapsa (§7.3)
        ("MLC-3", "com1/mz1", "2D2B", D(58), D(1600), True),  # demanda baja, nueva
        ("MLC-4", "zz/nunca-vista", "2D2B", D(58), D(1500), False),  # ND: mz nunca vista
        # H5: el tope del subsidio es exclusión dura TAMBIÉN aquí (§12)
        ("MLC-5", "com2/mz2", "2D2B", D(58), D(6500), False),
    ]
    filas, resumen = inf.arriendos_por_modelo(con, p, detalle, comps, {})
    assert resumen["pasa"] is True
    assert resumen["celdas_evaluadas"] >= int(p.d("modelo_arriendo.min_celdas_backtest"))
    assert resumen["candidatas"] == 2  # MLC-2 colapsó, MLC-4 quedó ND, MLC-5 sobre el tope
    llaves = {f["unidad_key"] for f in filas}
    assert llaves == {"MLC-1", "MLC-3"}
    por_llave = {f["unidad_key"]: f for f in filas}
    assert por_llave["MLC-1"]["demanda_honda"] is True
    assert por_llave["MLC-1"]["n_grupo"] == 0  # extrapolación pura, dicho
    assert por_llave["MLC-1"]["n_microzona"] >= 8  # jamás un efecto sin soporte (H1)
    assert por_llave["MLC-3"]["demanda_honda"] is False
    assert por_llave["MLC-3"]["nueva"] is True and por_llave["MLC-1"]["nueva"] is False
    # el intervalo envuelve: p25 < central < p75 (factor común, ensanchado por el
    # error fuera de muestra del backtest)
    for f in filas:
        assert f["p25_clp"] < f["arriendo_clp"] < f["p75_clp"]
        assert f["yield_p25"] < f["yield_modelo"]
    assert filas[0]["yield_modelo"] >= filas[-1]["yield_modelo"]

    # la banda de la vista filtrada también muerde (H5): con max 1.000 solo queda MLC-1
    filas_banda, _ = inf.arriendos_por_modelo(con, p, detalle, comps, {}, precio_max_uf=1000.0)
    assert {f["unidad_key"] for f in filas_banda} == {"MLC-1"}

    # el render publica la tabla con la vara del examen a la vista
    html = inf.render_html(
        "2026-10-14",
        "2026-10-07",
        [],
        inf.CambiosTop(),
        [],
        [],
        "",
        [],
        modelo_filas=filas,
        modelo_resumen=resumen,
    )
    assert "Arriendo por MODELO" in html
    assert "backtest leave-one-cell-out" in html and "→ PASA" in html
    assert "honda" in html and "baja" in html
    assert "avisos de la microzona" in html  # el soporte del efecto, a la vista (H1)
    assert ">nueva</span>" in html and ">usada</span>" in html  # D-015 rotulado (H5)
    assert "7 · Delta del mercado usado" in html


def test_arriendos_por_modelo_con_pocas_celdas_NO_publica(con) -> None:
    from flujocero.config import cargar

    p = cargar("params")
    # 18 celdas × 2 variantes = 36 exámenes < min_celdas_backtest (40)
    comps = _mercado_sintetico(n_mz=3)
    filas, resumen = inf.arriendos_por_modelo(
        con, p, [("MLC-9", "com0/mz0", "2D2B", D(58), D(1500), False)], comps, {}
    )
    assert resumen["pasa"] is False
    assert filas == []
    html = inf.render_html(
        "2026-10-14",
        "2026-10-07",
        [],
        inf.CambiosTop(),
        [],
        [],
        "",
        [],
        modelo_filas=filas,
        modelo_resumen=resumen,
    )
    assert "NO pasa su examen hoy" in html
    assert "pocas celdas evaluables" in html
    # sin estimaciones publicadas: ninguna fila de tabla del modelo
    assert "Arriendo modelo (p25" not in html


def test_sin_resumen_no_hay_seccion_del_modelo() -> None:
    html = inf.render_html("2026-10-14", "2026-10-07", [], inf.CambiosTop(), [], [], "", [])
    assert "Arriendo por MODELO" not in html
    assert "6 · Delta del mercado usado" in html


# ------------------------------- 14-oct · la edad del avistamiento, visible en la ficha


def test_la_ficha_dice_hace_cuanto_se_vio_el_aviso() -> None:
    """El #1 del 14-oct resulto probablemente vendido y nada lo decia: el gate de
    frescura tolera 21 dias, pero tolerar no es callar."""
    fresca = _fila("F")
    fresca.visto_hace_dias = 0
    reciente = _fila("R")
    reciente.visto_hace_dias = 4
    vieja = _fila("V")
    vieja.visto_hace_dias = 12
    html = inf.render_html(
        "2026-10-14", "2026-10-07", [fresca, reciente, vieja], inf.CambiosTop(), [], [], "", []
    )
    assert "hoy o ayer" in html
    assert "hace 4 días" in html
    assert "hace 12 días" in html and "puede estar vendido" in html
    # el aviso solo acompana a la VIEJA, no a las frescas
    assert html.count("puede estar vendido") == 1

    # snapshots viejos sin el dato (-1): la celda no aparece — ND no se inventa
    html2 = inf.render_html(
        "2026-10-14", "2026-10-07", [_fila("S")], inf.CambiosTop(), [], [], "", []
    )
    assert "Visto en el portal" not in html2


# ----------------------------------------------- T-960 · re-confirmacion del top


def test_comunas_del_top_dedup_orden_y_region() -> None:
    from flujocero.alcance import desde_config
    from flujocero.config import cargar

    alcance = desde_config(cargar("zonas"))
    mzs = [
        "nunoa/plaza-nunoa",
        "independencia/hospitales",
        "nunoa/parque-san-eugenio",  # comuna repetida: no se duplica
        "concepcion/centro-de-concepcion",  # fuera de la RM: viaja con su region_slug
        "",  # microzona vacia: se ignora
        "rancagua/la-compania",
    ]
    comunas = inf.comunas_del_top(mzs, alcance)
    assert [c for c, _ in comunas] == ["nunoa", "independencia", "concepcion", "rancagua"]
    por_nombre = dict(comunas)
    assert por_nombre["nunoa"] == "metropolitana"
    assert por_nombre["concepcion"] != "metropolitana"  # el slug real viene de zonas.yml
    # el tope acota el costo: cada comuna son minutos de corrida
    assert inf.comunas_del_top(mzs, alcance, max_comunas=2) == comunas[:2]


def test_la_ficha_dice_el_veredicto_de_la_reconfirmacion() -> None:
    viva = _fila("V")
    viva.reconfirmada = True
    caida = _fila("C")
    caida.reconfirmada = False
    caida.visto_hace_dias = 15
    sin_cubrir = _fila("S")
    sin_cubrir.visto_hace_dias = 3
    html = inf.render_html(
        "2026-10-14", "2026-10-07", [viva, caida, sin_cubrir], inf.CambiosTop(), [], [], "", []
    )
    assert "re-confirmada hoy" in html
    assert "no reapareció en la re-confirmación de hoy" in html
    assert "probablemente vendida" in html
    # la no cubierta cae a la escalera de edad de siempre
    assert "hace 3 días" in html
