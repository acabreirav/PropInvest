"""Tests del diagnóstico de huecos de arriendo — T-935."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import duckdb
import pytest

from flujocero import db
from flujocero.agg.arriendo import MIN_COMPARABLES
from flujocero.agg.faltantes import Hueco, diagnosticar

AHORA = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
RANGOS = [[0, 35], [35, 50], [50, 70], [70, 100], [100, 140]]


def _base(unidades, celdas):
    """`unidades`: (key, microzona, tipologia, m2). `celdas`: (microzona, tip, rango, n)."""
    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)
    # `fact_unidad_venta.microzona_id` tiene FK contra `dim_microzona`, asi que las dims van
    # primero. Es el esquema real haciendo su trabajo: una unidad no puede apuntar a una
    # microzona que no existe.
    for mz in sorted({m for _k, m, _t, _s in unidades if m}):
        comuna = mz.split("/")[0]
        con.execute(
            "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?,?,'RM') "
            "ON CONFLICT DO NOTHING",
            (comuna, comuna),
        )
        con.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES (?,?,?)",
            (mz, comuna, mz.split("/")[1]),
        )
    for key, mz, tip, m2 in unidades:
        con.execute(
            "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
            "precio_uf, evidence_level, valid_from, valid_to, source_id, source_url, "
            "fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
            "VALUES (?,?,?,?,2500,'V',?,NULL,'f','https://x',?,'p/1','raw/x','sha')",
            (key, mz, tip, m2, AHORA, AHORA),
        )
    for mz, tip, rango, n in celdas:
        con.execute(
            "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, "
            "arriendo_uf_mediana, n) VALUES (?,?,?,10.0,?)",
            (mz, tip, rango, n),
        )
    return con


# --------------------------------------------------------------- la palanca


def test_la_palanca_es_unidades_por_aviso_que_falta() -> None:
    h = Hueco("a/b", "2D2B", "50-70", unidades_bloqueadas=108, comparables_actuales=2)
    assert h.faltan == MIN_COMPARABLES - 2
    assert h.palanca == Decimal(108) / Decimal(MIN_COMPARABLES - 2)


def test_una_celda_ya_suficiente_no_tiene_palanca() -> None:
    """Sin esto, dividir por cero. Y conceptualmente: no hay nada que conseguir."""
    h = Hueco("a/b", "2D2B", "50-70", unidades_bloqueadas=50, comparables_actuales=MIN_COMPARABLES)
    assert h.faltan == 0
    assert h.palanca == 0


def test_gana_la_celda_que_rinde_mas_por_aviso_no_la_que_tiene_mas_unidades() -> None:
    """Es el punto entero del módulo.

    Una celda con 40 unidades a la que le faltan 7 rinde 5,7 por aviso. Otra con 16 a la que
    le falta 1 rinde 16. La segunda va primero aunque tenga menos unidades: conseguir un
    aviso desbloquea 16, y conseguir siete desbloquea 40.
    """
    con = _base(
        unidades=[
            *[(f"G-{i}", "a/grande", "2D2B", 55.0) for i in range(40)],
            *[(f"P-{i}", "b/chica", "2D2B", 55.0) for i in range(16)],
        ],
        celdas=[("a/grande", "2D2B", "50-70", 1), ("b/chica", "2D2B", "50-70", 7)],
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert [h.microzona_id for h in dg.huecos] == ["b/chica", "a/grande"]
    assert dg.huecos[0].palanca == 16
    assert dg.huecos[1].palanca == Decimal(40) / Decimal(7)


def test_a_igual_palanca_gana_la_de_mas_volumen() -> None:
    """Una corrida trae varios avisos de una, así que entre dos celdas que rinden lo mismo
    por aviso conviene la que desbloquea más."""
    con = _base(
        unidades=[
            *[(f"A-{i}", "a/uno", "2D2B", 55.0) for i in range(16)],
            *[(f"B-{i}", "b/dos", "2D2B", 55.0) for i in range(32)],
        ],
        celdas=[("a/uno", "2D2B", "50-70", 7), ("b/dos", "2D2B", "50-70", 6)],
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    # Las dos rinden 16 por aviso; gana la de 32 unidades.
    assert dg.huecos[0].palanca == dg.huecos[1].palanca == 16
    assert dg.huecos[0].microzona_id == "b/dos"


# --------------------------------------------------------------- qué cuenta y qué no


def test_una_celda_con_suficientes_comparables_no_es_un_hueco() -> None:
    con = _base(
        unidades=[("A-1", "a/uno", "2D2B", 55.0)],
        celdas=[("a/uno", "2D2B", "50-70", MIN_COMPARABLES)],
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.huecos == []
    assert dg.unidades_rankeables_hoy == 1


def test_una_unidad_sobre_140_m2_no_es_un_hueco_de_datos(caplog) -> None:
    """Pierde el DFL2 y no compite (§12). Ningún comparable de arriendo la va a rescatar, así
    que contarla como "bloqueada" mandaría a recolectar para nada."""
    con = _base(unidades=[("XL-1", "a/uno", "4D3B", 180.0)], celdas=[])
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.huecos == []
    assert dg.unidades_con_precio == 0


def test_el_rango_se_calcula_igual_que_en_la_agregacion() -> None:
    """Si acá se calculara distinto, el diagnóstico apuntaría a celdas que el emparejamiento
    nunca va a mirar: una lista de tareas falsas con cara de plan."""
    con = _base(
        unidades=[("A-1", "a/uno", "1D1B", 38.0)],
        celdas=[("a/uno", "1D1B", "35-50", MIN_COMPARABLES)],
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.unidades_rankeables_hoy == 1, "38 m² tiene que caer en el rango 35-50"


def test_una_unidad_sin_microzona_no_entra() -> None:
    con = _base(unidades=[("A-1", None, "2D2B", 55.0)], celdas=[])
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.unidades_con_precio == 0


def test_solo_cuenta_la_version_vigente_de_cada_aviso() -> None:
    """SCD tipo 2: una versión cerrada es historia de precios, no una unidad a la venta."""
    con = _base(unidades=[("A-1", "a/uno", "2D2B", 55.0)], celdas=[])
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, evidence_level, valid_from, valid_to, source_id, source_url, fetched_at, "
        "parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES ('A-1','a/uno','2D2B',55.0,2400,'V',?,?,'f','https://x',?,'p/1','raw/x','sha')",
        (AHORA, AHORA, AHORA),
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.unidades_con_precio == 1, "la versión cerrada se contó como una unidad más"


def test_una_unidad_con_precio_estimado_no_entra() -> None:
    """El §12 excluye del ranking todo precio `E`. Un "desde UF X" de proyecto es eso."""
    con = _base(unidades=[("V-1", "a/uno", "2D2B", 55.0)], celdas=[])
    con.execute("DELETE FROM fact_unidad_venta")
    con.execute(
        "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
        "precio_uf, evidence_level, valid_from, valid_to, source_id, source_url, fetched_at, "
        "parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES ('E-1','a/uno','2D2B',55.0,2500,'E',?,NULL,'f','https://x',?,'p/1','r','s')",
        (AHORA, AHORA),
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.unidades_con_precio == 0


# --------------------------------------------------------------- agregados


def test_los_totales_cuadran() -> None:
    con = _base(
        unidades=[
            *[(f"A-{i}", "sm/uno", "2D2B", 55.0) for i in range(10)],
            *[(f"B-{i}", "sm/dos", "1D1B", 40.0) for i in range(5)],
            ("C-1", "nu/tres", "2D2B", 55.0),
        ],
        celdas=[("nu/tres", "2D2B", "50-70", MIN_COMPARABLES)],
    )
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.unidades_con_precio == 16
    assert dg.unidades_rankeables_hoy == 1
    assert dg.desbloqueables == 15
    assert dg.avisos_necesarios == MIN_COMPARABLES * 2  # dos celdas desde cero


def test_por_comuna_agrupa_por_el_prefijo_de_la_microzona() -> None:
    con = _base(
        unidades=[
            *[(f"A-{i}", "san-miguel/uno", "2D2B", 55.0) for i in range(10)],
            *[(f"B-{i}", "san-miguel/dos", "1D1B", 40.0) for i in range(5)],
            ("C-1", "nunoa/tres", "2D2B", 55.0),
        ],
        celdas=[],
    )
    try:
        por_comuna = diagnosticar(con, RANGOS).por_comuna()
    finally:
        con.close()
    assert list(por_comuna) == ["san-miguel", "nunoa"], "no está ordenado por unidades"
    assert por_comuna["san-miguel"] == (15, MIN_COMPARABLES * 2)
    assert por_comuna["nunoa"] == (1, MIN_COMPARABLES)


def test_sin_unidades_no_hay_huecos_ni_division_por_cero() -> None:
    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)
    try:
        dg = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert dg.huecos == []
    assert dg.desbloqueables == 0
    assert dg.avisos_necesarios == 0


@pytest.mark.parametrize("minimo", [1, 4, 8, 20])
def test_el_umbral_entra_por_argumento_pero_su_valor_es_del_contrato(minimo: int) -> None:
    """Se puede parametrizar para explorar, pero el default es el `MIN_COMPARABLES` del
    §7.3 y bajarlo no es la respuesta a "faltan comparables"."""
    con = _base(unidades=[("A-1", "a/uno", "2D2B", 55.0)], celdas=[("a/uno", "2D2B", "50-70", 5)])
    try:
        dg = diagnosticar(con, RANGOS, minimo=minimo)
    finally:
        con.close()
    if minimo <= 5:
        assert dg.unidades_rankeables_hoy == 1
    else:
        assert dg.huecos[0].faltan == max(0, MIN_COMPARABLES - 5)


# --------------------------------------------------------------- recoleccion dirigida


def test_la_prioridad_por_comuna_es_la_que_usa_la_recoleccion_dirigida() -> None:
    """`--dirigida N` toma las N primeras comunas de `por_comuna()`.

    El orden tiene que ser por unidades que esperan, no por avisos que faltan: una comuna
    donde faltan 900 avisos para 200 unidades rinde menos que una donde faltan 300 para 570.
    Ordenar por esfuerzo en vez de por resultado mandaría la corrida al lugar equivocado.
    """
    con = _base(
        unidades=[
            *[(f"N-{i}", "nunoa/uno", "2D2B", 55.0) for i in range(30)],
            *[(f"M-{i}", "macul/uno", "2D2B", 55.0) for i in range(5)],
            *[(f"M2-{i}", "macul/dos", "1D1B", 40.0) for i in range(5)],
            *[(f"M3-{i}", "macul/tres", "3D2B", 80.0) for i in range(5)],
        ],
        celdas=[],
    )
    try:
        por_comuna = diagnosticar(con, RANGOS).por_comuna()
    finally:
        con.close()
    # Macul necesita MÁS avisos (tres celdas desde cero) pero Ñuñoa tiene más unidades.
    assert por_comuna["macul"][1] > por_comuna["nunoa"][1]
    assert list(por_comuna)[0] == "nunoa", "se ordenó por esfuerzo en vez de por resultado"
