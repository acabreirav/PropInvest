"""Sonda T-922b ronda 4 · los MIEMBROS de las relations de ruta de L7.

La ronda 3 mostró que L7 existe como relations de ruta (r15789478 "Dirección Brasil",
r17824814 "Dirección Estoril") y como túnel en obra, pero ningún elemento de estación
en construcción. Esta sonda baja a los miembros de esas relations: si ahí hay nodos de
estación, sus tags dicen cómo cosecharlos. De paso busca la estación de la extensión
L6 (Lo Errázuriz) por nombre.

Uso:  uv run python scripts/sonda_l7b.py
"""

from __future__ import annotations

import collections
import json
from datetime import UTC, datetime

import httpx

from flujocero.sources import osm_metro
from flujocero.sources.base import escribir_crudo

CONSULTA = """
[out:json][timeout:120];
relation(id:15789478,17824814)->.l7;
.l7 out body;
node(r.l7);
out body;
area["ISO3166-1"="CL"][admin_level=2]->.cl;
nwr(area.cl)[name~"Lo Errázuriz|Lo Errazuriz",i];
out tags center;
"""

print("— miembros de las relations L7 + búsqueda 'Lo Errázuriz' (~20 s)…")
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
    nombre="sonda_l7b",
    parser_version="sonda",
)
cuerpo = json.loads(doc.contenido.decode("utf-8"))
els = cuerpo.get("elements", [])

for e in els:
    if e.get("type") == "relation":
        roles = collections.Counter((m.get("type"), m.get("role")) for m in e.get("members", []))
        print(f"\n  relation r{e['id']} ({(e.get('tags') or {}).get('name')!r}):")
        for (tipo, rol), n in roles.most_common():
            print(f"    {n:>3} miembros {tipo} con rol {rol!r}")

print("\n  nodos miembros — combinaciones de tags de estación:")
combos = collections.Counter()
ejemplos: dict[tuple, list[str]] = {}
for e in els:
    if e.get("type") != "node":
        continue
    t = e.get("tags") or {}
    clave = (
        t.get("railway"),
        t.get("station"),
        t.get("public_transport"),
        t.get("subway"),
        ("opening_date" in t or "start_date" in t),
    )
    combos[clave] += 1
    ejemplos.setdefault(clave, []).append(t.get("name") or "(sin nombre)")
for clave, n in combos.most_common(12):
    nombres = ", ".join(ejemplos[clave][:4])
    print(f"    {n:>3} × railway/station/pt/subway/fecha={clave} · ej: {nombres}")

print("\n  3 nodos miembros CON nombre, tags completos:")
vistos = 0
for e in els:
    t = e.get("tags") or {}
    if e.get("type") == "node" and t.get("name"):
        print(f"    n{e['id']}: {json.dumps(t, ensure_ascii=False)}")
        vistos += 1
        if vistos >= 3:
            break

print("\n  resultados 'Lo Errázuriz':")
alguno = False
for e in els:
    t = e.get("tags") or {}
    if "errázuriz" in (t.get("name") or "").lower() or "errazuriz" in (t.get("name") or "").lower():
        print(f"    {e.get('type')}-{e['id']}: {json.dumps(t, ensure_ascii=False)[:260]}")
        alguno = True
if not alguno:
    print("    nada con ese nombre en OSM Chile")
