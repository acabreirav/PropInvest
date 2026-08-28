"""Verificación de robots.txt — CLAUDE.md §3.5.

`python -m flujocero.sources.robots_check <url>` debe pasar ANTES de escribir un scraper.

Guarda un snapshot del robots.txt en la zona cruda y devuelve su sha, que después viaja
en la columna `robots_snapshot_sha` de cada fila (§3.1). Es lo que permite responder, meses
después, "¿qué decía su robots.txt el día que recolectamos esto?".
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from flujocero.sources.base import RobotsVerdict, escribir_crudo, sha_de

TIMEOUT = 20.0


def url_robots(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/robots.txt"


def verificar(
    url: str,
    user_agent: str,
    source_id: str = "_robots",
    momento: datetime | None = None,
    cliente: httpx.Client | None = None,
    raiz_cruda: Path | None = None,
) -> RobotsVerdict:
    """Consulta el robots.txt del host de `url` y lo evalúa para `user_agent`.

    Un host sin robots.txt (404) se considera permitido: es la lectura estándar del
    protocolo. Un host que no responde NO se considera permitido — ante la duda, no.
    """
    momento = momento or datetime.now(UTC)
    destino = url_robots(url)
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    try:
        resp = cliente.get(destino, headers={"User-Agent": user_agent})
    except httpx.HTTPError as exc:
        return RobotsVerdict(
            allowed=False,
            url_robots=destino,
            snapshot_sha="",
            motivo=f"no se pudo leer robots.txt: {type(exc).__name__}: {exc}",
        )
    finally:
        if propio:
            cliente.close()

    if resp.status_code == 404:
        cuerpo = b""
        sha = sha_de(cuerpo)
        escribir_crudo(source_id, destino, cuerpo, momento, sha, "robots.txt", raiz_cruda)
        return RobotsVerdict(True, destino, sha, motivo="sin robots.txt (404): permitido")

    if resp.status_code >= 400:
        return RobotsVerdict(
            allowed=False,
            url_robots=destino,
            snapshot_sha="",
            motivo=f"robots.txt respondió {resp.status_code}; ante la duda, no",
        )

    cuerpo = resp.content
    sha = sha_de(cuerpo)
    escribir_crudo(source_id, destino, cuerpo, momento, sha, "robots.txt", raiz_cruda)

    parser = RobotFileParser()
    parser.parse(cuerpo.decode("utf-8", errors="replace").splitlines())
    permitido = parser.can_fetch(user_agent, url)
    demora = parser.crawl_delay(user_agent)
    return RobotsVerdict(
        allowed=bool(permitido),
        url_robots=destino,
        snapshot_sha=sha,
        crawl_delay_s=float(demora) if demora is not None else None,
        motivo="permitido por robots.txt" if permitido else "PROHIBIDO por robots.txt",
    )


def main(argv: list[str] | None = None) -> int:
    import os

    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("uso: python -m flujocero.sources.robots_check <url>", file=sys.stderr)
        return 2
    ua = os.environ.get("USER_AGENT", "FlujoCero-ResearchBot/1.0")
    v = verificar(argv[0], ua)
    print(f"url        : {argv[0]}")
    print(f"robots     : {v.url_robots}")
    print(f"user-agent : {ua}")
    print(f"veredicto  : {'PERMITIDO' if v.allowed else 'NO PERMITIDO'} — {v.motivo}")
    if v.crawl_delay_s:
        print(f"crawl-delay: {v.crawl_delay_s} s")
    print(f"snapshot   : sha256:{v.snapshot_sha[:16]}…" if v.snapshot_sha else "snapshot   : —")
    return 0 if v.allowed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
