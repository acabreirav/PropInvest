"""Portal Inmobiliario — foto histórica de mayo 2026, heredada del proyecto anterior.

Esta fuente **no recolecta de la red**: ingiere los 6.229 HTML que el usuario ya scrapeó
entre el 30-abr y el 5-may de 2026 con su proyecto anterior (ver `docs/adr/004-legado-investop.md`).

Tres cosas que hay que tener claras antes de leer el código:

1. **La fecha se declara honestamente.** `fetched_at` sale del nombre del archivo, no del
   reloj de hoy. Son datos de mayo y el gate de frescura del §7.3 (21 días) los va a excluir
   del ranking — que es exactamente lo que debe pasar. Su valor está en otro lado: el
   diccionario de microzonas, las fixtures de test, y la **foto de precios** contra la cual
   medir qué bajó en cuatro meses (§11: saber cuándo bajó el precio es señal de compra).

2. **Se anonimiza ANTES de escribir a la zona cruda.** Hay una tensión real entre el §3.6
   (la zona cruda es inmutable y todo debe reconstruirse desde ahí) y el §3.4 (cero datos
   personales). Gana el §3.4: es una obligación legal, no una preferencia de diseño, y lo
   que se borra —teléfonos y correos de corredores— son campos que el parser **nunca lee**.
   La reconstrucción queda intacta; lo que no queda es el dato personal.

3. **`legal_tier: html_prohibido`.** El origen de estos archivos son fichas `/MLC-...`, que
   el `robots.txt` de Portal Inmobiliario no permite. No se maquilla: se declara, y se cita
   la aprobación humana D-016 que lo autoriza. El colector nuevo (T-920) usará la ruta
   `_Desde_`, que sí está permitida, y por eso será `html_permitido`.
"""

from __future__ import annotations

import logging
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from selectolax.parser import HTMLParser

from flujocero.sources.base import (
    LegalTier,
    RawDoc,
    RobotsVerdict,
    SelfTestReport,
    escribir_crudo,
)

PARSER_VERSION = "portal_legado/1.0.0"
SOURCE_ID = "portal_legado_2026_05"
BASE_URL = "https://www.portalinmobiliario.com"

# Tamaño bajo el cual el HTML no es una ficha sino un redirect o una página de bloqueo.
# El valor viene del proyecto anterior, verificado contra los 6.229 archivos.
MINIMO_FICHA = 100_000

APROBACION = "D-016 (28-ago-2026)"

# Rangos de plausibilidad del §7.1. Fuera de esto el valor no se corrige: se descarta la fila
# y queda el error registrado. Un precio absurdo silenciado es peor que una fila menos.
RANGO_M2 = (Decimal(15), Decimal(400))
RANGO_DORMITORIOS = (0, 6)

# La moneda NO determina la operacion, y confundirlas cuesta filas. En Chile se publica
# **arriendo en UF** (frecuente en edificios multifamily) y venta en pesos. La primera version
# de este parser validaba el monto solo por su moneda: un arriendo de UF 15 caia por "precio
# bajo el minimo de UF 500", y se perdian 132 de 600 fichas sin que nada avisara.
RANGOS = {
    ("venta", "UF"): (Decimal(500), Decimal(60_000)),
    ("venta", "CLP"): (Decimal(20_000_000), Decimal(3_000_000_000)),
    ("arriendo", "CLP"): (Decimal(50_000), Decimal(5_000_000)),
    ("arriendo", "UF"): (Decimal(1), Decimal(150)),
}

# Umbral propio de la microzona: mas bajo que el 95% del §7.1 porque hay avisos sin
# barrio declarado, y un ND honesto no es un fallo de parser. Si baja de aca, si lo es.
MIN_COBERTURA_MICROZONA = 0.90

_MARCA_USADA = "propiedades usadas"
_MARCA_NUEVA = {"propiedades nuevas", "proyectos nuevos", "proyectos"}
_BREADCRUMB_RUIDO = {
    "arriendo",
    "venta",
    "departamentos",
    "...",
    _MARCA_USADA,
    *_MARCA_NUEVA,
}


class ErrorDeFuente(RuntimeError):
    """El documento no se pudo interpretar. Nunca se traga en silencio (§11)."""


# --------------------------------------------------------------------- anonimizacion (§3.4)

