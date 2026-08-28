"""MercadoLibre — autenticación y mediciones. Tarea T-011, capas 2, 3 y 4.

`legal_tier: api_oficial`. Es la puerta correcta: Portal Inmobiliario corre por debajo sobre
esta misma API, y el §13.6 del contrato prohíbe scrapear su HTML precisamente porque existe
esta alternativa.

Este módulo hace dos cosas y ninguna es recolectar todavía:

1. **Autenticación.** El `refresh_token` dura seis meses pero es de **un solo uso**: cada
   canje devuelve uno nuevo y el anterior muere. Perderlo obliga a repetir la autorización
   por navegador, así que el token nuevo se persiste ANTES de usarse.
2. **Medición.** El §G de `docs/01-fuentes.md` enumera cuatro brechas que hay que medir
   antes de comprometer arquitectura. `medir()` las responde con evidencia, no con
   suposiciones: cuál es el ID real de la categoría de departamentos, si la búsqueda exige
   token, cuál es el tope real de resultados y cuál es el rate limit.

Nada de esto adivina. Si una medición no se puede hacer, se reporta como `ND` (§3.2).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from flujocero.sources.base import LegalTier, RobotsVerdict

API = "https://api.mercadolibre.com"
SITIO = "MLC"  # Chile
TIMEOUT = 30.0
INTENTOS = 4

TRANSITORIOS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ReadError,
)

# Lo que dice `config/fuentes.yml` hoy, con una advertencia de "a verificar" al lado.
# El RUNBOOK es explicito: no aceptar que el agente lo asuma sin medirlo.
CATEGORIA_SUPUESTA = "MLC1459"


class ErrorDeFuente(RuntimeError):
    """La API respondió algo que no podemos interpretar. Nunca se traga en silencio (§11)."""


class TokenInvalido(ErrorDeFuente):
    """El refresh token fue rechazado. Hay que repetir la autorizacion por navegador."""


@dataclass
class Medicion:
    """Una brecha del §G, con su respuesta y la evidencia que la respalda."""

    brecha: str
    pregunta: str
    respuesta: str
    evidencia: str = ""
    evidence_level: str = "V"

    def __str__(self) -> str:
        cuerpo = f"[{self.evidence_level}] {self.brecha}: {self.respuesta}"
        return f"{cuerpo}\n      {self.evidencia}" if self.evidencia else cuerpo


@dataclass
class ReporteMedicion:
    momento: datetime
    mediciones: list[Medicion] = field(default_factory=list)

    def __str__(self) -> str:
        cab = f"Mediciones de MercadoLibre · {self.momento:%Y-%m-%d %H:%M UTC}\n"
        return cab + "\n".join(f"  {m}" for m in self.mediciones)


# --------------------------------------------------------------------------- autenticacion


def renovar_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    cliente: httpx.Client | None = None,
) -> dict[str, Any]:
    """Canjea el refresh token por un access token. Devuelve la respuesta completa.

    **El refresh token es de un solo uso.** La respuesta trae uno nuevo y el que se envió
    queda muerto. Quien llame DEBE persistir el nuevo antes de hacer nada mas.
    """
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    try:
        r = cliente.post(
            f"{API}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise ErrorDeFuente(f"no se pudo alcanzar {API}/oauth/token: {exc}") from exc
    finally:
        if propio:
            cliente.close()
    if r.status_code in (400, 401):
        raise TokenInvalido(
            f"MercadoLibre rechazo el refresh token ({r.status_code}): {r.text[:300]}. "
            "Suele significar que ya fue usado: cada canje devuelve uno nuevo y mata el "
            "anterior. Hay que repetir la autorizacion por navegador."
        )
    if r.status_code != 200:
        raise ErrorDeFuente(f"/oauth/token respondio {r.status_code}: {r.text[:300]}")
    datos = r.json()
    if "access_token" not in datos:
        raise ErrorDeFuente(f"respuesta sin access_token: {list(datos)}")
    return dict(datos)


def guardar_refresh_token(nuevo: str, ruta_env: Path) -> None:
    """Reescribe `MELI_REFRESH_TOKEN` en el .env. Se llama ANTES de usar el access token.

    Si el proceso muriera entre el canje y el guardado, el token viejo ya estaria muerto y
    el nuevo perdido: habria que rehacer la autorizacion por navegador.
    """
    if not ruta_env.is_file():
        raise ErrorDeFuente(f"no existe {ruta_env}; no hay donde guardar el token nuevo")
    lineas = ruta_env.read_text(encoding="utf-8").splitlines()
    salida, visto = [], False
    for linea in lineas:
        if linea.startswith("MELI_REFRESH_TOKEN="):
            salida.append(f"MELI_REFRESH_TOKEN={nuevo}")
            visto = True
        else:
            salida.append(linea)
    if not visto:
        salida.append(f"MELI_REFRESH_TOKEN={nuevo}")
    ruta_env.write_text("\n".join(salida) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- cliente


class Meli:
    """Cliente autenticado. No recolecta todavía: mide (T-011)."""

    id = "meli"
    legal_tier: LegalTier = "api_oficial"
    parser_version = "meli/0.1.0"

    def __init__(
        self,
        access_token: str,
        user_agent: str,
        cliente: httpx.Client | None = None,
    ) -> None:
        self.access_token = access_token
        self.user_agent = user_agent
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    def robots_ok(self) -> RobotsVerdict:
        from flujocero.sources import robots_check

        return robots_check.verificar(
            f"{API}/sites/{SITIO}", self.user_agent, source_id=self.id, cliente=self._cliente
        )

    def _cabeceras(self, con_token: bool = True) -> dict[str, str]:
        h = {"User-Agent": self.user_agent, "accept": "application/json"}
        if con_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    @retry(
        retry=retry_if_exception_type(TRANSITORIOS),
        stop=stop_after_attempt(INTENTOS),
        wait=wait_exponential_jitter(initial=1, max=20),
        reraise=True,
    )
    def get(self, ruta: str, con_token: bool = True, **params: Any) -> httpx.Response:
        return self._cliente.get(f"{API}{ruta}", headers=self._cabeceras(con_token), params=params)

    def cerrar(self) -> None:
        self._cliente.close()

    # ------------------------------------------------------------------ mediciones §G

    def medir(self, ahora: datetime | None = None) -> ReporteMedicion:
        """Responde las brechas 1 a 4 del §G de `docs/01-fuentes.md`, con evidencia."""
        rep = ReporteMedicion(momento=ahora or datetime.now(UTC))
        rep.mediciones.append(self._brecha_1_categoria())
        rep.mediciones.append(self._brecha_2_bearer())
        rep.mediciones.append(self._brecha_3_tope())
        rep.mediciones.append(self._brecha_4_rate_limit())
        return rep

    def _brecha_1_categoria(self) -> Medicion:
        """¿Cuál es el ID real de la categoría de departamentos en MLC?"""
        r = self.get(f"/sites/{SITIO}/categories")
        if r.status_code != 200:
            return Medicion(
                "G1 · categoria",
                "ID real de inmuebles/departamentos en MLC",
                "ND",
                f"/sites/{SITIO}/categories respondio {r.status_code}",
                "ND",
            )
        raiz = [c for c in r.json() if "inmueble" in c.get("name", "").lower()]
        if not raiz:
            nombres = [c.get("name") for c in r.json()][:12]
            return Medicion(
                "G1 · categoria",
                "ID real de inmuebles/departamentos en MLC",
                "ND",
                f"ninguna categoria raiz dice 'inmueble'. Encontradas: {nombres}",
                "ND",
            )
        cat_inmuebles = raiz[0]
        detalle = self.get(f"/categories/{cat_inmuebles['id']}")
        hijos = detalle.json().get("children_categories", []) if detalle.status_code == 200 else []
        deptos = [h for h in hijos if "departamento" in h.get("name", "").lower()]
        elegido = deptos[0] if deptos else None
        coincide = elegido and elegido["id"] == CATEGORIA_SUPUESTA
        return Medicion(
            "G1 · categoria",
            "ID real de inmuebles/departamentos en MLC",
            (
                f"{cat_inmuebles['id']} = {cat_inmuebles['name']}"
                + (
                    f" · departamentos = {elegido['id']}"
                    if elegido
                    else " · sin hijo 'departamento'"
                )
            ),
            (
                f"supuesto en fuentes.yml: {CATEGORIA_SUPUESTA} -> "
                f"{'COINCIDE' if coincide else 'NO COINCIDE, corregir fuentes.yml'}"
                f" · hijos: {[(h['id'], h['name']) for h in hijos][:8]}"
            ),
        )

    def _brecha_2_bearer(self) -> Medicion:
        """¿`/sites/MLC/search` exige Bearer hoy? Se prueba con y sin."""
        con = self.get(f"/sites/{SITIO}/search", con_token=True, q="departamento", limit=1)
        sin = self.get(f"/sites/{SITIO}/search", con_token=False, q="departamento", limit=1)
        return Medicion(
            "G2 · bearer",
            "¿la busqueda exige token?",
            (
                "SI, exige token"
                if sin.status_code in (401, 403) and con.status_code == 200
                else "NO lo exige"
                if sin.status_code == 200
                else "indeterminado"
            ),
            f"con token: HTTP {con.status_code} · sin token: HTTP {sin.status_code}",
            "V" if con.status_code == 200 or sin.status_code == 200 else "ND",
        )

    def _brecha_3_tope(self) -> Medicion:
        """¿Cuál es el tope real de resultados paginando con offset?"""
        r = self.get(f"/sites/{SITIO}/search", q="departamento", limit=1)
        if r.status_code != 200:
            return Medicion(
                "G3 · tope", "tope real de resultados", "ND", f"HTTP {r.status_code}", "ND"
            )
        total = r.json().get("paging", {}).get("total")
        topes = []
        for offset in (950, 1000, 4000):
            rr = self.get(f"/sites/{SITIO}/search", q="departamento", limit=1, offset=offset)
            topes.append(f"offset={offset}: HTTP {rr.status_code}")
            if rr.status_code != 200:
                break
            time.sleep(0.4)
        return Medicion(
            "G3 · tope",
            "tope real de resultados",
            f"total declarado {total}",
            " · ".join(topes) + ". Sobre el tope hay que usar search_type=scan",
        )

    def _brecha_4_rate_limit(self, n: int = 12) -> Medicion:
        """¿Cuál es el rate limit? Se mide con una ráfaga corta y se leen las cabeceras."""
        codigos, cabeceras = [], {}
        t0 = time.monotonic()
        for _ in range(n):
            r = self.get(f"/sites/{SITIO}/search", q="departamento", limit=1)
            codigos.append(r.status_code)
            for k, v in r.headers.items():
                if "ratelimit" in k.lower() or k.lower() == "retry-after":
                    cabeceras[k] = v
            if r.status_code == 429:
                break
        dur = time.monotonic() - t0
        golpeado = 429 in codigos
        return Medicion(
            "G4 · rate limit",
            "limite numerico de peticiones",
            (
                f"429 tras {codigos.index(429)} peticiones en {dur:.1f}s"
                if golpeado
                else f"{len(codigos)} peticiones en {dur:.1f}s sin 429"
            ),
            (
                f"cabeceras: {cabeceras}"
                if cabeceras
                else "la API no publica cabeceras de rate limit"
            ),
            "V" if cabeceras or golpeado else "D",
        )


def desde_entorno(
    entorno: dict[str, str], ruta_env: Path, cliente: httpx.Client | None = None
) -> Meli:
    """Renueva el token, **persiste el nuevo refresh token** y devuelve el cliente listo."""
    faltan = [
        k
        for k in ("MELI_CLIENT_ID", "MELI_CLIENT_SECRET", "MELI_REFRESH_TOKEN")
        if not entorno.get(k, "").strip()
    ]
    if faltan:
        raise ErrorDeFuente(f"faltan en el .env: {', '.join(faltan)}")
    datos = renovar_token(
        entorno["MELI_CLIENT_ID"].strip(),
        entorno["MELI_CLIENT_SECRET"].strip(),
        entorno["MELI_REFRESH_TOKEN"].strip(),
        cliente,
    )
    nuevo = datos.get("refresh_token")
    if nuevo:
        # ANTES de usar el access token: si el proceso muere aca, el viejo ya no sirve.
        guardar_refresh_token(nuevo, ruta_env)
    ua = entorno.get("USER_AGENT", "").strip() or "FlujoCero-ResearchBot/1.0"
    return Meli(access_token=datos["access_token"], user_agent=ua, cliente=cliente)


def ocultar_token(texto: str) -> str:
    """El access token nunca entra a un log ni a la base."""
    return re.sub(r"APP_USR-[\w-]+", "APP_USR-OCULTO", texto)
