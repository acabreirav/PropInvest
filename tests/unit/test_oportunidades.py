"""El puente venta × arriendo — T-029. El eslabon que faltaba."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.agg import oportunidades as op
from flujocero.config import cargar
from flujocero.finance.escenarios import escenario_base, evaluar_universo

RANGOS = [[0, 35], [35, 50], [50, 70], [70, 100], [100, 140]]
AHORA = datetime(2026, 8, 29, tzinfo=UTC)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    c.execute(
        "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('sm', 'San Miguel', 'RM')"
    )
    c.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) "
        "VALUES ('sm/el-llano', 'sm', 'El Llano'), ('sm/lo-vial', 'sm', 'Lo Vial')"
    )
    yield c
    c.close()


def celda(con, mz="sm/el-llano", tip="2D2B", rango="50-70", mediana="12.35", n=94):
    con.execute(
        "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, n, "
        "arriendo_uf_mediana, arriendo_uf_m2_mediana, calculado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (mz, tip, rango, n, D(mediana), D(mediana) / D(56), AHORA),
    )


def unidad(con, key="U1", mz="sm/el-llano", tip="2D2B", m2=56, precio="3000", ev="V", nueva=False):
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, es_vivienda_nueva, evidence_level, valid_from, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, mz, tip, m2, D(precio), nueva, ev, AHORA, AHORA),
    )


# ---------------------------------------------------------------------- el emparejamiento


def test_empareja_por_microzona_tipologia_y_rango(con) -> None:
    celda(con)
    unidad(con)
    r = op.emparejar(con, RANGOS)
    assert len(r.unidades) == 1
    u = r.unidades[0]
    assert u.arriendo_mensual_uf == D("12.35")
    assert u.arriendo_n_comparables == 94
    assert u.comuna_id == "sm"


def test_NO_cae_a_la_comuna_cuando_falta_la_celda(con) -> None:
    """§2.4: dentro de una comuna hay 17% de brecha a pocas cuadras, mas que entre comunas.
    Prestarle a El Llano la mediana de Lo Vial produciria un yield que no existe en ninguno
    de los dos barrios. Sin celda propia, la unidad no se rankea."""
    celda(con, mz="sm/lo-vial")
    unidad(con, mz="sm/el-llano")
    r = op.emparejar(con, RANGOS)
    assert r.unidades == []
    assert r.descartes["sin_comparables"] == 1


def test_una_celda_con_menos_de_8_comparables_no_sirve(con) -> None:
    celda(con, n=7)
    unidad(con)
    assert op.emparejar(con, RANGOS).descartes["sin_comparables"] == 1


def test_la_tipologia_tiene_que_coincidir(con) -> None:
    """Un 2D2B no se compara contra un 1D1B aunque compartan barrio y metraje."""
    celda(con, tip="1D1B")
    unidad(con, tip="2D2B")
    assert op.emparejar(con, RANGOS).unidades == []


def test_un_precio_estimado_no_entra(con) -> None:
    """§12: el 'desde UF X' de un proyecto no es el precio de esta unidad."""
    celda(con)
    unidad(con, ev="E")
    assert op.emparejar(con, RANGOS).total == 0, "ni siquiera se lee"


def test_un_precio_desde_no_entra_aunque_sea_V(con) -> None:
    """T-925c: el "Precio desde" de wp-json es evidencia V del PISO del modelo, no el
    precio de una unidad. Con evidence V igual queda fuera del ranking."""
    celda(con)
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, es_vivienda_nueva, evidence_level, precio_es_desde, valid_from, "
        "fetched_at) VALUES ('W1', 'sm/el-llano', '2D2B', 56, ?, TRUE, 'V', TRUE, ?, ?)",
        (D("3000"), AHORA, AHORA),
    )
    assert op.emparejar(con, RANGOS).total == 0, "ni siquiera se lee"


def test_sobre_140_m2_queda_fuera_por_el_DFL2(con) -> None:
    celda(con, rango="100-140")
    unidad(con, m2=150)
    assert op.emparejar(con, RANGOS).descartes["fuera_de_rango"] == 1


def test_el_DFL2_llega_como_por_verificar_no_como_negativo(con) -> None:
    """El portal declara DFL2 en 16 de 5.870 avisos. Marcarlo `False` vaciaria el ranking;
    marcarlo `True` regalaria un beneficio sin probar (T-917)."""
    celda(con)
    unidad(con)
    assert op.emparejar(con, RANGOS).unidades[0].acogida_dfl2 is None


def test_guarda_de_donde_salio_cada_arriendo(con) -> None:
    """La ficha tiene que poder mostrar sobre cuantos avisos se calculo su referencia."""
    celda(con)
    unidad(con)
    celda_txt, n, arr = op.emparejar(con, RANGOS).procedencia_arriendo["U1"]
    assert "sm/el-llano" in celda_txt and "2D2B" in celda_txt and "50-70" in celda_txt
    assert (n, arr) == (94, D("12.35"))


# --------------------------------------------------------------- el ranking de verdad


def test_el_motor_corre_sobre_datos_reales_y_rankea(con) -> None:
    """Lo que T-029 vino a resolver: hasta ahora el motor solo habia corrido sobre unidades
    inventadas. Dos unidades identicas salvo el precio deben ordenarse por el barato."""
    celda(con)
    unidad(con, key="BARATA", precio="2400")
    unidad(con, key="CARA", precio="3400")

    p, inv = cargar("params"), cargar("inversionista")
    r = op.emparejar(con, RANGOS)
    evals = evaluar_universo(r.unidades, escenario_base(p, inv), p, inv)
    vivos = [(u, e) for u, e in zip(r.unidades, evals, strict=True) if not e.excluido]
    assert vivos, "con arriendo real y precio bajo el tope, algo tiene que sobrevivir"

    por_key = {u.unidad_key: e for u, e in vivos}
    if len(por_key) == 2:
        assert por_key["BARATA"].rentabilidad_bruta > por_key["CARA"].rentabilidad_bruta
        assert por_key["BARATA"].score > por_key["CARA"].score


def test_el_yield_sale_del_arriendo_de_su_celda(con) -> None:
    """`yield = arriendo x 12 / precio`, con el arriendo de SU microzona."""
    celda(con, mediana="12.00")
    unidad(con, precio="3600")
    p, inv = cargar("params"), cargar("inversionista")
    r = op.emparejar(con, RANGOS)
    ev = evaluar_universo(r.unidades, escenario_base(p, inv), p, inv)[0]
    assert abs(ev.rentabilidad_bruta - D(12) * D(12) / D(3600)) < D("0.0001")


# ------------------------------------------------------- que parte del score esta viva


def test_los_componentes_sin_fuente_quedan_fuera_del_score_y_se_dicen(con) -> None:
    """`riesgo_microzona` y `catalizador` suman 25% del score y hoy no tienen fuente. La
    deteccion vive en `puntuar()` —sobre el conjunto vivo real, no una lista hardcodeada—
    y su peso se redistribuye. Aca se verifica el cable completo: emparejar -> evaluar ->
    score_inertes, y que `descuento_vs_microzona` ya NO este inerte, porque este mismo
    emparejamiento lo calcula ahora (era el 5% del §12 que valia 0 en todas)."""
    celda(con)
    unidad(con, key="A")
    unidad(con, key="B", precio="2800")
    r = op.emparejar(con, RANGOS)

    from flujocero.finance.escenarios import escenario_base, evaluar_universo

    p, inv = cargar("params"), cargar("inversionista")
    evals = evaluar_universo(r.unidades, escenario_base(p, inv), p, inv, pie_exacto=True)
    inertes = next(ev.score_inertes for ev in evals if not ev.excluido)
    assert "riesgo_microzona" in inertes
    assert "catalizador" in inertes
    assert "descuento_vs_microzona" not in inertes, (
        "dos precios distintos en la misma microzona tienen descuentos distintos"
    )
    assert op.peso_inerte(("riesgo_microzona", "catalizador"), p) == D("0.25")


def test_emparejar_calcula_el_descuento_contra_la_mediana_de_su_microzona(con) -> None:
    """El descuento es `D` puro: dos precios publicados y una division. La unidad mas barata
    que la mediana de su zona tiene descuento positivo; la mas cara, negativo."""
    celda(con)
    unidad(con, key="BARATA", precio="2600")
    unidad(con, key="MEDIA", precio="3000")
    unidad(con, key="CARA", precio="3400")
    r = op.emparejar(con, RANGOS)
    d = {u.unidad_key: u.descuento_vs_microzona for u in r.unidades}
    assert d["MEDIA"] == 0, "la mediana de la zona es ella misma"
    assert d["BARATA"] > 0 > d["CARA"]
    # (mediana - uf_m2) / mediana con mediana 3000/56 y barata 2600/56
    assert abs(d["BARATA"] - (D(3000) - D(2600)) / D(3000)) < D("1e-12")


def test_el_mismo_depto_publicado_dos_veces_ocupa_un_solo_lugar(con) -> None:
    """Visto en el primer ranking real: dos avisos identicos en UF 1.200 y 57,1 UF/m2 ocupando
    dos lugares del top. La clave natural del §7.3 —(proyecto_id, numero_unidad)— no los agarra
    porque ninguno de los dos campos existe en un aviso de portal: cada corredor publica con su
    propio MLC. La firma que si los junta es mismo barrio, tipologia, m2 y precio."""
    celda(con)
    unidad(con, key="CORREDOR-A", m2=56, precio="1200")
    unidad(con, key="CORREDOR-B", m2=56, precio="1200")
    r = op.emparejar(con, RANGOS)
    assert len(r.unidades) == 1
    assert r.descartes["duplicado"] == 1


def test_dos_deptos_distintos_del_mismo_barrio_no_se_colapsan(con) -> None:
    """El contrapeso: dedupe demasiado agresivo esconderia oferta real."""
    celda(con)
    unidad(con, key="A", m2=56, precio="1200")
    unidad(con, key="B", m2=56, precio="1250")
    unidad(con, key="C", m2=58, precio="1200")
    assert len(op.emparejar(con, RANGOS).unidades) == 3


# ------------------------------------------------- §7.1 sobre la tabla (T-042)


def test_la_cesion_de_promesa_no_llega_al_ranking(con) -> None:
    """El caso real: UF 850 por un 2D2B de 60 m² = 14,2 UF/m². Encabezó el ranking del
    31-ago-2026 con yield 17,58% contra 7,90% de la segunda, porque un ranking por yield
    ordena por precio bajo y una fila cuyo precio significa otra cosa flota hasta arriba."""
    celda(con)
    unidad(con, key="MLC-1939505225", m2=60, precio="850")
    unidad(con, key="LEGITIMA", m2=56, precio="3000")
    r = op.emparejar(con, RANGOS)
    assert r.descartes["precio_implausible"] == 1
    assert [u.unidad_key for u in r.unidades] == ["LEGITIMA"]


def test_el_descarte_dice_por_que_y_cual(con) -> None:
    """Contarlas no basta: son pocas y cada una es un aviso que dice una cosa y significa
    otra. La razón tiene que viajar con el descarte para poder ir a mirar el aviso."""
    celda(con)
    unidad(con, key="MLC-1939505225", m2=60, precio="850")
    (key, razon), *resto = op.emparejar(con, RANGOS).implausibles
    assert key == "MLC-1939505225" and not resto
    assert "14.2 UF/m²" in razon and "promesa" in razon


def test_la_fila_implausible_se_conserva_en_la_base(con) -> None:
    """§3.2: se marca y se excluye, **no se borra**. Si se descartara al parsear no habría
    forma de saber después cuántas hay ni de mirar el aviso."""
    celda(con)
    unidad(con, key="MLC-1939505225", m2=60, precio="850")
    op.emparejar(con, RANGOS)
    fila = con.execute(
        "SELECT precio_uf, m2_utiles FROM fact_unidad_venta WHERE unidad_key = 'MLC-1939505225'"
    ).fetchone()
    assert fila == (D(850), 60.0)


def test_no_descarta_la_unidad_mas_barata_de_su_microzona(con) -> None:
    """La diferencia con el detector de outliers del §7.3, y es la que importa. Con
    `[p1, p99]` y n chico el percentil cae casi sobre el extremo, así que el mínimo de cada
    microzona queda marcado siempre. Un rango absoluto no depende de los vecinos: la unidad
    barata pero posible sigue compitiendo, que es justo la candidata a mejor oportunidad."""
    celda(con)
    for i, precio in enumerate(["1200", "3000", "3500", "4000"]):
        unidad(con, key=f"U{i}", m2=56, precio=precio)
    r = op.emparejar(con, RANGOS)
    assert r.descartes["precio_implausible"] == 0
    assert "U0" in [u.unidad_key for u in r.unidades], "21,4 UF/m² es barato, no imposible"


# ------------------------------------------------- frescura del §7.3 (T-044)


def _con_fecha(con, key, visto, precio="3000"):
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, es_vivienda_nueva, evidence_level, valid_from, fetched_at) "
        "VALUES (?, 'sm/el-llano', '2D2B', 56, ?, FALSE, 'V', ?, ?)",
        (key, D(precio), visto, visto),
    )


def test_el_precio_de_hace_cuatro_meses_no_entra_al_ranking(con) -> None:
    """El §7.3 lo pedía desde siempre —*"ninguna fila usada en el ranking puede tener
    `fetched_at` > 21 días"*— y el emparejamiento no miraba la fecha. La segunda del ranking
    del 31-ago-2026 tenía precio del 4 de mayo."""
    celda(con)
    _con_fecha(con, "MAYO", datetime(2026, 5, 4, tzinfo=UTC))
    _con_fecha(con, "HOY", AHORA, precio="3100")
    r = op.emparejar(con, RANGOS, ahora=AHORA)
    assert r.descartes["desactualizada"] == 1
    assert [u.unidad_key for u in r.unidades] == ["HOY"]


def test_la_vieja_se_conserva_en_la_base(con) -> None:
    """No es un borrado: es la línea base contra la que se mide qué bajó de precio."""
    celda(con)
    _con_fecha(con, "MAYO", datetime(2026, 5, 4, tzinfo=UTC))
    op.emparejar(con, RANGOS, ahora=AHORA)
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1


def test_sin_ahora_no_se_filtra(con) -> None:
    """`ahora=None` conserva el comportamiento anterior: los tests que hablan de otra cosa
    no tienen que inventar fechas para seguir funcionando."""
    celda(con)
    _con_fecha(con, "MAYO", datetime(2026, 5, 4, tzinfo=UTC))
    assert len(op.emparejar(con, RANGOS).unidades) == 1


def test_el_borde_son_exactamente_21_dias(con) -> None:
    from flujocero.quality.checks import FRESCURA_MAX_DIAS

    celda(con)
    _con_fecha(con, "JUSTO", AHORA - timedelta(days=FRESCURA_MAX_DIAS))
    _con_fecha(con, "UN_DIA_MAS", AHORA - timedelta(days=FRESCURA_MAX_DIAS, seconds=1), "3100")
    r = op.emparejar(con, RANGOS, ahora=AHORA)
    assert [u.unidad_key for u in r.unidades] == ["JUSTO"]
    assert r.descartes["desactualizada"] == 1


def test_lo_que_el_gate_de_frescura_ANUNCIA_es_lo_que_el_ranking_HACE(con) -> None:
    """La contraprueba que faltaba, y la razón de fondo de esta tarea.

    `checks.frescura` imprimía *"2.696 filas con más de 21 días: quedan FUERA del ranking"*
    en cada corrida, y el emparejamiento no miraba `fetched_at`. El mensaje describía una
    consecuencia que no ocurría: séptimo caso de la familia "señal que se lee bien porque no
    está midiendo nada".

    Este test ata las dos mitades. Si alguien saca el filtro del emparejamiento, el gate
    sigue anunciando lo mismo y **este test es el que falla**.
    """
    from flujocero.quality import checks as qc

    celda(con)
    _con_fecha(con, "MAYO", datetime(2026, 5, 4, tzinfo=UTC))
    _con_fecha(con, "HOY", AHORA, precio="3100")

    filas = [
        dict(zip([d[0] for d in con.description], f, strict=True))
        for f in con.execute("SELECT * FROM fact_unidad_venta").fetchall()
    ]
    anunciadas = qc.frescura(filas, AHORA).filas_afectadas
    fuera = op.emparejar(con, RANGOS, ahora=AHORA).descartes["desactualizada"]
    assert anunciadas == fuera == 1, "el gate y el ranking tienen que contar lo mismo"


# ------------------------------------------------- el embudo por comuna (T-046)


def test_el_embudo_cuenta_lo_mismo_que_los_descartes(con) -> None:
    """La razón de ser del diseño: el embudo NO es una consulta paralela, es el mismo
    recorrido. Si algún día divergen, este test lo dice antes que un ranking equivocado."""
    celda(con)
    unidad(con, key="RANKEA")
    unidad(con, key="SIN_TIP", tip=None)
    unidad(con, key="OTRA_MZ", mz="sm/lo-vial")
    r = op.emparejar(con, RANGOS)
    total_embudo = sum(sum(m.values()) for m in r.por_comuna.values())
    assert total_embudo == r.total
    assert sum(m.get("rankea", 0) for m in r.por_comuna.values()) == len(r.unidades)
    for motivo, n in r.descartes.items():
        assert sum(m.get(motivo, 0) for m in r.por_comuna.values()) == n


def test_una_comuna_sin_ninguna_fila_no_aparece_en_el_embudo(con) -> None:
    """El silencio es la respuesta. Gran Concepción respondió 48 tarjetas por comuna en
    `probar-comunas`, se recolectó, y no apareció una sola unidad suya en el ranking. La
    pregunta era si se caían en un filtro o si nunca llegaron: ausencia del embudo = nunca
    llegaron, y eso apunta al colector de venta, no a la falta de comparables."""
    celda(con)
    unidad(con, key="U1")
    assert "concepcion" not in op.emparejar(con, RANGOS).por_comuna


def test_la_unidad_sin_microzona_no_se_pierde_del_embudo(con) -> None:
    """No tiene comuna que la reclame, y aun así tiene que estar contada en alguna parte:
    un embudo que no suma el total es otra señal que se lee bien sin medir."""
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, tipologia, m2_utiles, precio_uf, "
        "evidence_level, valid_from, fetched_at) VALUES ('HUERFANA', '2D2B', 56, 3000, 'V', "
        "?, ?)",
        (AHORA, AHORA),
    )
    r = op.emparejar(con, RANGOS)
    assert r.por_comuna["(sin microzona)"]["sin_microzona"] == 1
    assert sum(sum(m.values()) for m in r.por_comuna.values()) == r.total


# ------------------------------------------- la venta publicada en pesos (T-048)


def _en_pesos(con, key, clp, visto=AHORA, m2=56):
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, precio_clp, es_vivienda_nueva, evidence_level, valid_from, fetched_at) "
        "VALUES (?, 'sm/el-llano', '2D2B', ?, NULL, ?, FALSE, 'V', ?, ?)",
        (key, m2, clp, visto, visto),
    )


def _uf(con, fecha, valor):
    con.execute(
        "INSERT INTO dim_tiempo_financiero (serie, fecha, valor) VALUES ('uf', ?, ?)",
        (fecha.date(), D(valor)),
    )


def test_la_venta_en_pesos_ya_no_se_tira(con) -> None:
    """Antes `cargar_avisos` la omitía con un `logging.info`: no había columna donde ponerla.
    El costo no era el 6,1% de las ventas de la RM que se perdían, era que **una comuna
    entera podía esfumarse sin que nadie se enterara** — cuatro de las cinco del Gran
    Concepción."""
    celda(con)
    _uf(con, AHORA, "40871.14")
    _en_pesos(con, "EN_PESOS", 122_613_420)  # UF 3.000 exactas al valor de ese día
    r = op.emparejar(con, RANGOS, ahora=AHORA)
    assert [u.unidad_key for u in r.unidades] == ["EN_PESOS"]
    assert abs(r.unidades[0].precio_uf - D(3000)) < D("0.01")


def test_el_precio_convertido_es_D_no_V(con) -> None:
    """§3.2: sale de un cálculo determinístico sobre dos valores `V` —el peso publicado y la
    UF de su día—. El §12 excluye los `E` del ranking, no los `D`: compite, pero la ficha
    tiene que poder decir que ese número no se leyó, se calculó."""
    celda(con)
    _uf(con, AHORA, "40871.14")
    _en_pesos(con, "EN_PESOS", 122_613_420)
    # Precio distinto a proposito: con el mismo, la firma anti-duplicado del §7.3 —misma
    # microzona, tipologia, m2 y precio— colapsa las dos en una sola y el test mediria otra cosa.
    unidad(con, key="EN_UF", precio="3200")
    r = op.emparejar(con, RANGOS, ahora=AHORA)
    niveles = {u.unidad_key: u.evidence_precio for u in r.unidades}
    assert niveles == {"EN_PESOS": "D", "EN_UF": "V"}


def test_se_convierte_con_la_UF_DE_SU_DIA_no_con_la_de_hoy(con) -> None:
    """Un aviso de mayo vale lo que valía la UF en mayo. Convertirlo con la de hoy sería un
    precio de mayo expresado en UF de agosto — y la UF sube todos los días."""
    celda(con)
    mayo = datetime(2026, 5, 4, tzinfo=UTC)
    _uf(con, mayo, "39000")
    _uf(con, AHORA, "40871.14")
    _en_pesos(con, "DE_MAYO", 117_000_000, visto=mayo)  # UF 3.000 a la UF de mayo
    r = op.emparejar(con, RANGOS)  # sin `ahora`: el gate de frescura no estorba
    assert abs(r.unidades[0].precio_uf - D(3000)) < D("0.01")


def test_sin_la_UF_de_su_dia_se_descarta_y_se_cuenta(con) -> None:
    """No se convierte con la UF de otro día ni se cae en silencio (§3.2)."""
    celda(con)
    _en_pesos(con, "SIN_UF", 122_613_420)
    r = op.emparejar(con, RANGOS, ahora=AHORA)
    assert r.unidades == [] and r.descartes["sin_uf_del_dia"] == 1
    assert r.por_comuna["sm"]["sin_uf_del_dia"] == 1