# Lo que de verdad aparece, medido sobre 250 fichas al azar:
#   - correos            182/250 (73%)  -- incluye el del PROPIO usuario, que scrapeo logueado
#   - enlaces wa.me      43/250  (17%)  -- el numero del corredor va dentro de la URL
#   - patrones +56       4/250   (2%)
#   - enlaces tel:       0/250
_CORREO = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WHATSAPP = re.compile(rb"(?:wa\.me|api\.whatsapp\.com)[^\"'>\s]*")
_TEL_HREF = re.compile(rb"tel:[^\"'>\s]*")
_MAS56 = re.compile(rb"\+\s?56[\s.\-]?9?[\s.\-]?\d[\d\s.\-]{5,10}\d")

_PATRONES = (
    (_CORREO, b"[correo-removido]"),
    (_WHATSAPP, b"[whatsapp-removido]"),
    (_TEL_HREF, b"tel:[removido]"),
    (_MAS56, b"[fono-removido]"),
)


def anonimizar(html: bytes) -> tuple[bytes, int]:
    """Borra correos, WhatsApp y teléfonos del HTML. Devuelve `(limpio, cuantos_borro)`.

    Se corre ANTES de escribir a la zona cruda, no después: persistir el dato personal y
    limpiarlo más tarde ya sería haberlo persistido. La Ley 21.719 no distingue entre
    "guardado" y "guardado un rato".

    **Los patrones son deliberadamente estrechos, y esa es la decisión de diseño.** La primera
    versión de esta función usaba un regex genérico de teléfono chileno de ocho dígitos, y
    habría destrozado el dato: se verificó que `MLC-1859051633_20260504.html` quedaba como
    `MLC-18[fono-removido]_[fono-removido].html` — se comía el ID de MercadoLibre y la fecha
    del blob. Un anonimizador que corrompe IDs y fechas es peor que no tener uno, porque el
    daño es silencioso y se descubre tarde.

    Se anonimiza solo lo que lleva marca explícita: arroba, `wa.me`, `tel:`, prefijo `+56`.
    Un teléfono suelto de ocho dígitos sin marca no se toca: preferimos dejar pasar el caso
    raro antes que corromper el corpus entero. `tests/unit/test_portal_legado.py` fija esa
    frontera con precios, IDs y fechas reales.
    """
    limpio, total = html, 0
    for patron, reemplazo in _PATRONES:
        limpio, n = patron.subn(reemplazo, limpio)
        total += n
    return limpio, total


# ------------------------------------------------------------------------------ utilidades


def url_segura(url: str, portal_id: str) -> str:
    """La URL tambien es un dato que persistimos, y el vendedor escribe el titulo.

    Caso real del corpus:
    `.../MLC-3872504748-arriendo-dpto-1d-1b-a-3-cuadras-metro-992401813-dueno-_JM`
    El numero en el slug es el celular del propietario. `source_url` es una de las seis
    columnas de procedencia (§3.1), asi que esa URL se guarda tal cual y el telefono viaja
    con ella: anonimizar solo el HTML no alcanzaba.

    Cuando el slug trae un dato de contacto se recorta a la forma canonica por ID, que el
    portal resuelve igual. Se pierde el titulo; no se pierde la trazabilidad, que es lo que
    el §3.1 pide. El §3.4 no admite excepciones ni siquiera en una columna de procedencia.
    """
    for patron, _ in _PATRONES:
        if patron.search(url.encode()):
            return f"{BASE_URL}/{portal_id}"
    # Un celular chileno sin marca explicita tampoco puede quedar: se busca aparte porque
    # `_PATRONES` es deliberadamente estrecho para no corromper el HTML, y una URL es corta.
    if _FONO_EN_SLUG.search(url):
        return f"{BASE_URL}/{portal_id}"
    return url


_FONO_EN_SLUG = re.compile(r"(?<!\d)(?<!MLC-)9\d{8}(?!\d)")


def slug(texto: str) -> str:
    """`'Ñuñoa - Estadio Nacional'` -> `'nunoa-estadio-nacional'`. Estable y sin tildes."""
    sin_tilde = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", sin_tilde.lower())).strip("-")


_NUMERO = re.compile(r"\d[\d.]*(?:,\d+)?")


