"""El puente venta × arriendo — T-029. El eslabon que faltaba."""

from __future__ import annotations

from datetime import UTC, datetime
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


def test_delata_los_componentes_del_score_que_no_diferencian_nada(con) -> None:
    """`riesgo_microzona` y `catalizador` suman 25% del score y hoy no tienen fuente. Al
    valer todos igual, la normalizacion los vuelve una constante: reparten el mismo puntaje
    y no mueven una sola posicion. Un score que se presenta como completo cuando un cuarto de
    su peso esta inerte miente por omision."""
    celda(con)
    unidad(con, key="A")
    unidad(con, key="B", precio="2800")
    r = op.emparejar(con, RANGOS)
    inertes = op.componentes_inertes(r.unidades)
    assert set(inertes) == {"riesgo_microzona", "catalizador"}
    assert op.peso_inerte(inertes, cargar("params")) == D("0.25")


def test_un_componente_con_datos_distintos_deja_de_estar_inerte(con) -> None:
    celda(con)
    unidad(con, key="A")
    r = op.emparejar(con, RANGOS)
    from dataclasses import replace

    r.unidades.append(replace(r.unidades[0], unidad_key="B", riesgo_microzona=D("0.9")))
    assert "riesgo_microzona" not in op.componentes_inertes(r.unidades)


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
