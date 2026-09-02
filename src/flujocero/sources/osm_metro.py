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
PARSER_VERSION = "0.2.0"
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
# cercania, no subway. `railway=construction` + subway trae las estaciones de L7.
CONSULTA = """
[out:json][timeout:90];
area["ISO3166-1"="CL"][admin_level=2]->.cl;
(
  node(area.cl)[railway=station][station=subway];
  node(area.cl)[railway=station][network~"Biotr",i];
  node(area.cl)[railway=construction][station=subway];
  node(area.cl)[railway=proposed][station=subway];
  node(area.cl)["construction:railway"="station"][station=subway];
);
out body;
"""


@dataclass(frozen=True)
class Estacion:
    estacion_id: str
    nombre: str
    red: str  # 'metro-santiago' | 'biotren'
    linea: str | None  # normalizada en minusculas sin espacios; None si OSM no la trae
    estado: str  # 'operativa' | 'construccion'
    lat: float
    lon: float


@dataclass
class CosechaMetro:
    estaciones: list[Estacion] = field(default_factory=list)
    sin_nombre: int = 0
    error: str | None = None


def _linea_de(tags: dict[str, str]) -> str | None:
    """La linea segun OSM, si la declara. 'L7', 'Línea 7' y '7' colapsan a 'l7'."""
    crudo = tags.get("ref") or tags.get("line") or tags.get("subway_line")
    if not crudo:
        return None
    limpio = crudo.strip().lower().replace("línea", "l").replace("linea", "l").replace(" ", "")
    return limpio if limpio.startswith("l") else f"l{limpio}"


def parsear(cuerpo: dict[str, Any]) -> CosechaMetro:
    """Elementos Overpass -> estaciones. Puro: testeable contra fixture."""
    cosecha = CosechaMetro()
    for el in cuerpo.get("elements", []):
        tags = el.get("tags", {})
        nombre = tags.get("name")
        if not nombre:
            # un nodo de estacion sin nombre no sirve para auditar; se cuenta, no se inventa
            cosecha.sin_nombre += 1
            continue
        en_construccion = (
            tags.get("railway") in ("construction", "proposed")
            or tags.get("construction:railway") == "station"
        )
        red = "biotren" if "biotr" in (tags.get("network") or "").lower() else "metro-santiago"
        cosecha.estaciones.append(
            Estacion(
                estacion_id=f"osm-{el['id']}",
                nombre=nombre,
                red=red,
                linea=_linea_de(tags),
                estado="construccion" if en_construccion else "operativa",
                lat=float(el["lat"]),
                lon=float(el["lon"]),
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
        return parsear(json.loads(doc.contenido.decode("utf-8")))
    c = CosechaMetro()
    c.error = " · ".join(errores)
    return c


def cargar(conexion: Any, cosecha: CosechaMetro, momento: datetime) -> int:
    """Reemplaza `dim_estacion_metro` entero: es un derivado del ultimo blob."""
    conexion.execute("DELETE FROM dim_estacion_metro")
    for e in cosecha.estaciones:
        conexion.execute(
            "INSERT INTO dim_estacion_metro (estacion_id, nombre, red, linea, estado, lat, "
            "lon, source_id, source_url, fetched_at, parser_version, raw_blob_path, "
            "robots_snapshot_sha) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                e.estacion_id,
                e.nombre,
                e.red,
                e.linea,
                e.estado,
                e.lat,
                e.lon,
                SOURCE_ID,
                OVERPASS_URLS[0],
                momento,
                PARSER_VERSION,
                "data/raw/osm_metro",
                "api-publica-odbl",
            ),
        )
    return len(cosecha.estaciones)
