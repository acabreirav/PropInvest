"""Tests del explorador de fuentes."""

from __future__ import annotations

from flujocero.cli import _forma, _urls_de_sitemap

SITEMAP = b"""<?xml version="1.0"?><urlset xmlns="x">
<url><loc>https://a.cl/uno</loc><lastmod>2026-08-30</lastmod></url>
<url><loc> https://a.cl/dos </loc></url></urlset>"""


def test_lee_las_urls_de_un_sitemap():
    assert _urls_de_sitemap(SITEMAP) == ["https://a.cl/uno", "https://a.cl/dos"]


def test_un_html_cualquiera_no_es_sitemap():
    assert _urls_de_sitemap(b"<html><body>hola</body></html>") == []


def test_un_sitemap_malformado_devuelve_lo_que_se_pueda():
    roto = b"<urlset><url><loc>https://a.cl/uno</loc></url><url><loc>roto"
    assert _urls_de_sitemap(roto) == ["https://a.cl/uno"]


def test_describe_un_sitemap_por_su_tamano():
    assert "2 <loc>" in _forma(SITEMAP)[0]


def test_detecta_json_ld_y_su_tipo():
    html = b'<html><script type="application/ld+json">{"@type":"Apartment","x":1}</script></html>'
    linea = _forma(html)[0]
    assert "JSON-LD" in linea and "Apartment" in linea


def test_un_json_ld_roto_se_reporta_no_revienta():
    html = b'<html><script type="application/ld+json">{roto</script></html>'
    assert "no parsea" in _forma(html)[0]


def test_avisa_cuando_hay_estado_de_app_embebido():
    html = b"<html><script>window.__NUXT__={}</script></html>"
    assert any("__NUXT__" in x for x in _forma(html))


def test_describe_un_json_por_sus_claves():
    assert "JSON" in _forma(b'{"b":1,"a":2}')[0]


def test_detecta_montos_en_uf_y_en_pesos():
    html = b"<html>Arriendo $450.000 y venta UF 2.500</html>"
    txt = " ".join(_forma(html))
    assert "pesos" in txt and "UF" in txt


def test_no_revienta_con_bytes_no_utf8():
    assert _forma(b"\xff\xfe\x00mal") is not None


def test_la_falta_del_navegador_se_traduce_a_un_comando():
    """Reventaba con un traceback de 60 lineas terminado en un cartel en ingles. Un error de
    instalacion que exige leer un traceback para saber que hacer esta mal reportado."""
    from flujocero.cli import navegador_ausente

    exc = RuntimeError(
        "BrowserType.launch: Executable doesn't exist at "
        "C:\\\\...\\\\chromium_headless_shell-1234\\\\chrome-headless-shell.exe"
    )
    amable = navegador_ausente(exc)
    assert amable is not None
    assert "playwright install chromium" in amable.message


def test_otro_error_del_navegador_no_se_disfraza_de_falta_de_instalacion():
    """Si el navegador esta y falla por otra cosa, decir "instalalo" manda a perder el rato."""
    from flujocero.cli import navegador_ausente

    assert navegador_ausente(RuntimeError("Target page crashed")) is None