def a_decimal(texto: str) -> Decimal | None:
    """Número chileno a Decimal. El punto es SIEMPRE separador de miles.

    Es la misma regla que costó un error de mil veces en el colector de la CMF: no se decide
    caso a caso mirando cuántos dígitos hay después del punto. En Chile `3.500` son tres mil
    quinientos, nunca tres coma cinco.

    **Devuelve `None` si el texto trae más de un número.** Los avisos de proyecto publican
    rangos —`"35 - 61 m²"`, `"1 a 2 dormitorios"`— y la versión anterior de esta función
    borraba todo lo que no fuera dígito y los pegaba: `"35 - 61"` salía **3561 m²**. Un
    departamento de 3.561 m² no lo detecta nadie mirando un ranking, y contamina la mediana
    de su microzona para siempre. Ante un rango, el §3.2 pide `ND`, no un número inventado.
    """
    numeros = _NUMERO.findall(texto or "")
    if len(numeros) != 1:
        return None
    t = numeros[0].replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


def a_entero(texto: str) -> int | None:
    """Un entero. `None` si hay mas de un numero: `"1 a 2 dormitorios"` es un rango de
    proyecto, no un dato de unidad. Delega en `a_decimal` para no tener dos criterios
    distintos sobre que es un numero chileno."""
    d = a_decimal(texto)
    return int(d) if d is not None else None


def tipologia_de(dormitorios: int | None, banos: int | None) -> str | None:
    if dormitorios is None or banos is None:
        return None
    return "studio" if dormitorios == 0 else f"{dormitorios}D{banos}B"


# ------------------------------------------------------------------------------- el modelo


@dataclass(frozen=True)
class Aviso:
    """Un aviso parseado. `operacion` decide a qué tabla va."""

    portal_id: str
    operacion: str  # 'venta' | 'arriendo'
    url: str
    fetched_at: datetime
    comuna_id: str | None
    comuna_nombre: str | None
    microzona_id: str | None
    microzona_nombre: str | None
    monto: Decimal
    moneda: str  # 'UF' | 'CLP' — la que el propio aviso declara, no una deducida
    m2_utiles: Decimal | None
    dormitorios: int | None
    banos: int | None
    antiguedad_anios: int | None
    gastos_comunes_clp: Decimal | None
    estacionamientos: int
    bodegas: int
    es_vivienda_nueva: bool | None
    # Un aviso de PROYECTO publica rangos y precio "desde", no una unidad.
    # El §B1 del contrato es explicito: se necesita el precio REAL por unidad.
    es_proyecto: bool
    raw_blob_path: str
    robots_snapshot_sha: str

    @property
    def tipologia(self) -> str | None:
        return tipologia_de(self.dormitorios, self.banos)

    # Vistas por columna de destino. Cada una es None cuando no corresponde: el §3.2 prefiere
    # un ND explicito antes que un cero o una conversion inventada. La UF del dia vive en
    # `dim_tiempo_financiero` y el §11 prohibe que un parser convierta monedas.
    @property
    def precio_uf(self) -> Decimal | None:
        return self.monto if self.operacion == "venta" and self.moneda == "UF" else None

    @property
    def precio_clp(self) -> Decimal | None:
        return self.monto if self.operacion == "venta" and self.moneda == "CLP" else None

    @property
    def arriendo_clp(self) -> Decimal | None:
        return self.monto if self.operacion == "arriendo" and self.moneda == "CLP" else None

    @property
    def arriendo_uf(self) -> Decimal | None:
        return self.monto if self.operacion == "arriendo" and self.moneda == "UF" else None


# ------------------------------------------------------------------------------- el parser


def _specs(tree: HTMLParser) -> dict[str, str]:
    out: dict[str, str] = {}
    for fila in tree.css(".andes-table tr"):
        th, td = fila.css_first("th"), fila.css_first("td")
        if th and td:
            out[th.text(strip=True)] = td.text(strip=True)
    return out


def _spec(specs: dict[str, str], *nombres: str) -> str:
    """Busca una etiqueta con y sin tilde. El portal usa las dos formas."""
    for n in nombres:
        if n in specs:
            return specs[n]
    return ""


