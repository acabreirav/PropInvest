"""Tests del alcance geográfico — T-938.

El bug que originó el módulo: `params.yml` declara `excluir_microzonas_saturadas: true`,
`modelo.py` implementa la regla, y el emparejamiento real **nunca poblaba el campo**. La
exclusión dura del §12 no se disparaba jamás sobre datos reales.
"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest
import yaml

from flujocero import db
from flujocero.agg.faltantes import diagnosticar
from flujocero.agg.oportunidades import emparejar
from flujocero.alcance import Alcance, desde_config
from flujocero.config import Config, cargar

AHORA = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
RANGOS = [[0, 35], [35, 50], [50, 70], [70, 100], [100, 140]]

ZONAS_DE_PRUEBA = yaml.safe_load("""
fase_1:
  - comuna: san-miguel
    saturadas: []
  - comuna: nunoa
    saturadas: [estadio-nacional]
fase_2:
  - comuna: macul
    saturadas: [quilin-av-macul]
fase_3:
  - ciudad: gran-concepcion
excluidas:
  - {zona: providencia, razon: "2D2B en UF 8.921, sobre el tope"}
  - {zona: las-condes, razon: "ticket sobre el tope"}
""")


@pytest.fixture
def alc() -> Alcance:
    return desde_config(Config(ZONAS_DE_PRUEBA, "zonas_de_prueba"))


# --------------------------------------------------------------- la regla


def test_las_comunas_de_todas_las_fases_estan_dentro(alc: Alcance) -> None:
    assert alc.en_alcance("san-miguel")
    assert alc.en_alcance("macul")
    assert alc.en_alcance("gran-concepcion"), "fase 3 usa `ciudad`, no `comuna`"


def test_una_comuna_excluida_esta_fuera_con_su_razon(alc: Alcance) -> None:
    assert not alc.en_alcance("providencia")
    assert "sobre el tope" in alc.razon_fuera("providencia")


def test_el_alcance_es_lista_blanca_no_lista_negra(alc: Alcance) -> None:
    """Lo que no está declarado en una fase está FUERA.

    Al revés —tratar "no aparece en excluidas" como permitido— cualquier comuna que el
    colector traiga de pasada entraría al ranking sin que nadie lo decidiera. El colector
    trajo Las Condes y Providencia sin que estuvieran en el alcance.
    """
    assert not alc.en_alcance("puente-alto")
    assert "no esta declarada" in alc.razon_fuera("puente-alto")


def test_una_comuna_en_las_dos_listas_queda_excluida() -> None:
    """Es una contradicción del YAML, no algo que resolver en silencio. Gana la exclusión,
    que es el lado conservador."""
    datos = {
        "fase_1": [{"comuna": "providencia"}],
        "excluidas": [{"zona": "providencia", "razon": "sobre el tope"}],
    }
    a = desde_config(Config(datos, "contradictorio"))
    assert not a.en_alcance("providencia")


def test_none_y_vacio_estan_fuera(alc: Alcance) -> None:
    assert not alc.en_alcance(None)
    assert not alc.en_alcance("")


# --------------------------------------------------------------- saturadas


def test_las_saturadas_se_arman_con_el_microzona_id_completo(alc: Alcance) -> None:
    """En el YAML van por nombre corto bajo su comuna; el resto del sistema las mueve como
    `comuna/microzona`. Compararlas por el nombre corto no calzaría nunca."""
    assert alc.saturada("nunoa/estadio-nacional")
    assert not alc.saturada("estadio-nacional")
    assert not alc.saturada("nunoa/irarrazaval")


def test_una_microzona_saturada_no_es_rankeable_aunque_su_comuna_si_lo_sea(alc) -> None:
    entra, razon = alc.unidad_rankeable("nunoa/estadio-nacional")
    assert not entra
    assert "saturada" in razon
    assert alc.en_alcance("nunoa"), "la comuna sí está en alcance; la microzona no"


def test_una_microzona_de_comuna_excluida_no_es_rankeable(alc: Alcance) -> None:
    entra, razon = alc.unidad_rankeable("providencia/los-leones")
    assert not entra
    assert "excluida" in razon


def test_una_microzona_en_alcance_y_no_saturada_si_es_rankeable(alc: Alcance) -> None:
    assert alc.unidad_rankeable("san-miguel/el-llano") == (True, None)


# --------------------------------------------------------------- contra el YAML real


def test_el_zonas_real_carga_y_dice_lo_que_el_contrato_dice() -> None:
    """Anclas del §10 del contrato, para que un cambio silencioso de alcance se note."""
    a = desde_config(cargar("zonas"))
    assert a.en_alcance("san-miguel") and a.en_alcance("nunoa") and a.en_alcance("la-florida")
    assert not a.en_alcance("providencia"), "§10 la excluye: 2D2B en UF 8.921"
    assert not a.en_alcance("las-condes"), "§10 la excluye: ticket sobre el tope"
    assert a.saturada("nunoa/estadio-nacional"), "§10: saturada por evidencia Tattersall"


# --------------------------------------------------------------- el emparejamiento


def _base_con(unidades):
    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)
    for mz in sorted({m for _k, m in unidades}):
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
        con.execute(
            "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, "
            "arriendo_uf_mediana, n) VALUES (?,'2D2B','50-70',12.0,20)",
            (mz,),
        )
    for key, mz in unidades:
        con.execute(
            "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, m2_utiles, "
            "precio_uf, evidence_level, valid_from, valid_to, source_id, source_url, "
            "fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
            "VALUES (?,?,'2D2B',55.0,2500,'V',?,NULL,'f','https://x',?,'p/1','r','s')",
            (key, mz, AHORA, AHORA),
        )
    return con


UNIDADES = [
    ("OK-1", "san-miguel/el-llano"),
    ("SAT-1", "nunoa/estadio-nacional"),
    ("FUERA-1", "providencia/los-leones"),
]


def test_el_emparejamiento_descarta_las_saturadas_y_las_cuenta(alc: Alcance) -> None:
    """EL BUG ORIGINAL. El §12 excluye microzonas saturadas y esa regla no se disparaba
    nunca sobre datos reales, porque este emparejamiento no poblaba el campo."""
    con = _base_con(UNIDADES)
    try:
        r = emparejar(con, RANGOS, alcance=alc)
    finally:
        con.close()
    assert [u.unidad_key for u in r.unidades] == ["OK-1"]
    assert r.descartes["microzona_saturada"] == 1
    assert r.descartes["fuera_de_alcance"] == 1


def test_sin_alcance_el_emparejamiento_no_filtra_nada(alc: Alcance) -> None:
    """El comportamiento anterior se conserva con `alcance=None`, para que ningún llamador
    viejo cambie de conducta sin que alguien lo decida."""
    con = _base_con(UNIDADES)
    try:
        r = emparejar(con, RANGOS)
    finally:
        con.close()
    assert len(r.unidades) == 3
    assert r.descartes["microzona_saturada"] == 0


def test_el_emparejamiento_puebla_microzona_saturada_en_la_unidad(alc: Alcance) -> None:
    """Aunque las saturadas ya se descarten antes: si ese filtro cambia, el motor tiene que
    seguir teniendo con qué aplicar el §12."""
    con = _base_con([("OK-1", "san-miguel/el-llano")])
    try:
        r = emparejar(con, RANGOS, alcance=alc)
    finally:
        con.close()
    assert r.unidades[0].microzona_saturada is False


def test_el_motor_excluye_de_verdad_una_unidad_saturada() -> None:
    """La otra mitad del bug: comprobar que la regla del §12, una vez poblado el campo,
    efectivamente excluye. Sin este test el arreglo podría poblar un campo que nadie mira."""
    from flujocero.finance.escenarios import escenario_base
    from flujocero.finance.modelo import Unidad, evaluar

    p, inv = cargar("params"), cargar("inversionista")
    assert p.crudo("score.exclusiones_duras")["excluir_microzonas_saturadas"] is True
    from decimal import Decimal as D

    u = Unidad(
        "SAT-1",
        D(2500),
        D(55),
        "2D2B",
        "nunoa",
        "nunoa/estadio-nacional",
        D(12),
        20,
        True,
        microzona_saturada=True,
    )
    ev = evaluar(u, escenario_base(p, inv), p, inv)
    assert ev.excluido
    assert "saturada" in ev.motivo_exclusion


# --------------------------------------------------------------- el diagnóstico


def test_el_diagnostico_no_cuenta_como_desbloqueable_lo_que_no_puede_rankear(alc) -> None:
    """Una unidad en comuna excluida o microzona saturada no se desbloquea con comparables:
    se descarta por regla dura después. Contarla infla el objetivo y desvía la recolección —
    que es exactamente lo que pasó cuando `--dirigida 3` eligió Providencia."""
    con = _base_con(UNIDADES)
    con.execute("DELETE FROM agg_arriendo_microzona")  # todo bloqueado, para que cuente
    try:
        con_alcance = diagnosticar(con, RANGOS, alcance=alc)
        sin_alcance = diagnosticar(con, RANGOS)
    finally:
        con.close()
    assert sin_alcance.desbloqueables == 3
    assert con_alcance.desbloqueables == 1
    assert list(con_alcance.por_comuna()) == ["san-miguel"]


def test_las_comunas_del_e2e_estan_en_alcance() -> None:
    """El E2E se cayó cuando entró la lista blanca: sus microzonas sintéticas no estaban en
    `zonas.yml`. Este test ata las dos cosas para que el próximo cambio de alcance rompa acá
    —con un mensaje claro— y no en un E2E de siete minutos con la tabla vacía."""
    from tests.integration.test_dashboard_e2e import COMUNAS_EN_ALCANCE, MICROZONAS

    a = desde_config(cargar("zonas"))
    for comuna in COMUNAS_EN_ALCANCE:
        assert a.en_alcance(comuna), f"{comuna} salió del alcance; arregla el fixture del E2E"
    for mz in MICROZONAS:
        assert a.unidad_rankeable(mz)[0], f"{mz} no rankearía y el E2E quedaría sin filas"


def test_la_migracion_agrega_la_columna_a_una_base_que_ya_existia() -> None:
    """`schema.sql` usa `CREATE TABLE IF NOT EXISTS`, así que una base ya creada **nunca
    recibe una columna nueva**: el DDL corre sin error y sin efecto, y el primer INSERT que
    la mencione revienta.

    Pasó el 30-ago-2026 con `m2_mediana`. Este test simula una base vieja —crea la tabla sin
    la columna— y verifica que `migrar()` la agrega y que correrlo dos veces no falla.
    """
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE agg_arriendo_microzona (microzona_id VARCHAR, tipologia VARCHAR, "
        "rango_m2 VARCHAR, n INTEGER)"
    )
    columnas = lambda: {  # noqa: E731
        f[0] for f in con.execute("DESCRIBE agg_arriendo_microzona").fetchall()
    }
    assert "m2_mediana" not in columnas()
    assert db.migrar(con) == ["agg_arriendo_microzona.m2_mediana"]
    assert "m2_mediana" in columnas()
    db.migrar(con)  # idempotente
    assert "m2_mediana" in columnas()
    con.close()


def test_la_migracion_no_revienta_sobre_una_base_vacia() -> None:
    """En una base recién creada la tabla no existe todavía y el DDL ya la trae completa."""
    con = duckdb.connect(":memory:")
    assert db.migrar(con) == []
    con.close()
