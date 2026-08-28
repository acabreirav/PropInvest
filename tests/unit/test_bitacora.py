"""Tests de la bitacora — CLAUDE.md §7.1 (detector de parser roto) y §11 (parse_errors).

Nacieron de una auditoria: `run_log` y `parse_errors` existian en el esquema y nadie las
escribia. La consecuencia era que el detector de parser roto del §7.1 recibia siempre
`None` como conteo anterior y por lo tanto **nunca podia disparar**.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from flujocero import db
from flujocero.quality import bitacora

AHORA = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def con(tmp_path: Path):
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    db.aplicar_esquema(c)
    yield c
    c.close()


def _corrida(con, source_id: str, filas: int, ok: bool, momento: datetime) -> None:
    r = bitacora.abrir(source_id, momento)
    r.filas_insertadas = filas
    r.selftest_ok = ok
    bitacora.cerrar(con, r, ahora=momento + timedelta(seconds=30))


# --------------------------------------------------------------------- detector §7.1


def test_sin_historia_no_hay_con_que_comparar(con) -> None:
    assert bitacora.filas_de_la_ultima_corrida_exitosa(con, "cmf_indicadores") is None


def test_se_compara_contra_la_ultima_corrida_EXITOSA(con) -> None:
    """Una corrida fallida no puede convertirse en la nueva referencia: si lo hiciera,
    un parser roto bajaria el liston y el detector dejaria de disparar para siempre."""
    _corrida(con, "cmf_indicadores", 1000, True, AHORA - timedelta(days=2))
    _corrida(con, "cmf_indicadores", 3, False, AHORA - timedelta(days=1))
    assert bitacora.filas_de_la_ultima_corrida_exitosa(con, "cmf_indicadores") == 1000


def test_cada_fuente_tiene_su_propia_historia(con) -> None:
    _corrida(con, "cmf_indicadores", 1000, True, AHORA)
    _corrida(con, "otra_fuente", 7, True, AHORA)
    assert bitacora.filas_de_la_ultima_corrida_exitosa(con, "cmf_indicadores") == 1000
    assert bitacora.filas_de_la_ultima_corrida_exitosa(con, "otra_fuente") == 7


@pytest.mark.parametrize(
    ("anterior", "actual", "esperado"),
    [(1000, 1000, 0.0), (1000, 700, 0.30), (1000, 500, 0.50), (1000, 1200, -0.20), (None, 5, None)],
)
def test_calculo_de_la_caida(anterior, actual, esperado) -> None:
    r = bitacora.caida_pct(anterior, actual)
    assert (r is None and esperado is None) or abs(r - esperado) < 1e-9


def test_el_detector_del_selftest_dispara_con_la_historia_real(con) -> None:
    """La cadena completa: se guarda una corrida, el selftest la lee y falla por la caida."""
    from flujocero.sources.base import RawDoc
    from flujocero.sources.cmf_indicadores import CmfIndicadores

    _corrida(con, "cmf_indicadores", 974, True, AHORA - timedelta(days=1))
    anterior = bitacora.filas_de_la_ultima_corrida_exitosa(con, "cmf_indicadores")

    fx = Path(__file__).resolve().parents[1] / "fixtures" / "cmf" / "uf_periodo_2026_08.json"
    doc = RawDoc("cmf_indicadores", "u", AHORA, fx, fx.read_bytes(), "sha")
    rep = CmfIndicadores(apikey="x", user_agent="t").selftest(
        fixture=doc, n_filas_corrida_anterior=anterior
    )
    assert not rep.ok, "3 filas contra 974 es una caida del 99%: tiene que disparar"
    assert rep.checks["conteo_estable"] is False


# --------------------------------------------------------------------- parse_errors §11


def test_un_error_de_parseo_queda_registrado_con_su_documento(con) -> None:
    """§11: nada de try/except: pass. El error va a la tabla con el blob que lo produjo."""
    try:
        raise ValueError("valor ilegible en la fila 3")
    except ValueError as exc:
        eid = bitacora.registrar_error(
            con, "cmf_indicadores", "data/raw/cmf_indicadores/2026/08/28/uf.json.gz", exc, AHORA
        )
    assert eid
    filas = bitacora.errores_recientes(con, "cmf_indicadores")
    assert len(filas) == 1
    assert "uf.json.gz" in filas[0][2]
    assert "ValueError: valor ilegible" in filas[0][3]


def test_el_traceback_se_guarda_completo(con) -> None:
    """Sin traceback, un error registrado no sirve para diagnosticar nada."""
    try:
        raise KeyError("UFs")
    except KeyError as exc:
        bitacora.registrar_error(con, "x", "b.gz", exc, AHORA)
    tb = con.execute("SELECT traceback FROM parse_errors").fetchone()[0]
    assert "KeyError" in tb and "test_bitacora" in tb


def test_la_corrida_se_registra_aunque_falle(con) -> None:
    """Una corrida fallida que no queda escrita es una corrida que el detector no ve."""
    r = bitacora.abrir("cmf_indicadores", AHORA)
    r.notas = "recoleccion fallida: proxy 403"
    bitacora.cerrar(con, r, ahora=AHORA + timedelta(seconds=5))
    h = bitacora.historial(con, "cmf_indicadores")
    assert len(h) == 1
    assert h[0][4] is False, "selftest_ok debe quedar en falso"


def test_la_variacion_queda_guardada_para_auditar(con) -> None:
    _corrida(con, "cmf_indicadores", 1000, True, AHORA - timedelta(days=1))
    r = bitacora.abrir("cmf_indicadores", AHORA)
    r.filas_insertadas, r.selftest_ok = 700, True
    bitacora.cerrar(con, r, ahora=AHORA, filas_corrida_anterior=1000)
    delta = con.execute(
        "SELECT delta_vs_corrida_anterior FROM run_log ORDER BY inicio DESC LIMIT 1"
    ).fetchone()[0]
    assert abs(delta - 0.30) < 1e-9