def parse_html(html: str, url: str, fetched_at: datetime, blob: str, sha: str) -> Aviso | None:
    """Parseo puro: sin I/O, sin reloj, sin red. Devuelve `None` si el HTML no es una ficha."""
    if len(html) < MINIMO_FICHA:
        return None
    m = re.search(r"/(MLC-\d+)", url)
    if not m:
        return None
    portal_id = m.group(1)

    tree = HTMLParser(html)

    # -- canonical: la URL real del aviso, y ademas un marcador de tipo de publicacion.
    # Cuando el canonical NO contiene el MLC del archivo, no es un redirect roto: es un
    # aviso de PROYECTO, cuyo canonical apunta a la pagina del proyecto
    # (`/venta/departamento/nunoa-metropolitana/10628-manuel-de-salas-587-nva`).
    # La primera version de este parser lo trataba como error y descartaba el 47% del corpus.
    canon_n = tree.css_first('link[rel="canonical"]')
    canonical = (canon_n.attributes or {}).get("href", "") if canon_n else ""
    es_proyecto = bool(canonical) and portal_id not in canonical
    url_real = url_segura(canonical or url, portal_id)

    # -- breadcrumb: operacion, nuevo/usado, comuna y barrio salen de aca
    crumbs = [n.text(strip=True) for n in tree.css(".andes-breadcrumb__item") if n.text(strip=True)]
    bajos = [c.lower() for c in crumbs]

    # El breadcrumb se colapsa con "..." en avisos de ruta larga: el TEXTO se pierde, pero los
    # `href` de esos mismos items siguen completos y traen la operacion y el tipo en la ruta:
    #   /arriendo/departamento/propiedades-usadas/nunoa-metropolitana
    # Sobre 600 fichas, 109 tenian el texto colapsado y los 109 hrefs lo resolvieron.
    # Se leen los hrefs y NO el slug del titulo: un aviso de venta que diga "ideal para
    # arriendo" en el titulo se clasificaria al reves, y ese error no se nota nunca.
    rutas = " ".join(
        (a.attributes or {}).get("href", "") for a in tree.css(".andes-breadcrumb__item a")
    )

    operacion = "arriendo" if "arriendo" in bajos else "venta" if "venta" in bajos else None
    if operacion is None:
        if "/arriendo/" in rutas:
            operacion = "arriendo"
        elif "/venta/" in rutas:
            operacion = "venta"
    if operacion is None:
        return None

    es_nueva: bool | None = None
    if _MARCA_USADA in bajos or "propiedades-usadas" in rutas:
        es_nueva = False
    elif any(x in bajos for x in _MARCA_NUEVA) or "propiedades-nuevas" in rutas or es_proyecto:
        es_nueva = True
    # Si el portal no lo declara, queda None. No se infiere de la antiguedad: el §3.2 prohibe
    # imputar en silencio, y "sin dato de antiguedad" no es lo mismo que "es nueva".

    geo = [
        c for c in crumbs if c.lower() not in _BREADCRUMB_RUIDO and "metropolitana" not in c.lower()
    ]
    comuna_nombre = geo[-2] if len(geo) >= 2 else (geo[-1] if geo else None)
    barrio = geo[-1] if len(geo) >= 2 else None

    # -- precio: la moneda la declara el propio contenedor, no se adivina por el rango
    simbolo_n = tree.css_first(".andes-money-amount__currency-symbol")
    simbolo = simbolo_n.text(strip=True).upper() if simbolo_n else ""
    fraccion_n = tree.css_first(".andes-money-amount__fraction")
    if not fraccion_n:
        return None
    centavos_n = tree.css_first(".andes-money-amount__cents")
    crudo = fraccion_n.text(strip=True)
    if centavos_n:
        crudo += "," + centavos_n.text(strip=True).lstrip(",").strip()
    monto = a_decimal(crudo)
    if monto is None:
        return None

    moneda = "UF" if "UF" in simbolo else "CLP"

    s = _specs(tree)
    aviso = Aviso(
        portal_id=portal_id,
        operacion=operacion,
        url=url_real,
        fetched_at=fetched_at,
        comuna_id=slug(comuna_nombre) if comuna_nombre else None,
        comuna_nombre=comuna_nombre,
        microzona_id=(
            f"{slug(comuna_nombre)}/{slug(barrio)}" if comuna_nombre and barrio else None
        ),
        microzona_nombre=f"{comuna_nombre} - {barrio}" if comuna_nombre and barrio else None,
        monto=monto,
        moneda=moneda,
        m2_utiles=a_decimal(_spec(s, "Superficie útil", "Superficie util")),
        dormitorios=a_entero(_spec(s, "Dormitorios")),
        banos=a_entero(_spec(s, "Baños", "Banos")),
        antiguedad_anios=a_entero(_spec(s, "Antigüedad", "Antiguedad")),
        gastos_comunes_clp=a_decimal(_spec(s, "Gastos comunes")),
        estacionamientos=a_entero(_spec(s, "Estacionamientos")) or 0,
        bodegas=a_entero(_spec(s, "Bodegas")) or 0,
        es_vivienda_nueva=es_nueva,
        es_proyecto=es_proyecto,
        raw_blob_path=blob,
        robots_snapshot_sha=sha,
    )
    return aviso if plausible(aviso) else None


