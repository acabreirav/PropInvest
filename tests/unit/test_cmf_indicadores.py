"""Tests del colector CMF — T-010.

Nunca tocan la red: todo corre contra fixtures y contra un transporte HTTP simulado.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from flujocero.quality import source_contract as gate
from flujocero.sources.base import (
    COLUMNAS_PROCEDENCIA,
    Procedencia,
    ProcedenciaIncompleta,
    RawDoc,
    Scope,
    escribir_crudo,
    ocultar_secreto,
    ruta_cruda,
)
from flujocero.sources.cmf_indicadores import (
    CmfIndicadores,
    ErrorDeFuente,
    a_decimal,
    cargar_en_duckdb,
    desde_entorno,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cmf"
AHORA = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
UA = "FlujoCero-ResearchBot/1.0 (test)"


def doc_de_fixture(nombre: str, url: str = "https://api.cmfchile.cl/x?apikey=OCULTA") -> RawDoc:
    contenido = (FIXTURES / nombre).read_bytes()
    return RawDoc(
        source_id="cmf_indicadores",
        url=url,
        fetched_at=AHORA,
        ruta=FIXTURES / nombre,
        contenido=contenido,
        robots_snapshot_sha="sha-de-prueba",
    )


def colector(**kw) -> CmfIndicadores:
    return CmfIndicadores(apikey="clave-de-prueba", user_agent=UA, **kw)


# --------------------------------------------------------------------- formato chileno


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("20.939,49", Decimal("20939.49")),
        ("40.804,00", Decimal("40804.00")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("950,10", Decimal("950.10")),
        ("0,4", Decimal("0.4")),
        ("-0,2", Decimal("-0.2")),
        ("1.234.567", Decimal("1234567")),
        ("123", Decimal("123")),
        # El caso que rompia: un solo punto, sin decimales. En formato chileno el punto
        # es SIEMPRE separador de miles. Leerlo como decimal es un error de 1000x.
        ("40.804", Decimal("40804")),
        ("69.542", Decimal("69542")),
        ("1.500", Decimal("1500")),
    ],
)
def test_convierte_el_formato_chileno(texto: str, esperado: Decimal) -> None:
    """Punto de miles, coma decimal. Leer '20.939,49' como 20,93 sería un error de 1000x."""
    assert a_decimal(texto) == esperado


@pytest.mark.parametrize("basura", ["", "  ", "abc", "12,34,56"])
def test_un_valor_ilegible_es_error_no_un_cero(basura: str) -> None:
    """§11: nada de try/except: pass. Un formato que cambia tiene que gritar."""
    with pytest.raises(ErrorDeFuente):
        a_decimal(basura)


# --------------------------------------------------------------------- parseo


def test_parsea_la_serie_uf_con_procedencia_completa() -> None:
    filas = colector().parse(doc_de_fixture("uf_periodo_2026_08.json"))
    assert len(filas) == 3
    assert filas[0].serie == "uf"
    assert filas[0].valor == Decimal("40804.00")
    assert filas[0].unidad == "CLP"
    assert filas[0].evidence_level == "V"
    for col in COLUMNAS_PROCEDENCIA:
        assert getattr(filas[0], col), f"{col} vacío"


def test_identifica_la_serie_por_el_envoltorio_no_por_la_url() -> None:
    """Si la URL dice uf pero el cuerpo trae UTMs, gana el cuerpo."""
    doc = doc_de_fixture("utm_2026_08.json", url="https://api.cmfchile.cl/uf?apikey=OCULTA")
    filas = colector().parse(doc)
    assert [f.serie for f in filas] == ["utm"]


def test_un_envoltorio_desconocido_falla_en_vez_de_adivinar() -> None:
    with pytest.raises(ErrorDeFuente, match="ninguna clave conocida"):
        colector().parse(doc_de_fixture("envoltorio_desconocido.json"))


def test_un_registro_sin_valor_falla(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.json"
    ruta.write_text(json.dumps({"UFs": [{"Fecha": "2026-08-28"}]}))
    doc = RawDoc("cmf_indicadores", "u", AHORA, ruta, ruta.read_bytes(), "sha")
    with pytest.raises(ErrorDeFuente, match="sin Fecha/Valor"):
        colector().parse(doc)


# --------------------------------------------------------------------- procedencia


def test_procedencia_incompleta_no_se_puede_construir() -> None:
    """§3.1 como regla dura: el objeto no existe si falta una columna."""
    with pytest.raises(ProcedenciaIncompleta, match="raw_blob_path"):
        Procedencia(
            source_id="x",
            source_url="u",
            fetched_at=AHORA,
            parser_version="v",
            raw_blob_path="",
            robots_snapshot_sha="s",
        )


def test_fetched_at_sin_zona_horaria_es_rechazado() -> None:
    with pytest.raises(ProcedenciaIncompleta, match="tzinfo"):
        Procedencia("x", "u", datetime(2026, 8, 28), "v", "r", "s")  # noqa: DTZ001


def test_la_apikey_nunca_queda_en_la_url_persistida() -> None:
    sucio = "https://api.cmfchile.cl/uf?apikey=c4d742450e40&formato=json"
    assert "c4d742450e40" not in ocultar_secreto(sucio)
    assert "apikey=OCULTA" in ocultar_secreto(sucio)


# --------------------------------------------------------------------- zona cruda


def test_la_zona_cruda_usa_la_ruta_por_fecha(tmp_path: Path) -> None:
    r = ruta_cruda("cmf_indicadores", AHORA, "uf_hoy", raiz=tmp_path)
    assert r.relative_to(tmp_path).parts == (
        "cmf_indicadores",
        "2026",
        "08",
        "28",
        "uf_hoy.json.gz",
    )


def test_reescribir_el_mismo_dia_no_duplica(tmp_path: Path) -> None:
    """§3.6: re-ejecutar un colector el mismo día no acumula archivos."""
    for _ in range(3):
        escribir_crudo("cmf_indicadores", "u", b'{"UFs":[]}', AHORA, "sha", "uf", tmp_path)
    archivos = list((tmp_path / "cmf_indicadores" / "2026" / "08" / "28").iterdir())
    assert len(archivos) == 1
    with gzip.open(archivos[0], "rb") as fh:
        assert fh.read() == b'{"UFs":[]}'


# --------------------------------------------------------------------- recolección


def transporte(respuestas: dict[str, tuple[int, bytes]]) -> httpx.Client:
    def manejar(request: httpx.Request) -> httpx.Response:
        for fragmento, (code, cuerpo) in respuestas.items():
            if fragmento in str(request.url):
                return httpx.Response(code, content=cuerpo)
        return httpx.Response(404, content=b"no encontrado")

    return httpx.Client(transport=httpx.MockTransport(manejar))


def test_collect_persiste_antes_de_parsear(tmp_path: Path) -> None:
    cliente = transporte(
        {
            "robots.txt": (200, b"User-agent: *\nAllow: /\n"),
            "/uf": (200, (FIXTURES / "uf_periodo_2026_08.json").read_bytes()),
        }
    )
    c = colector(series=("uf",), cliente=cliente, raiz_cruda=tmp_path, pausa_s=0)
    docs = list(c.collect(Scope(ahora=AHORA)))
    assert len(docs) == 1
    assert docs[0].ruta.exists()
    assert docs[0].ruta.suffix == ".gz"
    assert "clave-de-prueba" not in docs[0].url


def test_un_error_http_no_se_traga(tmp_path: Path) -> None:
    cliente = transporte(
        {"robots.txt": (200, b"User-agent: *\nAllow: /\n"), "/uf": (401, b"apikey invalida")}
    )
    c = colector(series=("uf",), cliente=cliente, raiz_cruda=tmp_path, pausa_s=0)
    with pytest.raises(ErrorDeFuente, match="401"):
        list(c.collect(Scope(ahora=AHORA)))


def test_la_url_de_periodo_sigue_la_documentacion() -> None:
    u = colector().url("uf", desde="2024-01", hasta="2026-08")
    assert "/uf/periodo/2024/01/2026/08" in u
    assert "formato=json" in u


# --------------------------------------------------------------------- selftest y gate


def test_selftest_pasa_contra_la_fixture_pero_no_declara_forma_verificada() -> None:
    """Honestidad del reporte: sin muestra viva, no se afirma haber visto la API real."""
    rep = colector().selftest(fixture=doc_de_fixture("uf_periodo_2026_08.json"))
    assert rep.ok
    assert rep.checks["campos_requeridos"]
    assert rep.checks["rangos_plausibles"]
    assert rep.checks["forma_verificada"] is False


def test_selftest_detecta_un_valor_fuera_de_rango(tmp_path: Path) -> None:
    ruta = tmp_path / "absurdo.json"
    ruta.write_text(json.dumps({"UFs": [{"Fecha": "2026-08-28", "Valor": "3,50"}]}))
    doc = RawDoc("cmf_indicadores", "u", AHORA, ruta, ruta.read_bytes(), "sha")
    rep = colector().selftest(fixture=doc)
    assert not rep.ok
    assert rep.checks["rangos_plausibles"] is False


def test_selftest_detecta_el_parser_roto_por_caida_de_conteo() -> None:
    """§7.1: una caída >30% vs la corrida anterior es señal de parser roto."""
    rep = colector().selftest(
        fixture=doc_de_fixture("uf_periodo_2026_08.json"), n_filas_corrida_anterior=100
    )
    assert not rep.ok
    assert rep.checks["conteo_estable"] is False


def test_el_gate_de_contrato_acepta_el_colector() -> None:
    filas = colector().parse(doc_de_fixture("uf_periodo_2026_08.json"))
    rep = gate.verificar(colector(), filas)
    assert rep.ok, str(rep)


def test_el_gate_rechaza_filas_sin_procedencia() -> None:
    class FilaPelada:
        evidence_level = "V"

    rep = gate.verificar_filas("falsa", [FilaPelada()])
    assert not rep.ok
    assert any("source_id" in f for f in rep.fallos)


def test_el_gate_rechaza_un_legal_tier_inventado() -> None:
    class Rara:
        id = "rara"
        legal_tier = "lo_que_sea"
        parser_version = "1"

        def robots_ok(self): ...
        def collect(self, scope): ...
        def parse(self, doc): ...
        def selftest(self): ...

    rep = gate.verificar_protocolo(Rara())
    assert not rep.ok


# --------------------------------------------------------------------- carga idempotente


def test_la_carga_en_duckdb_es_idempotente(tmp_path: Path) -> None:
    """§3.6: correr dos veces el mismo día deja una fila por (fecha, serie), no dos."""
    import duckdb

    from flujocero import db

    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    db.aplicar_esquema(con)
    filas = colector().parse(doc_de_fixture("uf_periodo_2026_08.json"))
    cargar_en_duckdb(con, filas)
    cargar_en_duckdb(con, filas)
    assert con.execute("SELECT count(*) FROM dim_tiempo_financiero").fetchone()[0] == 3
    guardada = con.execute(
        "SELECT valor, evidence_level, source_id FROM dim_tiempo_financiero "
        "WHERE fecha = '2026-08-28' AND serie = 'uf'"
    ).fetchone()
    assert guardada[0] == Decimal("40804.000000")
    assert guardada[1] == "V"
    assert guardada[2] == "cmf_indicadores"


def test_la_vista_ancha_reconstruye_el_formato_de_siempre(tmp_path: Path) -> None:
    import duckdb

    from flujocero import db

    con = duckdb.connect(str(tmp_path / "t2.duckdb"))
    db.aplicar_esquema(con)
    c = colector()
    cargar_en_duckdb(con, c.parse(doc_de_fixture("uf_periodo_2026_08.json")))
    cargar_en_duckdb(con, c.parse(doc_de_fixture("utm_2026_08.json")))
    fila = con.execute(
        "SELECT uf_clp FROM v_tiempo_financiero WHERE fecha = '2026-08-28'"
    ).fetchone()
    assert fila[0] == Decimal("40804.000000")


# --------------------------------------------------------------------- entorno


def test_sin_apikey_el_mensaje_dice_donde_conseguirla() -> None:
    with pytest.raises(ErrorDeFuente, match="api.cmfchile.cl"):
        desde_entorno({})


def test_series_desconocidas_se_rechazan_al_construir() -> None:
    with pytest.raises(ValueError, match="series desconocidas"):
        colector(series=("dolar",))


def test_no_recolecta_si_robots_no_pasa(tmp_path: Path) -> None:
    """§3.5: la verificación de robots.txt pasa ANTES de recolectar, no después."""
    cliente = transporte({"robots.txt": (200, b"User-agent: *\nDisallow: /\n")})
    c = colector(series=("uf",), cliente=cliente, raiz_cruda=tmp_path, pausa_s=0)
    with pytest.raises(ErrorDeFuente, match="robots.txt no superada"):
        list(c.collect(Scope(ahora=AHORA)))


def test_una_caida_de_red_es_error_de_fuente_no_traceback(tmp_path: Path) -> None:
    def caer(request: httpx.Request) -> httpx.Response:
        if "robots.txt" in str(request.url):
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")
        raise httpx.ConnectError("proxy bloqueado")

    cliente = httpx.Client(transport=httpx.MockTransport(caer))
    c = colector(series=("uf",), cliente=cliente, raiz_cruda=tmp_path, pausa_s=0)
    with pytest.raises(ErrorDeFuente, match="no se pudo alcanzar"):
        list(c.collect(Scope(ahora=AHORA)))
