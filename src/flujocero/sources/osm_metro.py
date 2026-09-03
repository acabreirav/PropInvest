"""Estaciones de Metro y Biotren desde OpenStreetMap (Overpass) — T-922.

Es el insumo del `catalizador` del §12: *"distancia a Metro operativo o en construccion
con fecha creible (<= 3 anios)"*. OSM tiene la geometria completa y al dia (ODbL, datos
abiertos, `json_publico` en el orden del §3.5); lo que OSM NO tiene es la fecha de
apertura de lo que esta en construccion — esa vive curada a mano en `config/metro.yml`,
con fuente, porque una estacion en construccion sin fecha creible no cataliza nada.

Una sola consulta Overpass para todo Chile, filtrada a subway (Metro de Santiago) y a la
red Biotren (Gran Concepcion). Raw primero, como todo colector (§3.6). La atribucion
ODbL queda en el meta de cada blob via `source_url`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flujocero.sources.base import escribir_crudo

SOURCE_ID = "osm_metro"
PARSER_VERSION = "0.5.0"
# El endpoint principal devolvio HTTP 406 en la maquina real: el frontal de
# overpass-api.de rechaza clientes sin User-Agent identificable (politica de uso de OSM).
# Se manda identificacion honesta y, si un servidor igual rechaza, se prueba el siguiente
# espejo oficial — son la misma base de datos.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
)
CABECERAS = {
    "User-Agent": "FlujoCero-ResearchBot/1.0 (investigacion inmobiliaria personal, Chile)",
    "Accept": "application/json",
}

# subway agarra Metro de Santiago; la red Biotren va por nombre porque es tren de
# cercania, no subway. Las obras (L7, extension L6) NO llevan `station=subway`: el
# esquema de ciclo de vida de OSM las etiqueta `railway=construction` +
# `construction=station` (o el prefijo `construction:railway=station`), y la condicion
# de subway se muda a `construction:station` — exigir `station=subway` ahi cosechaba 0.
# Fuente: wiki.openstreetmap.org/wiki/Tag:railway=construction y Key:construction:.
# La cosecha de obras va ancha y el filtro de red se hace en `parsear` (puro, testeable).
#
# Medido en las corridas vivas del 03-sep-2026 (scripts/diag_metro.py, sonda_l7.py y
# sonda_l7b.py sobre blobs crudos):
# - las PROPUESTAS de L9 son nodos `proposed:railway=station`, linea en
#   `network`="Línea 9", apertura 2030+;
# - las estaciones de L7 (obra real, 2028) NO existen como estaciones sueltas: son
#   nodos miembros de las relations de ruta `route=subway` ref=L7 ("Dirección Brasil"
#   / "Dirección Estoril"), tageados `railway=stop` + `subway=yes` +
#   `network`="Línea 7" + `start_date`="2028" — por eso se cosechan TAMBIEN los
#   miembros de toda relation route=subway y se clasifican en `parsear`;
# - OJO: en esos nodos `ref` es el NUMERO DE PARADA (Radal trae ref="6"), la linea
#   verdadera va en `network` — `_linea_de` mira network primero.
CONSULTA = """
[out:json][timeout:120];
area["ISO3166-1"="CL"][admin_level=2]->.cl;
relation(area.cl)[route=subway]->.rutas;
(
  node(area.cl)[railway=station][station=subway];
  node(area.cl)[railway=station][network~"Biotr",i];
  nwr(area.cl)[railway~"^(construction|proposed)$"][station=subway];
  nwr(area.cl)[railway=construction][construction=station];
  nwr(area.cl)[railway=proposed][proposed=station];
  nwr(area.cl)["construction:railway"="station"];
  nwr(area.cl)["proposed:railway"="station"];
  node(r.rutas);
);
out center;
"""


@dataclass(frozen=True)
class Estacion:
    estacion_id: str
    nombre: str
    red: str  # 'metro-santiago' | 'biotren' | 'efe'
    linea: str | None  # normalizada en minusculas sin espacios; None si OSM no la trae
    estado: str  # 'operativa' | 'construccion' | 'propuesta'
    lat: float
    lon: float
    anio_apertura: int | None = None  # opening_date/start_date de OSM; corrobora metro.yml


@dataclass
class CosechaMetro:
    estaciones: list[Estacion] = field(default_factory=list)
    sin_nombre: int = 0
    fuera_de_red: int = 0  # obras cosechadas que no son Metro ni Biotren (tranvia…)
    omitidas: int = 0  # miembros de ruta sin clasificar (stop_position de linea operativa)
    duplicadas: int = 0  # mismo (nombre, red, linea, estado): parada + estacion, o 2 sentidos
    error: str | None = None


def _linea_de(tags: dict[str, str]) -> str | None:
    """La linea segun OSM, si la declara. 'L7', 'Línea 7' y '7' colapsan a 'l7'.

    `network` manda cuando ES una linea ("Línea 7", "Línea 9"): en los nodos de parada
    de L7 el `ref` es el NUMERO DE PARADA (Radal trae ref="6"), no la linea — leer ref
    primero inventaria la linea equivocada (medido en sonda_l7b, 03-sep-2026). Una red
    ("Metro de Santiago") no es una linea, ahi si cae a ref/line/subway_line."""
    red = (tags.get("network") or "").strip()
    crudo = red if red.lower().startswith(("línea", "linea")) else None
    if not crudo:
        crudo = tags.get("ref") or tags.get("line") or tags.get("subway_line")
    if not crudo:
        return None
    limpio = crudo.strip().lower().replace("línea", "l").replace("linea", "l").replace(" ", "")
    return limpio if limpio.startswith("l") else f"l{limpio}"


def _anio_apertura_de(tags: dict[str, str]) -> int | None:
    """El anio que OSM declara en opening_date/start_date, si es parseable."""
    for clave in ("opening_date", "start_date"):
        v = (tags.get(clave) or "").strip()[:4]
        if v.isdigit():
            return int(v)
    return None


def _es_de_red_objetivo(tags: dict[str, str]) -> bool:
    """Metro (subway) o Biotren. Las obras declaran subway en el tag con prefijo de ciclo
    de vida (`construction:station=subway`), no en `station` — por eso se miran los tres."""
    if (
        "subway"
        in (
            tags.get("station"),
            tags.get("construction:station"),
            tags.get("proposed:station"),
        )
        or tags.get("subway") == "yes"
    ):
        return True
    red = f"{tags.get('network', '')} {tags.get('operator', '')}".lower()
    return "metro de santiago" in red or "biotr" in red


def parsear(cuerpo: dict[str, Any], ahora: datetime | None = None) -> CosechaMetro:
    """Elementos Overpass -> estaciones. Puro: `ahora` entra por argumento (§11).

    `ahora` clasifica como NO operativa toda estacion con apertura declarada en el
    futuro (las 5 del tren Alameda-Melipilla venian tageadas railway=station con
    start_date 2027-2029 y se contaban como abiertas — medido en sonda_l7, 03-sep)."""
    cosecha = CosechaMetro()
    vistos: set[tuple[str, int]] = set()
    claves: set[tuple[str, str, str | None, str]] = set()
    for el in cuerpo.get("elements", []):
        tipo = el.get("type", "node")
        if tipo == "relation":
            continue  # las relations de ruta solo aportan sus nodos miembros
        if (tipo, el["id"]) in vistos:
            continue
        vistos.add((tipo, el["id"]))
        tags = el.get("tags", {})
        if not _es_de_red_objetivo(tags):
            # la cosecha de obras va ancha (sin exigir subway); el filtro de red vive aca
            cosecha.fuera_de_red += 1
            continue
        anio = _anio_apertura_de(tags)
        hay_construction = tags.get("railway") == "construction" or any(
            k == "construction" or k.startswith("construction:") for k in tags
        )
        hay_proposed = tags.get("railway") == "proposed" or any(
            k == "proposed" or k.startswith("proposed:") for k in tags
        )
        es_estacion_hoy = tags.get("railway") == "station" or tags.get("station") == "subway"
        if not (es_estacion_hoy or hay_construction or hay_proposed or anio is not None):
            # miembro de ruta sin nada que lo clasifique (p.ej. stop_position de una
            # linea operativa, cuya estacion ya entro por su propio nodo): fuera, contado
            cosecha.omitidas += 1
            continue
        nombre = tags.get("name")
        if not nombre:
            # un nodo de estacion sin nombre no sirve para auditar; se cuenta, no se inventa
            cosecha.sin_nombre += 1
            continue
        # ways/relations traen `center` en vez de lat/lon (out center); sin geometria, fuera
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            cosecha.sin_nombre += 1
            continue
        # una PROPUESTA (L9, apertura 2030+) no es una obra, y una estacion con apertura
        # FUTURA no es operativa aunque diga railway=station: nada sin abrir se vende
        # como abierto
        es_futura = anio is not None and ahora is not None and anio > ahora.year
        if hay_construction:
            estado = "construccion"
        elif hay_proposed or es_futura:
            estado = "propuesta"
        else:
            estado = "operativa"
        red_txt = (tags.get("network") or "").lower()
        if "biotr" in red_txt:
            red = "biotren"
        elif tags.get("train") == "yes" or "melipilla" in red_txt:
            red = "efe"  # tren de cercania EFE colado por un station=subway ajeno
        else:
            red = "metro-santiago"
        linea = _linea_de(tags)
        clave = (nombre, red, linea, estado)
        if clave in claves:
            # la misma estacion como parada por sentido, o parada + etiqueta: una basta
            cosecha.duplicadas += 1
            continue
        claves.add(clave)
        eid = f"osm-{el['id']}" if tipo == "node" else f"osm-{tipo}-{el['id']}"
        cosecha.estaciones.append(
            Estacion(
                estacion_id=eid,
                nombre=nombre,
                red=red,
                linea=linea,
                estado=estado,
                lat=float(lat),
                lon=float(lon),
                anio_apertura=anio,
            )
        )
    return cosecha


def recolectar(
    cliente: Any, ahora: datetime | None = None, raiz: Path | None = None
) -> CosechaMetro:
    """Una request a Overpass (con espejos de respaldo), blob a la zona cruda, y a parsear."""
    momento = ahora or datetime.now(UTC)
    errores: list[str] = []
    for url in OVERPASS_URLS:
        try:
            r = cliente.post(url, data={"data": CONSULTA}, headers=CABECERAS)
        except Exception as exc:  # noqa: BLE001 — un espejo caido no es fatal, se anota
            errores.append(f"{url}: {type(exc).__name__}: {exc}")
            continue
        if r.status_code != 200:
            errores.append(f"{url}: HTTP {r.status_code}: {r.text[:120]}")
            continue
        doc = escribir_crudo(
            SOURCE_ID,
            url,
            r.content,
            momento,
            robots_snapshot_sha="api-publica-odbl",
            nombre="estaciones_cl",
            raiz=raiz,
            parser_version=PARSER_VERSION,
        )
        return parsear(json.loads(doc.contenido.decode("utf-8")), ahora=momento)
    c = CosechaMetro()
    c.error = " · ".join(errores)
    return c


def cargar(conexion: Any, cosecha: CosechaMetro, momento: datetime) -> int:
    """Reemplaza `dim_estacion_metro` entero: es un derivado del ultimo blob."""
    # bases creadas antes del parser 0.5.0 no traen la columna; migracion en el sitio
    conexion.execute(
        "ALTER TABLE dim_estacion_metro ADD COLUMN IF NOT EXISTS anio_apertura INTEGER"
    )
    conexion.execute("DELETE FROM dim_estacion_metro")
    for e in cosecha.estaciones:
        conexion.execute(
            "INSERT INTO dim_estacion_metro (estacion_id, nombre, red, linea, estado, lat, "
            "lon, anio_apertura, source_id, source_url, fetched_at, parser_version, "
            "raw_blob_path, robots_snapshot_sha) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?)",
            (
                e.estacion_id,
                e.nombre,
                e.red,
                e.linea,
                e.estado,
                e.lat,
                e.lon,
                e.anio_apertura,
                SOURCE_ID,
                OVERPASS_URLS[0],
                momento,
                PARSER_VERSION,
                "data/raw/osm_metro",
                "api-publica-odbl",
            ),
        )
    return len(cosecha.estaciones)
