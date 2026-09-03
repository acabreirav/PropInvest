"""Sonda T-922b ronda 3 · ¿dónde vive la L7 en OSM?

La ampliación a nwr trajo CERO elementos nuevos: en OSM Chile no hay nada con
`construction=station` ni `construction:railway=station`. Hipótesis restantes:
  A) las estaciones de L7/L6-ext están tageadas como `railway=station` +
     `station=subway` con fecha futura (`opening_date`/`start_date`) — o sea,
     ya están DENTRO de nuestras 126 "operativas", mal clasificadas;
  B) la obra existe solo como túnel (ways `railway=construction` sin estaciones)
     y/o como relation de ruta — habría que derivar estaciones de otra parte.

Parte 1 relee el blob crudo local (cero requests). Parte 2 hace UNA consulta
exploratoria a Overpass y guarda el crudo (§3.6) antes de resumir.

Uso:  uv run python scripts/sonda_l7.py
"""

from __future__ import annotations

import collections
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from flujocero.sources import osm_metro
from flujocero.sources.base import escribir_crudo

RAIZ = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- parte 1: el blob local
blobs = sorted((RAIZ / "data" / "raw" / "osm_metro").rglob("estaciones_cl.json.gz"))
if blobs:
    cuerpo = json.loads(gzip.open(blobs[-1], "rb").read().decode("utf-8"))
    print(f"— parte 1 · blob local: {blobs[-1].name} ({blobs[-1].parent})")
    futuras = []
    for el in cuerpo.get("elements", []):
        t = el.get("tags", {})
        if t.get("railway") != "station":
            continue
        fecha = t.get("opening_date") or t.get("start_date") or ""
        if fecha[:4].isdigit() and int(fecha[:4]) >= 2026:
            futuras.append((t.get("name"), fecha, t.get("network"), t.get("ref")))
    if futuras:
        print(f"  ¡{len(futuras)} 'operativas' con fecha de apertura FUTURA! (hipótesis A)")
        for nombre, fecha, red, ref in futuras[:25]:
            print(f"    {nombre!r:<28} abre {fecha:<12} network={red!r} ref={ref!r}")
    else:
        print("  ninguna 'operativa' declara apertura futura — hipótesis A descartada")
else:
    print("— parte 1: sin blob local (corre recolectar-metro primero)")

# ------------------------------------------------------- parte 2: consulta exploratoria
# Todo lo que huela a obra de metro en Chile, sin asumir el tag de estación:
# el túnel (`railway=construction`), cualquier `construction=*` ferroviario, las
# relations de ruta subway (ahí L7 puede vivir como route con estado), y nombres "Línea 7".
CONSULTA = """
[out:json][timeout:120];
area["ISO3166-1"="CL"][admin_level=2]->.cl;
(
  nwr(area.cl)[railway=construction];
  nwr(area.cl)[construction=station];
  nwr(area.cl)["construction:station"];
  relation(area.cl)[route=subway];
  relation(area.cl)["construction:route"];
  nwr(area.cl)[name~"Línea 7|Linea 7",i][railway];
);
out tags center 600;
"""

print("\n— parte 2 · consulta exploratoria a Overpass (~30 s)…")
momento = datetime.now(UTC)
with httpx.Client(timeout=150) as cliente:
    respuesta = None
    for url in osm_metro.OVERPASS_URLS:
        try:
            r = cliente.post(url, data={"data": CONSULTA}, headers=osm_metro.CABECERAS)
        except Exception as exc:  # noqa: BLE001 — sonda: se anota y se prueba el espejo
            print(f"  {url}: {type(exc).__name__}")
            continue
        if r.status_code == 200:
            respuesta = r
            break
        print(f"  {url}: HTTP {r.status_code}")
if respuesta is None:
    raise SystemExit("  ningún espejo respondió")

doc = escribir_crudo(
    osm_metro.SOURCE_ID,
    str(respuesta.url),
    respuesta.content,
    momento,
    robots_snapshot_sha="api-publica-odbl",
    nombre="sonda_l7",
    parser_version="sonda",
)
cuerpo = json.loads(doc.contenido.decode("utf-8"))
els = cuerpo.get("elements", [])
print(f"  {len(els)} elementos. Resumen por (type, railway, construction, route):")
cuenta = collections.Counter(
    (
        e.get("type"),
        (e.get("tags") or {}).get("railway"),
        (e.get("tags") or {}).get("construction"),
        (e.get("tags") or {}).get("route"),
    )
    for e in els
)
for clave, n in cuenta.most_common(15):
    print(f"    {n:>4} × {clave}")

print("\n  relations de ruta subway (nombre · ref · estado que declaren):")
for e in els:
    t = e.get("tags") or {}
    if e.get("type") == "relation":
        print(
            f"    r{e['id']}: name={t.get('name')!r} ref={t.get('ref')!r} "
            f"route={t.get('route')!r} construction={t.get('construction')!r} "
            f"state={t.get('state')!r} opening_date={t.get('opening_date')!r}"
        )

print("\n  elementos con NOMBRE entre lo construction (candidatos a estación):")
mostrados = 0
for e in els:
    t = e.get("tags") or {}
    if t.get("name") and (t.get("railway") == "construction" or t.get("construction")):
        print(f"    {e.get('type')}-{e['id']}: {json.dumps(t, ensure_ascii=False)[:220]}")
        mostrados += 1
        if mostrados >= 20:
            break
if not mostrados:
    print("    ninguno — la obra no tiene elementos con nombre")
