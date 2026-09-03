"""Diagnóstico T-922b · ¿qué tags de línea traen las obras cosechadas?

Las 38 estaciones en construcción quedaron fuera del catalizador con el motivo
"sin linea en OSM o sin fecha creible". Este script lee el ÚLTIMO blob crudo de
`data/raw/osm_metro/` (cero requests nuevas, §3.6) y muestra qué declara cada nodo,
para decidir si el arreglo va en `_linea_de`, en `config/metro.yml`, o requiere
resolver la línea vía relation.

Uso:  uv run python scripts/diag_metro.py
"""

from __future__ import annotations

import collections
import gzip
import json
from pathlib import Path

from flujocero.sources import osm_metro

raiz = Path(__file__).resolve().parents[1] / "data" / "raw" / "osm_metro"
blobs = sorted(raiz.rglob("*.json.gz"))
if not blobs:
    raise SystemExit("no hay blobs en data/raw/osm_metro — corre recolectar-metro primero")
blob = blobs[-1]
cuerpo = json.loads(gzip.open(blob, "rb").read().decode("utf-8"))
print(f"blob: {blob}\n")

obras: list[tuple[int, dict[str, str]]] = []
for el in cuerpo.get("elements", []):
    t = el.get("tags", {})
    en_obra = (
        t.get("railway") in ("construction", "proposed")
        or t.get("construction:railway") == "station"
        or t.get("proposed:railway") == "station"
    )
    if en_obra and osm_metro._es_de_red_objetivo(t):
        obras.append((el["id"], t))

print(f"obras de la red objetivo: {len(obras)}")

por_linea = collections.Counter(osm_metro._linea_de(t) for _id, t in obras)
print(f"linea normalizada -> nodos: {dict(por_linea)}")

claves = collections.Counter(k for _id, t in obras for k in t)
print(f"tags presentes (tag: en cuantos nodos): {dict(claves.most_common(18))}")

print("\nejemplos completos (primeros 6):")
for _id, t in obras[:6]:
    print(f"  osm-{_id}: {json.dumps(t, ensure_ascii=False)}")
