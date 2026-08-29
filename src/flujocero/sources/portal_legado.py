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

import random
import re
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


# Los helpers compartidos con el colector vivo viven en `portal_comun`: mismo portal, mismas
# convenciones. Se reexportan para que este modulo siga siendo legible de arriba a abajo.
from flujocero.sources.portal_comun import (  # noqa: E402
    PATRONES as _PATRONES,
)
from flujocero.sources.portal_comun import (  # noqa: E402
    a_decimal,
    a_entero,
    anonimizar,
    cargar_avisos,
    slug,
    tipologia_de,
    url_segura,
)

__all__ = [
    "Aviso",
    "PortalLegado",
    "a_decimal",
    "a_entero",
    "anonimizar",
    "cargar_en_duckdb",
    "parse_html",
    "slug",
    "url_segura",
]


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
    """Delega en el cargador compartido: mismas tablas, misma semantica SCD tipo 2.

    Tenerlo dos veces seria peor que tenerlo lejos: se corrige una copia, no la otra, y el
    error queda escondido justo en la que nadie mira.
    """
    return cargar_avisos(conexion, list(avisos), SOURCE_ID, PARSER_VERSION)
