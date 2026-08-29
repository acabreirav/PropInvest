"""Tests del colector del legado — T-918. Nunca tocan la red ni la carpeta del usuario."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from flujocero.sources import portal_legado as pl
from flujocero.sources.base import leer_crudo

AHORA = datetime(2026, 5, 4, tzinfo=UTC)


def ficha(
    operacion: str = "venta",
    simbolo: str = "UF",
    monto: str = "3.500",
    crumbs: tuple[str, ...] = (
        "Departamentos",
        "Venta",
        "Propiedades usadas",
        "RM (Metropolitana)",
        "San Miguel",
        "El Llano",
    ),
    hrefs: str = "/venta/departamento/propiedades-usadas/san-miguel-metropolitana",
    specs: tuple[tuple[str, str], ...] = (
        ("Superficie útil", "58 m²"),
        ("Dormitorios", "2"),
        ("Baños", "2"),
    ),
    canonical: str = "https://www.portalinmobiliario.com/MLC-123-depto",
    relleno: int = 120_000,
) -> str:
    items = "".join(
        f'<li class="andes-breadcrumb__item"><a href="{hrefs}">{c}</a></li>' for c in crumbs
    )
    filas = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in specs)
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>'
        f'<ol class="andes-breadcrumb">{items}</ol>'
        f'<span class="andes-money-amount__currency-symbol">{simbolo}</span>'
        f'<span class="andes-money-amount__fraction">{monto}</span>'
        f'<table class="andes-table">{filas}</table>'
        f"<!--{'x' * relleno}--></body></html>"
    )


def parsear(html: str, url: str = "https://www.portalinmobiliario.com/MLC-123") -> pl.Aviso | None:
    return pl.parse_html(html, url, AHORA, "blob", "sha")


# --------------------------------------------------------------- anonimizacion (§3.4)


@pytest.mark.parametrize(
    "entrada,debe_borrar",
    [
        (b"escribe a corredor@inmobiliaria.cl hoy", True),
        (b'<a href="https://wa.me/56984499135?text=Hola">wsp</a>', True),
        (b'<a href="tel:+56223334444">llamar</a>', True),
        (b"llama al +56 9 8370 2878", True),
    ],
)
def test_borra_todo_dato_de_contacto(entrada: bytes, debe_borrar: bool) -> None:
    limpio, n = pl.anonimizar(entrada)
    assert (n > 0) == debe_borrar
    assert b"@inmobiliaria" not in limpio
    assert b"56984499135" not in limpio


@pytest.mark.parametrize(
    "dato",
    [
        b"precio UF 3.500",
        b"avaluo $40.804.000",
        b"MLC-1859051633_20260504.html",
        b"fetched_at 2026-05-04T00:00:00+00:00",
        b"superficie 58 m2, 12345678 visitas",
    ],
)
def test_no_toca_precios_ids_ni_fechas(dato: bytes) -> None:
    """La frontera que importa. Un regex generico de telefono de ocho digitos se come
    `20260504` y `1859051633`: corrompe la fecha del blob y el ID de MercadoLibre, en
    silencio. Se prefiere dejar pasar un telefono sin marca antes que eso."""
    limpio, n = pl.anonimizar(dato)
    assert limpio == dato and n == 0


# ------------------------------------------------------------------- numeros chilenos


@pytest.mark.parametrize(
    "texto,esperado",
    [("3.500", D(3500)), ("40.804", D(40804)), ("3.500,5", D("3500.5")), ("58 m²", D(58))],
)
def test_el_punto_es_siempre_separador_de_miles(texto: str, esperado: D) -> None:
    assert pl.a_decimal(texto) == esperado


@pytest.mark.parametrize("rango", ["35 - 61 m²", "1 a 2 dormitorios", "2.500 a 3.100"])
def test_un_rango_es_ND_y_no_un_numero_pegado(rango: str) -> None:
    """`"35 - 61 m²"` salia **3561 m²** al borrar los no-digitos y pegar lo que quedaba.
    Un depto de 3.561 m2 no lo pilla nadie en un ranking, y contamina la mediana de su
    microzona para siempre. El §3.2 pide ND ante la duda, no un numero inventado."""
    assert pl.a_decimal(rango) is None
    assert pl.a_entero(rango) is None


# --------------------------------------------------------------------------- parseo


def test_parsea_una_ficha_completa() -> None:
    a = parsear(ficha())
    assert a is not None
    assert (a.operacion, a.moneda, a.monto) == ("venta", "UF", D(3500))
    assert a.precio_uf == D(3500) and a.arriendo_clp is None
    assert a.comuna_id == "san-miguel"
    assert a.microzona_id == "san-miguel/el-llano"
    assert a.es_vivienda_nueva is False
    assert a.tipologia == "2D2B"


def test_el_breadcrumb_colapsado_se_resuelve_por_los_href() -> None:
    """El portal colapsa el texto a "..." en rutas largas, pero los href quedan enteros.
    Sobre 600 fichas reales, 109 tenian el texto colapsado y los 109 href lo resolvieron."""
    a = parsear(ficha(crumbs=("...", "...", "RM (Metropolitana)", "Ñuñoa", "Plaza Egaña")))
    assert a is not None and a.operacion == "venta"
    assert a.es_vivienda_nueva is False, "el href dice propiedades-usadas"


def test_no_se_lee_la_operacion_del_titulo() -> None:
    """Un aviso de VENTA que diga "ideal para arriendo" no puede clasificarse como arriendo.
    Por eso se leen los href del breadcrumb y nunca el slug del titulo."""
    html = ficha(canonical="https://www.portalinmobiliario.com/MLC-123-venta-ideal-arriendo")
    a = parsear(html)
    assert a is not None and a.operacion == "venta"


def test_el_canonical_de_proyecto_no_descarta_la_ficha() -> None:
    """Cuando el canonical apunta al proyecto y no al MLC, es un aviso de PROYECTO, no un
    redirect roto. La primera version lo trataba como error y botaba el 47% del corpus."""
    a = parsear(
        ficha(
            canonical="https://www.portalinmobiliario.com/venta/departamento/nunoa-metropolitana/10628-nva",
            crumbs=(
                "Departamentos",
                "Venta",
                "Proyectos",
                "RM (Metropolitana)",
                "Ñuñoa",
                "Metro Ñuñoa",
            ),
            hrefs="/venta/departamento/proyectos/nunoa-metropolitana",
        )
    )
    assert a is not None
    assert a.es_vivienda_nueva is True
    assert a.url.endswith("10628-nva"), "source_url es la URL real del portal, no una armada"


def test_un_arriendo_publicado_en_UF_no_se_descarta() -> None:
    """La moneda no determina la operacion. Un arriendo de UF 15 caia por "bajo el minimo
    de UF 500" cuando el rango se elegia solo por moneda: 132 de 600 fichas perdidas."""
    a = parsear(
        ficha(
            operacion="arriendo",
            simbolo="UF",
            monto="15",
            crumbs=("Departamentos", "Arriendo", "RM (Metropolitana)", "Macul", "Villa Macul"),
            hrefs="/arriendo/departamento/propiedades-usadas/macul-metropolitana",
        )
    )
    assert a is not None
    assert a.arriendo_uf == D(15) and a.arriendo_clp is None and a.precio_uf is None


