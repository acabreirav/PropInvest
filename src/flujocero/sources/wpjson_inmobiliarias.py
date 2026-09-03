"""Precios de proyectos nuevos vía wp-json + HTML permitido — capa 3, T-925c. Piloto: Socovesa.

La ruta la fijaron cuatro corridas de `probar-wpjson --volcar-ld` contra el sitio vivo
(02/03-sep-2026, crudo en `data/raw/wpjson_inmobiliarias/`):

1. `sitemap.xml` → `proyecto-sitemap.xml` lista las páginas de UNIDAD
   (`…/nuestros-proyectos/<proyecto>/<unidad>/`). El slug de proyecto del sitemap puede
   estar desactualizado (`punta-maitenes-…/` da 404): NO se navega por él, se resuelve.
2. Cada página declara su registro REST en `<link rel="alternate" type="application/json">`
   → `wp/v2/proyecto/<id>`. La colección (`?per_page=`) redirige a HTML; el registro
   individual sí responde JSON.
3. El REST trae la metadata (`class_list`: `ciudad-*`, `estado-*`, `tipologia-*`,
   `disponibilidad-*`) y `parent` → el registro del PROYECTO, cuyo `link` es la URL
   canónica real.
4. El precio NO está en el REST (`acf` viene vacío): vive en el HTML de la página del
   proyecto, en bloques de modelo (`ul.planta_list` + `div.planta_precio` + el botón
   "Cotizar unidad" cuyo `data-url` trae el slug del modelo).

**"Precio desde" POR MODELO, no precio por unidad.** Cada fila se marca
`precio_es_desde=TRUE` y el emparejamiento la EXCLUYE del ranking: un "desde" es el piso
del modelo, no el precio de una unidad rankeable (B1 exige precio real). Lo que sí aporta
hoy: el censo de la oferta nueva con su piso de precio, la señal de baja de precio (SCD),
y la comuna/estado de venta de cada proyecto.

Legal: `html_permitido` — robots.txt del dominio se verifica antes de cada corrida y
las páginas usadas están permitidas; el wp-json es además JSON público. Sin formularios,
sin datos personales (ADR 010 adenda; ADR 011).
"""

from __future__ import annotations

import html as html_mod
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flujocero.sources import robots_check
from flujocero.sources.base import escribir_crudo
from flujocero.sources.portal_comun import tipologia_de

SOURCE_ID = "wpjson_inmobiliarias"
PARSER_VERSION = "wpjson_inmobiliarias/0.1.0"
LEGAL_TIER = "html_permitido"
UA = "FlujoCero-ResearchBot/1.0"
# Cortesía por defecto; si robots.txt declara Crawl-delay mayor, manda robots.
PAUSA_S = 1.0

RE_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>")
RE_REST_ID = re.compile(r"wp-json/wp/v2/proyecto/(\d+)")
RE_BLOQUE_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


@dataclass(frozen=True)
class ProyectoWp:
    """Un proyecto inmobiliario según su registro REST — la parte con metadata."""

    dominio: str
    proyecto_slug: str
    nombre: str
    comuna_slug: str | None  # de `class_list: ciudad-<slug>`; None = el REST no lo trae (ND)
    estado: str | None  # ej. 'venta-en-blanco', 'entrega-inmediata'
    tipo_bien: str | None  # 'casa' | 'departamento' | None
    url: str
    fetched_at: datetime
    raw_blob_path: str
    robots_snapshot_sha: str


@dataclass(frozen=True)
class ModeloWp:
    """Un modelo dentro de la página del proyecto — la parte con precio "desde"."""

    dominio: str
    proyecto_slug: str
    modelo_slug: str
    precio_desde_uf: Decimal | None  # None = el bloque no trae precio (ND, no cero)
    m2_totales: Decimal | None
    dormitorios: int | None
    banos: int | None
    url: str
    fetched_at: datetime
    raw_blob_path: str
    robots_snapshot_sha: str


