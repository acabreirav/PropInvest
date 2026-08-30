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
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from flujocero.sources import robots_rfc9309 as rfc9309
from flujocero.sources.base import RobotsVerdict, escribir_crudo, sha_de

TIMEOUT = 20.0
INTENTOS = 4

# RFC 9309 §2.4: la vida util normal de un robots.txt cacheado es de hasta 24 h. El §2.3.1.3
# agrega que, si el archivo lleva mucho tiempo inalcanzable, el crawler puede apoyarse en una
# copia cacheada. Se usa esa puerta —no la de "asumir que no hay restricciones"— porque un
# snapshot real que dijo algo es mejor evidencia que suponer.
CACHE_NORMAL_H = 24
CACHE_MAX_DIAS_SI_CAIDO = 30

# Cortes de red que si vale reintentar. Medido contra api.cmfchile.cl el 28-ago-2026:
# el mismo host devolvio 404 y minutos despues 500 para el mismo robots.txt.
TRANSITORIOS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ReadError,
)


class ServidorInestable(httpx.HTTPError):
    """Un 5xx al pedir robots.txt. Se reintenta: es una caida, no una prohibicion."""


def snapshot_cacheado(
    source_id: str, momento: datetime, raiz: Path | None = None
) -> tuple[bytes, datetime] | None:
    """El robots.txt guardado mas reciente para esta fuente, si no es demasiado viejo.

    La zona cruda ya guarda un snapshot en cada verificacion exitosa (§3.1), asi que esto
    no agrega almacenamiento: solo lo lee de vuelta cuando el servidor esta caido.
    """
    import gzip

    from flujocero.sources.base import ZONA_CRUDA

    base = (raiz or ZONA_CRUDA) / source_id
    if not base.is_dir():
        return None
    candidatos = sorted(base.glob("*/*/*/robots.txt.json.gz"), reverse=True)
    for ruta in candidatos:
        try:
            anio, mes, dia = (int(x) for x in ruta.parts[-4:-1])
            guardado = datetime(anio, mes, dia, tzinfo=UTC)
        except (ValueError, IndexError):
            continue
        if (momento - guardado).days > CACHE_MAX_DIAS_SI_CAIDO:
            return None
        with gzip.open(ruta, "rb") as fh:
            return fh.read(), guardado
    return None


