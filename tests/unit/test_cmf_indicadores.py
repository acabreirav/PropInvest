"""Tests del colector CMF — T-010.

Nunca tocan la red: todo corre contra fixtures y contra un transporte HTTP simulado.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
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
    INTENTOS,
    CmfIndicadores,
    ErrorDeFuente,
    a_decimal,
    cargar_en_duckdb,
    desde_entorno,
    ventanas,
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
    archivos = sorted(
        p.name for p in (tmp_path / "cmf_indicadores" / "2026" / "08" / "28").iterdir()
    )
    assert archivos == ["uf.json.gz", "uf.meta.json"], "el blob y su sidecar, sin duplicar"
    with gzip.open(tmp_path / "cmf_indicadores/2026/08/28/uf.json.gz", "rb") as fh:
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


# --------------------------------------------------------------------- troceado del periodo


@pytest.mark.parametrize(
    ("desde", "hasta", "esperado"),
    [
        (
            "2024-01",
            "2026-08",
            [("2024-01", "2024-12"), ("2025-01", "2025-12"), ("2026-01", "2026-08")],
        ),
        ("2026-08", "2026-08", [("2026-08", "2026-08")]),
        ("2025-06", "2026-03", [("2025-06", "2026-03")]),
        ("2024-01", "2024-12", [("2024-01", "2024-12")]),
        (
            "2024-06",
            "2026-06",
            [("2024-06", "2025-05"), ("2025-06", "2026-05"), ("2026-06", "2026-06")],
        ),
    ],
)
def test_el_periodo_se_trocea_en_ventanas_de_un_ano(desde, hasta, esperado) -> None:
    """La API cierra la conexion con rangos largos. 32 meses fallan; un ano responde."""
    assert ventanas(desde, hasta) == esperado


def test_las_ventanas_cubren_el_rango_completo_sin_huecos_ni_solapes() -> None:
    tramos = ventanas("2024-01", "2026-08")
    assert tramos[0][0] == "2024-01"
    assert tramos[-1][1] == "2026-08"
    for (_, fin), (inicio, _) in zip(tramos[:-1], tramos[1:], strict=True):
        fy, fm = (int(x) for x in fin.split("-"))
        iy, im = (int(x) for x in inicio.split("-"))
        assert iy * 12 + im == fy * 12 + fm + 1, f"hueco o solape entre {fin} y {inicio}"


def test_un_rango_invertido_es_error() -> None:
    with pytest.raises(ValueError, match="invertido"):
        ventanas("2026-08", "2024-01")


def test_collect_pide_una_ventana_por_ano_y_por_serie(tmp_path: Path) -> None:
    pedidas: list[str] = []

    def manejar(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "robots.txt" in url:
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")
        pedidas.append(url)
        return httpx.Response(200, content=(FIXTURES / "uf_periodo_2026_08.json").read_bytes())

    c = colector(
        series=("uf",),
        cliente=httpx.Client(transport=httpx.MockTransport(manejar)),
        raiz_cruda=tmp_path,
        pausa_s=0,
    )
    docs = list(c.collect(Scope(desde="2024-01", hasta="2026-08", ahora=AHORA)))
    assert len(docs) == 3, "un documento por ano calendario"
    assert any("2024/01/2024/12" in u for u in pedidas)
    assert any("2025/01/2025/12" in u for u in pedidas)
    assert any("2026/01/2026/08" in u for u in pedidas)
    assert len({d.ruta for d in docs}) == 3, "cada ventana en su propio archivo crudo"


# --------------------------------------------------------------------- reintentos


def test_un_corte_de_conexion_se_reintenta_y_termina_pasando(tmp_path: Path) -> None:
    """§5 del contrato: backoff exponencial con jitter. Es EL fallo que vio el usuario:
    `RemoteProtocolError: Server disconnected without sending a response`."""
    intentos = {"n": 0}

    def manejar(request: httpx.Request) -> httpx.Response:
        if "robots.txt" in str(request.url):
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, content=(FIXTURES / "uf_periodo_2026_08.json").read_bytes())

    c = colector(
        series=("uf",),
        cliente=httpx.Client(transport=httpx.MockTransport(manejar)),
        raiz_cruda=tmp_path,
        pausa_s=0,
    )
    docs = list(c.collect(Scope(desde="2026-08", hasta="2026-08", ahora=AHORA)))
    assert len(docs) == 1
    assert intentos["n"] == 3, "reintento hasta que respondio"


def test_si_el_corte_persiste_se_rinde_con_un_mensaje_util(tmp_path: Path) -> None:
    def manejar(request: httpx.Request) -> httpx.Response:
        if "robots.txt" in str(request.url):
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    c = colector(
        series=("uf",),
        cliente=httpx.Client(transport=httpx.MockTransport(manejar)),
        raiz_cruda=tmp_path,
        pausa_s=0,
    )
    with pytest.raises(ErrorDeFuente, match=f"tras {INTENTOS} intentos"):
        list(c.collect(Scope(desde="2026-08", hasta="2026-08", ahora=AHORA)))


def test_un_401_no_se_reintenta_nunca(tmp_path: Path) -> None:
    """Reintentar un error de credencial solo consigue que te bloqueen."""
    intentos = {"n": 0}

    def manejar(request: httpx.Request) -> httpx.Response:
        if "robots.txt" in str(request.url):
            return httpx.Response(200, content=b"User-agent: *\nAllow: /\n")
        intentos["n"] += 1
        return httpx.Response(401, content=b"apikey invalida")

    c = colector(
        series=("uf",),
        cliente=httpx.Client(transport=httpx.MockTransport(manejar)),
        raiz_cruda=tmp_path,
        pausa_s=0,
    )
    with pytest.raises(ErrorDeFuente, match="401"):
        list(c.collect(Scope(desde="2026-08", hasta="2026-08", ahora=AHORA)))
    assert intentos["n"] == 1, "un 401 no se reintenta"


# --------------------------------------------------------------------- zona cruda y rebuild


def test_el_blob_crudo_viaja_con_su_procedencia(tmp_path: Path) -> None:
    """LA DEUDA QUE ENCONTRO LA AUDITORIA.

    De las seis columnas del §3.1, la ruta permite deducir `source_id`, `fetched_at` y
    `raw_blob_path`. Las otras tres se perdian, y con ellas la posibilidad de que
    `make rebuild --from-raw` produjera una fila legal. No era dificil: era ilegal.
    """
    from flujocero.sources.base import leer_crudo, ruta_meta

    doc = escribir_crudo(
        "cmf_indicadores",
        "https://api.cmfchile.cl/uf?apikey=OCULTA",
        b'{"UFs":[]}',
        AHORA,
        "sha-robots-abc",
        "uf",
        tmp_path,
        "cmf_indicadores/1.1.0",
    )
    assert ruta_meta(doc.ruta).is_file()

    releido = leer_crudo(doc.ruta)
    assert releido.url == "https://api.cmfchile.cl/uf?apikey=OCULTA"
    assert releido.robots_snapshot_sha == "sha-robots-abc"
    assert releido.fetched_at == AHORA
    assert releido.contenido == b'{"UFs":[]}'


def test_la_apikey_no_queda_en_el_sidecar(tmp_path: Path) -> None:
    """El .meta.json se versiona en ningun lado, pero vive en disco: sin secretos."""
    from flujocero.sources.base import ruta_meta

    doc = escribir_crudo(
        "cmf_indicadores",
        ocultar_secreto("https://api.cmfchile.cl/uf?apikey=SECRETA123"),
        b"{}",
        AHORA,
        "sha",
        "uf",
        tmp_path,
        "v1",
    )
    assert "SECRETA123" not in ruta_meta(doc.ruta).read_text()


def test_un_blob_sin_sidecar_no_se_reconstruye_inventando_procedencia(tmp_path: Path) -> None:
    """§3.1 es regla dura: antes que inventar una procedencia, no se reconstruye."""
    from flujocero.sources.base import MetadatoAusente, leer_crudo, ruta_meta

    doc = escribir_crudo("cmf_indicadores", "u", b"{}", AHORA, "sha", "uf", tmp_path, "v1")
    ruta_meta(doc.ruta).unlink()
    with pytest.raises(MetadatoAusente, match="§3.1"):
        leer_crudo(doc.ruta)


def test_rebuild_reconstruye_las_mismas_filas_desde_la_zona_cruda(tmp_path: Path) -> None:
    """§3.6 · la prueba de fuego: recolectar, borrar la base, reconstruir, comparar."""
    import duckdb

    from flujocero import db
    from flujocero.sources.base import blobs_crudos, leer_crudo
    from flujocero.sources.registro import entrada

    cliente = transporte(
        {
            "robots.txt": (200, b"User-agent: *\nAllow: /\n"),
            "/uf": (200, (FIXTURES / "uf_periodo_2026_08.json").read_bytes()),
        }
    )
    c = colector(series=("uf",), cliente=cliente, raiz_cruda=tmp_path, pausa_s=0)

    con = duckdb.connect(str(tmp_path / "a.duckdb"))
    db.aplicar_esquema(con)
    filas_originales = []
    for doc in c.collect(Scope(desde="2026-08", hasta="2026-08", ahora=AHORA)):
        filas_originales.extend(c.parse(doc))
    cargar_en_duckdb(con, filas_originales)
    antes = con.execute(
        "SELECT fecha, serie, valor, source_url, robots_snapshot_sha "
        "FROM dim_tiempo_financiero ORDER BY fecha"
    ).fetchall()
    con.close()

    # La base se pierde entera. Solo queda la zona cruda.
    (tmp_path / "a.duckdb").unlink()

    con2 = duckdb.connect(str(tmp_path / "b.duckdb"))
    db.aplicar_esquema(con2)
    ent = entrada("cmf_indicadores")
    assert ent is not None
    filas = []
    for b in blobs_crudos("cmf_indicadores", tmp_path):
        if b.name == "robots.txt.json.gz":
            continue
        filas.extend(ent.parse(leer_crudo(b)))
    ent.cargar(con2, filas)
    despues = con2.execute(
        "SELECT fecha, serie, valor, source_url, robots_snapshot_sha "
        "FROM dim_tiempo_financiero ORDER BY fecha"
    ).fetchall()
    con2.close()

    assert despues == antes, "la reconstruccion no reprodujo las filas originales"
    assert antes, "la prueba no vale si no habia filas que reconstruir"


def test_el_registro_conoce_las_fuentes_que_tienen_colector() -> None:
    from flujocero.sources.registro import entrada, fuentes_conocidas

    assert "cmf_indicadores" in fuentes_conocidas()
    assert entrada("una_fuente_que_no_existe") is None, "no se inventa un parser"


# ------------------------------------------------------- contra la respuesta REAL (T-909)
#
# Las fixtures de arriba las reconstrui desde la documentacion de la CMF. Estas son los
# bytes exactos que devolvio api.cmfchile.cl el 28-ago-2026 desde una IP chilena.
# Ver tests/fixtures/cmf/PROCEDENCIA.md.

REALES = FIXTURES / "real"


def doc_real(nombre: str) -> RawDoc:
    from flujocero.sources.base import leer_crudo

    return leer_crudo(REALES / nombre)


def test_parsea_la_respuesta_real_de_la_cmf() -> None:
    filas = colector().parse(doc_real("uf_2026-01_2026-08.json.gz"))
    assert len(filas) == 243
    assert all(f.serie == "uf" for f in filas)
    por_fecha = {f.fecha: f.valor for f in filas}
    # Anclas verificables a ojo contra el blob crudo.
    assert por_fecha[date(2026, 1, 1)] == Decimal("39731.79")
    assert por_fecha[date(2026, 8, 29)] == Decimal("40871.14")
    assert por_fecha[date(2026, 8, 31)] == Decimal("40873.77")


def test_la_respuesta_real_no_filtra_la_apikey() -> None:
    """`base.ocultar_secreto` la reemplaza ANTES de persistir, y por eso estas fixtures se
    pueden versionar en un repo publico. Si algun dia deja de hacerlo, este test avisa."""
    for nombre in ("uf_2024-01_2024-12", "uf_2025-01_2025-12", "uf_2026-01_2026-08"):
        meta = (REALES / f"{nombre}.meta.json").read_text(encoding="utf-8")
        assert "apikey=OCULTA" in meta
        d = json.loads(meta)
        assert "apikey=OCULTA" in d["source_url"]


def test_la_uf_real_se_interpola_geometricamente_por_tramo() -> None:
    """El invariante real de la UF, al tercer intento. Los dos primeros los desmintio el dato.

    Escribi primero "la UF nunca baja": **falso**. Entre el 2026-01-10 y el 2026-02-09 cayo
    de 39.759,95 a 39.682,99 (-0,2%), porque el IPC del mes anterior fue negativo.

    Escribi despues "la UF se mueve en tramos lineales": **tambien falso**. Dentro de un
    mismo tramo el monto diario va de 13,22 a 13,35, un +1%.

    Lo que si se cumple: la UF se recalcula el dia 10 de cada mes con el IPC del mes
    anterior y **compone a tasa diaria constante** hasta el 9 del mes siguiente. La razon
    entre dias consecutivos es constante hasta 4e-07, que es el redondeo al centavo.

    Como test es mucho mas fuerte que los dos anteriores: un solo valor con los miles mal
    leidos —`39.759,95` interpretado como 39,75— da una razon de ~1000 en vez de ~1,0003.
    """
    filas = sorted(colector().parse(doc_real("uf_2026-01_2026-08.json.gz")), key=lambda f: f.fecha)
    tramos: dict[tuple[int, int], list[Decimal]] = {}
    for f in filas:
        # El tramo va del 10 de un mes al 9 del siguiente: antes del dia 10 la fila
        # pertenece al tramo que abrio el mes anterior.
        if f.fecha.day >= 10:
            clave = (f.fecha.year, f.fecha.month)
        elif f.fecha.month > 1:
            clave = (f.fecha.year, f.fecha.month - 1)
        else:
            clave = (f.fecha.year - 1, 12)
        tramos.setdefault(clave, []).append(f.valor)

    completos = [v for v in sorted(tramos.items()) if len(v[1]) >= 25]
    assert len(completos) >= 5, f"solo {len(completos)} tramos completos: no prueba nada"
    for clave, valores in completos:
        razones = [b / a for a, b in zip(valores, valores[1:], strict=False)]
        assert max(razones) - min(razones) < Decimal("2e-6"), (
            f"el tramo {clave} no compone a tasa constante: razones entre "
            f"{min(razones)} y {max(razones)}"
        )


def test_la_uf_real_efectivamente_baja_en_un_tramo_y_queda_plana_en_otro() -> None:
    """Contraprueba: sin esto, una serie siempre creciente pasaria el test de arriba sin
    haber ejercitado los dos casos que me desmintieron."""
    por_fecha = {f.fecha: f.valor for f in colector().parse(doc_real("uf_2026-01_2026-08.json.gz"))}
    # IPC negativo: la UF BAJA todos los dias del tramo.
    assert por_fecha[date(2026, 2, 9)] < por_fecha[date(2026, 1, 10)]
    # IPC cero (febrero 2026): la UF queda EXACTAMENTE plana un mes entero.
    assert por_fecha[date(2026, 4, 9)] == por_fecha[date(2026, 3, 10)]


def test_el_selftest_contra_la_respuesta_real_pasa(monkeypatch) -> None:
    from flujocero.sources.base import RobotsVerdict

    monkeypatch.setattr(
        CmfIndicadores,
        "robots_ok",
        lambda self: RobotsVerdict(True, "https://api.cmfchile.cl/robots.txt", "sha"),
    )
    docs = [doc_real(f"uf_{p}.json.gz") for p in ("2024-01_2024-12", "2025-01_2025-12")]
    rep = colector().selftest(muestra_viva=docs)
    assert rep.ok, rep.detalle
    assert rep.checks["forma_verificada"] is True
