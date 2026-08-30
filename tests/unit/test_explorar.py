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