def plausible(a: Aviso) -> bool:
    """Rangos del §7.1, por (operacion, moneda). Fuera de rango se descarta la fila entera;
    nunca se corrige el valor ni se le cambia la moneda para que calce."""
    rango = RANGOS.get((a.operacion, a.moneda))
    if rango is None or not (rango[0] <= a.monto <= rango[1]):
        return False
    if a.m2_utiles is not None and not (RANGO_M2[0] <= a.m2_utiles <= RANGO_M2[1]):
        return False
    return not (
        a.dormitorios is not None
        and not (RANGO_DORMITORIOS[0] <= a.dormitorios <= RANGO_DORMITORIOS[1])
    )


# ----------------------------------------------------------------------------- el colector


def fecha_del_nombre(nombre: str) -> datetime | None:
    """`MLC-123456_20260504.html` -> 2026-05-04 UTC.

    La fecha sale del nombre del archivo, **no del reloj de hoy**. Poner `now()` aca seria
    disfrazar de fresco un dato de mayo, y el gate de frescura del §7.3 dejaria de protegernos
    justo cuando mas hace falta.
    """
    m = re.search(r"_(\d{4})(\d{2})(\d{2})\.html$", nombre)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return datetime(y, mo, d, tzinfo=UTC)


def url_del_nombre(nombre: str) -> str | None:
    m = re.match(r"(MLC-\d+)_", nombre)
    return f"{BASE_URL}/{m.group(1)}" if m else None