def _veredicto_desde_cuerpo(
    cuerpo: bytes, url: str, user_agent: str, destino: str, motivo: str
) -> RobotsVerdict:
    """Evalua con el RFC 9309 y, ante desacuerdo con la stdlib, se queda con lo mas estricto.

    Por que no basta `RobotFileParser` (T-926): **no implementa comodines**. Guarda
    `Disallow: /admin/*` como el literal `/admin/%2A` y responde `allowed` para `/admin/x`.
    O sea **sub-bloquea**, que es la direccion peligrosa: sobre-bloquear molesta, sub-bloquear
    te hace pedir lo que el sitio prohibio, y el §3.5 es una regla dura.

    Se corren los dos y se toma la conjuncion. La stdlib no entiende `*` pero si maneja
    detalles del formato viejo que nuestro evaluador podria estar pasando por alto, asi que
    un `False` suyo tambien vale. **Permitido solo si los dos dicen que si.**
    """
    texto = cuerpo.decode("utf-8", errors="replace")

    v = rfc9309.evaluar(texto, user_agent, url)

    stdlib = RobotFileParser()
    stdlib.parse(texto.splitlines())
    permitido_stdlib = bool(stdlib.can_fetch(user_agent, url))

    permitido = v.permitido and permitido_stdlib
    porque = v.porque
    if v.permitido and not permitido_stdlib:
        porque = f"{v.porque}; pero RobotFileParser lo niega — se toma lo mas estricto"

    demora = v.crawl_delay
    if demora is None:
        de_stdlib = stdlib.crawl_delay(user_agent)
        demora = float(de_stdlib) if de_stdlib is not None else None

    return RobotsVerdict(
        allowed=permitido,
        url_robots=destino,
        snapshot_sha=sha_de(cuerpo),
        crawl_delay_s=demora,
        motivo=f"{motivo} — {porque}".strip(" —")
        if permitido
        else f"PROHIBIDO por robots.txt ({porque})",
    )


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

    Semantica del RFC 9309, que distingue tres cosas que es facil confundir:

    - **4xx (no disponible)**, incluido el 404: NO hay restricciones. Se permite.
    - **5xx (inalcanzable)**: se reintenta con backoff. Agotados los reintentos se asume
      prohibicion total, pero por caida del servidor y no por decision suya.
    - **2xx**: se parsea y manda lo que diga.

    La distincion importa: un 500 transitorio tratado como prohibicion detiene una
    recoleccion legitima, y tratarlo como permiso saltaria una prohibicion real.
    """
    momento = momento or datetime.now(UTC)
    destino = url_robots(url)
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    @retry(
        retry=retry_if_exception_type((*TRANSITORIOS, ServidorInestable)),
        stop=stop_after_attempt(INTENTOS),
        wait=wait_exponential_jitter(initial=1, max=15),
        reraise=True,
    )
    def _pedir() -> httpx.Response:
        r = cliente.get(destino, headers={"User-Agent": user_agent})
        # Un 5xx NO es una respuesta del protocolo de robots: es el servidor caido.
        # Se reintenta antes de sacar cualquier conclusion sobre permisos.
        if r.status_code >= 500:
            raise ServidorInestable(f"robots.txt respondio {r.status_code}")
        return r

    try:
        resp = _pedir()
    except ServidorInestable as exc:
        # Servidor caido. Antes de detener nada, se busca el snapshot que este mismo
        # verificador guardo en una corrida anterior: el RFC 9309 §2.3.1.3 admite apoyarse
        # en una copia cacheada cuando el archivo es inalcanzable, y un snapshot real es
        # mejor evidencia que cualquier suposicion.
        cache = snapshot_cacheado(source_id, momento, raiz_cruda)
        if cache is not None:
            cuerpo, guardado = cache
            edad_h = (momento - guardado).total_seconds() / 3600
            nota = (
                f"{exc} tras {INTENTOS} intentos; se usa el snapshot guardado el "
                f"{guardado:%Y-%m-%d} ({edad_h:.0f} h). RFC 9309 §2.3.1.3"
            )
            if not cuerpo:
                # Snapshot de un 4xx: el sitio no tenia robots.txt cuando lo miramos.
                return RobotsVerdict(True, destino, sha_de(cuerpo), motivo=nota)
            return _veredicto_desde_cuerpo(cuerpo, url, user_agent, destino, nota)
        # Sin cache no hay de donde sacar la politica del sitio: el RFC manda no recolectar.
        return RobotsVerdict(
            allowed=False,
            url_robots=destino,
            snapshot_sha="",
            motivo=(
                f"{exc} tras {INTENTOS} intentos y sin snapshot guardado de que apoyarse. "
                "No es una prohibicion: es el servidor caido. RFC 9309 manda no recolectar "
                "mientras robots.txt sea inalcanzable y no haya copia."
            ),
        )
    except httpx.HTTPError as exc:
        return RobotsVerdict(
            allowed=False,
            url_robots=destino,
            snapshot_sha="",
            motivo=(
                f"no se pudo leer robots.txt tras {INTENTOS} intentos: {type(exc).__name__}: {exc}"
            ),
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
        # 4xx que no es 404. El RFC 9309 §2.3.1.4 trata todo "no disponible" (4xx) como
        # ausencia de restricciones, igual que el 404.
        cuerpo = b""
        sha = sha_de(cuerpo)
        escribir_crudo(source_id, destino, cuerpo, momento, sha, "robots.txt", raiz_cruda)
        return RobotsVerdict(
            True, destino, sha, motivo=f"robots.txt respondio {resp.status_code} (4xx): permitido"
        )

    cuerpo = resp.content
    escribir_crudo(source_id, destino, cuerpo, momento, sha_de(cuerpo), "robots.txt", raiz_cruda)
    return _veredicto_desde_cuerpo(cuerpo, url, user_agent, destino, "permitido por robots.txt")


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