@dataclass
class Cosecha:
    proyectos: list[ProyectoWp] = field(default_factory=list)
    modelos: list[ModeloWp] = field(default_factory=list)
    requests: int = 0
    urls_unidad: int = 0
    errores: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ parseo puro (testeable)


def uf_de(texto: str) -> Decimal | None:
    """'3.390 UF' / 'UF 6.390' / '3.390,5' → Decimal. Punto de miles, coma decimal (es-CL)."""
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)(,\d+)?", texto)
    if m is None:
        return None
    crudo = m.group(1).replace(".", "") + (m.group(2) or "").replace(",", ".")
    try:
        return Decimal(crudo)
    except InvalidOperation:  # pragma: no cover - el regex ya lo garantiza
        return None


def rest_id_de(html: str) -> int | None:
    """El id del registro `wp/v2/proyecto/<id>` que la página declara en <link rel=alternate>."""
    m = RE_REST_ID.search(html)
    return int(m.group(1)) if m else None


def proyecto_slug_de(url: str) -> str | None:
    """`…/nuestros-proyectos/<proyecto>/…` → '<proyecto>'."""
    m = re.search(r"/nuestros-proyectos/([^/]+)", url)
    return m.group(1) if m else None


def meta_de_rest(datos: dict[str, Any]) -> dict[str, Any]:
    """Metadata del registro REST. Todo lo que no venga queda None (ND, §3.2).

    La comuna viene como `ciudad-<slug>` en Socovesa y `comuna-<slug>` en Pilares;
    Pilares además publica dormitorios y baños como tags (`tag-2-dormitorio`,
    `tag-1-bano`). Mismo wp-json, dos vocabularios.
    """
    clases = datos.get("class_list") or []
    por_prefijo: dict[str, str] = {}
    dormitorios = banos = None
    for clase in clases:
        for prefijo in ("ciudad-", "comuna-", "estado-", "tipologia-", "disponibilidad-"):
            if clase.startswith(prefijo):
                # la primera gana: no se ha visto más de una clase por taxonomía
                por_prefijo.setdefault(prefijo, clase[len(prefijo) :])
        m_d = re.match(r"tag-(\d+)-dormitorio", clase)
        if m_d:
            dormitorios = int(m_d.group(1))
        m_b = re.match(r"tag-(\d+)-bano", clase)
        if m_b:
            banos = int(m_b.group(1))
    titulo = (datos.get("title") or {}).get("rendered") or ""
    return {
        "slug": datos.get("slug"),
        "nombre": html_mod.unescape(titulo).strip(),
        "link": datos.get("link"),
        "parent": datos.get("parent") or 0,
        "comuna_slug": por_prefijo.get("ciudad-") or por_prefijo.get("comuna-"),
        "estado": por_prefijo.get("estado-"),
        "tipo_bien": por_prefijo.get("tipologia-"),
        "disponibilidad": por_prefijo.get("disponibilidad-"),
        "dormitorios": dormitorios,
        "banos": banos,
    }


