"""Tests de la verificacion de robots.txt — CLAUDE.md §3.5, RFC 9309.

Nacieron de un fallo real: `api.cmfchile.cl/robots.txt` devolvio 404 en una corrida y 500
minutos despues, y el colector trato ese 500 como una prohibicion. No lo era: era el
servidor caido.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from flujocero.sources import robots_check as rc

AHORA = datetime(2026, 8, 28, tzinfo=UTC)
UA = "FlujoCero-ResearchBot/1.0 (test)"
URL = "https://api.cmfchile.cl/api-sbifv3/recursos_api/uf"


def cliente_que(respuestas: list[int | Exception], cuerpo: bytes = b"") -> httpx.Client:
    """Devuelve, en orden, cada elemento de `respuestas`. Repite el ultimo si se acaba."""
    caja = {"i": 0}

    def manejar(request: httpx.Request) -> httpx.Response:
        i = min(caja["i"], len(respuestas) - 1)
        caja["i"] += 1
        r = respuestas[i]
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r, content=cuerpo)

    return httpx.Client(transport=httpx.MockTransport(manejar))


def test_url_de_robots_se_arma_desde_el_host() -> None:
    assert rc.url_robots(URL) == "https://api.cmfchile.cl/robots.txt"


def test_sin_robots_txt_404_se_permite(tmp_path: Path) -> None:
    """RFC 9309 §2.3.1.4: 'no disponible' significa sin restricciones."""
    v = rc.verificar(URL, UA, cliente=cliente_que([404]), momento=AHORA, raiz_cruda=tmp_path)
    assert v.allowed
    assert v.snapshot_sha, "hasta el robots.txt ausente deja su huella (§3.1)"


@pytest.mark.parametrize("codigo", [401, 403, 410, 451])
def test_cualquier_4xx_se_permite(codigo: int, tmp_path: Path) -> None:
    v = rc.verificar(URL, UA, cliente=cliente_que([codigo]), momento=AHORA, raiz_cruda=tmp_path)
    assert v.allowed, f"un {codigo} es 'no disponible', no una prohibicion"


def test_un_500_transitorio_se_reintenta_y_termina_permitiendo(tmp_path: Path) -> None:
    """EL FALLO REAL: dos 500 seguidos y despues el 404 que el servidor daba antes."""
    v = rc.verificar(
        URL, UA, cliente=cliente_que([500, 500, 404]), momento=AHORA, raiz_cruda=tmp_path
    )
    assert v.allowed, "no se rinde al primer 500"


def test_un_500_persistente_prohibe_pero_dice_que_es_una_caida(tmp_path: Path) -> None:
    """RFC 9309 §2.3.1.3: inalcanzable implica no recolectar. Pero el motivo debe decir
    que es el servidor caido y no una decision del sitio, o el mensaje confunde."""
    v = rc.verificar(URL, UA, cliente=cliente_que([500]), momento=AHORA, raiz_cruda=tmp_path)
    assert not v.allowed
    assert "no es una prohibicion" in v.motivo.lower()
    assert str(rc.INTENTOS) in v.motivo


def test_un_corte_de_conexion_se_reintenta(tmp_path: Path) -> None:
    corte = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    v = rc.verificar(
        URL, UA, cliente=cliente_que([corte, corte, 404]), momento=AHORA, raiz_cruda=tmp_path
    )
    assert v.allowed


def test_un_corte_persistente_no_se_considera_permiso(tmp_path: Path) -> None:
    corte = httpx.ConnectError("sin ruta al host")
    v = rc.verificar(URL, UA, cliente=cliente_que([corte]), momento=AHORA, raiz_cruda=tmp_path)
    assert not v.allowed
    assert not v.snapshot_sha, "sin snapshot no hay procedencia, y sin procedencia no hay fila"


def test_un_disallow_real_si_prohibe(tmp_path: Path) -> None:
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([200], b"User-agent: *\nDisallow: /\n"),
        momento=AHORA,
        raiz_cruda=tmp_path,
    )
    assert not v.allowed
    assert "PROHIBIDO" in v.motivo


def test_un_allow_real_permite_y_lee_el_crawl_delay(tmp_path: Path) -> None:
    cuerpo = b"User-agent: *\nAllow: /\nCrawl-delay: 2\n"
    v = rc.verificar(
        URL, UA, cliente=cliente_que([200], cuerpo), momento=AHORA, raiz_cruda=tmp_path
    )
    assert v.allowed
    assert v.crawl_delay_s == 2.0
    assert v.snapshot_sha == rc.sha_de(cuerpo)


def test_el_snapshot_queda_en_la_zona_cruda(tmp_path: Path) -> None:
    """§3.1: el `robots_snapshot_sha` de cada fila tiene que poder auditarse contra el
    archivo que se guardo ese dia."""
    rc.verificar(
        URL,
        UA,
        cliente=cliente_que([200], b"User-agent: *\nAllow: /\n"),
        momento=AHORA,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    guardado = tmp_path / "cmf_indicadores" / "2026" / "08" / "28" / "robots.txt.json.gz"
    assert guardado.exists()


# --------------------------------------------------------------------- cache del snapshot


def _sembrar_snapshot(tmp_path: Path, cuerpo: bytes, dia: str = "28") -> None:
    """Deja un snapshot en la zona cruda como lo haria una verificacion exitosa."""
    import gzip

    d = tmp_path / "cmf_indicadores" / "2026" / "08" / dia
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / "robots.txt.json.gz", "wb") as fh:
        fh.write(cuerpo)


def test_con_el_servidor_caido_se_usa_el_snapshot_guardado(tmp_path: Path) -> None:
    """EL BLOQUEO REAL: la API de datos responde, robots.txt lleva rato en 500, y ya
    teniamos un snapshot de una corrida anterior. RFC 9309 §2.3.1.3 admite apoyarse en el."""
    _sembrar_snapshot(tmp_path, b"User-agent: *\nAllow: /\n")
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([500]),
        momento=AHORA,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    assert v.allowed
    assert "snapshot guardado" in v.motivo
    assert v.snapshot_sha, "la procedencia sigue completa: hay sha del cuerpo cacheado"


def test_un_snapshot_vacio_significa_que_no_habia_robots_txt(tmp_path: Path) -> None:
    """Es el caso de la CMF: robots.txt daba 404 y se guardo el snapshot vacio."""
    _sembrar_snapshot(tmp_path, b"")
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([500]),
        momento=AHORA,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    assert v.allowed


def test_un_snapshot_que_prohibia_sigue_prohibiendo(tmp_path: Path) -> None:
    """La cache no es una puerta trasera: si el sitio prohibia, la copia tambien prohibe."""
    _sembrar_snapshot(tmp_path, b"User-agent: *\nDisallow: /\n")
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([500]),
        momento=AHORA,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    assert not v.allowed
    assert "PROHIBIDO" in v.motivo


def test_un_snapshot_demasiado_viejo_no_se_usa(tmp_path: Path) -> None:
    """Pasados 30 dias el RFC ya no respalda apoyarse en la copia."""
    _sembrar_snapshot(tmp_path, b"User-agent: *\nAllow: /\n")
    muy_despues = datetime(2026, 11, 30, tzinfo=UTC)
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([500]),
        momento=muy_despues,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    assert not v.allowed
    assert "sin snapshot" in v.motivo


def test_sin_snapshot_y_servidor_caido_no_se_recolecta(tmp_path: Path) -> None:
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([500]),
        momento=AHORA,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    assert not v.allowed
    assert "sin snapshot guardado" in v.motivo


def test_el_servidor_vivo_siempre_gana_sobre_la_cache(tmp_path: Path) -> None:
    """La cache es un respaldo, no un atajo: si el servidor responde, manda el servidor."""
    _sembrar_snapshot(tmp_path, b"User-agent: *\nAllow: /\n")
    v = rc.verificar(
        URL,
        UA,
        cliente=cliente_que([200], b"User-agent: *\nDisallow: /\n"),
        momento=AHORA,
        source_id="cmf_indicadores",
        raiz_cruda=tmp_path,
    )
    assert not v.allowed, "la respuesta viva prohibe, aunque la cache permitiera"
