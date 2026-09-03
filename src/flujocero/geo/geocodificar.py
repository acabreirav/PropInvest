"""Geocodificación de proyectos nuevos vía Nominatim (OSM) — T-931c.

El informe evalúa la oferta nueva al "desde" SOLO si el proyecto tiene coordenadas
(microzona por geo — el §2.4 prohíbe usar la mediana comunal como comparable). Fundamenta
y RVC publican GeoCoordinates; el resto quedaba fuera (sin_geo=217 unidades el 03-sep).
Nominatim resuelve "dirección (o nombre) + comuna, Chile" → lat/lon.

Reglas duras:
- Política de uso de Nominatim (operations.osmfoundation.org/policies/nominatim/):
  MÁXIMO absoluto 1 request/segundo y User-Agent identificable. `json_publico` en el
  orden del §3.5, ODbL igual que osm_metro. La pausa vive en `PAUSA_S` y solo los tests
  la bajan.
- El resultado se acepta SOLO si su dirección devuelta menciona la comuna declarada del
  proyecto (comparación sin acentos): una coordenada en la comuna equivocada es peor
  que ninguna — ND antes que inventar (§3.2).
- Raw primero (§3.6): cada respuesta a `data/raw/nominatim_geocode/` y las seis columnas
  de procedencia en `geo_proyecto`.
- Se escribe en `geo_proyecto` (tabla propia con upsert), NO con UPDATE de dim_proyecto:
  la FK de DuckDB veta el UPDATE de una fila referenciada por facts — el mismo veto que
  congeló los dims del colector wpjson.
"""

from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flujocero.sources.base import escribir_crudo

SOURCE_ID = "nominatim_geocode"
PARSER_VERSION = "0.1.0"
URL = "https://nominatim.openstreetmap.org/search"
CABECERAS = {
    "User-Agent": "FlujoCero-ResearchBot/1.0 (investigacion inmobiliaria personal, Chile)",
    "Accept": "application/json",
}
PAUSA_S = 1.1  # la política pide 1 req/s como máximo ABSOLUTO; 1,1 s deja margen


@dataclass
class ResumenGeocode:
    consultados: int = 0
    geocodificados: int = 0
    comuna_no_coincide: int = 0  # Nominatim respondió, pero en otra comuna: ND, contado
    sin_resultado: int = 0
    errores: list[str] = field(default_factory=list)


def _plano(texto: str) -> str:
    """minúsculas y sin acentos: 'Ñuñoa' y 'Nunoa' deben coincidir."""
    sin = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin if not unicodedata.combining(c)).lower()


def construir_consulta(nombre: str, direccion: str | None, comuna_nombre: str) -> str:
    """La dirección publicada manda; sin ella, el nombre del proyecto + comuna resuelve
    la mayoría de los edificios (Nominatim indexa nombres de edificios OSM)."""
    base = (direccion or "").strip() or (nombre or "").strip()
    return f"{base}, {comuna_nombre}, Chile"


def parsear(cuerpo: list[dict[str, Any]], comuna_nombre: str) -> tuple[float, float, str] | None:
    """Primer resultado de Nominatim → (lat, lon, display_name), SOLO si la dirección
    devuelta menciona la comuna declarada. Puro: testeable contra fixture."""
    if not cuerpo:
        return None
    r = cuerpo[0]
    display = str(r.get("display_name") or "")
    if _plano(comuna_nombre) not in _plano(display):
        return None
    try:
        return float(r["lat"]), float(r["lon"]), display
    except (KeyError, TypeError, ValueError):
        return None


def geocodificar(
    cliente: Any,
    conexion: Any,
    ahora: datetime | None = None,
    limite: int = 0,
    pausa_s: float = PAUSA_S,
    raiz: Path | None = None,
) -> ResumenGeocode:
    """Resuelve lat/lon para los proyectos de OFERTA NUEVA sin geo (ni publicada ni ya
    geocodificada). Solo oferta nueva: geocodificar todo dim_proyecto a 1 req/s tardaría
    horas y las usadas no pasan por la microzona del proyecto."""
    momento = ahora or datetime.now(UTC)
    resumen = ResumenGeocode()
    pendientes = conexion.execute(
        """
        SELECT p.proyecto_id, p.nombre, p.direccion, c.nombre
        FROM dim_proyecto p
        JOIN dim_comuna c USING (comuna_id)
        LEFT JOIN geo_proyecto g USING (proyecto_id)
        WHERE p.lat IS NULL AND g.proyecto_id IS NULL
          AND EXISTS (
            SELECT 1 FROM fact_unidad_venta f
            WHERE f.proyecto_id = p.proyecto_id
              AND f.precio_es_desde AND f.valid_to IS NULL
          )
        ORDER BY p.proyecto_id
        """
    ).fetchall()
    if limite:
        pendientes = pendientes[:limite]

    for i, (pid, nombre, direccion, comuna_nombre) in enumerate(pendientes):
        if i:
            time.sleep(pausa_s)
        resumen.consultados += 1
        consulta = construir_consulta(nombre, direccion, comuna_nombre)
        try:
            r = cliente.get(
                URL,
                params={
                    "q": consulta,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "cl",
                },
                headers=CABECERAS,
            )
        except Exception as exc:  # noqa: BLE001 — un proyecto fallido no mata la corrida
            resumen.errores.append(f"{pid}: {type(exc).__name__}: {exc}")
            continue
        if r.status_code != 200:
            resumen.errores.append(f"{pid}: HTTP {r.status_code}")
            continue
        doc = escribir_crudo(
            SOURCE_ID,
            str(r.url),
            r.content,
            momento,
            robots_snapshot_sha="api-publica-odbl-politica-1rps",
            nombre=pid,
            raiz=raiz,
            parser_version=PARSER_VERSION,
        )
        cuerpo = json.loads(doc.contenido.decode("utf-8"))
        res = parsear(cuerpo, comuna_nombre)
        if res is None:
            if cuerpo:
                resumen.comuna_no_coincide += 1
            else:
                resumen.sin_resultado += 1
            continue
        lat, lon, display = res
        conexion.execute(
            "INSERT INTO geo_proyecto (proyecto_id, lat, lon, consulta, resultado, "
            "evidence_level, source_id, source_url, fetched_at, parser_version, "
            "raw_blob_path, robots_snapshot_sha) VALUES (?, ?, ?, ?, ?, 'V', ?, ?, ?, ?, "
            "?, ?) ON CONFLICT (proyecto_id) DO UPDATE SET lat=excluded.lat, "
            "lon=excluded.lon, consulta=excluded.consulta, resultado=excluded.resultado, "
            "fetched_at=excluded.fetched_at, raw_blob_path=excluded.raw_blob_path",
            (
                pid,
                lat,
                lon,
                consulta,
                display,
                SOURCE_ID,
                str(r.url),
                momento,
                PARSER_VERSION,
                str(doc.ruta),
                "api-publica-odbl-politica-1rps",
            ),
        )
        resumen.geocodificados += 1
    return resumen