def modelos_de_html(html: str, url_pagina: str) -> list[dict[str, Any]]:
    """Los bloques de modelo de la página del proyecto.

    Se ancla en `div.planta_precio` (solo los modelos PROPIOS lo tienen; las tarjetas
    `card_proyecto` de proyectos ajenos que la página promociona no traen ese bloque, así
    que quedan fuera por construcción). Desde el ancla se sube al contenedor `col_content`
    y ahí se leen la `planta_list` (m², dormitorios, baños) y el `data-url` del botón
    "Cotizar unidad", cuyo último segmento es el slug del modelo.
    """
    from selectolax.parser import HTMLParser

    arbol = HTMLParser(html)
    slug_proyecto = proyecto_slug_de(url_pagina) or ""
    salida: list[dict[str, Any]] = []
    for i, ancla in enumerate(arbol.css("div.planta_precio")):
        contenedor = ancla
        for _ in range(4):
            padre = contenedor.parent
            if padre is None:
                break
            contenedor = padre
            if "col_content" in (contenedor.attributes.get("class") or ""):
                break
        nodo_uf = ancla.css_first("p.uf")
        precio = uf_de(nodo_uf.text()) if nodo_uf is not None else uf_de(ancla.text())

        m2 = dormitorios = banos = None
        lista = contenedor.css_first("ul.planta_list")
        if lista is not None:
            texto = lista.text(separator=" ")
            m_m2 = re.search(r"([\d.,]+)\s*m", texto)
            m2 = uf_de(m_m2.group(1)) if m_m2 else None
            m_d = re.search(r"(\d+)\s*dormitorio", texto, re.I)
            dormitorios = int(m_d.group(1)) if m_d else None
            m_b = re.search(r"(\d+)\s*bañ", texto, re.I)
            banos = int(m_b.group(1)) if m_b else None

        modelo_slug = None
        cta = contenedor.css_first("a[data-url]")
        if cta is not None:
            m_slug = re.search(r"/([^/?]+)/?\?", cta.attributes.get("data-url") or "")
            modelo_slug = m_slug.group(1) if m_slug else None
        if not modelo_slug:
            # sin botón de cotización no hay slug estable: el índice al menos es
            # reproducible dentro de la misma versión de la página
            modelo_slug = f"modelo-{i + 1}"

        salida.append(
            {
                "proyecto_slug": slug_proyecto,
                "modelo_slug": modelo_slug,
                "precio_desde_uf": precio,
                "m2_totales": m2,
                "dormitorios": dormitorios,
                "banos": banos,
            }
        )
    return salida


def modelo_de_html_pilares(html: str, url_pagina: str) -> dict[str, Any]:
    """El bloque de modelo del theme de Pilares: la página ES el modelo.

    `h1.planta__title` trae el nombre, `p.single__details__dividendo` el "Desde UF X",
    y la `planta__minilist` los atributos. Dormitorios/baños vienen además como tags en
    el REST (meta_de_rest los extrae) — acá son respaldo si la lista los trae.
    """
    from selectolax.parser import HTMLParser

    arbol = HTMLParser(html)
    nodo_precio = arbol.css_first("p.single__details__dividendo")
    precio = uf_de(nodo_precio.text()) if nodo_precio is not None else None
    m2 = dormitorios = banos = None
    lista = arbol.css_first("ul.planta__minilist") or arbol.css_first("ul.single__details")
    if lista is not None:
        texto = lista.text(separator=" ")
        m_m2 = re.search(r"([\d.,]+)\s*m", texto)
        m2 = uf_de(m_m2.group(1)) if m_m2 else None
        m_d = re.search(r"(\d+)\s*dormitorio", texto, re.I)
        dormitorios = int(m_d.group(1)) if m_d else None
        m_b = re.search(r"(\d+)\s*bañ", texto, re.I)
        banos = int(m_b.group(1)) if m_b else None
    return {
        "precio_desde_uf": precio,
        "m2_totales": m2,
        "dormitorios": dormitorios,
        "banos": banos,
    }


# Perfil por dominio: dónde vive el precio dentro de la jerarquía REST (parent-chain).
#   raiz   → el precio está en la página del proyecto (Socovesa: bloques planta)
#   modelo → cada modelo tiene su propia página con el precio (Pilares: 3 niveles
#            unidad → modelo → proyecto)
# Un dominio sin perfil NO se recolecta: primero su sonda (probar-wpjson --volcar-ld)
# y su entrada aquí, con fixture. Almagro queda fuera a propósito: tickets observados
# UF 10.590–16.790, todos sobre el tope UF 6.000 del subsidio (ADR 011).
PERFILES: dict[str, dict[str, Any]] = {
    "socovesa.cl": {"precio_en": "raiz"},
    "pilares.cl": {"precio_en": "modelo"},
}


