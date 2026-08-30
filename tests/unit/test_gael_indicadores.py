"""Tests del colector Gael Cloud — T-908.

Nunca tocan la red: todo corre contra fixtures y contra un transporte HTTP simulado.
Ningun test duerme de verdad: el limitador recibe un reloj y un `dormir` falsos.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import pytest

from flujocero import db
from flujocero.quality import source_contract as gate
from flujocero.sources.base import COLUMNAS_PROCEDENCIA, RawDoc, Scope
from flujocero.sources.gael_indicadores import (
    BASE,
    CUPO_PETICIONES,
    CUPO_VENTANA_S,
    CupoExcedido,
    Discrepancia,
    ErrorDeFuente,
    GaelIndicadores,
    Limitador,
    a_decimal_desambiguada,
    a_fecha,
    cargar_en_duckdb,
    desde_entorno,
)

AHORA = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
UA = "FlujoCero-ResearchBot/1.0 (test)"


def colector(**kw) -> GaelIndicadores:
    return GaelIndicadores(user_agent=UA, **kw)


def doc(cuerpo: object, tmp_path: Path, nombre: str = "uf.json") -> RawDoc:
    ruta = tmp_path / nombre
    contenido = json.dumps(cuerpo).encode("utf-8")
    ruta.write_bytes(contenido)
    return RawDoc(
        source_id="gael_indicadores",
        url="https://api.gael.cloud/general/public/monedas/UF",
        fetched_at=AHORA,
        ruta=ruta,
        contenido=contenido,
        robots_snapshot_sha="sha-de-prueba",
    )


# ------------------------------------------------------- el numero, que es lo peligroso


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        # numero JSON: no hay nada que interpretar
        (40804.5, Decimal("40804.5")),
        (40804, Decimal("40804")),
        # coma y punto juntos: el ultimo separador manda, en cualquiera de los dos ordenes
        ("40.804,25", Decimal("40804.25")),
        ("40,804.25", Decimal("40804.25")),
        ("1.234.567,89", Decimal("1234567.89")),
        # solo coma: la coma es decimal, sin ambiguedad posible
        ("40804,25", Decimal("40804.25")),
    ],
)
def test_lee_los_formatos_sin_ambiguedad(crudo: object, esperado: Decimal) -> None:
    assert a_decimal_desambiguada(crudo, (Decimal("20000"), Decimal("100000"))) == esperado


def test_solo_punto_se_resuelve_por_el_rango_plausible() -> None:
    """`"40.804"` es cuarenta mil ochocientos cuatro en chileno y 40,8 en gringo.

    Solo una de las dos lecturas cae en el rango de la UF, asi que se puede decidir sin
    adivinar. Es exactamente el caso que un parser ingenuo lee mil veces mal.
    """
    rango = (Decimal("20000"), Decimal("100000"))
    assert a_decimal_desambiguada("40.804", rango) == Decimal("40804")


def test_solo_punto_con_decimales_reales_tambien_se_resuelve() -> None:
    rango = (Decimal("20000"), Decimal("100000"))
    # 40804.25 cabe; 4080425 no. Gana la lectura decimal.
    assert a_decimal_desambiguada("40804.25", rango) == Decimal("40804.25")


def test_si_las_dos_lecturas_son_plausibles_se_rechaza() -> None:
    """La regla del §3.2 llevada al parseo: antes que un numero inventado, ninguno.

    Con un rango ancho, `"40.804"` cabe como 40.804 y como 40,804. No hay forma de saber
    cual quiso decir la fuente, asi que no se carga.
    """
    with pytest.raises(ErrorDeFuente, match="dos lecturas"):
        a_decimal_desambiguada("40.804", (Decimal("1"), Decimal("100000")))


def test_sin_rango_un_valor_ambiguo_tambien_se_rechaza() -> None:
    with pytest.raises(ErrorDeFuente, match="dos lecturas"):
        a_decimal_desambiguada("40.804")


def test_un_valor_fuera_de_todo_rango_plausible_es_error() -> None:
    with pytest.raises(ErrorDeFuente, match="no cae en el rango"):
        a_decimal_desambiguada("3.5", (Decimal("20000"), Decimal("100000")))


@pytest.mark.parametrize("basura", ["", "   ", "abc", None, True])
def test_un_valor_ilegible_es_error_no_un_cero(basura: object) -> None:
    """§11: nada de try/except: pass. Un formato que cambia tiene que gritar."""
    with pytest.raises(ErrorDeFuente):
        a_decimal_desambiguada(basura, (Decimal("20000"), Decimal("100000")))


# ------------------------------------------------------- la fecha, que es igual de peligrosa


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("2026-08-29", date(2026, 8, 29)),
        ("2026-08-29T00:00:00", date(2026, 8, 29)),
        ("2026-08-29 00:00:00", date(2026, 8, 29)),
        ("2026-08-29T00:00:00Z", date(2026, 8, 29)),
        # dia > 12: no puede ser un mes, asi que no hay ambiguedad
        ("29-08-2026", date(2026, 8, 29)),
        ("29/08/2026", date(2026, 8, 29)),
    ],
)
def test_lee_las_fechas_no_ambiguas(crudo: str, esperado: date) -> None:
    assert a_fecha(crudo) == esperado


def test_una_fecha_ambigua_se_rechaza_en_vez_de_adivinar() -> None:
    """`05-08-2026` es 5 de agosto en Chile y 8 de mayo en formato gringo.

    Una UF con tres meses de error corrompe toda conversion de pesos a UF de ese dia, y no
    se nota mirando la tabla. Se prefiere fallar fuerte.
    """
    with pytest.raises(ErrorDeFuente, match="ambigua"):
        a_fecha("05-08-2026")


@pytest.mark.parametrize("basura", ["", "ayer", "2026-13-01", "20260829"])
def test_una_fecha_ilegible_es_error(basura: str) -> None:
    with pytest.raises(ErrorDeFuente):
        a_fecha(basura)


# ------------------------------------------------------- el cupo, que es lo que te banea


def test_el_limitador_deja_pasar_hasta_el_cupo_sin_esperar() -> None:
    reloj = {"t": 0.0}
    esperas: list[float] = []
    lim = Limitador(maximo=3, ventana_s=10.0, reloj=lambda: reloj["t"], dormir=esperas.append)
    for _ in range(3):
        assert lim.pedir_turno() == 0.0
    assert esperas == []


def test_el_limitador_frena_la_peticion_que_se_pasa() -> None:
    """Frena ANTES de pedir. El castigo de Gael no es un 429 pasajero: es una hora."""
    reloj = {"t": 0.0}

    def dormir(s: float) -> None:
        reloj["t"] += s  # el reloj falso avanza igual que avanzaria el real

    lim = Limitador(maximo=3, ventana_s=10.0, reloj=lambda: reloj["t"], dormir=dormir)
    for _ in range(3):
        lim.pedir_turno()
    espera = lim.pedir_turno()
    assert espera == pytest.approx(10.0)
    assert reloj["t"] == pytest.approx(10.0)


def test_el_limitador_olvida_las_peticiones_viejas() -> None:
    reloj = {"t": 0.0}
    lim = Limitador(maximo=3, ventana_s=10.0, reloj=lambda: reloj["t"], dormir=lambda s: None)
    for _ in range(3):
        lim.pedir_turno()
    reloj["t"] = 11.0
    assert lim.espera_necesaria() == 0.0


def test_el_cupo_por_defecto_deja_margen_bajo_el_limite_de_gael() -> None:
    """El limite documentado es 9 en 10 s. Pedimos 6 porque no sabemos si el servidor
    cuenta la ventana igual que nosotros, y equivocarse cuesta una hora."""
    assert CUPO_PETICIONES < 9
    assert CUPO_VENTANA_S == 10.0


# ------------------------------------------------------- parseo


CUERPO_UNA_SERIE = {
    "Codigo": "UF",
    "Nombre": "Unidad de Fomento",
    "Valor": "40.804,25",
    "Fecha": "2026-08-29T00:00:00",
}
CUERPO_LISTA = [
    {"Codigo": "DOLAR", "Nombre": "Dolar", "Valor": "950,10", "Fecha": "2026-08-29"},
    {"Codigo": "UF", "Nombre": "Unidad de Fomento", "Valor": "40.804,25", "Fecha": "2026-08-29"},
    {"Codigo": "UTM", "Nombre": "UTM", "Valor": "69.542,00", "Fecha": "2026-08-29"},
]


def test_parsea_una_serie_con_procedencia_completa(tmp_path: Path) -> None:
    filas = colector().parse(doc(CUERPO_UNA_SERIE, tmp_path))
    assert len(filas) == 1
    f = filas[0]
    assert (f.serie, f.valor, f.unidad, f.evidence_level) == ("uf", Decimal("40804.25"), "CLP", "V")
    assert f.fecha == date(2026, 8, 29)
    for col in COLUMNAS_PROCEDENCIA:
        assert getattr(f, col), f"{col} vacio"


def test_del_endpoint_general_toma_solo_las_series_que_usa(tmp_path: Path) -> None:
    """El dolar y el euro no entran al modelo. Se descartan sin ruido; lo que no se
    descarta en silencio es una serie conocida que no se pudo interpretar."""
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    assert sorted(f.serie for f in filas) == ["uf", "utm"]


def test_identifica_la_serie_por_el_cuerpo_no_por_la_url(tmp_path: Path) -> None:
    """Si se pidio UF y Gael devuelve UTM, gana el cuerpo: queremos notarlo."""
    cuerpo = {"Codigo": "UTM", "Valor": "69.542,00", "Fecha": "2026-08-29"}
    filas = colector().parse(doc(cuerpo, tmp_path))  # url dice /UF
    assert [f.serie for f in filas] == ["utm"]


def test_una_respuesta_sin_ninguna_serie_conocida_falla(tmp_path: Path) -> None:
    cuerpo = [{"Codigo": "DOLAR", "Valor": "950,10", "Fecha": "2026-08-29"}]
    with pytest.raises(ErrorDeFuente, match="ninguna serie conocida|ningun registro"):
        colector().parse(doc(cuerpo, tmp_path))


def test_un_campo_de_valor_ausente_falla_en_vez_de_imputar(tmp_path: Path) -> None:
    cuerpo = {"Codigo": "UF", "Fecha": "2026-08-29"}
    with pytest.raises(ErrorDeFuente, match="ningun campo de valor"):
        colector().parse(doc(cuerpo, tmp_path))


def test_codigo_le_gana_a_nombre_sin_considerarlo_ambiguo(tmp_path: Path) -> None:
    """Un registro real trae `Codigo` Y `Nombre`. No son sinonimos ambiguos: hay un orden
    de preferencia obvio. Una version anterior rechazaba una respuesta legible por esto."""
    cuerpo = {
        "Codigo": "UF",
        "Nombre": "Cualquier Cosa",
        "Valor": "40.804,25",
        "Fecha": "2026-08-29",
    }
    assert colector().parse(doc(cuerpo, tmp_path))[0].serie == "uf"


def test_sin_codigo_cae_al_nombre(tmp_path: Path) -> None:
    cuerpo = {"Nombre": "UF", "Valor": "40.804,25", "Fecha": "2026-08-29"}
    assert colector().parse(doc(cuerpo, tmp_path))[0].serie == "uf"


def test_dos_campos_de_valor_en_el_mismo_registro_fallan(tmp_path: Path) -> None:
    """No hay forma de saber cual es el bueno, y elegir mal es silencioso."""
    cuerpo = {"Codigo": "UF", "Valor": "40.804,25", "Value": "1,0", "Fecha": "2026-08-29"}
    with pytest.raises(ErrorDeFuente, match="mas de un campo"):
        colector().parse(doc(cuerpo, tmp_path))


def test_los_nombres_de_campo_no_distinguen_mayusculas(tmp_path: Path) -> None:
    cuerpo = {"codigo": "UF", "valor": "40.804,25", "fecha": "2026-08-29"}
    assert colector().parse(doc(cuerpo, tmp_path))[0].valor == Decimal("40804.25")


def test_una_respuesta_que_no_es_objeto_ni_lista_falla(tmp_path: Path) -> None:
    with pytest.raises(ErrorDeFuente, match="no es objeto ni lista"):
        colector().parse(doc("40804", tmp_path))


def test_las_filas_pasan_el_gate_de_contrato_de_fuente(tmp_path: Path) -> None:
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    assert gate.verificar(colector(), filas).ok


# ------------------------------------------------------- lo que esta fuente NO hace


def test_pedirle_una_serie_historica_falla_con_un_mensaje_claro() -> None:
    """El endpoint publico no toma fechas. Devolver un dia cuando te pidieron treinta es
    peor que no devolver nada: el backfill quedaria con un hoyo que nadie ve."""
    with pytest.raises(ErrorDeFuente, match="no sirve series historicas"):
        list(colector().collect(Scope(desde="2026-01", hasta="2026-08", ahora=AHORA)))


def test_series_desconocidas_se_rechazan_al_construir() -> None:
    with pytest.raises(ValueError, match="series desconocidas"):
        colector(series=("uf", "dolar"))


# ------------------------------------------------------- red simulada


def _transporte(manejador) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(manejador))


def _robots_ok(monkeypatch) -> None:
    from flujocero.sources.base import RobotsVerdict

    monkeypatch.setattr(
        GaelIndicadores,
        "robots_ok",
        lambda self: RobotsVerdict(True, "https://api.gael.cloud/robots.txt", "sha-fake"),
    )


def test_collect_escribe_a_la_zona_cruda_antes_de_parsear(monkeypatch, tmp_path: Path) -> None:
    _robots_ok(monkeypatch)
    pedidas: list[str] = []

    def manejador(req: httpx.Request) -> httpx.Response:
        pedidas.append(str(req.url))
        return httpx.Response(200, json=CUERPO_UNA_SERIE)

    c = colector(
        cliente=_transporte(manejador),
        raiz_cruda=tmp_path,
        limitador=Limitador(dormir=lambda s: None),
    )
    docs = list(c.collect(Scope(ahora=AHORA)))
    assert len(docs) == 2  # uf y utm
    assert all(d.ruta.exists() for d in docs)
    assert pedidas == [
        "https://api.gael.cloud/general/public/monedas/UF",
        "https://api.gael.cloud/general/public/monedas/UTM",
    ]


def test_un_429_no_se_reintenta_nunca(monkeypatch, tmp_path: Path) -> None:
    """Reintentar un baneo lo prolonga. Es la diferencia deliberada con la CMF, donde el
    corte SI es transitorio y SI se reintenta."""
    _robots_ok(monkeypatch)
    intentos = {"n": 0}

    def manejador(req: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        return httpx.Response(429, text="rate limit")

    c = colector(
        cliente=_transporte(manejador),
        raiz_cruda=tmp_path,
        limitador=Limitador(dormir=lambda s: None),
    )
    with pytest.raises(CupoExcedido, match="baneada UNA HORA"):
        list(c.collect(Scope(ahora=AHORA)))
    assert intentos["n"] == 1, "un 429 se pidio mas de una vez: eso alarga el baneo"


def test_sin_robots_no_se_recolecta(monkeypatch, tmp_path: Path) -> None:
    from flujocero.sources.base import RobotsVerdict

    monkeypatch.setattr(
        GaelIndicadores,
        "robots_ok",
        lambda self: RobotsVerdict(False, "u", "", motivo="Disallow: /"),
    )
    c = colector(raiz_cruda=tmp_path)
    with pytest.raises(ErrorDeFuente, match="robots.txt no superada"):
        list(c.collect(Scope(ahora=AHORA)))


# ------------------------------------------------------- carga: el fallback no pisa


def _conexion() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)
    return con


def _fila_cmf(con, fecha: date, serie: str, valor: str) -> None:
    con.execute(
        "INSERT INTO dim_tiempo_financiero VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            fecha,
            serie,
            Decimal(valor),
            "CLP",
            "V",
            "cmf_indicadores",
            "https://api.cmfchile.cl/x",
            AHORA,
            "cmf_indicadores/1.1.0",
            "raw/x",
            "sha",
        ),
    )


def test_rellena_el_hueco_cuando_la_cmf_no_tiene_ese_dia(tmp_path: Path) -> None:
    con = _conexion()
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    rep = cargar_en_duckdb(con, filas)
    assert (rep.insertadas, rep.ya_estaban, rep.discrepancias) == (2, 0, [])
    assert con.execute("SELECT count(*) FROM dim_tiempo_financiero").fetchone()[0] == 2


def test_el_fallback_nunca_pisa_una_fila_de_la_cmf(tmp_path: Path) -> None:
    """Una fuente de respaldo que sobrescribe a la primaria convierte una caida pasajera
    de la CMF en un cambio permanente de los datos, sin que nadie lo pida."""
    con = _conexion()
    _fila_cmf(con, date(2026, 8, 29), "uf", "40804.25")
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    rep = cargar_en_duckdb(con, filas)
    assert rep.insertadas == 1  # solo la utm, que faltaba
    assert rep.ya_estaban == 1
    quedo = con.execute(
        "SELECT valor, source_id FROM dim_tiempo_financiero WHERE serie='uf'"
    ).fetchone()
    assert quedo[1] == "cmf_indicadores", "el fallback piso a la fuente primaria"


def test_dos_fuentes_que_discrepan_lo_reportan_en_vez_de_elegir(tmp_path: Path) -> None:
    """Dos valores oficiales distintos del mismo dia es un hallazgo de calidad de datos,
    no algo que el cargador deba resolver solo."""
    con = _conexion()
    _fila_cmf(con, date(2026, 8, 29), "uf", "40000.00")
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    rep = cargar_en_duckdb(con, filas)
    assert len(rep.discrepancias) == 1
    d = rep.discrepancias[0]
    assert d.serie == "uf"
    assert d.valor_existente == Decimal("40000.00")
    assert d.valor_nuevo == Decimal("40804.25")
    assert "DISCREPANCIAS" in str(rep)


def test_una_brecha_de_redondeo_no_se_reporta_como_discrepancia(tmp_path: Path) -> None:
    """La CMF publica 2 decimales y la columna guarda 6. Eso no es un desacuerdo."""
    con = _conexion()
    _fila_cmf(con, date(2026, 8, 29), "uf", "40804.250001")
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    assert cargar_en_duckdb(con, filas).discrepancias == []


def test_cargar_dos_veces_no_duplica(tmp_path: Path) -> None:
    """§3.6: re-ejecutar el mismo dia no duplica filas."""
    con = _conexion()
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    cargar_en_duckdb(con, filas)
    rep = cargar_en_duckdb(con, filas)
    assert rep.insertadas == 0
    assert con.execute("SELECT count(*) FROM dim_tiempo_financiero").fetchone()[0] == 2


def test_la_brecha_relativa_se_calcula_sin_dividir_por_cero() -> None:
    d = Discrepancia(date(2026, 8, 29), "uf", "cmf_indicadores", Decimal(0), Decimal(1))
    assert d.brecha_rel == Decimal(0)


# ------------------------------------------------------- selftest


def test_el_selftest_sin_muestra_viva_no_finge_haber_visto_la_fuente(tmp_path: Path) -> None:
    """Misma disciplina que el ADR 001: la forma viene de documentacion y se dice."""
    rep = colector().selftest(fixture=doc(CUERPO_LISTA, tmp_path))
    assert rep.ok
    assert rep.checks["forma_verificada"] is False
    assert "no ha sido confirmada" in rep.detalle["forma_verificada"]


def test_el_selftest_marca_forma_verificada_con_muestra_viva(monkeypatch, tmp_path: Path) -> None:
    _robots_ok(monkeypatch)
    rep = colector().selftest(muestra_viva=[doc(CUERPO_LISTA, tmp_path)])
    assert rep.ok
    assert rep.checks["forma_verificada"] is True


def test_el_selftest_detecta_el_parser_roto_por_caida_de_conteo(tmp_path: Path) -> None:
    rep = colector().selftest(fixture=doc(CUERPO_LISTA, tmp_path), n_filas_corrida_anterior=20)
    assert not rep.ok
    assert rep.checks["conteo_estable"] is False


def test_el_selftest_sin_documentos_falla() -> None:
    assert not colector().selftest().ok


def test_el_selftest_rechaza_un_valor_fuera_de_rango(tmp_path: Path) -> None:
    """Una UF de mil pesos no es una UF. El rango se comparte con el modulo de la CMF."""
    cuerpo = {"Codigo": "UF", "Valor": 1000, "Fecha": "2026-08-29"}
    rep = colector().selftest(fixture=doc(cuerpo, tmp_path))
    assert not rep.ok
    assert rep.checks["rangos_plausibles"] is False


# ------------------------------------------------------- construccion


def test_gael_no_pide_credencial() -> None:
    """A diferencia de la CMF, aca no hay apikey que falte: la fuente es abierta."""
    c = desde_entorno({})
    assert c.user_agent == "FlujoCero-ResearchBot/1.0"


def test_toma_el_user_agent_del_entorno() -> None:
    assert desde_entorno({"USER_AGENT": "X/2.0"}).user_agent == "X/2.0"


# ------------------------------------------------------- reconstruccion


def test_la_fuente_primaria_gana_venga_en_el_orden_que_venga(tmp_path: Path) -> None:
    """`make rebuild` recorre la zona cruda sin garantizar orden entre fuentes.

    Gael inserta solo si falta y la CMF hace `DO UPDATE`, asi que el resultado es el mismo
    en los dos ordenes. Sin esta propiedad, reconstruir dos veces podria dar bases
    distintas segun como el sistema de archivos listara las carpetas.
    """
    from flujocero.sources.cmf_indicadores import Indicador as IndicadorCmf
    from flujocero.sources.cmf_indicadores import cargar_en_duckdb as cargar_cmf

    def fila_cmf() -> IndicadorCmf:
        return IndicadorCmf(
            fecha=date(2026, 8, 29),
            serie="uf",
            valor=Decimal("40000.00"),
            unidad="CLP",
            evidence_level="V",
            source_id="cmf_indicadores",
            source_url="https://api.cmfchile.cl/x",
            fetched_at=AHORA,
            parser_version="cmf_indicadores/1.1.0",
            raw_blob_path="raw/x",
            robots_snapshot_sha="sha",
        )

    filas_gael = colector().parse(doc(CUERPO_LISTA, tmp_path))

    resultados = []
    for gael_primero in (True, False):
        con = _conexion()
        if gael_primero:
            cargar_en_duckdb(con, filas_gael)
            cargar_cmf(con, [fila_cmf()])
        else:
            cargar_cmf(con, [fila_cmf()])
            cargar_en_duckdb(con, filas_gael)
        resultados.append(
            con.execute(
                "SELECT valor, source_id FROM dim_tiempo_financiero WHERE serie='uf'"
            ).fetchone()
        )
        con.close()

    assert resultados[0] == resultados[1], "el orden de reconstruccion cambia la base"
    assert resultados[0][1] == "cmf_indicadores"


def test_el_registro_sabe_reconstruir_gael() -> None:
    """Un source_id sin entrada en el registro no se reconstruye desde la zona cruda."""
    from flujocero.sources import registro

    ent = registro.entrada("gael_indicadores")
    assert ent is not None
    assert ent.tabla == "dim_tiempo_financiero"


def test_el_registro_cuenta_solo_las_filas_que_de_verdad_inserto(tmp_path: Path) -> None:
    from flujocero.sources import registro

    con = _conexion()
    _fila_cmf(con, date(2026, 8, 29), "uf", "40804.25")
    ent = registro.entrada("gael_indicadores")
    assert ent is not None
    filas = colector().parse(doc(CUERPO_LISTA, tmp_path))
    assert ent.cargar(con, filas) == 1  # la uf ya estaba; solo entra la utm


# ------------------------------------------------------- hallazgos de la auto-critica §7.6


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("1.234.567", Decimal("1234567")),
        ("40.804.500", Decimal("40804500")),
    ],
)
def test_mas_de_un_punto_no_es_ambiguo(crudo: str, esperado: Decimal) -> None:
    """Ningun formato usa el punto como decimal dos veces.

    Lo encontro la auto-critica del §7.6: la version anterior calculaba las dos lecturas
    siempre, y `Decimal("1.234.567")` reventaba. Un valor perfectamente legible se
    rechazaba porque la lectura "decimal" ni siquiera existe.
    """
    assert a_decimal_desambiguada(crudo, (Decimal("1"), Decimal("99999999"))) == esperado


def test_la_consulta_de_robots_tambien_gasta_cupo(monkeypatch) -> None:
    """El servidor de Gael cuenta TODOS los GET, incluido el del robots.txt.

    Un contador que ignora una de cada tres peticiones no es un contador, y aca
    equivocarse cuesta una hora de baneo.
    """
    from flujocero.sources import robots_check
    from flujocero.sources.base import RobotsVerdict

    monkeypatch.setattr(robots_check, "verificar", lambda *a, **k: RobotsVerdict(True, "u", "sha"))
    turnos = {"n": 0}

    class LimitadorContador(Limitador):
        def pedir_turno(self) -> float:
            turnos["n"] += 1
            return 0.0

    c = colector(limitador=LimitadorContador(dormir=lambda s: None))
    c.robots_ok()
    assert turnos["n"] == 1, "la peticion de robots.txt no paso por el limitador"


def test_una_fila_invalida_no_revienta_el_parseo_con_traceback(tmp_path: Path) -> None:
    """Un `evidence_level` invalido levanta `ValidationError` de pydantic, que hereda de
    `ValueError` y NO de `ErrorDeFuente`. La CLI tiene que atrapar las dos familias o el
    fallback muere con un traceback justo cuando es lo unico que queda funcionando."""
    from pydantic import ValidationError

    from flujocero.sources.gael_indicadores import Indicador

    with pytest.raises(ValidationError) as exc:
        Indicador(
            fecha=date(2026, 8, 29),
            serie="uf",
            valor=Decimal(1),
            unidad="CLP",
            evidence_level="X",
            source_id="gael_indicadores",
            source_url="u",
            fetched_at=AHORA,
            parser_version="p",
            raw_blob_path="r",
            robots_snapshot_sha="s",
        )
    assert isinstance(exc.value, ValueError)


# ------------------------------------------------------- contra la respuesta REAL
#
# Todo lo de arriba corre contra una fixture que reconstrui desde documentacion. Lo de aca
# corre contra los bytes exactos que devolvio api.gael.cloud el 30-ago-2026 02:56 UTC desde
# una IP chilena residencial. Ver tests/fixtures/gael/PROCEDENCIA.md.

REALES = Path(__file__).resolve().parents[1] / "fixtures" / "gael" / "real"
REALES_CMF = Path(__file__).resolve().parents[1] / "fixtures" / "cmf" / "real"


def doc_real(nombre: str) -> RawDoc:
    from flujocero.sources.base import leer_crudo

    return leer_crudo(REALES / nombre)


def test_parsea_la_respuesta_real_de_la_uf() -> None:
    filas = colector().parse(doc_real("uf_vigente.json.gz"))
    assert len(filas) == 1
    f = filas[0]
    assert f.serie == "uf"
    assert f.valor == Decimal("40871.14")
    assert f.unidad == "CLP"
    for col in COLUMNAS_PROCEDENCIA:
        assert getattr(f, col), f"{col} vacio"


def test_parsea_la_respuesta_real_de_la_utm() -> None:
    filas = colector().parse(doc_real("utm_vigente.json.gz"))
    assert [(f.serie, f.valor) for f in filas] == [("utm", Decimal("68647.00"))]


def test_la_marca_de_tiempo_real_de_gael_no_corre_la_fecha_un_dia() -> None:
    """Gael fecha el valor `2026-08-29T22:00:03.403Z` — la hora de su refresco diario, no
    una fecha de calendario limpia.

    Si esa marca correspondiera al dia siguiente, TODA conversion de pesos a UF quedaria
    corrida en un dia y no se notaria mirando la tabla. El test siguiente prueba contra la
    CMF que no lo esta; este fija la lectura de la marca.
    """
    assert colector().parse(doc_real("uf_vigente.json.gz"))[0].fecha == date(2026, 8, 29)


def test_las_dos_fuentes_reales_coinciden_al_peso() -> None:
    """El hallazgo del 30-ago-2026, convertido en test.

    Dos fuentes oficiales independientes —la CMF, que es el organismo que publica la UF, y
    Gael, que es un intermediario— dan el MISMO valor para el mismo dia. Que ambas esten
    mal igual es mucho menos probable que una sola este mal, asi que esto es evidencia
    externa sobre el numero del que depende todo lo demas del modelo.

    Ademas cruza dos formatos numericos distintos: la CMF manda `"40.871,14"` (punto de
    miles + coma decimal) y Gael manda `"40871,14"` (solo coma). Pasan por ramas distintas
    del parser y tienen que llegar al mismo Decimal.
    """
    from flujocero.sources.base import leer_crudo
    from flujocero.sources.cmf_indicadores import CmfIndicadores

    del_gael = colector().parse(doc_real("uf_vigente.json.gz"))[0]

    cmf = CmfIndicadores(apikey="no-se-usa-al-parsear", user_agent="test")
    de_la_cmf = {
        f.fecha: f.valor for f in cmf.parse(leer_crudo(REALES_CMF / "uf_2026-01_2026-08.json.gz"))
    }

    assert del_gael.fecha in de_la_cmf, (
        f"la CMF no tiene el dia {del_gael.fecha} que Gael dice tener: eso seria una senal "
        "de que las dos fuentes fechan distinto el mismo valor"
    )
    assert de_la_cmf[del_gael.fecha] == del_gael.valor


def test_el_selftest_contra_la_respuesta_real_pasa(monkeypatch) -> None:
    _robots_ok(monkeypatch)
    docs = [doc_real("uf_vigente.json.gz"), doc_real("utm_vigente.json.gz")]
    rep = colector().selftest(muestra_viva=docs)
    assert rep.ok, rep.detalle
    assert rep.checks["forma_verificada"] is True
    assert rep.n_filas == 2


def test_el_robots_real_de_gael_permite_el_endpoint_publico() -> None:
    """El archivo real trae una directiva MALFORMADA: `Allow /general/public/*`, sin los dos
    puntos. El RFC 9309 manda ignorar la linea malformada, asi que el permiso NO viene de
    ese `Allow` sino de que ningun `Disallow:` cubre /general/public/monedas.

    Se fija con un test porque el dia que Gael arregle el typo el resultado no debe cambiar,
    y porque alguien que lea el archivo a ojo puede creer que dependemos de esa linea.
    """
    import gzip

    from flujocero.sources.robots_check import _veredicto_desde_cuerpo

    crudo = gzip.open(REALES / "robots.txt.json.gz", "rb").read()
    texto = crudo.decode("utf-8")
    assert "Allow /general/public/*" in texto, "cambio el robots real; revisa el veredicto"
    assert not [ln for ln in texto.splitlines() if ln.strip().lower().startswith("allow:")], (
        "ahora SI hay un Allow bien formado: el permiso puede venir de ahi y no solo de "
        "los Disallow. Revisa el razonamiento de este test."
    )
    v = _veredicto_desde_cuerpo(crudo, f"{BASE}/UF", UA, "https://api.gael.cloud/robots.txt", "")
    assert v.allowed, v.motivo


def test_el_robots_real_de_gael_si_prohibe_lo_que_dice_prohibir() -> None:
    """Contraprueba del test anterior: si el parser diera `allowed` para TODO, el test de
    arriba pasaria sin probar nada. Las rutas que Gael prohibe tienen que salir prohibidas."""
    import gzip

    from flujocero.sources.robots_check import _veredicto_desde_cuerpo

    crudo = gzip.open(REALES / "robots.txt.json.gz", "rb").read()
    for prohibida in ("/admin/x", "/general/auth/x", "/general/endpoints/x", "/mobileapp/x"):
        v = _veredicto_desde_cuerpo(crudo, f"https://api.gael.cloud{prohibida}", UA, "u", "")
        assert not v.allowed, f"{prohibida} deberia estar prohibida y salio permitida"
