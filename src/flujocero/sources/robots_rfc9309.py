"""Evaluacion de robots.txt segun el RFC 9309. Tarea T-926.

Existe porque el `RobotFileParser` de la libreria estandar **no implementa comodines**, y
eso hace que sub-bloquee: da permiso para rutas que el sitio prohibe.

Lo encontro una contraprueba en los tests de Gael el 30-ago-2026. Su robots.txt real dice
`Disallow: /admin/*` y el parser de la stdlib respondia `allowed=True` para `/admin/x`,
porque guarda la regla como el literal `/admin/%2A` — trata el asterisco como un caracter
mas. El RFC 9309 §2.2.3 define `*` como "cualquier secuencia" y `$` como fin de ruta.

**La direccion del error es la peligrosa.** Un verificador que sobre-bloquea deja pasar
recolecciones legitimas y molesta; uno que sub-bloquea **te hace pedir lo que el sitio
prohibio**, y el §3.5 del contrato es una regla dura, no una preferencia.

Reglas implementadas, todas del RFC 9309:

- §2.2.2 · Se elige el grupo cuyo `User-agent` calza mas especificamente con el nuestro;
  si ninguno calza, manda el grupo `*`. Sin grupo aplicable, no hay restriccion.
- §2.2.3 · `*` = cualquier secuencia (incluida la vacia). `$` al final ancla el fin de ruta.
- §2.2.2 · **Gana la regla cuyo patron es mas largo**, no la que aparece primero. Ante
  empate gana `Allow` — el RFC lo dice explicito, y es lo que hace que un
  `Allow: /a/b` conviva con un `Disallow: /a/`.
- §2.2.1 · Una linea sin `:` es malformada y se ignora. El robots real de Gael trae
  `Allow /general/public/*` sin los dos puntos: esa linea NO otorga permiso.

Modulo puro: sin red, sin reloj, sin estado. Entra texto y sale un veredicto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class Regla:
    """Una linea `Allow:` o `Disallow:` de un grupo."""

    permite: bool
    patron: str

    @property
    def especificidad(self) -> int:
        """El RFC ordena por longitud del patron, no por orden de aparicion."""
        return len(self.patron)


@dataclass(frozen=True)
class Grupo:
    """Un bloque `User-agent:` con sus reglas y su `Crawl-delay`."""

    agentes: tuple[str, ...]
    reglas: tuple[Regla, ...]
    crawl_delay: float | None = None


@dataclass(frozen=True)
class Veredicto:
    """Por que se permitio o se prohibio. El `porque` es para el humano que audite esto."""

    permitido: bool
    regla: Regla | None
    porque: str
    crawl_delay: float | None = None


def _normalizar(ruta: str) -> str:
    """Deja la ruta comparable: sin host, con el porcentaje resuelto una sola vez.

    El RFC 9309 §2.2.2 compara rutas ya decodificadas. Sin esto, `/a%2Fb` y `/a/b` se
    tratarian distinto segun quien las escriba.
    """
    if "://" in ruta:
        p = urlparse(ruta)
        ruta = p.path or "/"
        if p.query:
            ruta = f"{ruta}?{p.query}"
    if not ruta.startswith("/"):
        ruta = "/" + ruta
    return unquote(ruta)


def compilar(patron: str) -> re.Pattern[str]:
    """Traduce un patron del RFC 9309 a una expresion regular anclada al inicio.

    `*` es cualquier secuencia; `$` al final ancla el fin de la ruta. Todo lo demas se
    escapa, para que un `.` o un `+` en la ruta no se conviertan en comodines por accidente.
    """
    ancla_final = patron.endswith("$")
    cuerpo = patron[:-1] if ancla_final else patron
    partes = [re.escape(t) for t in cuerpo.split("*")]
    regex = ".*".join(partes)
    return re.compile("^" + regex + ("$" if ancla_final else ""))


def parsear(texto: str) -> list[Grupo]:
    """Convierte el texto de un robots.txt en grupos. Ignora lo malformado, sin adivinar."""
    grupos: list[Grupo] = []
    agentes: list[str] = []
    reglas: list[Regla] = []
    demora: float | None = None
    esperando_agentes = False  # varios `User-agent:` seguidos forman UN grupo

    def cerrar() -> None:
        nonlocal agentes, reglas, demora
        if agentes:
            grupos.append(Grupo(tuple(agentes), tuple(reglas), demora))
        agentes, reglas, demora = [], [], None

    for linea_cruda in texto.splitlines():
        linea = linea_cruda.split("#", 1)[0].strip()
        if not linea:
            continue
        if ":" not in linea:
            # §2.2.1: linea malformada. Se ignora. El robots real de Gael trae
            # `Allow /general/public/*` sin los dos puntos, y NO otorga permiso.
            continue
        campo, _, valor = linea.partition(":")
        campo = campo.strip().lower()
        valor = valor.strip()

        if campo == "user-agent":
            if not esperando_agentes:
                cerrar()
                esperando_agentes = True
            agentes.append(valor.lower())
            continue

        esperando_agentes = False
        if campo in ("allow", "disallow"):
            if campo == "disallow" and valor == "":
                # §2.2.2: `Disallow:` vacio no prohibe nada. Es un permiso, no una regla
                # de longitud cero que ganaria por especificidad.
                continue
            reglas.append(Regla(permite=campo == "allow", patron=valor))
        elif campo == "crawl-delay":
            try:
                demora = float(valor)
            except ValueError:
                continue
    cerrar()
    return grupos


def grupo_aplicable(grupos: list[Grupo], user_agent: str) -> Grupo | None:
    """§2.2.2 · gana el token de `User-agent` mas especifico que calce con el nuestro.

    El calce es por prefijo y sin distinguir mayusculas: un grupo `User-agent: claudebot`
    aplica a `ClaudeBot/1.0 (+http://...)`. El comodin `*` solo se usa si no calzo ninguno.
    """
    ua = user_agent.lower()
    mejor: Grupo | None = None
    mejor_largo = -1
    comodin: Grupo | None = None
    for g in grupos:
        for token in g.agentes:
            if token == "*":
                if comodin is None:
                    comodin = g
                continue
            if ua.startswith(token) or token in ua:
                if len(token) > mejor_largo:
                    mejor, mejor_largo = g, len(token)
    return mejor or comodin


def evaluar(texto: str, user_agent: str, url_o_ruta: str) -> Veredicto:
    """El veredicto del RFC 9309 para esta ruta y este user-agent."""
    grupos = parsear(texto)
    grupo = grupo_aplicable(grupos, user_agent)
    if grupo is None:
        return Veredicto(True, None, "el robots.txt no tiene ningun grupo aplicable")

    ruta = _normalizar(url_o_ruta)
    calzan = [r for r in grupo.reglas if compilar(r.patron).match(ruta)]
    if not calzan:
        return Veredicto(True, None, "ninguna regla del grupo calza con la ruta", grupo.crawl_delay)

    # §2.2.2 · gana el patron mas largo; ante empate gana Allow.
    ganadora = max(calzan, key=lambda r: (r.especificidad, r.permite))
    verbo = "Allow" if ganadora.permite else "Disallow"
    return Veredicto(
        ganadora.permite,
        ganadora,
        f"{verbo}: {ganadora.patron} (patron mas especifico de {len(calzan)} que calzan)",
        grupo.crawl_delay,
    )


__all__ = ["Grupo", "Regla", "Veredicto", "compilar", "evaluar", "grupo_aplicable", "parsear"]