# ----------------------------------------------------------------------------- recolección


def recolectar(
    cliente: Any,
    dominio: str,
    ahora: datetime | None = None,
    raiz: Path | None = None,
    pausa: float = PAUSA_S,
    limite_proyectos: int | None = None,
) -> Cosecha:
    """Sitemap → una unidad por proyecto → REST unidad → REST proyecto → HTML del proyecto.

    Cada respuesta se escribe a la zona cruda ANTES de leerse (§3.6). Un proyecto que
    falle no bota la cosecha: queda en `errores` con su motivo.
    """
    momento = ahora or datetime.now(UTC)
    cosecha = Cosecha()
    perfil = PERFILES.get(dominio)
    if perfil is None:
        cosecha.errores.append(
            f"{dominio}: sin perfil en PERFILES — primero su sonda "
            "(probar-wpjson --volcar-ld) y su entrada con fixture"
        )
        return cosecha
    base = f"https://{dominio}" if dominio.startswith("www.") else f"https://www.{dominio}"

    veredicto = robots_check.verificar(
        f"{base}/nuestros-proyectos/", UA, source_id=SOURCE_ID, cliente=cliente
    )
    if not veredicto.allowed:
        cosecha.errores.append(f"robots.txt de {dominio} PROHIBE la ruta: {veredicto.motivo}")
        return cosecha
    pausa = max(pausa, veredicto.crawl_delay_s or 0.0)
    sha = veredicto.snapshot_sha

    def pedir(url: str, nombre: str) -> Any | None:
        cosecha.requests += 1
        try:
            r = cliente.get(url, headers={"User-Agent": UA})
        except Exception as exc:  # noqa: BLE001 - un dominio caído no bota la corrida
            cosecha.errores.append(f"{url}: {type(exc).__name__}: {exc}")
            return None
        time.sleep(pausa)
        if r.status_code != 200:
            cosecha.errores.append(f"{url}: HTTP {r.status_code}")
            return None
        return escribir_crudo(
            SOURCE_ID,
            url,
            r.content,
            momento,
            robots_snapshot_sha=sha,
            nombre=nombre,
            raiz=raiz,
            parser_version=PARSER_VERSION,
        )

    dom = dominio.replace(".", "_")

    # 1 · sitemap → URLs de unidad
    urls_unidad: list[str] = []
    for candidato in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"):
        doc = pedir(f"{base}{candidato}", f"{dom}_sitemap")
        if doc is None:
            continue
        locs = RE_LOC.findall(doc.contenido.decode("utf-8", errors="replace"))
        subs = [u for u in locs if u.endswith(".xml")]
        urls_unidad = [u for u in locs if not u.endswith(".xml")]
        for sub in sorted(subs, key=lambda u: "proyecto" not in u):
            if any("proyecto" in u for u in urls_unidad):
                break
            doc_sub = pedir(sub, f"{dom}_sitemap_{sub.rsplit('/', 1)[-1].removesuffix('.xml')}")
            if doc_sub is not None:
                urls_unidad.extend(
                    u
                    for u in RE_LOC.findall(doc_sub.contenido.decode("utf-8", errors="replace"))
                    if not u.endswith(".xml")
                )
        if urls_unidad:
            break
    urls_unidad = [u for u in urls_unidad if "/nuestros-proyectos/" in u]
    cosecha.urls_unidad = len(urls_unidad)
    if not urls_unidad:
        cosecha.errores.append(f"{dominio}: el sitemap no lista páginas de proyecto")
        return cosecha

    # 2 · una unidad representante por RAMA (la URL sin su último segmento). En Socovesa
    # la rama es el proyecto (…/<proyecto>/<unidad>); en Pilares es el modelo
    # (…/<proyecto>/<modelo>/<unidad>). Agrupar por rama cubre ambas jerarquías.
    representantes: dict[str, str] = {}
    for u in urls_unidad:
        rama = u.rstrip("/").rsplit("/", 1)[0]
        # una rama con ≤3 barras es la seccion raiz del sitio (la pagina indice que
        # algunos sitemaps tambien listan): no es una unidad, se salta
        if rama.count("/") <= 3:
            continue
        representantes.setdefault(rama, u)
    grupos = sorted(representantes.items())
    if limite_proyectos is not None:
        grupos = grupos[:limite_proyectos]

    # Un registro puede responder 200 con HTML en vez de JSON (proyecto en borrador
    # que redirige a una pagina de error, y follow_redirects la sigue). No es JSON
    # roto nuestro: se registra con su URL y se sigue con el resto del catalogo.
    def _json_o_nada(doc: Any) -> Any | None:
        try:
            return doc.json()
        except ValueError:
            cosecha.errores.append(
                f"{doc.url}: HTTP 200 pero el cuerpo no es JSON "
                f"(empieza con {doc.contenido[:40]!r})"
            )
            return None

    def _rest(pid: int) -> tuple[Any, dict[str, Any]] | None:
        doc = pedir(f"{base}/wp-json/wp/v2/proyecto/{pid}", f"{dom}_rest_{pid}")
        if doc is None:
            return None
        datos = _json_o_nada(doc)
        return None if datos is None else (doc, datos)

    nodos_vistos: set[int] = set()
    raices_registradas: set[int] = set()
    raices: dict[int, tuple[Any, dict[str, Any]]] = {}  # cache: id → registro raíz

    for rama, url_unidad in grupos:
        etiqueta = rama.rsplit("/", 1)[-1] or "raiz"
        doc_unidad = pedir(url_unidad, f"{dom}_unidad_{etiqueta}")
        if doc_unidad is None:
            continue
        rid = rest_id_de(doc_unidad.contenido.decode("utf-8", errors="replace"))
        if rid is None:
            cosecha.errores.append(f"{url_unidad}: sin <link> al registro REST")
            continue

        # la cadena parent completa: unidad → (modelo) → proyecto raíz
        par = _rest(rid)
        if par is None:
            continue
        cadena = [par]
        while int(cadena[-1][1].get("parent") or 0) and len(cadena) < 4:
            padre_id = int(cadena[-1][1]["parent"])
            if padre_id in raices:
                cadena.append(raices[padre_id])
                break
            par = _rest(padre_id)
            if par is None:
                break
            cadena.append(par)
        doc_raiz, datos_raiz = cadena[-1]
        if int(datos_raiz.get("parent") or 0):
            continue  # un fetch de la cadena falló: el motivo ya quedó en errores
        raices[int(datos_raiz["id"])] = (doc_raiz, datos_raiz)

        # el nodo con precio: la raíz (Socovesa) o el modelo un nivel abajo (Pilares)
        if perfil["precio_en"] == "modelo" and len(cadena) >= 2:
            datos_nodo = cadena[-2][1]
        else:
            datos_nodo = datos_raiz
        nid = int(datos_nodo.get("id") or 0)
        if nid in nodos_vistos:
            continue  # dos ramas del sitemap resolvieron al mismo nodo canónico
        nodos_vistos.add(nid)

        meta_raiz = meta_de_rest(datos_raiz)
        meta_nodo = meta_de_rest(datos_nodo)
        if not meta_nodo["link"] or not meta_raiz["slug"]:
            cosecha.errores.append(f"rest {nid}: sin link o slug — se salta")
            continue

        raiz_id = int(datos_raiz["id"])
        if raiz_id not in raices_registradas:
            raices_registradas.add(raiz_id)
            cosecha.proyectos.append(
                ProyectoWp(
                    dominio=dominio,
                    proyecto_slug=meta_raiz["slug"],
                    nombre=meta_raiz["nombre"] or meta_raiz["slug"],
                    comuna_slug=meta_raiz["comuna_slug"] or meta_nodo["comuna_slug"],
                    estado=meta_raiz["estado"] or meta_nodo["estado"],
                    tipo_bien=meta_raiz["tipo_bien"] or meta_nodo["tipo_bien"],
                    url=str(doc_raiz.url),
                    fetched_at=doc_raiz.fetched_at,
                    raw_blob_path=str(doc_raiz.ruta),
                    robots_snapshot_sha=doc_raiz.robots_snapshot_sha,
                )
            )

        doc_html = pedir(str(meta_nodo["link"]), f"{dom}_pagina_{meta_nodo['slug']}")
        if doc_html is None:
            continue
        html_pagina = doc_html.contenido.decode("utf-8", errors="replace")
        link = str(meta_nodo["link"])
        if perfil["precio_en"] == "modelo":
            m = modelo_de_html_pilares(html_pagina, link)
            cosecha.modelos.append(
                ModeloWp(
                    dominio=dominio,
                    proyecto_slug=meta_raiz["slug"],
                    modelo_slug=meta_nodo["slug"] or f"modelo-{nid}",
                    precio_desde_uf=m["precio_desde_uf"],
                    m2_totales=m["m2_totales"],
                    dormitorios=m["dormitorios"] or meta_nodo["dormitorios"],
                    banos=m["banos"] or meta_nodo["banos"],
                    url=link,
                    fetched_at=doc_html.fetched_at,
                    raw_blob_path=str(doc_html.ruta),
                    robots_snapshot_sha=doc_html.robots_snapshot_sha,
                )
            )
        else:
            for m in modelos_de_html(html_pagina, link):
                cosecha.modelos.append(
                    ModeloWp(
                        dominio=dominio,
                        proyecto_slug=meta_raiz["slug"],
                        modelo_slug=m["modelo_slug"],
                        precio_desde_uf=m["precio_desde_uf"],
                        m2_totales=m["m2_totales"],
                        dormitorios=m["dormitorios"],
                        banos=m["banos"],
                        url=link,
                        fetched_at=doc_html.fetched_at,
                        raw_blob_path=str(doc_html.ruta),
                        robots_snapshot_sha=doc_html.robots_snapshot_sha,
                    )
                )
    return cosecha


