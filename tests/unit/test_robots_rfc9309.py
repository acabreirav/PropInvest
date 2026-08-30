"""Tests del evaluador RFC 9309 — T-926.

Modulo puro: nada de red. Entra texto de robots.txt y sale un veredicto.

El caso que lo origino esta al final, con el robots REAL de Gael: la libreria estandar
respondia `allowed` para `/admin/x` teniendo un `Disallow: /admin/*` al frente.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from flujocero.sources.robots_rfc9309 import compilar, evaluar, grupo_aplicable, parsear

UA = "FlujoCero-ResearchBot/1.0"


# --------------------------------------------------------------- comodines (§2.2.3)


@pytest.mark.parametrize(
    ("patron", "ruta", "calza"),
    [
        ("/admin/*", "/admin/x", True),
        ("/admin/*", "/admin/", True),  # `*` tambien calza con la secuencia vacia
        ("/admin/*", "/admins", False),
        ("/*.php", "/foo/bar.php", True),
        ("/*.php", "/foo/bar.html", False),
        ("/*_Desde_", "/departamento-venta-san-miguel/_Desde_49", True),
        ("/*_Desde_", "/departamento-venta-san-miguel", False),
        # `$` ancla el fin de la ruta
        ("/fish$", "/fish", True),
        ("/fish$", "/fish.html", False),
        ("/*.pdf$", "/docs/a.pdf", True),
        ("/*.pdf$", "/docs/a.pdf.html", False),
        # sin comodines se compara por prefijo, como siempre
        ("/propiedades/", "/propiedades/MLC-1", True),
        ("/propiedades/", "/venta/depto", False),
    ],
)
def test_los_comodines_del_rfc_se_respetan(patron: str, ruta: str, calza: bool) -> None:
    assert bool(compilar(patron).match(ruta)) is calza


def test_los_metacaracteres_de_regex_no_son_comodines_por_accidente() -> None:
    """Un `.` o un `+` en un patron son caracteres literales, no comodines de regex.

    Sin escapar, `Disallow: /a.b` bloquearia tambien `/axb`, o sea sobre-bloquearia; y
    peor, un `(` sin escapar reventaria la compilacion en medio de una recoleccion.
    """
    assert compilar("/a.b").match("/a.b")
    assert not compilar("/a.b").match("/axb")
    assert compilar("/c++").match("/c++")
    assert compilar("/(x)").match("/(x)")


# --------------------------------------------------------------- especificidad (§2.2.2)


def test_gana_el_patron_mas_largo_no_el_que_aparece_primero() -> None:
    """El RFC ordena por longitud del patron. Es lo que permite abrir una excepcion
    dentro de un directorio prohibido."""
    texto = "User-agent: *\nDisallow: /a/\nAllow: /a/publico/\n"
    assert evaluar(texto, UA, "/a/privado/x").permitido is False
    assert evaluar(texto, UA, "/a/publico/x").permitido is True


def test_el_orden_de_las_lineas_no_cambia_el_resultado() -> None:
    largo = "User-agent: *\nAllow: /a/publico/\nDisallow: /a/\n"
    corto = "User-agent: *\nDisallow: /a/\nAllow: /a/publico/\n"
    for t in (largo, corto):
        assert evaluar(t, UA, "/a/publico/x").permitido is True
        assert evaluar(t, UA, "/a/otro").permitido is False


def test_ante_empate_de_longitud_gana_allow() -> None:
    """Lo dice el RFC explicitamente. Sin esta regla el resultado dependeria del orden."""
    texto = "User-agent: *\nDisallow: /x/y\nAllow: /x/y\n"
    assert evaluar(texto, UA, "/x/y").permitido is True


def test_sin_regla_que_calce_se_permite() -> None:
    texto = "User-agent: *\nDisallow: /admin/\n"
    assert evaluar(texto, UA, "/publico/x").permitido is True


def test_disallow_vacio_no_prohibe_nada() -> None:
    """`Disallow:` sin valor es un permiso. Tratarlo como un patron de longitud cero lo
    haria calzar con TODO y bloquearia el sitio entero."""
    texto = "User-agent: *\nDisallow:\n"
    assert evaluar(texto, UA, "/lo-que-sea").permitido is True


# --------------------------------------------------------------- grupos (§2.2.1, §2.2.2)


def test_una_linea_sin_dos_puntos_es_malformada_y_no_otorga_permiso() -> None:
    """El robots real de Gael trae `Allow /general/public/*`, sin los dos puntos.

    Si se aceptara, un sitio podria "permitir" algo por accidente de tipeo. Y al reves:
    creer que dependemos de esa linea nos haria pasar por alto que el permiso real viene
    de otro lado.
    """
    texto = "User-agent: *\nAllow /todo/*\nDisallow: /todo/\n"
    assert evaluar(texto, UA, "/todo/x").permitido is False


def test_se_ignoran_los_comentarios() -> None:
    texto = "User-agent: *\n# Disallow: /admin/\nDisallow: /otro/  # nota\n"
    assert evaluar(texto, UA, "/admin/x").permitido is True
    assert evaluar(texto, UA, "/otro/x").permitido is False


def test_manda_el_grupo_mas_especifico_no_el_comodin() -> None:
    texto = "User-agent: *\nDisallow: /\n\nUser-agent: FlujoCero-ResearchBot\nDisallow: /admin/\n"
    assert evaluar(texto, UA, "/datos").permitido is True, "se aplico el grupo * en vez del propio"
    assert evaluar(texto, UA, "/admin/x").permitido is False


def test_un_agente_sin_grupo_propio_cae_al_comodin() -> None:
    texto = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow:\n"
    assert evaluar(texto, "OtroBot/1.0", "/x").permitido is False
    assert evaluar(texto, "Googlebot/2.1", "/x").permitido is True


def test_varios_user_agent_seguidos_forman_un_solo_grupo() -> None:
    texto = "User-agent: A\nUser-agent: B\nDisallow: /no/\n"
    grupos = parsear(texto)
    assert len(grupos) == 1
    assert grupos[0].agentes == ("a", "b")
    assert evaluar(texto, "B/1.0", "/no/x").permitido is False


def test_sin_ningun_grupo_no_hay_restriccion() -> None:
    assert evaluar("", UA, "/x").permitido is True
    assert evaluar("# solo un comentario\n", UA, "/x").permitido is True


def test_el_crawl_delay_se_lee_del_grupo_aplicable() -> None:
    texto = "User-agent: *\nCrawl-delay: 2\nDisallow: /admin/\n"
    assert evaluar(texto, UA, "/x").crawl_delay == 2.0


def test_un_crawl_delay_ilegible_no_revienta_el_parseo() -> None:
    texto = "User-agent: *\nCrawl-delay: pronto\nDisallow: /admin/\n"
    v = evaluar(texto, UA, "/x")
    assert v.permitido is True
    assert v.crawl_delay is None


def test_acepta_una_url_completa_o_una_ruta_suelta() -> None:
    texto = "User-agent: *\nDisallow: /admin/\n"
    assert evaluar(texto, UA, "https://ejemplo.cl/admin/x").permitido is False
    assert evaluar(texto, UA, "/admin/x").permitido is False


def test_grupo_aplicable_devuelve_none_si_no_hay_grupos() -> None:
    assert grupo_aplicable([], UA) is None


# --------------------------------------------------------------- contra los robots REALES

REALES = Path(__file__).resolve().parents[1] / "fixtures"


def _robots_real(relativa: str) -> str:
    return gzip.open(REALES / relativa, "rb").read().decode("utf-8")


def test_el_robots_real_de_gael_prohibe_lo_que_dice_prohibir() -> None:
    """EL CASO QUE ORIGINO ESTE MODULO.

    `RobotFileParser` de la stdlib respondia `allowed=True` para `/admin/x` teniendo un
    `Disallow: /admin/*` al frente, porque guarda la regla como el literal `/admin/%2A`.
    Sub-bloquear es la direccion peligrosa: te hace pedir lo que el sitio prohibio.
    """
    texto = _robots_real("gael/real/robots.txt.json.gz")
    for prohibida in ("/admin/x", "/general/auth/x", "/general/endpoints/x", "/mobileapp/x"):
        assert evaluar(texto, UA, prohibida).permitido is False, f"{prohibida} salio permitida"


def test_el_robots_real_de_gael_permite_el_endpoint_publico() -> None:
    """Y el permiso NO viene del `Allow /general/public/*` —esa linea esta malformada y se
    ignora— sino de que ningun `Disallow:` cubre esa ruta."""
    texto = _robots_real("gael/real/robots.txt.json.gz")
    v = evaluar(texto, UA, "/general/public/monedas/UF")
    assert v.permitido is True
    assert v.regla is None, (
        "el permiso vino de una regla explicita: si Gael arreglo el typo del Allow, "
        "actualiza el razonamiento de este test"
    )
