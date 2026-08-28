"""Tests del colector de tasas hipotecarias — T-012.

La fixture es el archivo REAL que la CMF publica hoy, que resulta ser de 2006.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from flujocero.quality import source_contract as gate
from flujocero.sources.base import RawDoc
from flujocero.sources.cmf_tasas_hipotecarias import (
    CmfTasasHipotecarias,
    ErrorDeFuente,
    PlanillaObsoleta,
    antiguedad_meses,
    cargar_en_duckdb,
    parsear_fecha_consulta,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "cmf_tasas"
    / "articles-46417_recurso_1_2006.xls"
)
AHORA = datetime(2026, 8, 28, tzinfo=UTC)


def doc() -> RawDoc:
    return RawDoc(
        "cmf_tasas_hipotecarias",
        "https://www.cmfchile.cl/portal/estadisticas/617/articles-46417_recurso_1.xls",
        AHORA,
        FIXTURE,
        FIXTURE.read_bytes(),
        "sha-de-prueba",
    )


def colector(**kw) -> CmfTasasHipotecarias:
    return CmfTasasHipotecarias(user_agent="FlujoCero/test", **kw)


# --------------------------------------------------------------------- fecha


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Fecha de la consulta: 22 al 26 de mayo de 2006", date(2006, 5, 26)),
        ("Fecha de la consulta: 3 de enero de 2026", date(2026, 1, 3)),
        ("fecha de la consulta: 1 al 5 de diciembre de 2025", date(2025, 12, 5)),
    ],
)
def test_lee_la_fecha_de_consulta(texto: str, esperado: date) -> None:
    """Del rango se toma el último día: hasta ahí el dato es válido."""
    assert parsear_fecha_consulta(texto) == esperado


def test_una_fecha_ilegible_es_error() -> None:
    with pytest.raises(ErrorDeFuente):
        parsear_fecha_consulta("Fecha de la consulta: la semana pasada")


def test_antiguedad_en_meses() -> None:
    assert antiguedad_meses(date(2006, 5, 26), date(2026, 8, 28)) == 243
    assert antiguedad_meses(date(2026, 8, 1), date(2026, 8, 28)) == 0


# --------------------------------------------------------------------- el hallazgo


def test_el_archivo_real_de_la_cmf_es_de_2006_y_se_rechaza() -> None:
    """EL HALLAZGO DE T-012.

    La URL que `config/fuentes.yml` declara como fuente de tasas por banco sirve una
    planilla de mayo de 2006, firmada por la SBIF (disuelta en 2019) y con bancos que ya
    no existen. Este test fija que el sistema la RECHACE en vez de usarla.
    """
    with pytest.raises(PlanillaObsoleta, match="243 meses"):
        colector().parse(doc(), ahora=date(2026, 8, 28))


def test_la_misma_planilla_parsea_bien_si_la_fecha_es_contemporanea() -> None:
    """El rechazo es por antigüedad, no por un parser roto: la estructura se lee entera."""
    filas = colector().parse(doc(), ahora=date(2006, 6, 1))
    assert len(filas) == 117
    assert len({f.banco for f in filas}) == 17
    assert {f.producto for f in filas} == {
        "letras_credito",
        "mutuo_endosable",
        "mutuo_no_endosable",
    }
    assert {int(f.monto_credito_uf) for f in filas} == {1000, 1500, 3000}


def test_captura_los_metadatos_que_impiden_comparar_a_ciegas() -> None:
    """20 años y 75% de LTV: no son los 30 años y 90% del escenario base."""
    f = colector().parse(doc(), ahora=date(2006, 6, 1))[0]
    assert f.plazo_anios == 20
    assert D("0.70") < f.ltv < D("0.80")


def test_no_ofrece_es_nd_y_no_cero() -> None:
    """§3.2: 'n/o' significa que el banco no vende ese producto. Cero sería una mentira."""
    filas = colector().parse(doc(), ahora=date(2006, 6, 1))
    bbva = [f for f in filas if f.banco == "Banco BBVA"]
    # BBVA no ofrece letras de crédito: no debe existir la fila, no debe valer 0.
    assert all(f.producto != "letras_credito" for f in bbva)
    assert all(f.tasa_anual > 0 for f in filas)


def test_limpia_las_marcas_al_pie_del_nombre_del_banco() -> None:
    filas = colector().parse(doc(), ahora=date(2006, 6, 1))
    assert any(f.banco == "Corpbanca" for f in filas) or all("(" not in f.banco for f in filas)
    assert all(not f.banco.startswith(("(", "*")) for f in filas)


def test_no_se_cuelan_las_notas_al_pie_como_bancos() -> None:
    filas = colector().parse(doc(), ahora=date(2006, 6, 1))
    prohibidos = ("notas", "fuente", "n/o", "actualizado", "corresponde")
    assert all(not f.banco.lower().startswith(prohibidos) for f in filas)


# --------------------------------------------------------------------- robustez


def test_una_planilla_sin_hojas_de_tasas_falla_ruidosamente(tmp_path: Path) -> None:
    import xlwt  # type: ignore[import-untyped]

    libro = xlwt.Workbook()
    libro.add_sheet("Otra cosa")
    ruta = tmp_path / "vacio.xls"
    libro.save(str(ruta))
    d = RawDoc("cmf_tasas_hipotecarias", "u", AHORA, ruta, ruta.read_bytes(), "sha")
    with pytest.raises(ErrorDeFuente, match="ninguna hoja de tasas"):
        colector().parse(d, ahora=date(2026, 8, 28))


def test_el_selftest_reporta_la_obsolescencia_como_fallo_de_frescura() -> None:
    rep = colector().selftest(fixture=doc(), ahora=date(2026, 8, 28))
    assert not rep.ok
    assert rep.checks["frescura"] is False
    assert "243 meses" in rep.detalle["frescura"]


def test_el_selftest_pasa_con_fecha_contemporanea() -> None:
    rep = colector().selftest(fixture=doc(), ahora=date(2006, 6, 1))
    assert rep.ok, rep.detalle
    assert rep.n_filas == 117


def test_el_gate_de_contrato_acepta_el_colector() -> None:
    filas = colector().parse(doc(), ahora=date(2006, 6, 1))
    rep = gate.verificar(colector(), filas)
    assert rep.ok, str(rep)


# --------------------------------------------------------------------- carga


def test_la_carga_deja_la_mejor_tasa_por_banco(tmp_path: Path) -> None:
    """La planilla trae 3 productos x 3 montos por banco. Se guarda la mínima, que es una
    decisión explícita y no un promedio silencioso."""
    import duckdb

    from flujocero import db

    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    db.aplicar_esquema(con)
    filas = colector().parse(doc(), ahora=date(2006, 6, 1))
    n = cargar_en_duckdb(con, filas)
    assert n == 17, "una fila por banco"
    cargar_en_duckdb(con, filas)
    assert con.execute("SELECT count(*) FROM dim_tasa_banco").fetchone()[0] == 17

    bice = con.execute(
        "SELECT tasa_anual FROM dim_tasa_banco WHERE banco = 'Banco BICE'"
    ).fetchone()[0]
    minima = min(f.tasa_anual for f in filas if f.banco == "Banco BICE")
    assert abs(D(str(bice)) - minima) < D("1e-9")