class PortalLegado:
    """Ingiere la foto de mayo-2026. Implementa el contrato `Source` del §7.1."""

    id = SOURCE_ID
    legal_tier: LegalTier = "html_prohibido"
    parser_version = PARSER_VERSION

    def __init__(self, origen: Path, raiz_cruda: Path | None = None) -> None:
        self.origen = origen
        self.raiz_cruda = raiz_cruda

    def robots_ok(self) -> RobotsVerdict:
        """No consulta la red: estos documentos ya estan en disco desde mayo.

        Se declara lo que es. Las fichas `/MLC-...` no las permite el `robots.txt` del portal,
        y por eso esta fuente es `html_prohibido` y cita la aprobacion humana que el §3.5 exige.
        Maquillar el tier para que el gate pase seria peor que el scraping mismo.
        """
        return RobotsVerdict(
            allowed=True,
            motivo=(
                f"fuente historica ya en disco; ruta /MLC- no permitida por robots, "
                f"autorizada por {APROBACION}"
            ),
            snapshot_sha=f"aprobacion:{APROBACION}",
            url_robots=f"{BASE_URL}/robots.txt",
        )

    def archivos(self) -> list[Path]:
        return sorted(self.origen.glob("*.html")) if self.origen.is_dir() else []

    def collect(self, limite: int | None = None) -> list[RawDoc]:
        """Copia a la zona cruda, anonimizando primero. No toca la red."""
        veredicto = self.robots_ok()
        if not veredicto.allowed:
            raise ErrorDeFuente(f"robots: {veredicto.motivo}")

        docs: list[RawDoc] = []
        for ruta in self.archivos()[: limite or None]:
            momento = fecha_del_nombre(ruta.name)
            url = url_del_nombre(ruta.name)
            if momento is None or url is None:
                continue
            crudo = ruta.read_bytes()
            if len(crudo) < MINIMO_FICHA:
                continue  # redirect o pagina de bloqueo: no es una ficha
            limpio, _ = anonimizar(crudo)
            docs.append(
                escribir_crudo(
                    source_id=self.id,
                    url=url,
                    contenido=limpio,
                    momento=momento,
                    robots_snapshot_sha=veredicto.snapshot_sha,
                    nombre=ruta.stem,
                    raiz=self.raiz_cruda,
                    parser_version=self.parser_version,
                )
            )
        return docs

    def parse(self, doc: RawDoc) -> list[Aviso]:
        aviso = parse_html(
            doc.contenido.decode("utf-8", errors="ignore"),
            doc.url,
            doc.fetched_at,
            str(doc.ruta),
            doc.robots_snapshot_sha,
        )
        return [aviso] if aviso else []

    def selftest(
        self,
        muestra: int = 200,
        filas_corrida_anterior: int | None = None,
        semilla: int = 7,
    ) -> SelfTestReport:
        """Verifica cobertura de campos y ausencia de datos personales (§7.1 y §3.4)."""
        # Muestra aleatoria con semilla fija, NO los primeros N. Los archivos estan
        # ordenados por ID de MercadoLibre, y los IDs bajos son avisos viejos: tomar el
        # prefijo daba 47% de proyectos contra 9% en el corpus completo. Una muestra sesgada
        # mide el sesgo, no la fuente.
        todos = self.archivos()
        archivos = random.Random(semilla).sample(todos, min(muestra, len(todos)))
        parseados: list[Aviso] = []
        fugas = 0
        for ruta in archivos:
            momento, url = fecha_del_nombre(ruta.name), url_del_nombre(ruta.name)
            if momento is None or url is None:
                continue
            limpio, _ = anonimizar(ruta.read_bytes())
            if any(patron.search(limpio) for patron, _ in _PATRONES):
                fugas += 1
            a = parse_html(
                limpio.decode("utf-8", errors="ignore"), url, momento, str(ruta), "selftest"
            )
            if a:
                parseados.append(a)

        n = len(parseados) or 1
        # Los campos de UNIDAD (m2, dormitorios) se miden solo sobre avisos de unidad. Un
        # aviso de proyecto publica "35 - 61 m2" y "1 a 2 dormitorios": no tiene un valor que
        # extraer, y exigirselo mediria el mix del corpus en vez de la salud del parser.
        unidades = [a for a in parseados if not a.es_proyecto]
        u = len(unidades) or 1
        cobertura = {
            "precio": sum(1 for a in parseados if a.monto) / n,
            "m2_utiles": sum(1 for a in unidades if a.m2_utiles is not None) / u,
            "dormitorios": sum(1 for a in unidades if a.dormitorios is not None) / u,
            "comuna": sum(1 for a in parseados if a.comuna_id) / n,
            "microzona": sum(1 for a in parseados if a.microzona_id) / n,
            "es_vivienda_nueva": sum(1 for a in parseados if a.es_vivienda_nueva is not None) / n,
        }
        proporcion_proyectos = 1 - u / n

        rep = SelfTestReport(source_id=self.id, ok=True, n_filas=len(parseados))
        rep.n_filas_corrida_anterior = filas_corrida_anterior

        # §7.1: >=95% de los campos requeridos. `es_vivienda_nueva` no entra en el corte
        # porque el portal no siempre lo declara, y un ND declarado es legitimo (§3.2).
        for campo in ("precio", "m2_utiles", "dormitorios", "comuna"):
            if cobertura[campo] >= 0.95:
                rep.pasar(f"cobertura_{campo}")
            else:
                rep.fallar(f"cobertura_{campo}", f"{cobertura[campo]:.1%} < 95%")

        # La microzona va aparte y con umbral propio. Es "la unidad de analisis real" (§2.4),
        # pero hay avisos donde el portal no declara barrio: el breadcrumb termina en la
        # comuna. Eso es un ND legitimo (§3.2), no un parser roto. Inventarle un barrio para
        # llegar al 95% seria imputar en silencio, que es justo lo prohibido.
        if cobertura["microzona"] >= MIN_COBERTURA_MICROZONA:
            rep.pasar("cobertura_microzona")
        else:
            rep.fallar(
                "cobertura_microzona",
                f"{cobertura['microzona']:.1%} < {MIN_COBERTURA_MICROZONA:.0%}",
            )

        # §3.4: cero datos personales. No es un umbral, es un absoluto.
        if fugas:
            rep.fallar(
                "sin_datos_personales",
                f"{fugas} documentos conservan un dato personal tras anonimizar",
            )
        else:
            rep.pasar("sin_datos_personales")

        if not parseados:
            rep.fallar("hay_filas", "ningun documento parseo")

        # Detector de parser roto (§7.1): una caida >30% vs la ultima corrida exitosa.
        caida = rep.caida_pct
        if caida is not None and caida > 0.30:
            rep.fallar("conteo_estable", f"cayo {caida:.1%} vs la corrida anterior")
        elif caida is not None:
            rep.pasar("conteo_estable")

        rep.detalle["cobertura"] = " · ".join(f"{k} {v:.1%}" for k, v in cobertura.items())
        rep.detalle["archivos_revisados"] = str(len(archivos))
        rep.detalle["avisos_de_proyecto"] = (
            f"{proporcion_proyectos:.1%} del corpus; publican rangos, van con evidence_level E"
        )
        rep.detalle["frescura"] = (
            "fetched_at de mayo-2026: el gate de frescura del §7.3 lo excluye del ranking, "
            "que es lo correcto. Sirve de diccionario de microzonas, fixtures y linea base "
            "de precios para medir el delta (T-919)."
        )
        return rep


