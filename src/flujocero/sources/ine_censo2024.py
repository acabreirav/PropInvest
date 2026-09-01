"""Censo 2024 del INE, por manzana — la fuente de `riesgo_microzona` (T-014).

Dos archivos oficiales, DESCARGADOS A MANO por el inversionista (el proxy del entorno
remoto bloquea ine.gob.cl, y una descarga de 100+ MB no necesita colector):

- `Base_manzana_entidad_CPV24.*` — las 189 variables de personas, hogares y viviendas
  por manzana-entidad, de censo2024.ine.gob.cl/resultados.
- `shp-apc2023-r{02,04,08,13}.zip` — la cartografia censal (poligonos de manzana) de la
  Base Cartografica APC 2023, regiones del alcance del §10, del portal Geodatos Abiertos.

Este modulo hace la mitad de zona cruda (§3.6): toma lo que haya en
`data/incoming/censo2024/`, lo copia VERBATIM a `data/raw/ine_censo2024/{yyyy}/{mm}/{dd}/`
—fechado por la fecha de descarga del archivo, no por hoy— y le escribe el `.meta.json`
del §3.1 al lado. Sin gzip encima: un ZIP re-comprimido es puro costo, y un CSV de 115 MB
se conserva legible tal cual. La idempotencia es por sha: re-correr no duplica ni pisa.

`robots_snapshot_sha` lleva un sentinela declarado: esto es descarga manual de datos
abiertos oficiales, no scraping — no hay robots.txt que consultar y fingir uno seria
inventar procedencia. `legal_tier` conceptual: `api_oficial` (datos abiertos del Estado).

El parser (CSV -> dim_manzana, SHP -> geometrias) es la otra mitad de T-014 y se escribe
contra el formato REAL de los archivos, no contra lo que imaginamos que traen.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flujocero.sources.base import RAIZ, ZONA_CRUDA

SOURCE_ID = "ine_censo2024"
PARSER_VERSION = "0.1.0"
CARPETA_INCOMING = RAIZ / "data" / "incoming" / "censo2024"

# La URL de la pagina de descarga oficial, por familia de archivo. Idealmente seria el
# enlace directo al archivo; el INE los sirve detras de botones y lo que el inversionista
# pudo copiar fue la pagina. Es procedencia real —pagina + nombre de archivo + sha— y se
# registra tal cual es, no se adorna.
URL_RESULTADOS = "https://censo2024.ine.gob.cl/resultados/"
URL_GEODATOS = "https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos"
ROBOTS_SHA_MANUAL = "descarga-manual-datos-abiertos-oficiales"


def url_de_origen(nombre: str) -> str:
    """De que pagina oficial salio este archivo, por su nombre."""
    if "cpv24" in nombre.lower():
        return URL_RESULTADOS
    return URL_GEODATOS


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


@dataclass(frozen=True)
class Promocion:
    """Que paso con un archivo de incoming al promoverlo a la zona cruda."""

    nombre: str
    destino: Path
    accion: str  # "copiado" | "ya_estaba" | "conflicto"
    bytes: int
    sha: str


def promover(
    origen: Path | None = None, raiz: Path | None = None, ahora: datetime | None = None
) -> list[Promocion]:
    """`data/incoming/censo2024/` → zona cruda, con meta §3.1 y sin duplicar.

    - Se fecha por el **mtime del archivo** (la fecha en que se descargo), no por hoy:
      `fetched_at` miente si dice cuando corrio el comando en vez de cuando se bajo el dato.
    - `ya_estaba`: mismo nombre y mismo sha en la zona cruda — no se toca.
    - `conflicto`: mismo nombre, sha distinto — NO se pisa (la zona cruda es inmutable);
      se reporta para que un humano mire cual es cual.
    - El original en incoming se conserva: borrar lo que el usuario descargo no es
      decision de este codigo.
    """
    origen = origen or CARPETA_INCOMING
    if not origen.is_dir():
        return []
    salida: list[Promocion] = []
    for archivo in sorted(origen.iterdir()):
        if not archivo.is_file() or archivo.name.endswith(".meta.json"):
            continue
        momento = ahora or datetime.fromtimestamp(archivo.stat().st_mtime, tz=UTC)
        base = (raiz or ZONA_CRUDA) / SOURCE_ID / f"{momento:%Y}" / f"{momento:%m}"
        destino = base / f"{momento:%d}" / archivo.name
        sha = _sha256(archivo)
        if destino.exists():
            accion = "ya_estaba" if _sha256(destino) == sha else "conflicto"
            salida.append(Promocion(archivo.name, destino, accion, archivo.stat().st_size, sha))
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archivo, destino)
        destino.with_name(destino.name.rsplit(".", 1)[0] + ".meta.json").write_text(
            json.dumps(
                {
                    "source_id": SOURCE_ID,
                    "source_url": url_de_origen(archivo.name),
                    "archivo_original": archivo.name,
                    "fetched_at": momento.isoformat(),
                    "robots_snapshot_sha": ROBOTS_SHA_MANUAL,
                    "parser_version": PARSER_VERSION,
                    "sha_contenido": sha,
                    "bytes": archivo.stat().st_size,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        salida.append(Promocion(archivo.name, destino, "copiado", archivo.stat().st_size, sha))
    return salida


# ----------------------------------------------------------------- carga a DuckDB (T-014)


def _blobs_crudos(patron: str, raiz: Path | None = None) -> list[Path]:
    base = (raiz or ZONA_CRUDA) / SOURCE_ID
    return sorted(base.rglob(patron)) if base.is_dir() else []


def _meta_de(blob: Path) -> dict[str, object]:
    meta = blob.with_name(blob.name.rsplit(".", 1)[0] + ".meta.json")
    return json.loads(meta.read_text(encoding="utf-8"))


# Columna del CSV del INE -> columna de dim_manzana. El resto de las 189 queda en la zona
# cruda; sumar una es agregarla aqui y al DDL, y re-correr `ingerir-censo`.
_MAPEO_CSV = {
    "MANZENT": "manzent",
    "CUT": "cut",
    "COMUNA": "comuna",
    "REGION": "region",
    "TIPO_MZ": "tipo_mz",
    "n_per": "n_personas",
    "n_hog": "n_hogares",
    "prom_per_hog": "prom_personas_hogar",
    "prom_edad": "prom_edad",
    "prom_escolaridad18": "prom_escolaridad18",
    "n_vp": "n_viviendas",
    "n_vp_ocupada": "n_viv_ocupadas",
    "n_vp_desocupada": "n_viv_desocupadas",
    "n_tipo_viv_depto": "n_viv_depto",
    "n_tipo_viv_casa": "n_viv_casa",
    "n_tenencia_arrendada_contrato": "n_hog_arrienda_contrato",
    "n_tenencia_arrendada_sin_contrato": "n_hog_arrienda_sin_contrato",
    "n_tenencia_propia_pagada": "n_hog_propia_pagada",
    "n_tenencia_propia_pagandose": "n_hog_propia_pagandose",
    "n_hog_unipersonales": "n_hog_unipersonales",
}


def cargar_csv(conexion: object, raiz: Path | None = None) -> int:
    """`Base_manzana_entidad_CPV24.csv` (zona cruda) → `dim_manzana`, dentro de DuckDB.

    Tres particularidades del archivo real del INE, verificadas mirando sus primeras filas:

    - **`*` es un valor enmascarado por privacidad** (conteos chicos). Entra como NULL,
      jamas como 0: un cero inventado sesga toda tasa calculada encima (§3.2, ND).
    - **Decimal con coma chilena** (`28,8`): `decimal_separator=','`.
    - `ID_ENTIDAD` viene destruido por Excel (`1,10101E+11`) EN EL ARCHIVO OFICIAL.
      No se usa: la llave es `MANZENT`, que si esta intacta.

    `dim_manzana` es un derivado de la zona cruda: se recarga completa (DELETE + INSERT),
    y las seis columnas del §3.1 salen del `.meta.json` del blob.
    """
    blobs = _blobs_crudos("Base_manzana_entidad_CPV24.csv", raiz)
    if not blobs:
        raise FileNotFoundError(
            "no hay Base_manzana_entidad_CPV24.csv en la zona cruda: corre la promocion "
            "primero (cli ingerir-censo)"
        )
    blob = blobs[-1]  # el mas reciente, por orden de ruta fechada
    meta = _meta_de(blob)

    # MANZENT llega inferido como BIGINT y la llave es texto; el resto va tal cual.
    origen = ", ".join(
        'CAST("MANZENT" AS VARCHAR)' if c == "MANZENT" else f'"{c}"' for c in _MAPEO_CSV
    )
    destino = ", ".join(_MAPEO_CSV.values())
    conexion.execute("DELETE FROM dim_manzana")  # type: ignore[attr-defined]
    conexion.execute(  # type: ignore[attr-defined]
        f"INSERT INTO dim_manzana ({destino}, source_id, source_url, fetched_at, "  # noqa: S608
        "parser_version, raw_blob_path, robots_snapshot_sha) "
        f"SELECT {origen}, ?, ?, ?, ?, ?, ? "  # noqa: S608
        "FROM read_csv(?, delim=';', header=true, nullstr='*', decimal_separator=',', "
        "sample_size=-1)",
        (
            meta["source_id"],
            meta["source_url"],
            meta["fetched_at"],
            meta["parser_version"],
            str(blob),
            meta["robots_snapshot_sha"],
            str(blob),
        ),
    )
    fila = conexion.execute("SELECT count(*) FROM dim_manzana").fetchone()  # type: ignore[attr-defined]
    return int(fila[0])


def cargar_geometria(conexion: object, raiz: Path | None = None) -> dict[str, str]:
    """Los poligonos de `Manzana_Urbana.shp` de cada ZIP regional → `dim_manzana`.

    Devuelve `{zip: resultado}` legible. Tolerante a proposito con el nombre de la columna
    de la llave: el diccionario de capas APC2023 no se parseo todavia, asi que se busca la
    columna que contenga `manzent` (case-insensitive) y, si no aparece, se reportan las
    columnas reales del DBF en vez de adivinar — el mensaje ES el diagnostico.

    Reproyecta a EPSG:4326 y guarda el poligono como WKB mas su centroide en lat/lon.
    """
    import zipfile

    import geopandas as gpd

    resultados: dict[str, str] = {}
    for zip_path in _blobs_crudos("shp-apc2023-r*.zip", raiz):
        with zipfile.ZipFile(zip_path) as zf:
            miembro = next(
                (n for n in zf.namelist() if n.lower().endswith("manzana_urbana.shp")), None
            )
        if miembro is None:
            resultados[zip_path.name] = "sin capa Manzana_Urbana.shp adentro"
            continue
        gdf = gpd.read_file(f"zip://{zip_path}!{miembro}")
        col = next((c for c in gdf.columns if "manzent" in c.lower()), None)
        if col is None:
            resultados[zip_path.name] = f"sin columna MANZENT; el DBF trae: {list(gdf.columns)}"
            continue
        gdf = gdf.to_crs(4326)
        tabla = gdf[[col]].copy()
        tabla.columns = ["manzent"]
        tabla["manzent"] = tabla["manzent"].astype("int64", errors="ignore").astype(str)
        centroides = gdf.geometry.representative_point()
        tabla["lat"] = centroides.y
        tabla["lon"] = centroides.x
        tabla["wkb"] = gdf.geometry.to_wkb()
        conexion.register("tmp_geo", tabla)  # type: ignore[attr-defined]
        conexion.execute(  # type: ignore[attr-defined]
            "UPDATE dim_manzana SET lat = g.lat, lon = g.lon, geom_wkb = g.wkb "
            "FROM tmp_geo g WHERE dim_manzana.manzent = g.manzent"
        )
        conexion.unregister("tmp_geo")  # type: ignore[attr-defined]
        resultados[zip_path.name] = f"{len(tabla)} poligonos leidos"
    return resultados
