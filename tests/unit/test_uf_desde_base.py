"""La UF deja de ser un parametro fijo — deuda declarada en la auditoria del 28-ago-2026.

T-010 cargo 974 valores reales de UF y el motor seguia usando el `40804` de `params.yml`.
El §11 le prohibe I/O al motor, asi que la lectura ocurre afuera y el valor entra por
argumento, con su `evidence` y su fuente.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import duckdb
import pytest

from flujocero import db
from flujocero.config import cargar, con_valor, uf_desde_la_base

AHORA = datetime(2026, 8, 28, tzinfo=UTC)


@pytest.fixture
def con(tmp_path: Path):
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    db.aplicar_esquema(c)
    yield c
    c.close()


def _uf(con, fecha: str, valor: str) -> None:
    con.execute(
        "INSERT INTO dim_tiempo_financiero (fecha, serie, valor, unidad, evidence_level, "
        "source_id, source_url, fetched_at, parser_version, raw_blob_path, robots_snapshot_sha) "
        "VALUES (?, 'uf', ?, 'CLP', 'V', 'cmf_indicadores', 'https://api.cmfchile.cl/uf', "
        "?, 'cmf/1.1.0', 'data/raw/x.gz', 'sha')",
        (fecha, D(valor), AHORA),
    )


def test_sin_serie_cargada_devuelve_none_y_no_inventa(con) -> None:
    """§3.2: prohibido imputar en silencio. Quien llama decide si cae al valor fijo."""
    assert uf_desde_la_base(con) is None


def test_toma_la_uf_mas_reciente(con) -> None:
    _uf(con, "2026-08-26", "40794.25")
    _uf(con, "2026-08-28", "40804.00")
    _uf(con, "2026-08-27", "40799.12")
    valor, fuente = uf_desde_la_base(con)
    assert valor == D("40804.00")
    assert "cmf_indicadores" in fuente and "2026-08-28" in fuente


def test_puede_pedirse_la_uf_de_una_fecha_pasada(con) -> None:
    """Para valorizar una operacion con la UF del dia en que ocurrio, no la de hoy."""
    _uf(con, "2026-08-26", "40794.25")
    _uf(con, "2026-08-28", "40804.00")
    valor, _ = uf_desde_la_base(con, "2026-08-27")
    assert valor == D("40794.25")


def test_el_valor_inyectado_viaja_con_evidencia_y_fuente() -> None:
    p = cargar("params")
    q = con_valor(p, "macro.valor_uf_clp", 41234.5, "cmf_indicadores · 2026-08-31")
    assert q.d("macro.valor_uf_clp") == D("41234.5")
    crudo = q.crudo("macro.valor_uf_clp")
    assert crudo["evidence"] == "V", "un dato de la base es Verificado, no Estimado"
    assert "cmf_indicadores" in crudo["fuente"]


def test_inyectar_no_muta_la_configuracion_original() -> None:
    """Si mutara, una evaluacion contaminaria a la siguiente."""
    p = cargar("params")
    original = p.d("macro.valor_uf_clp")
    con_valor(p, "macro.valor_uf_clp", 99999, "prueba")
    assert p.d("macro.valor_uf_clp") == original


def test_el_rango_de_sensibilidad_se_conserva_al_inyectar() -> None:
    """Si el valor tenia rango declarado (§3.2), no se pierde al reemplazarlo."""
    p = cargar("params")
    q = con_valor(p, "macro.inflacion_anual_esperada", 0.035, "prueba")
    assert q.crudo("macro.inflacion_anual_esperada")["rango"] == [0.02, 0.04]