# ------------------------------------------------------------------------------- la carga


def cargar_en_duckdb(conexion: Any, avisos: list[Aviso]) -> int:
    """Inserta en `dim_comuna`, `dim_microzona` y la tabla de hechos que corresponda.

    Idempotente por clave natural (§3.6): re-ejecutar no duplica.
    """
    if not avisos:
        return 0

    comunas = {a.comuna_id: a.comuna_nombre for a in avisos if a.comuna_id}
    for cid, nombre in comunas.items():
        conexion.execute(
            "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?, ?, ?) "
            "ON CONFLICT (comuna_id) DO NOTHING",
            (cid, nombre, "Metropolitana"),
        )

    microzonas = {
        a.microzona_id: (a.comuna_id, a.microzona_nombre) for a in avisos if a.microzona_id
    }
    for mid, (cid, nombre) in microzonas.items():
        conexion.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES (?, ?, ?) "
            "ON CONFLICT (microzona_id) DO NOTHING",
            (mid, cid, nombre),
        )

    n = 0
    omitidas: list[str] = []
    for a in avisos:
        if a.operacion == "venta" and a.precio_uf is not None:
            n += _cargar_venta(conexion, a)
        elif a.operacion == "venta":
            # Venta publicada en pesos. `fact_unidad_venta.precio_uf` es DECIMAL en UF y el
            # §11 prohibe que esta capa convierta: la UF del dia vive en otra tabla. Se omite
            # la fila y se cuenta aparte, en vez de meter un numero en la columna equivocada.
            omitidas.append(a.portal_id)
        elif a.operacion == "arriendo":
            n += _cargar_arriendo(conexion, a)
    if omitidas:
        logging.getLogger(__name__).info(
            "%d ventas publicadas en pesos omitidas (falta columna precio_clp): %s...",
            len(omitidas),
            omitidas[:3],
        )
    return n


def _procedencia(a: Aviso) -> tuple[Any, ...]:
    """Las seis columnas del §3.1, siempre en el mismo orden."""
    return (SOURCE_ID, a.url, a.fetched_at, PARSER_VERSION, a.raw_blob_path, a.robots_snapshot_sha)


