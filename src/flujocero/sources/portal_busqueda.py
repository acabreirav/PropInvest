"""Portal Inmobiliario — colector vivo, **solo por la ruta que el `robots.txt` permite**.

Tarea T-920. Es el reemplazo del scraper heredado, y las diferencias importan más que el
parecido:

| | legado (`investop`) | este |
|---|---|---|
| ruta | fichas `/MLC-...` | listados `_Desde_`, las únicas permitidas |
| identidad | User-Agent de Chrome falso | el `USER_AGENT` declarado de Flujo Cero |
| navegador | `--disable-blink-features=AutomationControlled` | ninguno: `httpx` a secas |
| sesión | autenticado con la cuenta del usuario | **anónimo** |
| moneda | `float`, UF fija en 38.000 | `Decimal`, UF desde `dim_tiempo_financiero` |
| procedencia | ninguna | las seis columnas del §3.1 |

**Por qué la ruta `_Desde_` alcanza.** El §13.6 del contrato dice que el `robots.txt` del
portal bloquea `/propiedades/` y permite solo `/*_Desde_`. Verificado contra el corpus real:
de 48 tarjetas por página, **38 son unidades individuales con precio exacto, dormitorios,
baños, m² útiles y barrio**. Las otras 10 son proyectos, que publican rangos y "desde".
Todo lo que el motor necesita para rankear stock usado está en territorio permitido, así que
la aprobación D-016 queda de respaldo y no de vía principal — que es el orden del §3.5.

**La página 1 también se pide con `_Desde_1`.** El portal la sirve sin sufijo, pero esa forma
no calza con `/*_Desde_` y quedaría fuera de lo permitido. Pedirla con offset 1 devuelve lo
mismo y se mantiene dentro de la regla.

**Sobre la identidad.** Lo que el scraper anterior arriesgaba no era una IP: era la cuenta de
MercadoLibre del usuario, con la que compra. Este colector no se autentica. Si el portal
responde 403 a un cliente honesto, se acata y se registra; el §3.5 ya dice qué significa
necesitar proxies o disfraces para entrar.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from flujocero.sources.base import (
    LegalTier,
    RawDoc,
    RobotsVerdict,
    SelfTestReport,
    escribir_crudo,
)
from flujocero.sources.portal_comun import (
    BASE_URL,
    a_decimal,
    a_entero,
    anonimizar,
    cargar_avisos,
    slug,
    texto_seguro,
    tipologia_de,
    url_segura,
)

log = logging.getLogger(__name__)

SOURCE_ID = "portal_busqueda"
PARSER_VERSION = "portal_busqueda/1.0.0"
TIMEOUT = 30.0
INTENTOS = 4
POR_PAGINA = 48  # tamaño de página estándar de MercadoLibre, verificado en el corpus

# Pausa entre peticiones. El scraper anterior usaba 3–5 s y no fue bloqueado en 6.229 fichas;
# se conserva ese rango. Un colector cortés es también un colector que sigue funcionando.
PAUSA_MIN, PAUSA_MAX = 3.0, 5.0

TRANSITORIOS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ReadError,
)

TIPOS = {"usadas": "propiedades-usadas", "nuevas": "propiedades-nuevas", "proyectos": "proyectos"}

RANGOS = {
    ("venta", "UF"): (Decimal(500), Decimal(60_000)),
    ("venta", "CLP"): (Decimal(20_000_000), Decimal(3_000_000_000)),
    ("arriendo", "CLP"): (Decimal(50_000), Decimal(5_000_000)),
    ("arriendo", "UF"): (Decimal(1), Decimal(150)),
}
RANGO_M2 = (Decimal(15), Decimal(400))


class ErrorDeFuente(RuntimeError):
    """La respuesta no se pudo interpretar. Nunca se traga en silencio (§11)."""


class Bloqueado(ErrorDeFuente):
    """El portal rechazó a un cliente honesto. Se acata: no se insiste disfrazado."""


# ------------------------------------------------------------------------------------ URL


# Las regiones que el alcance del §10 puede pedir. El slug es el que usa el PORTAL en su
# URL, no el nombre oficial de la region, y **no se adivina**: cada uno se verifica con
# `cli probar-comunas` contra el sitio antes de recolectar. Un slug mal puesto no da error
# obvio — el portal responde 200 con cero resultados y la corrida "funciona" sin traer nada.
REGIONES = ("metropolitana", "bio-bio", "biobio", "coquimbo", "antofagasta", "valparaiso")


def url_busqueda(
    operacion: str,
    comuna_slug: str,
    offset: int = 1,
    tipo: str | None = None,
    region_slug: str = "metropolitana",
) -> str:
    """Construye la URL de listado. **Siempre con `_Desde_`**, incluso la primera página.

    El portal sirve la página 1 sin sufijo, pero esa forma no calza con el patrón `/*_Desde_`
    que el `robots.txt` permite. `_Desde_1` devuelve lo mismo y queda dentro de la regla.
    Elegir la URL permitida cuando existe una equivalente no cuesta nada y evita discutir
    después si el colector estaba autorizado.
    """
    if operacion not in ("venta", "arriendo"):
        raise ValueError(f"operacion invalida: {operacion!r}")
    partes = [BASE_URL, operacion, "departamento"]
    if tipo:
        if tipo not in TIPOS:
            raise ValueError(f"tipo invalido: {tipo!r}; usa uno de {sorted(TIPOS)}")
        partes.append(TIPOS[tipo])
    if not region_slug:
        raise ValueError("falta el slug de region: sin el la URL apunta a otra parte del pais")
    partes.append(f"{comuna_slug}-{region_slug}_Desde_{max(1, offset)}")
    return "/".join(partes)


def offset_de_pagina(pagina: int) -> int:
    """Página 1 -> offset 1; página 2 -> 49; página 3 -> 97."""
    return (max(1, pagina) - 1) * POR_PAGINA + 1


# --------------------------------------------------------------------------------- modelo


@dataclass(frozen=True)
class Tarjeta:
    """Una tarjeta del listado. Es el aviso completo para lo que el motor necesita."""

    portal_id: str
    operacion: str
    url: str
    fetched_at: datetime
    titulo: str | None
    monto: Decimal
    moneda: str
    dormitorios: int | None
    banos: int | None
    m2_utiles: Decimal | None
    comuna_nombre: str | None
    barrio: str | None
    es_proyecto: bool
    # Sale de la RUTA de busqueda (`/propiedades-usadas/`), que es un filtro del portal.
    # Es informacion declarada, no una inferencia sobre el titulo. `None` cuando se busco
    # sin filtro de tipo y por lo tanto el portal no lo dice.
    es_vivienda_nueva: bool | None
    raw_blob_path: str
    robots_snapshot_sha: str

    @property
    def comuna_id(self) -> str | None:
        return slug(self.comuna_nombre) if self.comuna_nombre else None

    @property
    def microzona_id(self) -> str | None:
        if not (self.comuna_nombre and self.barrio):
            return None
        return f"{slug(self.comuna_nombre)}/{slug(self.barrio)}"

    @property
    def microzona_nombre(self) -> str | None:
        return (
            f"{self.comuna_nombre} - {self.barrio}" if self.comuna_nombre and self.barrio else None
        )

    @property
    def tipologia(self) -> str | None:
        return tipologia_de(self.dormitorios, self.banos)

    @property
    def precio_uf(self) -> Decimal | None:
        return self.monto if self.operacion == "venta" and self.moneda == "UF" else None

    @property
    def arriendo_clp(self) -> Decimal | None:
        return self.monto if self.operacion == "arriendo" and self.moneda == "CLP" else None

    @property
    def arriendo_uf(self) -> Decimal | None:
        return self.monto if self.operacion == "arriendo" and self.moneda == "UF" else None


# --------------------------------------------------------------------------------- parser


def _texto(nodo: Any, selector: str) -> str:
    n = nodo.css_first(selector)
    return n.text(strip=True) if n else ""


def comuna_de_la_url(url: str) -> str | None:
    """`.../propiedades-usadas/san-miguel-metropolitana_Desde_1` -> `'san-miguel'`.

    Es el filtro de busqueda: la comuna que el portal aplico, no una deduccion.
    """
    # La comuna y la region llevan guiones las dos (`san-miguel-metropolitana`), asi que
    # partir por el ultimo guion no sirve: hay que anclar contra las regiones conocidas.
    m = re.search(rf"/([a-z0-9-]+)-(?:{'|'.join(REGIONES)})_Desde_", url)
    return m.group(1) if m else None


def _ubicacion(texto: str, comuna_url: str | None = None) -> tuple[str | None, str | None]:
    """Devuelve `(comuna, barrio)` de una tarjeta.

    **La comuna sale del filtro de busqueda, no del texto de la tarjeta.** El texto es
    irregular y no hay forma de saber por su forma que parte es que:

        "Milán 1242, El Llano, San Miguel"     -> direccion, barrio, comuna
        "Apoquindo 4900, Barrio El Golf"       -> direccion, barrio       (sin comuna)
        "Barrio Italia"                        -> barrio                  (sin comuna)

    Contando desde el final salian 46 comunas donde habia 6: "El Llano", "Plaza Egaña" y
    "Metro Ñuñoa" entraron a `dim_comuna` como si fueran municipios. Eso rompe la microzona,
    que es la clave de todo el analisis (§2.4).

    El filtro que el portal aplico —`san-miguel-metropolitana` en la URL— es un dato duro y
    siempre esta. El barrio es la ultima parte del texto que no sea la comuna misma.
    """
    partes = [x.strip() for x in (texto or "").split(",") if x.strip()]
    if not comuna_url:
        # Sin URL de busqueda no hay ancla; se cae a la heuristica vieja, que es lo unico
        # disponible. Pasa solo en tests que parsean una tarjeta suelta.
        if len(partes) >= 2:
            return partes[-1], partes[-2]
        return (partes[0], None) if partes else (None, None)

    # Si el texto trae la comuna escrita, se usa esa forma: conserva tildes y la ñ, que el
    # slug pierde. Si no, se prettifica el slug ("san-miguel" -> "San Miguel").
    escrita = next((x for x in partes if slug(x) == comuna_url), None)
    comuna = escrita or comuna_url.replace("-", " ").title()

    candidatos = [x for x in partes if slug(x) != comuna_url]
    barrio = candidatos[-1] if candidatos else None
    # Una direccion no es un barrio: si lo unico que queda tiene numeros, no se inventa uno.
    if barrio and any(ch.isdigit() for ch in barrio):
        barrio = None
    return comuna, barrio


def _atributos(tarjeta: Any) -> tuple[int | None, int | None, Decimal | None]:
    """`['3 dormitorios', '3 baños', '113 m² útiles']` -> `(3, 3, 113)`.

    Un proyecto publica `'1 a 2 dormitorios'` y `'35 - 61 m² útiles'`: `a_entero` y
    `a_decimal` devuelven `None` ante un rango, así que el proyecto queda con sus campos en
    ND en vez de con un número inventado.
    """
    dorm = banos = None
    m2: Decimal | None = None
    for li in tarjeta.css(".poly-attributes_list li, .poly-attributes-list__item"):
        t = li.text(strip=True).lower()
        if "dormitorio" in t:
            dorm = a_entero(t)
        elif "baño" in t or "bano" in t:
            banos = a_entero(t)
        elif "m²" in t or "m2" in t:
            m2 = a_decimal(t)
    return dorm, banos, m2


def _es_proyecto(tarjeta: Any) -> bool:
    """Un proyecto publica "Desde UF X" y un conteo de unidades disponibles.

    El §B1 exige el precio REAL por unidad: un "desde" no lo es, y por eso el proyecto se
    marca y después se carga con `evidence_level` `E`, que el §12 ya excluye del ranking.
    """
    t = tarjeta.text()
    return "Desde" in t or "unidades disponibles" in t or "PROYECTO" in t.upper()


def tipo_de_la_ruta(url: str) -> bool | None:
    """`/propiedades-usadas/` -> False (no es nueva). `/proyectos/` -> True. Sin filtro -> ND."""
    if "/propiedades-usadas/" in url:
        return False
    if "/propiedades-nuevas/" in url or "/proyectos/" in url:
        return True
    return None


def contar_tarjetas_en_html(html: str) -> int:
    """Cuantas tarjetas hay en la pagina, ANTES de exigirles nada.

    Existe para que la cobertura del §7.1 se mida contra el denominador correcto. El parser
    descarta en silencio la tarjeta sin enlace `MLC-`, sin texto de precio, o con un precio
    que no se puede leer — y despues `selftest` reportaba `precio 100%` **porque medía sobre
    las que sobrevivieron**. Toda tarjeta que llega al final tiene precio por construccion,
    asi que ese 100% era una tautologia con cara de metrica: no podia bajar nunca, ni cuando
    el portal cambiara el selector de precio y se perdiera la mitad del lote.

    Es el mismo selector que usa `parse_busqueda`; si uno cambia, el otro tiene que cambiar.
    """
    tree = HTMLParser(html)
    return len(tree.css(".poly-card") or tree.css("li.ui-search-layout__item"))


def parse_busqueda(
    html: str,
    url_pagina: str,
    operacion: str,
    fetched_at: datetime,
    blob: str,
    sha: str,
) -> list[Tarjeta]:
    """Parseo puro de una página de listado: sin I/O, sin reloj, sin red."""
    es_nueva = tipo_de_la_ruta(url_pagina)
    comuna_url = comuna_de_la_url(url_pagina)
    tree = HTMLParser(html)
    tarjetas = tree.css(".poly-card") or tree.css("li.ui-search-layout__item")
    salida: list[Tarjeta] = []
    vistos: set[str] = set()

    for c in tarjetas:
        enlace = c.css_first("a[href]")
        href = (enlace.attributes or {}).get("href", "") if enlace else ""
        m = re.search(r"/(MLC-\d+)", href)
        if not m:
            continue
        portal_id = m.group(1)
        if portal_id in vistos:
            continue  # la misma tarjeta aparece dos veces (imagen y titulo enlazan igual)
        vistos.add(portal_id)

        precio_txt = _texto(c, ".poly-price__current, .andes-money-amount")
        if not precio_txt:
            continue
        moneda = "UF" if "UF" in precio_txt.upper() else "CLP"
        monto = a_decimal(precio_txt)
        if monto is None:
            continue

        dorm, banos, m2 = _atributos(c)
        comuna, barrio = _ubicacion(_texto(c, ".poly-component__location"), comuna_url)

        t = Tarjeta(
            portal_id=portal_id,
            operacion=operacion,
            # El titulo lo escribe el vendedor y a veces mete su celular; la URL lo arrastra.
            url=url_segura(href.split("#")[0].split("?")[0], portal_id),
            fetched_at=fetched_at,
            titulo=texto_seguro(_texto(c, ".poly-component__title")) or None,
            monto=monto,
            moneda=moneda,
            dormitorios=dorm,
            banos=banos,
            m2_utiles=m2,
            comuna_nombre=comuna,
            barrio=barrio,
            es_proyecto=_es_proyecto(c),
            es_vivienda_nueva=es_nueva,
            raw_blob_path=blob,
            robots_snapshot_sha=sha,
        )
        if plausible(t):
            salida.append(t)
    return salida


def plausible(t: Tarjeta) -> bool:
    """Rangos del §7.1 por `(operacion, moneda)`. Fuera de rango se descarta la fila entera;
    nunca se corrige el valor ni se le cambia la moneda para que calce."""
    rango = RANGOS.get((t.operacion, t.moneda))
    if rango is None or not (rango[0] <= t.monto <= rango[1]):
        return False
    return not (t.m2_utiles is not None and not (RANGO_M2[0] <= t.m2_utiles <= RANGO_M2[1]))


# ------------------------------------------------------------------------------- colector


class PortalBusqueda:
    """Colector vivo. Implementa el contrato `Source` del §7.1."""

    id = SOURCE_ID
    legal_tier: LegalTier = "html_permitido"
    parser_version = PARSER_VERSION

    def __init__(
        self,
        user_agent: str,
        cliente: httpx.Client | None = None,
        pausa: tuple[float, float] = (PAUSA_MIN, PAUSA_MAX),
        raiz_cruda: Any = None,
        semilla: int | None = None,
    ) -> None:
        if not user_agent or "Mozilla" in user_agent:
            # Un UA de navegador seria disfrazarse, y el §3.5 y D-016 lo excluyen: la
            # aprobacion cubre recolectar, no esquivar. Ademas es lo que hacia el scraper
            # anterior, y es justo lo que este colector viene a no hacer.
            raise ValueError(
                "el User-Agent debe ser el declarado de Flujo Cero, no uno de navegador"
            )
        self.user_agent = user_agent
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        self.pausa = pausa
        self.raiz_cruda = raiz_cruda
        self._azar = random.Random(semilla)
        self._veredicto: RobotsVerdict | None = None

    def robots_ok(self) -> RobotsVerdict:
        """Se verifica contra una URL `_Desde_` real, no contra la raíz del sitio.

        Preguntar por el host y no por la ruta daría un permiso que no es el que se va a
        usar: acá lo que importa es si `/*_Desde_` está permitido, no si el dominio existe.
        """
        from flujocero.sources import robots_check

        if self._veredicto is None:
            self._veredicto = robots_check.verificar(
                url_busqueda("venta", "nunoa", 49),
                self.user_agent,
                source_id=self.id,
                cliente=self._cliente,
            )
        return self._veredicto

    def _dormir(self) -> None:
        time.sleep(self._azar.uniform(*self.pausa))

    @retry(
        retry=retry_if_exception_type(TRANSITORIOS),
        stop=stop_after_attempt(INTENTOS),
        wait=wait_exponential_jitter(initial=2, max=30),
        reraise=True,
    )
    def _pedir(self, url: str) -> httpx.Response:
        return self._cliente.get(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-CL,es;q=0.9",
            },
        )

    def collect(
        self,
        comunas: list[str] | list[tuple[str, str]],
        operaciones: tuple[str, ...] = ("venta", "arriendo"),
        max_paginas: int = 10,
        tipo: str | None = None,
        ahora: datetime | None = None,
    ) -> list[RawDoc]:
        """Recorre los listados permitidos y escribe a la zona cruda, anonimizando primero.

        `comunas` acepta slugs sueltos —que se asumen de la Region Metropolitana, que es lo
        que habia antes— o pares `(comuna, region)`. La region importa desde que el alcance
        del §10 incluye fase 3: Gran Concepcion, La Serena y Antofagasta no estan en la RM, y
        con el slug de region equivocado el portal responde **200 con cero resultados**. No
        da error: la corrida "funciona" y no trae nada.

        `ahora` entra por argumento para que los tests sean deterministas (§11).
        """
        veredicto = self.robots_ok()
        if not veredicto.allowed:
            # §3.5: robots_check pasa ANTES de recolectar, no despues.
            raise ErrorDeFuente(f"robots.txt no permite esta ruta: {veredicto.motivo}")

        momento = ahora or datetime.now(UTC)
        docs: list[RawDoc] = []
        for operacion in operaciones:
            for entrada in comunas:
                comuna, region = (
                    entrada if isinstance(entrada, tuple) else (entrada, "metropolitana")
                )
                for pagina in range(1, max_paginas + 1):
                    url = url_busqueda(
                        operacion, comuna, offset_de_pagina(pagina), tipo, region_slug=region
                    )
                    if docs:
                        self._dormir()
                    r = self._pedir(url)
                    if r.status_code == 404:
                        break  # se acabaron las paginas de esta comuna
                    if r.status_code in (403, 429):
                        raise Bloqueado(
                            f"el portal respondio {r.status_code} a un cliente honesto en "
                            f"{url}. No se reintenta disfrazado: el §3.5 dice que necesitar "
                            f"disfraz es senal de estar en la categoria equivocada."
                        )
                    if r.status_code != 200:
                        raise ErrorDeFuente(f"{url} respondio {r.status_code}")

                    limpio, _ = anonimizar(r.content)
                    doc = escribir_crudo(
                        source_id=self.id,
                        url=url,
                        contenido=limpio,
                        momento=momento,
                        robots_snapshot_sha=veredicto.snapshot_sha,
                        nombre=f"{operacion}_{comuna}_p{pagina:02d}",
                        raiz=self.raiz_cruda,
                        parser_version=self.parser_version,
                    )
                    docs.append(doc)

                    tarjetas = self.parse(doc)
                    log.info(
                        "%s %s pagina %d: %d tarjetas", operacion, comuna, pagina, len(tarjetas)
                    )
                    if len(tarjetas) < POR_PAGINA // 2:
                        break  # pagina incompleta: es la ultima
        return docs

    def parse(self, doc: RawDoc) -> list[Tarjeta]:
        operacion = "arriendo" if "/arriendo/" in doc.url else "venta"
        return parse_busqueda(
            doc.contenido.decode("utf-8", errors="ignore"),
            doc.url,
            operacion,
            doc.fetched_at,
            str(doc.ruta),
            doc.robots_snapshot_sha,
        )

    def selftest(
        self, docs: list[RawDoc], filas_corrida_anterior: int | None = None
    ) -> SelfTestReport:
        """§7.1 sobre lo recolectado: cobertura, rangos y detector de parser roto."""
        tarjetas = [t for d in docs for t in self.parse(d)]
        rep = SelfTestReport(source_id=self.id, ok=True, n_filas=len(tarjetas))
        rep.n_filas_corrida_anterior = filas_corrida_anterior

        unidades = [t for t in tarjetas if not t.es_proyecto]
        u = len(unidades) or 1
        n = len(tarjetas) or 1
        # El denominador son las tarjetas que hay en el HTML, no las que sobrevivieron al
        # parseo. Con `1.0 if tarjetas` esto reportaba 100% siempre — ver
        # `contar_tarjetas_en_html`.
        en_html = sum(
            contar_tarjetas_en_html(d.contenido.decode("utf-8", errors="ignore")) for d in docs
        )
        cobertura = {
            "precio": len(tarjetas) / en_html if en_html else 0.0,
            "m2_utiles": sum(1 for t in unidades if t.m2_utiles is not None) / u,
            "dormitorios": sum(1 for t in unidades if t.dormitorios is not None) / u,
            "comuna": sum(1 for t in tarjetas if t.comuna_id) / n,
            "microzona": sum(1 for t in tarjetas if t.microzona_id) / n,
        }
        for campo in ("precio", "m2_utiles", "dormitorios", "comuna"):
            if cobertura[campo] >= 0.95:
                rep.pasar(f"cobertura_{campo}")
            else:
                rep.fallar(f"cobertura_{campo}", f"{cobertura[campo]:.1%} < 95%")

        if not tarjetas:
            rep.fallar("hay_filas", "ninguna tarjeta parseo: el portal cambio su HTML")

        caida = rep.caida_pct
        if caida is not None and caida > 0.30:
            rep.fallar("conteo_estable", f"cayo {caida:.1%} vs la corrida anterior")
        elif caida is not None:
            rep.pasar("conteo_estable")

        v = self.robots_ok()
        if v.allowed:
            rep.pasar("robots")
        else:
            rep.fallar("robots", v.motivo)

        rep.detalle["cobertura"] = " · ".join(f"{k} {v:.1%}" for k, v in cobertura.items())
        rep.detalle["proyectos"] = f"{1 - u / n:.1%} del lote (van con evidence_level E)"
        return rep

    def cerrar(self) -> None:
        self._cliente.close()


def cargar_en_duckdb(conexion: Any, tarjetas: list[Tarjeta]) -> int:
    """Mismo cargador compartido que usa el colector historico (§3.6, SCD tipo 2)."""
    return cargar_avisos(conexion, list(tarjetas), SOURCE_ID, PARSER_VERSION)


# ------------------------------------------------- ingesta de paginas de busqueda guardadas


def fecha_del_nombre(nombre: str) -> datetime | None:
    """`venta_san-miguel_p01_20260504.html` -> 2026-05-04 UTC."""
    m = re.search(r"_(\d{4})(\d{2})(\d{2})\.html$", nombre)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return datetime(y, mo, d, tzinfo=UTC)


def url_del_nombre(nombre: str) -> str | None:
    """Reconstruye la URL de listado que produjo ese archivo, en su forma permitida."""
    m = re.match(r"(venta|arriendo)_([a-z-]+)_p(\d+)_", nombre)
    if not m:
        return None
    operacion, comuna, pagina = m.group(1), m.group(2), int(m.group(3))
    return url_busqueda(operacion, comuna, offset_de_pagina(pagina), "usadas")


def ingerir_guardadas(
    origen: Any,
    raiz_cruda: Any = None,
    progreso: Any = None,
) -> list[RawDoc]:
    """Mete a la zona cruda paginas de listado ya descargadas, con su fecha real.

    Existe por una razon concreta y medida: **el portal publica precios distintos en la
    tarjeta y en la ficha**. Sobre 2.689 unidades presentes en las dos superficies del mismo
    dia, 48 tenian precios distintos, una de ellas UF 13.000 en la tarjeta contra UF 15.900
    en la ficha — misma unidad, mismo dia, mismo titulo, 22% de diferencia.

    Comparar una tarjeta de hoy contra una ficha de mayo inventaria cambios de precio que
    nunca ocurrieron. La linea base tiene que ser **tarjeta contra tarjeta**, y las paginas
    de listado de mayo ya estan en el disco del usuario.

    No toca la red: los documentos ya existen.
    """
    from pathlib import Path as _P

    carpeta = _P(str(origen))
    archivos = sorted(carpeta.glob("*.html")) if carpeta.is_dir() else []
    docs: list[RawDoc] = []
    for i, ruta in enumerate(archivos, 1):
        if progreso is not None:
            progreso(i, len(archivos))
        momento, url = fecha_del_nombre(ruta.name), url_del_nombre(ruta.name)
        if momento is None or url is None:
            continue
        limpio, _ = anonimizar(ruta.read_bytes())
        docs.append(
            escribir_crudo(
                source_id=SOURCE_ID,
                url=url,
                contenido=limpio,
                momento=momento,
                robots_snapshot_sha="historico:paginas-ya-descargadas",
                nombre=ruta.stem,
                raiz=raiz_cruda,
                parser_version=PARSER_VERSION,
            )
        )
    return docs