# ----------------------------------------------------------------------------------- carga


def cargar(conexion: Any, cosecha: Cosecha) -> dict[str, int]:
    """Upsert en `dim_proyecto` + SCD tipo 2 simplificado en `fact_unidad_venta`.

    La versión simplificada respecto de `portal_comun._cargar_venta` es deliberada: acá hay
    UNA superficie (la página del proyecto), así que no existe el problema tarjeta/ficha.
    Tres casos: no existe → insertar; mismo precio → refrescar procedencia; precio distinto
    → cerrar versión y abrir otra. Una captura más vieja que la vigente no reescribe nada.
    """
    contadores = {
        "proyectos": 0,
        "modelos_nuevos": 0,
        "versiones_nuevas": 0,
        "refrescos": 0,
        "sin_precio": 0,
        "fuera_de_orden": 0,
        "proyectos_congelados_con_cambio": 0,
    }
    for p in cosecha.proyectos:
        if p.comuna_slug:
            conexion.execute(
                "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?, ?, '') "
                "ON CONFLICT (comuna_id) DO NOTHING",
                (p.comuna_slug, p.comuna_slug.replace("-", " ").title()),
            )
        proyecto_id = f"wpjson-{p.dominio}-{p.proyecto_slug}"
        existe = conexion.execute(
            "SELECT 1 FROM dim_proyecto WHERE proyecto_id = ?", (proyecto_id,)
        ).fetchone()
        if existe:
            # DuckDB implementa UPDATE (y el upsert) reescribiendo la fila completa, y eso
            # viola la FK apenas fact_unidad_venta referencia el proyecto. Mientras haya
            # filas apuntando, la dimensión queda CONGELADA y se cuenta — visible en el
            # resumen de la corrida, no un fallo silencioso. Refrescar el estado de venta
            # de un proyecto con historial exigiría soltar la FK: decisión aparte.
            referencias = conexion.execute(
                "SELECT count(*) FROM fact_unidad_venta WHERE proyecto_id = ?",
                (proyecto_id,),
            ).fetchone()[0]
            if referencias:
                cambio = conexion.execute(
                    "SELECT count(*) FROM dim_proyecto WHERE proyecto_id = ? "
                    "AND (nombre IS DISTINCT FROM ? OR estado IS DISTINCT FROM ?)",
                    (proyecto_id, p.nombre, p.estado),
                ).fetchone()[0]
                contadores["proyectos_congelados_con_cambio"] += int(cambio)
                contadores["proyectos"] += 1
                continue
            conexion.execute(
                "UPDATE dim_proyecto SET nombre = ?, estado = ?, "
                "comuna_id = coalesce(?, comuna_id), source_url = ?, fetched_at = ?, "
                "parser_version = ?, raw_blob_path = ?, robots_snapshot_sha = ? "
                "WHERE proyecto_id = ?",
                (
                    p.nombre,
                    p.estado,
                    p.comuna_slug,
                    p.url,
                    p.fetched_at,
                    PARSER_VERSION,
                    p.raw_blob_path,
                    p.robots_snapshot_sha,
                    proyecto_id,
                ),
            )
        else:
            conexion.execute(
                "INSERT INTO dim_proyecto (proyecto_id, nombre, inmobiliaria, comuna_id, "
                "estado, source_id, source_url, fetched_at, parser_version, raw_blob_path, "
                "robots_snapshot_sha) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proyecto_id,
                    p.nombre,
                    p.dominio,
                    p.comuna_slug,
                    p.estado,
                    SOURCE_ID,
                    p.url,
                    p.fetched_at,
                    PARSER_VERSION,
                    p.raw_blob_path,
                    p.robots_snapshot_sha,
                ),
            )
        contadores["proyectos"] += 1

    for m in cosecha.modelos:
        if m.precio_desde_uf is None:
            # sin precio la fila no aporta al delta ni al censo de precios; se cuenta y
            # NO se inventa nada (§3.2)
            contadores["sin_precio"] += 1
            continue
        clave = f"wpjson-{m.dominio}-{m.proyecto_slug}-{m.modelo_slug}"
        vigente = conexion.execute(
            "SELECT valid_from, precio_uf FROM fact_unidad_venta "
            "WHERE unidad_key = ? AND valid_to IS NULL",
            (clave,),
        ).fetchone()
        procedencia = (
            SOURCE_ID,
            m.url,
            m.fetched_at,
            PARSER_VERSION,
            m.raw_blob_path,
            m.robots_snapshot_sha,
        )
        if vigente is not None and vigente[0] > m.fetched_at:
            contadores["fuera_de_orden"] += 1
            continue
        if vigente is not None and vigente[1] == m.precio_desde_uf:
            conexion.execute(
                "UPDATE fact_unidad_venta SET fetched_at = ?, source_url = ?, "
                "raw_blob_path = ?, robots_snapshot_sha = ? "
                "WHERE unidad_key = ? AND valid_to IS NULL",
                (m.fetched_at, m.url, m.raw_blob_path, m.robots_snapshot_sha, clave),
            )
            contadores["refrescos"] += 1
            continue
        if vigente is not None:
            conexion.execute(
                "UPDATE fact_unidad_venta SET valid_to = ? "
                "WHERE unidad_key = ? AND valid_to IS NULL",
                (m.fetched_at, clave),
            )
            contadores["versiones_nuevas"] += 1
        else:
            contadores["modelos_nuevos"] += 1
        conexion.execute(
            "INSERT INTO fact_unidad_venta (unidad_key, proyecto_id, numero_unidad, tipologia, "
            "dormitorios, banos, m2_totales, es_vivienda_nueva, precio_uf, precio_es_desde, "
            "disponible, evidence_level, valid_from, "
            "source_id, source_url, fetched_at, parser_version, raw_blob_path, "
            "robots_snapshot_sha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, ?, TRUE, ?, 'V', ?, ?, ?, ?, ?, ?, ?)",
            (
                clave,
                f"wpjson-{m.dominio}-{m.proyecto_slug}",
                m.modelo_slug,
                tipologia_de(m.dormitorios, m.banos),
                m.dormitorios,
                m.banos,
                float(m.m2_totales) if m.m2_totales is not None else None,
                m.precio_desde_uf,
                None,  # disponible: el bloque de modelo no lo dice (ND)
                m.fetched_at,
                *procedencia,
            ),
        )
    return contadores


