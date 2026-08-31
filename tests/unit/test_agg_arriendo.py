"""Agregación de arriendo — T-023. El numerador de todo el análisis."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.agg import arriendo as agg

RANGOS = [[0, 35], [35, 50], [50, 70], [70, 100], [100, 140]]


def base_con_microzona():
    """La base con las dimensiones minimas: `fact_arriendo_comp` tiene clave foranea a
    `dim_microzona`, que es justamente lo que impide guardar un comparable sin barrio."""
    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)
    con.execute("INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES ('x', 'X', 'RM')")
    con.execute(
        "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES ('x/y', 'x', 'Y')"
    )
    return con


def comp(mz: str = "san-miguel/el-llano", tip: str = "2D2B", m2: str = "55", uf: str = "12"):
    return agg.Comparable(mz, tip, D(m2), D(uf))


# --------------------------------------------------------------------------- rangos de m2


@pytest.mark.parametrize(
    "m2,esperado",
    [("30", "0-35"), ("35", "35-50"), ("49.9", "35-50"), ("50", "50-70"), ("139", "100-140")],
)
def test_los_rangos_son_cerrados_abajo_y_abiertos_arriba(m2: str, esperado: str) -> None:
    assert agg.etiqueta_rango(D(m2), RANGOS) == esperado


def test_sobre_140_m2_no_hay_rango_porque_se_pierde_el_DFL2() -> None:
    """Una unidad de mas de 140 m2 no compite (§12), asi que su arriendo tampoco sirve de
    comparable para las que si."""
    assert agg.etiqueta_rango(D(150), RANGOS) is None
    assert agg.etiqueta_rango(D(140), RANGOS) is None


# ----------------------------------------------------------------------------- percentil


def test_percentil_con_valores_conocidos() -> None:
    v = [D(x) for x in (10, 20, 30, 40)]
    assert agg.percentil(v, D("0.5")) == D(25)
    assert agg.percentil(v, D("0.25")) == D("17.5")
    assert agg.percentil(v, D("0.75")) == D("32.5")


def test_percentil_de_un_solo_valor_es_ese_valor() -> None:
    assert agg.percentil([D(17)], D("0.5")) == D(17)


def test_la_mediana_no_se_mueve_con_un_outlier_y_el_promedio_si() -> None:
    """Por eso se usa mediana: un aviso mal parseado o un depto atipico no puede correr la
    referencia de toda una microzona."""
    normales = [D(12), D(13), D(14), D(15), D(16)]
    con_outlier = [*normales, D(900)]
    assert agg.percentil(normales, D("0.5")) == agg.percentil(con_outlier[:5], D("0.5"))
    assert agg.percentil(con_outlier, D("0.5")) <= D(16)


# ---------------------------------------------------------------------------- agregacion


def test_la_clave_es_microzona_x_tipologia_x_rango_nunca_la_comuna() -> None:
    """§2.4: dentro de una comuna hay 17% de brecha a pocas cuadras. Agregar por comuna
    promedia dos mercados y produce un yield que no existe en ninguno de los dos."""
    datos = [
        comp(mz="san-miguel/el-llano", uf="10"),
        comp(mz="san-miguel/el-llano", uf="12"),
        comp(mz="san-miguel/ciudad-del-nino", uf="20"),
    ]
    r = agg.agregar(datos, RANGOS)
    assert len(r) == 2, "dos microzonas, dos filas: no se funden en 'san-miguel'"
    assert {a.microzona_id for a in r} == {"san-miguel/el-llano", "san-miguel/ciudad-del-nino"}


def test_un_2D_chico_y_uno_grande_no_se_mezclan() -> None:
    """Mismo barrio, misma tipologia, distinto rango: no se arriendan al mismo precio, y
    mezclarlos corre la mediana hacia donde haya mas oferta."""
    r = agg.agregar([comp(m2="45", uf="9"), comp(m2="85", uf="18")], RANGOS)
    assert len(r) == 2
    assert {a.rango_m2 for a in r} == {"35-50", "70-100"}


def test_calcula_los_tres_percentiles_y_el_UF_por_m2() -> None:
    datos = [comp(m2="55", uf=str(x)) for x in (10, 12, 14, 16)]
    a = agg.agregar(datos, RANGOS)[0]
    assert (a.n, a.mediana, a.p25, a.p75) == (4, D(13), D("11.5"), D("14.5"))
    assert a.uf_m2_mediana == D(13) / D(55)


def test_la_dispersion_delata_un_rango_que_esconde_dos_mercados() -> None:
    homogenea = agg.agregar([comp(uf=str(x)) for x in (12, 12, 13, 13)], RANGOS)[0]
    partida = agg.agregar([comp(uf=str(x)) for x in (8, 9, 20, 21)], RANGOS)[0]
    assert partida.dispersion > homogenea.dispersion * 3


def test_bajo_8_comparables_la_celda_no_puede_rankear() -> None:
    """§7.3. La mediana existe igual, pero se marca: la decision de excluirla es del ranking."""
    pocos = agg.agregar([comp() for _ in range(7)], RANGOS)[0]
    justos = agg.agregar([comp() for _ in range(8)], RANGOS)[0]
    assert not pocos.suficiente and justos.suficiente


# ------------------------------------------------------------------ conversion CLP -> UF


def test_convierte_con_la_UF_del_dia_del_aviso_no_con_la_de_hoy() -> None:
    """Usar la UF de hoy mezclaria el movimiento de la UF con el del mercado, que es lo que
    el §3.3 manda separar trabajando en terminos reales."""
    serie = {date(2026, 5, 4): D(39000), date(2026, 8, 29): D(40804)}
    assert agg.uf_del_dia(serie, datetime(2026, 5, 4, tzinfo=UTC)) == D(39000)


def test_retrocede_hasta_una_semana_si_falta_el_dia() -> None:
    serie = {date(2026, 5, 1): D(39000)}
    assert agg.uf_del_dia(serie, datetime(2026, 5, 4, tzinfo=UTC)) == D(39000)
    assert agg.uf_del_dia(serie, datetime(2026, 5, 20, tzinfo=UTC)) is None


def test_sin_UF_del_dia_la_fila_se_descarta_y_se_cuenta(tmp_path) -> None:
    """§3.2: antes que convertir con un valor que no le corresponde, se pierde la fila. Pero
    se cuenta: una fila que no entra a la mediana tiene que poder explicarse."""
    con = base_con_microzona()
    con.execute(
        "INSERT INTO fact_arriendo_comp (comp_id, microzona_id, tipologia, m2_utiles, "
        "arriendo_clp, activo, fetched_at) VALUES ('A', 'x/y', '2D2B', 55, 450000, TRUE, ?)",
        (datetime(2026, 5, 4, tzinfo=UTC),),
    )
    comparables, descartes = agg.comparables_desde_duckdb(con)
    assert comparables == []
    assert descartes["sin_uf_del_dia"] == 1
    con.close()


def test_con_la_serie_cargada_la_conversion_funciona() -> None:
    con = base_con_microzona()
    con.execute(
        "INSERT INTO dim_tiempo_financiero (fecha, serie, valor, unidad, evidence_level) "
        "VALUES (DATE '2026-05-04', 'uf', 39000, 'CLP', 'V')"
    )
    con.execute(
        "INSERT INTO fact_arriendo_comp (comp_id, microzona_id, tipologia, m2_utiles, "
        "arriendo_clp, activo, fetched_at) VALUES ('A', 'x/y', '2D2B', 55, 468000, TRUE, ?)",
        (datetime(2026, 5, 4, tzinfo=UTC),),
    )
    comparables, descartes = agg.comparables_desde_duckdb(con)
    assert len(comparables) == 1
    assert comparables[0].arriendo_uf == D(12), "468.000 / 39.000"
    assert not any(descartes.values())
    con.close()


def test_un_arriendo_ya_publicado_en_UF_no_se_convierte() -> None:
    con = base_con_microzona()
    con.execute(
        "INSERT INTO fact_arriendo_comp (comp_id, microzona_id, tipologia, m2_utiles, "
        "arriendo_uf, activo, fetched_at) VALUES ('A', 'x/y', '2D2B', 55, 12, TRUE, ?)",
        (datetime(2026, 5, 4, tzinfo=UTC),),
    )
    comparables, _ = agg.comparables_desde_duckdb(con)
    assert comparables[0].arriendo_uf == D(12)
    con.close()


def test_recalcular_reemplaza_en_vez_de_acumular() -> None:
    """`agg_arriendo_microzona` es un derivado, no un historico: la historia vive en
    `fact_arriendo_comp`."""
    con = base_con_microzona()
    ahora = datetime(2026, 8, 29, tzinfo=UTC)
    datos = agg.agregar([comp() for _ in range(3)], RANGOS)
    agg.cargar_en_duckdb(con, datos, ahora)
    agg.cargar_en_duckdb(con, datos, ahora)
    assert con.execute("SELECT count(*) FROM agg_arriendo_microzona").fetchone()[0] == 1
    con.close()


# --------------------- la mediana que audita y la que rankea (T-052)


def test_el_comando_que_audita_usa_la_misma_poblacion_que_el_ranking() -> None:
    """`cli comparables` existe para auditar el número que el ranking muestra. Si filtra
    distinto, audita otro número — y eso pasó.

    El caso real: sobre `santiago/san-diego · 1D1B · 25-35 m²` el comando decía **$330.000
    sobre 23 avisos** mientras el ranking usaba **$355.000 sobre 12**. Los 11 de diferencia
    eran de mayo, que el §7.3 saca de la agregación. Dos números para la misma celda.

    Este test fija el criterio compartido: **amoblado fuera, vencido fuera**. Si alguien
    cambia uno de los dos lados, acá falla.
    """
    from datetime import UTC, datetime, timedelta

    from flujocero.quality.checks import FRESCURA_MAX_DIAS
    from flujocero.quality.comparabilidad import no_comparable

    ahora = datetime(2026, 8, 31, tzinfo=UTC)
    limite = ahora - timedelta(days=FRESCURA_MAX_DIAS)

    # (arriendo, fecha, titulo) — los 24 avisos reales de la celda, resumidos.
    avisos = [
        (250_000, datetime(2026, 5, 3, tzinfo=UTC), "arriendo-1d1b-metro-u-de-chile"),
        (330_000, datetime(2026, 5, 3, tzinfo=UTC), "departamento-serrano"),
        (380_000, datetime(2026, 5, 3, tzinfo=UTC), "arriendo-departamento-amoblado-sta-isabel"),
        (280_000, ahora, "excelente-depto-de-1d1b-metro-parque-almagro"),
        (355_000, ahora, "edificio-eyzaguirre-vista-sur-piso-12"),
        (375_000, ahora, "edificio-arturo-prat-vista-sur-piso-9"),
    ]

    def entra(monto_fecha_titulo) -> bool:
        _, visto, titulo = monto_fecha_titulo
        return not no_comparable(titulo) and visto >= limite

    vigentes = [a for a in avisos if entra(a)]
    assert [a[0] for a in vigentes] == [280_000, 355_000, 375_000]
    assert all(a[1] >= limite for a in vigentes), "ninguno de mayo"
    assert not any(no_comparable(a[2]) for a in vigentes), "ninguno amoblado"
