"""T-924 · la medición por tramo de m²: colocación, GGCC/m² y salida."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.agg import micro_riesgo as mr

AHORA = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    c.execute("INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('x', 'X', '')")
    c.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES ('x/z', 'x', 'Z')"
    )
    c.execute("INSERT INTO dim_proyecto (proyecto_id, nombre, comuna_id) VALUES ('p', 'P', 'x')")
    yield c
    c.close()


def _comp(c, cid, m2, dias=None, publicado=None, ggcc=None, **kw):
    base = dict(amoblado=False, sospechoso=False, activo=True)
    base.update(kw)
    c.execute(
        "INSERT INTO fact_arriendo_comp (comp_id, microzona_id, tipologia, m2_utiles, "
        "arriendo_uf, gastos_comunes_clp, dias_en_mercado, publicado_en, activo, amoblado, "
        "sospechoso, evidence_level, fetched_at) VALUES (?, 'x/z', '1D1B', ?, ?, ?, ?, ?, "
        "?, ?, ?, 'V', ?)",
        (
            cid,
            m2,
            D("8"),
            ggcc,
            dias,
            publicado,
            base["activo"],
            base["amoblado"],
            base["sospechoso"],
            AHORA,
        ),
    )


def test_medir_arriendo_agrupa_por_tramo_y_prefiere_dias_declarados(con) -> None:
    _comp(con, "A", 22.0, dias=40, ggcc=80000)  # <25: GGCC/m2 = 3.636
    _comp(con, "B", 23.0, dias=60, ggcc=90000)
    # sin dias declarados: la edad sale de publicado_en → 10 dias
    _comp(con, "C", 40.0, publicado=(AHORA - timedelta(days=10)).date(), ggcc=90000)
    # los filtros del §7.3: amoblado y sospechoso quedan fuera de las medianas
    _comp(con, "D", 41.0, dias=200, amoblado=True)
    _comp(con, "E", 42.0, dias=200, sospechoso=True)

    filas = {f.tramo: f for f in mr.medir_arriendo(con)}
    assert filas["<25"].n == 2 and filas["<25"].edad_mediana_dias == 50.0
    assert filas["<25"].ggcc_m2_mediana_clp == pytest.approx((80000 / 22 + 90000 / 23) / 2)
    assert filas["35-50"].n == 1 and filas["35-50"].edad_mediana_dias == 10.0
    # el GGCC/m2 mas alto en el tramo chico queda medido, no supuesto
    assert filas["<25"].ggcc_m2_mediana_clp > filas["35-50"].ggcc_m2_mediana_clp


def test_medir_arriendo_sin_fecha_es_nd_no_cero(con) -> None:
    _comp(con, "A", 22.0)  # ni dias ni publicado_en
    filas = {f.tramo: f for f in mr.medir_arriendo(con)}
    assert filas["<25"].edad_mediana_dias is None and filas["<25"].n_con_fecha == 0
    assert filas["<25"].ggcc_m2_mediana_clp is None and filas["<25"].n_con_ggcc == 0
    # sin `ahora` la cota de edad queda ND, jamas un cero inventado; la fraccion vista
    # fresca no depende del reloj y se mide siempre (0 declarado sobre 0 etiquetas)
    assert filas["<25"].edad_cota_inf_mediana_dias is None
    assert filas["<25"].pct_visto_fresco == 0.0 and filas["<25"].n_con_etiqueta == 0


def test_las_cotas_t924b_salen_de_la_primera_vista_y_la_etiqueta(con) -> None:
    """`edad>=` viene de visto_primera_vez (o fetched_at si la fila es de antes de la
    migracion) y `% fresco` es la fraccion que ALGUNA captura vio recien publicada —
    anclada a la captura de cada fila, no al reloj de la medicion (verificador M-1/M-2:
    medir meses despues no puede convertir la evidencia en 0%)."""
    _comp(con, "A", 22.0)
    con.execute(
        "UPDATE fact_arriendo_comp SET visto_primera_vez = ?, publicado_desde = ? "
        "WHERE comp_id = 'A'",
        (AHORA - timedelta(days=20), (AHORA - timedelta(days=20)).date()),
    )
    _comp(con, "B", 23.0)  # sin primera vista propia ni etiqueta: cota 0 dias, no visto fresco

    filas = {f.tramo: f for f in mr.medir_arriendo(con, AHORA)}
    f = filas["<25"]
    assert f.edad_cota_inf_mediana_dias == pytest.approx(10.0)  # mediana(20, 0)
    # A fue vista fresca hace 20 dias: SIGUE contando — la evidencia no caduca
    assert f.pct_visto_fresco == pytest.approx(0.5)
    assert f.n_con_etiqueta == 1

    # medir en otro momento no cambia la fraccion (M-1): solo la cota de edad crece
    tarde = {f.tramo: f for f in mr.medir_arriendo(con, AHORA + timedelta(days=30))}
    assert tarde["<25"].pct_visto_fresco == pytest.approx(0.5)
    assert tarde["<25"].edad_cota_inf_mediana_dias == pytest.approx(40.0)  # mediana(50, 30)


def test_publicado_en_autoreferente_o_relisting_no_entra_a_la_edad(con) -> None:
    """Verificador M-3/M-6: un publicado_en igual al dia de captura es 0 por
    construccion (etiqueta HOY) — no es un dato de edad —, y uno POSTERIOR a la
    primera vista propia es un relisting. Ninguno alimenta la mediana."""
    _comp(con, "H", 22.0)  # etiqueta HOY: publicado_en == dia de fetched_at
    con.execute(
        "UPDATE fact_arriendo_comp SET publicado_en = ? WHERE comp_id = 'H'",
        (AHORA.date(),),
    )
    _comp(con, "R", 23.0)  # relisting: publicado_en 42 dias DESPUES de la primera vista
    con.execute(
        "UPDATE fact_arriendo_comp SET publicado_en = ?, visto_primera_vez = ? WHERE comp_id = 'R'",
        ((AHORA - timedelta(days=5)).date(), AHORA - timedelta(days=47)),
    )
    _comp(con, "V", 24.0, publicado=(AHORA - timedelta(days=10)).date())  # edad legitima

    f = {x.tramo: x for x in mr.medir_arriendo(con, AHORA)}["<25"]
    assert f.n_con_fecha == 1, "solo V aporta edad; H y R quedan fuera"
    assert f.edad_mediana_dias == pytest.approx(10.0)


def test_el_filtro_de_amoblados_es_el_mismo_del_ranking(con) -> None:
    """Verificador m-7: la columna `amoblado` nunca se puebla — el filtro real del §7.3
    es `no_comparable` sobre la URL. La medicion usa LOS DOS."""
    _comp(con, "A", 22.0)
    con.execute(
        "UPDATE fact_arriendo_comp SET source_url = 'https://x/depto-amoblado-metro' "
        "WHERE comp_id = 'A'"
    )
    _comp(con, "B", 23.0)
    filas = {f.tramo: f for f in mr.medir_arriendo(con)}
    assert filas["<25"].n == 1, "el amoblado declarado en la URL queda fuera de la mediana"


def _venta(c, key, m2, primera, ultima, p1, p2):
    for i, (cuando, precio) in enumerate(((primera, p1), (ultima, p2))):
        c.execute(
            "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, "
            "precio_uf, m2_utiles, evidence_level, valid_from, fetched_at) "
            "VALUES (?, 'p', ?, ?, ?, 'V', ?, ?)",
            (key, f"v{i}", D(str(precio)), m2, cuando, cuando),
        )


def test_medir_venta_compara_la_foto_de_mayo_por_tramo(con) -> None:
    mayo = datetime(2026, 5, 10, tzinfo=UTC)
    # chica de mayo que NO se volvio a ver (ultima captura en mayo)
    _venta(con, "K1", 22.0, mayo, mayo + timedelta(days=1), 1500, 1500)
    # chica de mayo re-vista hace poco, y ademas bajo de precio
    _venta(con, "K2", 23.0, mayo, AHORA - timedelta(days=2), 1500, 1400)
    # grande de mayo re-vista, sin cambio
    _venta(con, "K3", 60.0, mayo, AHORA - timedelta(days=2), 3000, 3000)
    # posterior a mayo: fuera de la foto
    _venta(con, "K4", 22.0, datetime(2026, 8, 30, tzinfo=UTC), AHORA, 1500, 1500)

    filas = {f.tramo: f for f in mr.medir_venta(con, AHORA)}
    assert filas["<25"].n_mayo == 2
    assert filas["<25"].pct_no_vistas == pytest.approx(0.5)
    assert filas["<25"].pct_bajaron_precio == pytest.approx(0.5)
    assert filas["50-70"].n_mayo == 1 and filas["50-70"].pct_no_vistas == 0.0