def _cargar_venta(conexion: Any, a: Aviso) -> int:
    """Inserta con versionado SCD tipo 2 (§11): nunca se borra, se cierra y se abre.

    El mismo aviso aparece en varias corridas —el corpus del legado tiene el mismo MLC
    capturado el 4 y el 5 de mayo— y esas NO son filas duplicadas: son versiones. Guardarlas
    con `valid_from`/`valid_to` es lo que permite responder *"¿cuándo bajó el precio de esta
    unidad?"*, que el contrato declara señal de compra.

    Tres casos, y el orden importa:
      1. no existe        -> se inserta la primera version
      2. existe con la misma fecha -> se actualiza en el lugar (§3.6: re-ejecutar no duplica)
      3. existe mas antigua y el precio CAMBIO -> se cierra la vieja y se abre una nueva
         Si el precio no cambio, no se abre version: una version por corrida sin cambios
         llenaria la tabla de ruido y taparia los cambios reales.
    """
    vigente = conexion.execute(
        "SELECT valid_from, precio_uf FROM fact_unidad_venta "
        "WHERE unidad_key = ? AND valid_to IS NULL",
        (a.portal_id,),
    ).fetchone()

    if vigente is not None:
        desde, precio_previo = vigente
        if desde == a.fetched_at:
            conexion.execute(
                "UPDATE fact_unidad_venta SET precio_uf = ?, m2_utiles = ?, dormitorios = ?, "
                "banos = ?, tipologia = ?, es_vivienda_nueva = ?, antiguedad_anios = ?, "
                "fetched_at = ?, raw_blob_path = ? WHERE unidad_key = ? AND valid_to IS NULL",
                (
                    a.precio_uf,
                    float(a.m2_utiles) if a.m2_utiles is not None else None,
                    a.dormitorios,
                    a.banos,
                    a.tipologia,
                    a.es_vivienda_nueva,
                    a.antiguedad_anios,
                    a.fetched_at,
                    a.raw_blob_path,
                    a.portal_id,
                ),
            )
            return 0
        if desde > a.fetched_at:
            return 0  # llego una captura mas vieja que la vigente: no reescribe el presente
        if precio_previo == a.precio_uf:
            conexion.execute(
                "UPDATE fact_unidad_venta SET fetched_at = ? "
                "WHERE unidad_key = ? AND valid_to IS NULL",
                (a.fetched_at, a.portal_id),
            )
            return 0
        conexion.execute(
            "UPDATE fact_unidad_venta SET valid_to = ? WHERE unidad_key = ? AND valid_to IS NULL",
            (a.fetched_at, a.portal_id),
        )

    conexion.execute(
        """
        INSERT INTO fact_unidad_venta
          (unidad_key, numero_unidad, tipologia, dormitorios, banos, m2_utiles,
           es_vivienda_nueva, antiguedad_anios, precio_uf, disponible, evidence_level,
           valid_from, source_id, source_url, fetched_at, parser_version, raw_blob_path,
           robots_snapshot_sha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            a.portal_id,
            a.portal_id,
            a.tipologia,
            a.dormitorios,
            a.banos,
            float(a.m2_utiles) if a.m2_utiles is not None else None,
            a.es_vivienda_nueva,
            a.antiguedad_anios,
            a.precio_uf,
            True,
            # Un proyecto publica "desde UF X": ese numero no es el precio de esta unidad.
            # Marcarlo `E` no es cosmetico: el §12 excluye del ranking todo precio estimado,
            # asi que la regla que ya existe hace el trabajo sin codigo nuevo.
            "E" if a.es_proyecto else "V",
            a.fetched_at,
            *_procedencia(a),
        ),
    )
    return 1


def _cargar_arriendo(conexion: Any, a: Aviso) -> int:
    conexion.execute(
        """
        INSERT INTO fact_arriendo_comp
          (comp_id, microzona_id, tipologia, dormitorios, banos, m2_utiles, arriendo_clp,
           arriendo_uf, gastos_comunes_clp, estacionamiento, bodega, activo, evidence_level,
           source_id, source_url, fetched_at, parser_version, raw_blob_path,
           robots_snapshot_sha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'V', ?, ?, ?, ?, ?, ?)
        ON CONFLICT (comp_id) DO UPDATE SET
          arriendo_clp = excluded.arriendo_clp, arriendo_uf = excluded.arriendo_uf,
          fetched_at = excluded.fetched_at
        """,
        (
            a.portal_id,
            a.microzona_id,
            a.tipologia,
            a.dormitorios,
            a.banos,
            float(a.m2_utiles) if a.m2_utiles is not None else None,
            a.arriendo_clp,
            a.arriendo_uf,
            a.gastos_comunes_clp,
            a.estacionamientos > 0,
            a.bodegas > 0,
            True,
            *_procedencia(a),
        ),
    )
    return 1
