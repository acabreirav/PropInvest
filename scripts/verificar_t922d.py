"""T-922d · las verificaciones vivas que dejó el verificador §7.6 del 03-sep.

(a) start_date en las obras L6 — YA MEDIDA en sonda_l7b (nodos Lo Errázuriz: 2027). Aquí:
(b) cuántas estaciones OPERATIVAS del blob traen tags proposed:*/construction:* (riesgo
    de degradación — hoy neutralizado, se mide igual);
(c) cuántas estaciones quedaron en la base mapeadas como relation/way;
(d) homónimas en la base y la distancia entre ellas (el dedupe exige ~300 m);
(e) si los miembros de la relation r16358740 "Propuesta de Extensión L7" traen fecha
    copiada (única vía por la que aún podrían catalizar) — UNA consulta a Overpass.

Uso:  uv run python scripts/verificar_t922d.py
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx

from flujocero import db
from flujocero.sources import osm_metro
from flujocero.sources.base import escribir_crudo

RAIZ = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------ (b) sobre el blob
blobs = sorted((RAIZ / "data" / "raw" / "osm_metro").rglob("estaciones_cl.json.gz"))
if blobs:
    cuerpo = json.loads(gzip.open(blobs[-1], "rb").read().decode("utf-8"))
    con_prefijos = []
    for el in cuerpo.get("elements", []):
        t = el.get("tags", {})
        if t.get("railway") == "station" and any(
            k.startswith(("proposed", "construction")) for k in t
        ):
            con_prefijos.append(
                (t.get("name"), [k for k in t if ":" in k or k in ("proposed", "construction")])
            )
    print(f"(b) operativas railway=station con tags de ciclo de vida: {len(con_prefijos)}")
    for nombre, claves in con_prefijos[:10]:
        print(f"    {nombre!r}: {claves}")
else:
    print("(b) sin blob local — corre recolectar-metro primero")

# ------------------------------------------------------------------ (c) y (d) en la base
con = duckdb.connect(str(db.crear()), read_only=False)
try:
    filas = con.execute(
        "SELECT estacion_id, nombre, red, linea, estado, lat, lon FROM dim_estacion_metro"
    ).fetchall()
finally:
    con.close()
no_nodos = [f for f in filas if "-way-" in f[0] or "-relation-" in f[0]]
print(f"\n(c) estaciones mapeadas como way/relation en la base: {len(no_nodos)}")
for f in no_nodos[:10]:
    print(f"    {f[0]}: {f[1]!r} ({f[4]}, linea={f[3]})")

print("\n(d) homónimas en la base y su distancia:")
por_nombre: dict[str, list] = {}
for f in filas:
    por_nombre.setdefault(f[1], []).append(f)
alguna = False
for nombre, grupo in sorted(por_nombre.items()):
    if len(grupo) < 2:
        continue
    alguna = True
    for i in range(len(grupo)):
        for j in range(i + 1, len(grupo)):
            a, b = grupo[i], grupo[j]
            dist = math.hypot((a[5] - b[5]) * 111_000, (a[6] - b[6]) * 93_000)
            print(f"    {nombre!r}: {a[0]}({a[4]},{a[3]}) vs {b[0]}({b[4]},{b[3]}) a {dist:,.0f} m")
if not alguna:
    print("    ninguna — el dedupe no dejó pares")

# ------------------------------------------------------------------ (e) r16358740
CONSULTA = """
[out:json][timeout:90];
relation(id:16358740)->.ext;
.ext out body;
node(r.ext);
out body;
"""
print("\n(e) miembros de r16358740 'Propuesta de Extensión L7' (~15 s)…")
momento = datetime.now(UTC)
respuesta = None
with httpx.Client(timeout=120) as cliente:
    for url in osm_metro.OVERPASS_URLS:
        try:
            r = cliente.post(url, data={"data": CONSULTA}, headers=osm_metro.CABECERAS)
        except Exception as exc:  # noqa: BLE001 — sonda
            print(f"    {url}: {type(exc).__name__}")
            continue
        if r.status_code == 200:
            respuesta = r
            break
        print(f"    {url}: HTTP {r.status_code}")
if respuesta is None:
    raise SystemExit("    ningún espejo respondió")
doc = escribir_crudo(
    osm_metro.SOURCE_ID,
    str(respuesta.url),
    respuesta.content,
    momento,
    robots_snapshot_sha="api-publica-odbl",
    nombre="verificar_t922d",
    parser_version="sonda",
)
cuerpo = json.loads(doc.contenido.decode("utf-8"))
nodos = [e for e in cuerpo.get("elements", []) if e.get("type") == "node"]
con_fecha = [
    e
    for e in nodos
    if (e.get("tags") or {}).get("start_date") or (e.get("tags") or {}).get("opening_date")
]
print(f"    {len(nodos)} nodos miembros · {len(con_fecha)} CON fecha declarada")
for e in con_fecha[:10]:
    t = e.get("tags") or {}
    print(
        f"    ⚠ {t.get('name')!r} fecha={t.get('start_date') or t.get('opening_date')!r} "
        f"network={t.get('network')!r} — si dice Línea 7 y ≤2029, catalizaría: avisar"
    )
if not con_fecha:
    print("    ninguno con fecha: la guarda 'propuesta sin fecha propia' los bloquea a todos ✓")
