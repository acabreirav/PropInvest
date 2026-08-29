"""Tests del colector vivo — T-920. Nunca tocan la red."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from flujocero.sources import portal_busqueda as pb

AHORA = datetime(2026, 8, 29, tzinfo=UTC)
UA = "FlujoCero-ResearchBot/1.0 (test)"
ROBOTS_OK = "User-agent: *\nDisallow: /propiedades/\nAllow: /*_Desde_\n"


def tarjeta_html(
    mlc: str = "MLC-1",
    precio: str = "UF3.200",
    atributos: tuple[str, ...] = ("2 dormitorios", "2 baños", "58 m² útiles"),
    ubicacion: str = "Milán 1242, El Llano, San Miguel",
    titulo: str = "Depto luminoso",
    extra: str = "",
) -> str:
    lis = "".join(f"<li>{a}</li>" for a in atributos)
    return (
        f'<div class="poly-card">'
        f'<a class="poly-component__title" href="https://portalinmobiliario.com/{mlc}-x-_JM#tr">{titulo}</a>'
        f'<span class="poly-price__current">{precio}</span>'
        f'<ul class="poly-attributes_list">{lis}</ul>'
        f'<span class="poly-component__location">{ubicacion}</span>{extra}</div>'
    )


def parsear(
    html: str,
    url: str = "https://x/venta/departamento/propiedades-usadas/a_Desde_1",
    op: str = "venta",
) -> list[pb.Tarjeta]:
    return pb.parse_busqueda(html, url, op, AHORA, "blob", "sha")


# ------------------------------------------------------------------- la ruta permitida


def test_la_pagina_1_tambien_se_pide_con_Desde() -> None:
    """El portal la sirve sin sufijo, pero esa forma no calza con `/*_Desde_`, que es lo
    unico que el robots.txt permite. `_Desde_1` devuelve lo mismo y queda dentro de la regla:
    elegir la URL permitida cuando existe una equivalente no cuesta nada."""
    for pagina in (1, 2, 3):
        u = pb.url_busqueda("venta", "san-miguel", pb.offset_de_pagina(pagina))
        assert "_Desde_" in u
    assert pb.url_busqueda("venta", "x", pb.offset_de_pagina(1)).endswith("_Desde_1")
    assert pb.url_busqueda("venta", "x", pb.offset_de_pagina(2)).endswith("_Desde_49")


def test_nunca_construye_una_ruta_de_ficha() -> None:
    """`/propiedades/` y las fichas `/MLC-` son lo que el robots.txt bloquea."""
    u = pb.url_busqueda("arriendo", "nunoa", 49, "usadas")
    assert "/propiedades/" not in u and "MLC-" not in u
    assert "/arriendo/departamento/propiedades-usadas/" in u


@pytest.mark.parametrize("mala", ["comprar", "", "VENTA"])
def test_una_operacion_invalida_no_arma_una_url_rara(mala: str) -> None:
    with pytest.raises(ValueError):
        pb.url_busqueda(mala, "nunoa", 1)


# ------------------------------------------------------------------------- la identidad


def test_rechaza_un_user_agent_de_navegador() -> None:
    """El scraper anterior usaba un UA de Chrome falso. D-016 es explicita: la aprobacion
    cubre recolectar, no esquivar. Lo que se arriesgaba no era una IP: era la cuenta."""
    with pytest.raises(ValueError, match="User-Agent"):
        pb.PortalBusqueda(user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/124.0.0.0")


def test_no_recolecta_si_robots_no_permite() -> None:
    """§3.5: `robots_check` pasa ANTES de recolectar, no despues."""

    def manejar(req: httpx.Request) -> httpx.Response:
        if "robots.txt" in str(req.url):
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        raise AssertionError("no debe pedir la pagina si robots dijo que no")

    col = pb.PortalBusqueda(UA, httpx.Client(transport=httpx.MockTransport(manejar)), pausa=(0, 0))
    with pytest.raises(pb.ErrorDeFuente, match="robots"):
        col.collect(comunas=["nunoa"], operaciones=("venta",), max_paginas=1, ahora=AHORA)


def test_un_403_no_se_reintenta_disfrazado() -> None:
    """Si el portal rechaza a un cliente honesto, se acata y se dice. El §3.5 ya explica que
    necesitar disfraz es senal de estar en la categoria equivocada."""

    def manejar(req: httpx.Request) -> httpx.Response:
        if "robots.txt" in str(req.url):
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(403)

    col = pb.PortalBusqueda(UA, httpx.Client(transport=httpx.MockTransport(manejar)), pausa=(0, 0))
    with pytest.raises(pb.Bloqueado, match="403"):
        col.collect(comunas=["nunoa"], operaciones=("venta",), max_paginas=1, ahora=AHORA)


# ---------------------------------------------------------------------------- el parseo


def test_parsea_una_tarjeta_de_unidad() -> None:
    t = parsear(tarjeta_html())[0]
    assert t.portal_id == "MLC-1"
    assert (t.monto, t.moneda) == (D(3200), "UF")
    assert (t.dormitorios, t.banos, t.m2_utiles) == (2, 2, D(58))
    assert t.microzona_id == "san-miguel/el-llano"
    assert t.tipologia == "2D2B"
    assert t.es_vivienda_nueva is False, "la RUTA dice propiedades-usadas"
    assert not t.es_proyecto


def test_la_comuna_se_lee_desde_el_final_porque_la_direccion_trae_comas() -> None:
    """`'Profesor Rodolfo Lenz, 300 - 600, Plaza Ñuñoa, Ñuñoa'`: contar desde el principio
    daria "300 - 600" como comuna."""
    t = parsear(tarjeta_html(ubicacion="Profesor Rodolfo Lenz, 300 - 600, Plaza Ñuñoa, Ñuñoa"))[0]
    assert t.comuna_nombre == "Ñuñoa" and t.barrio == "Plaza Ñuñoa"


def test_un_proyecto_se_marca_y_sus_rangos_quedan_en_ND() -> None:
    """§B1: se necesita el precio REAL por unidad. Un "Desde" no lo es, y `1 a 2 dormitorios`
    no es un dato: `a_entero` devuelve ND antes que inventar un numero."""
    html = tarjeta_html(
        precio="Desde UF2.680",
        atributos=("1 a 2 dormitorios", "1 baño", "35 - 61 m² útiles"),
        extra="<span>14 unidades disponibles</span>",
    )
    t = parsear(html)[0]
    assert t.es_proyecto
    assert t.dormitorios is None and t.m2_utiles is None
    assert t.banos == 1, "lo que no es rango si se extrae"


def test_el_telefono_en_el_titulo_no_llega_a_la_base() -> None:
    """Caso real del corpus: el vendedor escribe su celular en el titulo, y el titulo va
    en la URL, que es columna de procedencia (§3.1)."""
    html = tarjeta_html(
        mlc="MLC-9", precio="$450.000", titulo="Arriendo metro 992401813 dueno"
    ).replace("MLC-9-x-_JM", "MLC-9-arriendo-metro-992401813-dueno-_JM")
    t = parsear(html, op="arriendo")[0]
    assert "992401813" not in t.url
    assert "992401813" not in (t.titulo or "")


def test_la_misma_tarjeta_enlazada_dos_veces_no_se_duplica() -> None:
    doble = tarjeta_html().replace(
        "</div>", '<a href="https://portalinmobiliario.com/MLC-1-x-_JM">foto</a></div>'
    )
    assert len(parsear(doble)) == 1


def test_un_precio_fuera_de_rango_se_descarta_entero() -> None:
    assert parsear(tarjeta_html(precio="UF99.999")) == []


def test_un_arriendo_en_UF_es_valido() -> None:
    """La moneda no determina la operacion: hay arriendos publicados en UF."""
    t = parsear(tarjeta_html(precio="UF15"), op="arriendo")[0]
    assert t.arriendo_uf == D(15) and t.arriendo_clp is None


@pytest.mark.parametrize(
    "url,esperado",
    [
        ("https://x/venta/departamento/propiedades-usadas/a_Desde_1", False),
        ("https://x/venta/departamento/proyectos/a_Desde_1", True),
        ("https://x/venta/departamento/a_Desde_1", None),
    ],
)
def test_el_tipo_sale_de_la_ruta_y_es_ND_si_no_se_filtro(url: str, esperado: bool | None) -> None:
    """Es informacion declarada por el portal, no una inferencia sobre el titulo."""
    assert pb.tipo_de_la_ruta(url) is esperado


# --------------------------------------------------------------- contra paginas reales


CORPUS = Path("/home/user/acabreirav/flujocero-legado/data/raw/portal_inmobiliario/search")


@pytest.mark.skipif(not CORPUS.is_dir(), reason="el corpus del legado no esta en esta maquina")
def test_contra_una_pagina_real_del_portal() -> None:
    f = sorted(CORPUS.glob("venta_san-miguel_p01_*.html"))[0]
    ts = pb.parse_busqueda(
        f.read_text(encoding="utf-8", errors="ignore"),
        "https://x/venta/departamento/propiedades-usadas/san-miguel-metropolitana_Desde_1",
        "venta",
        AHORA,
        str(f),
        "sha",
    )
    assert len(ts) >= 40, "una pagina del portal trae 48 tarjetas"
    unidades = [t for t in ts if not t.es_proyecto]
    assert sum(1 for t in unidades if t.m2_utiles) / len(unidades) >= 0.95
    assert sum(1 for t in ts if t.microzona_id) / len(ts) >= 0.95


# ------------------------------------------------------- la comuna sale del filtro, no del texto

URL_SM = "https://x/venta/departamento/propiedades-usadas/san-miguel-metropolitana_Desde_1"


@pytest.mark.parametrize(
    "texto,barrio_esperado",
    [
        ("Milán 1242, El Llano, San Miguel", "El Llano"),
        ("Apoquindo 4900, Barrio El Golf", "Barrio El Golf"),
        ("Barrio Italia", "Barrio Italia"),
        ("San Miguel", None),
        ("Av. Ossa 123", None),
        ("", None),
    ],
)
def test_la_comuna_sale_de_la_url_y_el_barrio_del_texto(texto: str, barrio_esperado) -> None:
    """El texto de la tarjeta es irregular y no hay forma de saber por su forma que parte es
    que. Contando desde el final salian **46 comunas donde habia 6**: "El Llano",
    "Plaza Egaña" y "Metro Ñuñoa" entraban a dim_comuna como si fueran municipios, y eso
    rompe la microzona, que es la clave de todo el analisis."""
    t = parsear(tarjeta_html(ubicacion=texto), url=URL_SM)[0]
    assert t.comuna_id == "san-miguel"
    assert t.barrio == barrio_esperado


def test_una_direccion_no_se_confunde_con_un_barrio() -> None:
    """Si lo unico que queda tiene numeros, es una calle. No se inventa un barrio (§3.2)."""
    t = parsear(tarjeta_html(ubicacion="Gran Avenida 5432"), url=URL_SM)[0]
    assert t.barrio is None and t.microzona_id is None


def test_el_nombre_de_la_comuna_conserva_tildes_cuando_el_texto_los_trae() -> None:
    url = "https://x/venta/departamento/propiedades-usadas/nunoa-metropolitana_Desde_1"
    t = parsear(tarjeta_html(ubicacion="Irarrázaval 3400, Plaza Egaña, Ñuñoa"), url=url)[0]
    assert t.comuna_nombre == "Ñuñoa"
    assert t.microzona_id == "nunoa/plaza-egana"


def test_sin_la_comuna_escrita_el_slug_se_prettifica() -> None:
    t = parsear(tarjeta_html(ubicacion="El Llano"), url=URL_SM)[0]
    assert t.comuna_nombre == "San Miguel"


@pytest.mark.parametrize(
    "url,esperado",
    [
        (URL_SM, "san-miguel"),
        ("https://x/arriendo/departamento/las-condes-metropolitana_Desde_49", "las-condes"),
        ("https://x/sin-formato", None),
    ],
)
def test_la_comuna_se_lee_de_la_ruta_de_busqueda(url: str, esperado) -> None:
    assert pb.comuna_de_la_url(url) == esperado