def test_un_html_chico_no_es_una_ficha() -> None:
    assert parsear(ficha(relleno=10)) is None


def test_una_venta_fuera_de_rango_se_descarta_entera() -> None:
    """Fuera de rango no se corrige el valor: se cae la fila. Un precio absurdo silenciado
    es peor que una fila menos."""
    assert parsear(ficha(monto="99.999")) is None


# ------------------------------------------------------------------------ zona cruda


def test_el_fetched_at_sale_del_nombre_no_del_reloj() -> None:
    """Poner now() disfrazaria de fresco un dato de mayo, y el gate de frescura del §7.3
    dejaria de protegernos justo cuando mas hace falta."""
    assert pl.fecha_del_nombre("MLC-123_20260504.html") == datetime(2026, 5, 4, tzinfo=UTC)
    assert pl.fecha_del_nombre("sin-fecha.html") is None


def test_collect_anonimiza_antes_de_escribir(tmp_path: Path) -> None:
    """§3.4 vs §3.6: persistir el dato personal y limpiarlo despues ya seria haberlo
    persistido. La Ley 21.719 no distingue "guardado" de "guardado un rato"."""
    origen = tmp_path / "origen"
    origen.mkdir()
    sucio = ficha().replace("</body>", "contacto: corredor@ejemplo.cl</body>")
    (origen / "MLC-123_20260504.html").write_text(sucio, encoding="utf-8")

    col = pl.PortalLegado(origen=origen, raiz_cruda=tmp_path / "raw")
    docs = col.collect()
    assert len(docs) == 1

    guardado = gzip.open(docs[0].ruta, "rb").read()
    assert b"corredor@ejemplo.cl" not in guardado
    assert b"[correo-removido]" in guardado
    assert docs[0].fetched_at == datetime(2026, 5, 4, tzinfo=UTC)


