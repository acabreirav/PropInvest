"""Tests de MercadoLibre — T-011. Nunca tocan la red."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from flujocero.sources import meli

AHORA = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
UA = "FlujoCero-ResearchBot/1.0 (test)"

CATEGORIAS = [
    {"id": "MLC1747", "name": "Accesorios para Vehiculos"},
    {"id": "MLC1459", "name": "Inmuebles"},
]
INMUEBLES = {
    "id": "MLC1459",
    "name": "Inmuebles",
    "children_categories": [
        {"id": "MLC1472", "name": "Departamentos"},
        {"id": "MLC1466", "name": "Casas"},
    ],
}


def transporte(mapa: dict[str, tuple[int, object]], cabeceras=None) -> httpx.Client:
    def manejar(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for frag, (code, cuerpo) in mapa.items():
            if frag in url:
                b = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
                return httpx.Response(code, content=b, headers=cabeceras or {})
        return httpx.Response(404, content=b'{"error":"no encontrado"}')

    return httpx.Client(transport=httpx.MockTransport(manejar))


def cliente(mapa, cabeceras=None) -> meli.Meli:
    return meli.Meli("APP_USR-token-de-prueba", UA, transporte(mapa, cabeceras))


# --------------------------------------------------------------------- token


def test_el_refresh_token_nuevo_se_persiste_antes_de_usarse(tmp_path: Path) -> None:
    """El refresh token de MercadoLibre es de UN SOLO USO: el canje mata el anterior.
    Si el proceso muriera entre canjear y guardar, habria que rehacer la autorizacion."""
    env = tmp_path / ".env"
    env.write_text("MELI_CLIENT_ID=1\nMELI_REFRESH_TOKEN=TG-viejo\nOTRA=x\n")
    meli.guardar_refresh_token("TG-nuevo", env)
    texto = env.read_text()
    assert "MELI_REFRESH_TOKEN=TG-nuevo" in texto
    assert "TG-viejo" not in texto
    assert "OTRA=x" in texto, "no se pisan las otras variables"


def test_si_falta_la_variable_se_agrega(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MELI_CLIENT_ID=1\n")
    meli.guardar_refresh_token("TG-nuevo", env)
    assert "MELI_REFRESH_TOKEN=TG-nuevo" in env.read_text()


def test_un_refresh_token_ya_usado_da_un_mensaje_accionable() -> None:
    c = transporte({"/oauth/token": (400, {"error": "invalid_grant"})})
    with pytest.raises(meli.TokenInvalido, match="autorizacion por navegador"):
        meli.renovar_token("id", "secret", "TG-usado", c)


def test_una_respuesta_sin_access_token_es_error() -> None:
    c = transporte({"/oauth/token": (200, {"token_type": "Bearer"})})
    with pytest.raises(meli.ErrorDeFuente, match="sin access_token"):
        meli.renovar_token("id", "secret", "TG-x", c)


def test_el_access_token_no_se_filtra_en_logs() -> None:
    sucio = "fallo con APP_USR-249429408292250-082801-abc-258494802 adentro"
    assert "APP_USR-OCULTO" in meli.ocultar_token(sucio)
    assert "082801-abc" not in meli.ocultar_token(sucio)


def test_faltan_credenciales_y_lo_dice(tmp_path: Path) -> None:
    with pytest.raises(meli.ErrorDeFuente, match="MELI_CLIENT_ID"):
        meli.desde_entorno({}, tmp_path / ".env")


# --------------------------------------------------------------------- brecha 1


def test_mide_la_categoria_real_y_la_contrasta_con_el_supuesto() -> None:
    """El RUNBOOK es explicito: no aceptar `MLC1459` sin verificar."""
    c = cliente(
        {"/sites/MLC/categories": (200, CATEGORIAS), "/categories/MLC1459": (200, INMUEBLES)}
    )
    m = c._brecha_1_categoria()
    assert "MLC1459" in m.respuesta and "MLC1472" in m.respuesta
    assert "COINCIDE" in m.evidencia
    assert m.evidence_level == "V"


def test_si_la_categoria_supuesta_no_coincide_lo_grita() -> None:
    otras = [{"id": "MLC9999", "name": "Inmuebles"}]
    c = cliente(
        {
            "/sites/MLC/categories": (200, otras),
            "/categories/MLC9999": (
                200,
                {"children_categories": [{"id": "MLC1", "name": "Departamentos"}]},
            ),
        }
    )
    m = c._brecha_1_categoria()
    assert "NO COINCIDE" in m.evidencia


def test_sin_categoria_de_inmuebles_reporta_nd_y_no_inventa() -> None:
    """§3.2: antes que adivinar un ID, se reporta ND."""
    c = cliente({"/sites/MLC/categories": (200, [{"id": "MLC1", "name": "Autos"}])})
    m = c._brecha_1_categoria()
    assert m.respuesta == "ND"
    assert m.evidence_level == "ND"


# --------------------------------------------------------------------- brecha 2


def test_detecta_que_la_busqueda_exige_token() -> None:
    llamadas = []

    def manejar(request: httpx.Request) -> httpx.Response:
        con_token = "Authorization" in request.headers
        llamadas.append(con_token)
        return httpx.Response(200 if con_token else 401, content=b'{"results":[]}')

    c = meli.Meli("APP_USR-x", UA, httpx.Client(transport=httpx.MockTransport(manejar)))
    m = c._brecha_2_bearer()
    assert m.respuesta == "SI, exige token"
    assert llamadas == [True, False], "se prueba con y sin, en ese orden"


def test_detecta_que_la_busqueda_es_publica() -> None:
    c = cliente({"/sites/MLC/search": (200, {"results": [], "paging": {"total": 5}})})
    assert c._brecha_2_bearer().respuesta == "NO lo exige"


# --------------------------------------------------------------------- brechas 3 y 4


def test_mide_el_tope_de_resultados() -> None:
    def manejar(request: httpx.Request) -> httpx.Response:
        offset = int(dict(request.url.params).get("offset", 0))
        if offset > 1000:
            return httpx.Response(400, content=b'{"error":"offset invalido"}')
        return httpx.Response(200, content=json.dumps({"paging": {"total": 48213}}).encode())

    c = meli.Meli("APP_USR-x", UA, httpx.Client(transport=httpx.MockTransport(manejar)))
    m = c._brecha_3_tope()
    assert "48213" in m.respuesta
    assert "offset=4000: HTTP 400" in m.evidencia
    assert "search_type=scan" in m.evidencia


def test_mide_el_rate_limit_leyendo_las_cabeceras() -> None:
    c = cliente(
        {"/sites/MLC/search": (200, {"paging": {"total": 1}})},
        cabeceras={"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "998"},
    )
    m = c._brecha_4_rate_limit(n=3)
    assert "sin 429" in m.respuesta
    # httpx normaliza los nombres de cabecera a minusculas.
    assert "x-ratelimit-limit" in m.evidencia.lower()
    assert m.evidence_level == "V"


def test_si_llega_un_429_lo_reporta_con_el_conteo() -> None:
    caja = {"n": 0}

    def manejar(request: httpx.Request) -> httpx.Response:
        caja["n"] += 1
        if caja["n"] > 3:
            return httpx.Response(429, content=b"{}", headers={"Retry-After": "60"})
        return httpx.Response(200, content=b'{"paging":{"total":1}}')

    c = meli.Meli("APP_USR-x", UA, httpx.Client(transport=httpx.MockTransport(manejar)))
    m = c._brecha_4_rate_limit(n=10)
    assert "429 tras 3 peticiones" in m.respuesta
    assert "retry-after" in m.evidencia.lower()


def test_el_reporte_completo_cubre_las_cuatro_brechas() -> None:
    c = cliente(
        {
            "/sites/MLC/categories": (200, CATEGORIAS),
            "/categories/MLC1459": (200, INMUEBLES),
            "/sites/MLC/search": (200, {"paging": {"total": 100}}),
        }
    )
    rep = c.medir(ahora=AHORA)
    assert len(rep.mediciones) == 4
    assert [m.brecha.split(" ")[0] for m in rep.mediciones] == ["G1", "G2", "G3", "G4"]
    assert "2026-08-28" in str(rep)