# -------------------------------------------------------------------------------- selftest


def selftest_fixture(carpeta: Path | None = None) -> tuple[bool, list[str]]:
    """§7.1, mitad de fixture: el parser extrae ≥95% de los campos requeridos y los
    rangos son plausibles. La mitad viva es la corrida misma de `recolectar-wpjson`,
    que imprime conteos y errores para el ojo humano.
    """
    from flujocero.sources.base import RAIZ

    carpeta = carpeta or RAIZ / "tests" / "fixtures" / "wpjson"
    fallas: list[str] = []
    html = (carpeta / "proyecto.html").read_text(encoding="utf-8")
    rest = json.loads((carpeta / "proyecto_rest.json").read_text(encoding="utf-8"))

    modelos = modelos_de_html(
        html, "https://www.socovesa.cl/nuestros-proyectos/portal-del-libertador-ix/"
    )
    if len(modelos) != 2:
        fallas.append(f"fixture: se esperaban 2 modelos, salieron {len(modelos)}")
    campos = ("precio_desde_uf", "m2_totales", "dormitorios", "banos", "modelo_slug")
    poblados = sum(1 for m in modelos for c in campos if m.get(c) is not None)
    esperados = len(modelos) * len(campos)
    if esperados and poblados / esperados < 0.95:
        fallas.append(f"fixture: {poblados}/{esperados} campos poblados (<95%)")
    for m in modelos:
        p = m.get("precio_desde_uf")
        if p is not None and not (Decimal(500) <= p <= Decimal(60000)):
            fallas.append(f"fixture: precio_uf fuera de rango plausible: {p}")
        m2 = m.get("m2_totales")
        if m2 is not None and not (Decimal(15) <= m2 <= Decimal(400)):
            fallas.append(f"fixture: m2 fuera de rango plausible: {m2}")

    meta = meta_de_rest(rest)
    if not meta["slug"] or not meta["link"]:
        fallas.append("fixture REST: sin slug o link")
    if meta["comuna_slug"] is None:
        fallas.append("fixture REST: no extrajo la comuna de class_list")

    # perfil "modelo" (Pilares): la pagina ES el modelo, con su REST de tags
    html_p = (carpeta / "pilares_modelo.html").read_text(encoding="utf-8")
    rest_p = json.loads((carpeta / "pilares_modelo_rest.json").read_text(encoding="utf-8"))
    modelo_p = modelo_de_html_pilares(
        html_p,
        "https://www.pilares.cl/nuestros-proyectos/proyectos-para-vivir/rodriguez-velasco-10/depto-a1/",
    )
    if modelo_p["precio_desde_uf"] != Decimal("2990"):
        fallas.append(f"fixture pilares: precio {modelo_p['precio_desde_uf']} != 2990")
    meta_p = meta_de_rest(rest_p)
    if meta_p["comuna_slug"] != "la-florida":
        fallas.append("fixture pilares REST: no extrajo comuna-la-florida")
    if meta_p["dormitorios"] != 1 or meta_p["banos"] != 1:
        fallas.append("fixture pilares REST: no extrajo dormitorios/banos de los tags")
    return (not fallas, fallas)