def test_el_ciclo_completo_reconstruye_desde_la_zona_cruda(tmp_path: Path) -> None:
    """§3.6: toda tabla analitica debe poder reconstruirse desde `data/raw/`."""
    origen = tmp_path / "origen"
    origen.mkdir()
    (origen / "MLC-123_20260504.html").write_text(ficha(), encoding="utf-8")
    col = pl.PortalLegado(origen=origen, raiz_cruda=tmp_path / "raw")
    docs = col.collect()

    avisos = col.parse(leer_crudo(docs[0].ruta))
    assert len(avisos) == 1
    assert avisos[0].precio_uf == D(3500)
    assert avisos[0].fetched_at == datetime(2026, 5, 4, tzinfo=UTC)


def test_declara_su_tier_real_y_cita_la_aprobacion() -> None:
    """Maquillar el legal_tier para que el gate pase seria peor que el scraping mismo."""
    col = pl.PortalLegado(origen=Path("/no/existe"))
    assert col.legal_tier == "html_prohibido"
    v = col.robots_ok()
    assert "D-016" in v.motivo and "D-016" in v.snapshot_sha


# ---------------------------------------------------------------------------- carga


def test_carga_idempotente_y_con_las_seis_columnas(tmp_path: Path) -> None:
    import duckdb

    from flujocero import db

    origen = tmp_path / "origen"
    origen.mkdir()
    (origen / "MLC-123_20260504.html").write_text(ficha(), encoding="utf-8")
    (origen / "MLC-456_20260504.html").write_text(
        ficha(
            operacion="arriendo",
            simbolo="$",
            monto="450.000",
            crumbs=("Departamentos", "Arriendo", "RM (Metropolitana)", "Macul", "Villa Macul"),
            hrefs="/arriendo/departamento/propiedades-usadas/macul-metropolitana",
            canonical="https://www.portalinmobiliario.com/MLC-456-depto",
        ),
        encoding="utf-8",
    )
    col = pl.PortalLegado(origen=origen, raiz_cruda=tmp_path / "raw")
    avisos = [a for d in col.collect() for a in col.parse(leer_crudo(d.ruta))]
    assert len(avisos) == 2

    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)  # el mismo DDL que usa `crear()`
    pl.cargar_en_duckdb(con, avisos)
    pl.cargar_en_duckdb(con, avisos)  # §3.6: re-ejecutar no duplica

    assert con.execute("SELECT count(*) FROM fact_arriendo_comp").fetchone()[0] == 1
    faltantes = con.execute(
        "SELECT count(*) FROM fact_arriendo_comp WHERE source_id IS NULL OR source_url IS NULL "
        "OR fetched_at IS NULL OR parser_version IS NULL OR raw_blob_path IS NULL "
        "OR robots_snapshot_sha IS NULL"
    ).fetchone()[0]
    assert faltantes == 0, "§3.1: sin las seis columnas la fila no se inserta"
    assert con.execute("SELECT count(*) FROM dim_microzona").fetchone()[0] == 2
    con.close()


# ------------------------------------------------------- URL con dato personal y SCD tipo 2


def test_la_url_tambien_se_limpia_porque_el_vendedor_escribe_el_titulo() -> None:
    """Caso real del corpus: `.../MLC-3872504748-arriendo-...-metro-992401813-dueno-_JM`.
    Ese numero es el celular del propietario, y `source_url` es una de las seis columnas de
    procedencia: se guarda tal cual y el telefono viaja con ella. Anonimizar solo el HTML
    no alcanzaba."""
    sucia = "https://www.portalinmobiliario.com/MLC-3872504748-arriendo-metro-992401813-dueno-_JM"
    assert pl.url_segura(sucia, "MLC-3872504748") == (
        "https://www.portalinmobiliario.com/MLC-3872504748"
    )


def test_una_url_limpia_conserva_su_slug() -> None:
    """Recortar siempre perderia el titulo sin ninguna razon. Solo se recorta si hace falta."""
    limpia = "https://www.portalinmobiliario.com/MLC-1505292465-depto-parque-arauco-_JM"
    assert pl.url_segura(limpia, "MLC-1505292465") == limpia


