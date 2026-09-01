"""El diccionario de barrios de MercadoLibre, con su centro — capa 2, T-014b.

Es la fuente que el CLAUDE.md §4 declara para la microzonificacion: la cascada
`country -> state -> city -> neighborhood` de `classified_locations` es **el vocabulario
de barrios que efectivamente usan los avisos** — nuestras microzonas se llaman como se
llaman porque el portal las llama asi. Este colector le agrega lo que no teniamos: el
`neighborhood_id` oficial y el **centro geografico** de cada barrio.

Para que: las microzonas no tienen poligono, y sin geografia no hay puente hacia las
manzanas censales de `dim_manzana` (T-014). Con el centro de cada barrio, cada manzana se
asigna a su barrio mas cercano dentro de la misma comuna — una particion de Voronoi, que
es una aproximacion DECLARADA (el ADR de T-014b la documenta), no un poligono inventado.

Legal: `api_oficial` (§3.5, primer lugar del orden de preferencia). Se recolecta SOLO el
alcance del §10: 16 regiones enteras serian requests para barrios donde no rankeamos nada.

`/sites/MLC/search` esta 403 para todos (ADR 003); `classified_locations` es otro recurso
y la unica forma de saber si responde es pedirlo — raw primero, como siempre (§3.6).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flujocero.sources.base import RawDoc, escribir_crudo
from flujocero.sources.portal_comun import slug

SOURCE_ID = "meli_locations"
PARSER_VERSION = "0.1.0"
RUTA_PAIS = "/classified_locations/countries/CL"
# La API oficial declara sus limites por app, no por robots.txt; la pausa es cortesia
# y suficiente: el alcance completo son ~300 requests.
PAUSA_S = 0.3


@dataclass(frozen=True)
class Barrio:
    """Un barrio del diccionario MELI, listo para cruzar con dim_microzona."""

    comuna_slug: str
    barrio_slug: str
    neighborhood_id: str
    nombre: str
    lat: float | None  # None = la API no trajo geo_information: ND, no cero
    lon: float | None


@dataclass
class Cosecha:
    barrios: list[Barrio] = field(default_factory=list)
    comunas_encontradas: set[str] = field(default_factory=set)
    comunas_sin_ciudad_meli: set[str] = field(default_factory=set)
    requests: int = 0
    errores: list[str] = field(default_factory=list)


def _json_de(doc: RawDoc) -> Any:
    return json.loads(doc.contenido.decode("utf-8"))


def recolectar(
    cliente: Any,
    comunas: frozenset[str],
    ahora: datetime | None = None,
    raiz: Path | None = None,
    pausa: float = PAUSA_S,
) -> Cosecha:
    """Camina la cascada del pais al barrio, guardando CADA respuesta en crudo antes de
    leerla. Restringido a `comunas` (slugs del §10): el resto del pais no se pide.

    Un nivel que falle no bota la cosecha: se registra el error con el motivo que da el
    cuerpo de MercadoLibre (no solo el codigo) y se sigue con lo que si respondio.
    """
    momento = ahora or datetime.now(UTC)
    cosecha = Cosecha()

    def pedir(ruta: str, nombre: str) -> Any | None:
        cosecha.requests += 1
        r = cliente.get(ruta)
        time.sleep(pausa)
        if r.status_code != 200:
            cosecha.errores.append(f"{ruta}: HTTP {r.status_code} · {cliente.motivo(r)}")
            return None
        doc = escribir_crudo(
            SOURCE_ID,
            f"https://api.mercadolibre.com{ruta}",
            r.content,
            momento,
            robots_snapshot_sha="api-oficial-sin-robots",
            nombre=nombre,
            raiz=raiz,
            parser_version=PARSER_VERSION,
        )
        return _json_de(doc)

    pais = pedir(RUTA_PAIS, "pais_CL")
    if pais is None:
        return cosecha

    for estado in pais.get("states", []):
        detalle_estado = pedir(
            f"/classified_locations/states/{estado['id']}", f"estado_{estado['id']}"
        )
        if detalle_estado is None:
            continue
        for ciudad in detalle_estado.get("cities", []):
            cslug = slug(ciudad.get("name", ""))
            if cslug not in comunas:
                continue
            cosecha.comunas_encontradas.add(cslug)
            detalle_ciudad = pedir(
                f"/classified_locations/cities/{ciudad['id']}", f"ciudad_{cslug}"
            )
            if detalle_ciudad is None:
                continue
            for barrio in detalle_ciudad.get("neighborhoods", []):
                detalle = pedir(
                    f"/classified_locations/neighborhoods/{barrio['id']}",
                    f"barrio_{cslug}_{slug(barrio.get('name', ''))}",
                )
                lat = lon = None
                if detalle is not None:
                    ubicacion = (detalle.get("geo_information") or {}).get("location") or {}
                    lat, lon = ubicacion.get("latitude"), ubicacion.get("longitude")
                cosecha.barrios.append(
                    Barrio(
                        comuna_slug=cslug,
                        barrio_slug=slug(barrio.get("name", "")),
                        neighborhood_id=str(barrio["id"]),
                        nombre=barrio.get("name", ""),
                        lat=lat,
                        lon=lon,
                    )
                )
    cosecha.comunas_sin_ciudad_meli = set(comunas) - cosecha.comunas_encontradas
    return cosecha


def cargar(conexion: Any, cosecha: Cosecha, momento: datetime) -> dict[str, int]:
    """Cruza los barrios MELI con `dim_microzona` por `comuna/slug`, la misma clave que
    fabrican los colectores del portal — por construccion es el mismo vocabulario.

    - Microzona existente: se le escribe `meli_neighborhood_id` y su centro.
    - Barrio sin microzona nuestra: se INSERTA (la capa 2 dice que este diccionario ES
      dim_microzona); nace sin avisos, con centro, listo para cuando lleguen.
    - El centro puede venir NULL: se escribe NULL (ND), y el que consuma decide.
    """
    contadores = {"actualizadas": 0, "insertadas": 0, "sin_centro": 0}
    for b in cosecha.barrios:
        mid = f"{b.comuna_slug}/{b.barrio_slug}"
        if b.lat is None or b.lon is None:
            contadores["sin_centro"] += 1
        existe = conexion.execute(
            "SELECT 1 FROM dim_microzona WHERE microzona_id = ?", (mid,)
        ).fetchone()
        if existe:
            conexion.execute(
                "UPDATE dim_microzona SET meli_neighborhood_id = ?, centro_lat = ?, "
                "centro_lon = ? WHERE microzona_id = ?",
                (b.neighborhood_id, b.lat, b.lon, mid),
            )
            contadores["actualizadas"] += 1
        else:
            conexion.execute(
                "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?, ?, '') "
                "ON CONFLICT (comuna_id) DO NOTHING",
                (b.comuna_slug, b.comuna_slug),
            )
            conexion.execute(
                "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre, "
                "meli_neighborhood_id, centro_lat, centro_lon) VALUES (?, ?, ?, ?, ?, ?)",
                (mid, b.comuna_slug, b.nombre, b.neighborhood_id, b.lat, b.lon),
            )
            contadores["insertadas"] += 1
    return contadores