def test_el_mismo_aviso_en_dos_fechas_genera_versiones_no_duplicados(tmp_path: Path) -> None:
    """El corpus tiene el mismo MLC capturado el 4 y el 5 de mayo. §11: SCD tipo 2."""
    import duckdb

    from flujocero import db

    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)

    def aviso(fecha: datetime, precio: str) -> pl.Aviso:
        return pl.Aviso(
            portal_id="MLC-1",
            operacion="venta",
            url="https://x/MLC-1",
            fetched_at=fecha,
            comuna_id="san-miguel",
            comuna_nombre="San Miguel",
            microzona_id="san-miguel/el-llano",
            microzona_nombre="San Miguel - El Llano",
            monto=D(precio),
            moneda="UF",
            m2_utiles=D(58),
            dormitorios=2,
            banos=2,
            antiguedad_anios=10,
            gastos_comunes_clp=None,
            estacionamientos=0,
            bodegas=0,
            es_vivienda_nueva=False,
            es_proyecto=False,
            raw_blob_path="b",
            robots_snapshot_sha="s",
        )

    d4 = datetime(2026, 5, 4, tzinfo=UTC)
    d5 = datetime(2026, 5, 5, tzinfo=UTC)

    pl.cargar_en_duckdb(con, [aviso(d4, "3500")])
    pl.cargar_en_duckdb(con, [aviso(d4, "3500")])  # re-ejecutar el mismo dia no duplica
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1

    pl.cargar_en_duckdb(con, [aviso(d5, "3500")])  # sin cambio de precio: sigue una version
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1

    pl.cargar_en_duckdb(con, [aviso(d5, "3300")])  # BAJO el precio: nueva version
    filas = con.execute(
        "SELECT precio_uf, valid_from, valid_to FROM fact_unidad_venta ORDER BY valid_from"
    ).fetchall()
    assert len(filas) == 2, "la version vieja se conserva; es la senal de compra"
    assert filas[0][0] == D("3500.00") and filas[0][2] == d5, "la vieja quedo cerrada"
    assert filas[1][0] == D("3300.00") and filas[1][2] is None, "la nueva es la vigente"
    con.close()


def test_una_captura_mas_vieja_no_reescribe_el_presente(tmp_path: Path) -> None:
    """Los archivos se recorren ordenados por ID, no por fecha: puede llegar una captura
    del dia 4 despues de haber cargado la del 5. No debe pisar la version vigente."""
    import duckdb

    from flujocero import db

    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)

    def aviso(fecha: datetime, precio: str) -> pl.Aviso:
        return pl.Aviso(
            portal_id="MLC-2",
            operacion="venta",
            url="https://x/MLC-2",
            fetched_at=fecha,
            comuna_id="macul",
            comuna_nombre="Macul",
            microzona_id="macul/villa-macul",
            microzona_nombre="Macul - Villa Macul",
            monto=D(precio),
            moneda="UF",
            m2_utiles=D(50),
            dormitorios=2,
            banos=1,
            antiguedad_anios=5,
            gastos_comunes_clp=None,
            estacionamientos=0,
            bodegas=0,
            es_vivienda_nueva=False,
            es_proyecto=False,
            raw_blob_path="b",
            robots_snapshot_sha="s",
        )

    pl.cargar_en_duckdb(con, [aviso(datetime(2026, 5, 5, tzinfo=UTC), "3000")])
    pl.cargar_en_duckdb(con, [aviso(datetime(2026, 5, 4, tzinfo=UTC), "9999")])
    vigente = con.execute(
        "SELECT precio_uf FROM fact_unidad_venta WHERE valid_to IS NULL"
    ).fetchone()
    assert vigente[0] == D("3000.00")
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1
    con.close()


def test_el_precio_desde_de_un_proyecto_no_es_evidencia_V(tmp_path: Path) -> None:
    """§B1: se necesita el precio REAL por unidad. Un "desde UF X" se marca `E`, y el §12
    ya excluye del ranking todo precio estimado: la regla existente hace el trabajo."""
    import duckdb

    from flujocero import db

    con = duckdb.connect(":memory:")
    db.aplicar_esquema(con)
    base = dict(
        operacion="venta",
        url="https://x",
        fetched_at=datetime(2026, 5, 4, tzinfo=UTC),
        comuna_id="nunoa",
        comuna_nombre="Ñuñoa",
        microzona_id="nunoa/plaza-egana",
        microzona_nombre="Ñuñoa - Plaza Egaña",
        monto=D(3500),
        moneda="UF",
        m2_utiles=None,
        dormitorios=None,
        banos=None,
        antiguedad_anios=None,
        gastos_comunes_clp=None,
        estacionamientos=0,
        bodegas=0,
        es_vivienda_nueva=True,
        raw_blob_path="b",
        robots_snapshot_sha="s",
    )
    pl.cargar_en_duckdb(
        con,
        [
            pl.Aviso(portal_id="MLC-P", es_proyecto=True, **base),
            pl.Aviso(portal_id="MLC-U", es_proyecto=False, **base),
        ],
    )
    niveles = dict(
        con.execute("SELECT unidad_key, evidence_level FROM fact_unidad_venta").fetchall()
    )
    assert niveles == {"MLC-P": "E", "MLC-U": "V"}
    con.close()
