"""Sonda T-931d · ¿dónde viven los m² de Ingevec y las direcciones de Socovesa/Pilares?

Escanea los blobs crudos MÁS RECIENTES de wpjson_inmobiliarias (cero requests): para
cada página HTML busca (a) patrones de superficie (m², mts²) con su contexto, y
(b) patrones de dirección (Ubicación/Dirección + calle y número). Con lo que salga se
escribe el parser contra dato medido, no adivinado.

Uso:  uv run python scripts/sonda_t931d.py
"""

from __future__ import annotations

import gzip
import re
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "data" / "raw" / "wpjson_inmobiliarias"

RE_M2 = re.compile(
    r".{0,80}?(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:m²|m2|mts²|mts2|mt2)(?!\w).{0,60}",
    re.I,
)
RE_DIR = re.compile(
    r".{0,30}(?:Ubicaci[oó]n|Direcci[oó]n)[^A-Za-z0-9]{0,20}.{0,140}",
    re.I,
)
RE_CALLE = re.compile(
    r"[A-ZÁÉÍÓÚÑ][\wáéíóúñüÁÉÍÓÚÑ.\- ]{3,40}\s(?:N[°º]?\s?)?\d{2,5}(?:\s?,\s?[A-ZÁÉÍÓÚÑ][\wáéíóúñ ]+)?"
)

dias = sorted({p.parent for p in RAIZ.rglob("*.gz")})
if not dias:
    raise SystemExit("sin blobs en data/raw/wpjson_inmobiliarias")
ultimo = dias[-1]
print(f"escaneando: {ultimo} ({len(list(ultimo.glob('*.gz')))} blobs)\n")

# Solo paginas de PROYECTO: la primera corrida muestreo el blog y la portada de
# Ingevec (0 coincidencias triviales). El nombre del blob delata la pagina.
FILTRO_PROYECTO = {
    "ingevec": re.compile(r"ingevec.*proyecto-"),
    "socovesa": re.compile(r"socovesa(?!.*(casa-\d|depto-|bodega|estacionamiento|blog))"),
    "pilares": re.compile(r"pilares(?!.*(depto-|oficina|casa-|bodega|estacionamiento|blog))"),
    "fundamenta": re.compile(r"fundamenta.*(proyecto|eco-)"),
}
por_dominio: dict[str, list[Path]] = defaultdict(list)
for ruta in sorted(ultimo.glob("*.gz")):
    nombre = ruta.name.lower()
    for dom, filtro in FILTRO_PROYECTO.items():
        if dom in nombre and filtro.search(nombre):
            try:
                contenido = gzip.open(ruta, "rb").read().decode("utf-8", errors="replace")
            except OSError:
                break
            if "<html" in contenido.lower() or "<!doctype" in contenido.lower():
                por_dominio[dom].append(ruta)
            break

# --- Ingevec: ¿donde estan los m²?
print(f"== INGEVEC · patrones de m² ({len(por_dominio.get('ingevec', []))} páginas de proyecto) ==")
for ruta in por_dominio.get("ingevec", [])[:4]:
    html = gzip.open(ruta, "rb").read().decode("utf-8", errors="replace")
    # quitar scripts para no matchear JSON interno
    limpio = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    hallazgos = []
    for m in RE_M2.finditer(limpio):
        frag = re.sub(r"\s+", " ", m.group(0)).strip()
        if frag not in hallazgos:
            hallazgos.append(frag)
    print(f"\n  {ruta.name}: {len(hallazgos)} coincidencias")
    for h in hallazgos[:10]:
        print(f"    · {h}")
    if not hallazgos:
        # quizas los m² viven en un JSON embebido: buscar en el html completo
        crudos = []
        for m in RE_M2.finditer(html):
            frag = re.sub(r"\s+", " ", m.group(0)).strip()
            if frag not in crudos:
                crudos.append(frag)
        print(f"    (con scripts incluidos: {len(crudos)})")
        for h in crudos[:6]:
            print(f"    · {h}")

# --- Socovesa y Pilares: ¿publican direccion en alguna parte?
for dom in ("socovesa", "pilares"):
    print(f"\n== {dom.upper()} · patrones de dirección (2 páginas de muestra) ==")
    for ruta in por_dominio.get(dom, [])[:3]:
        html = gzip.open(ruta, "rb").read().decode("utf-8", errors="replace")
        limpio = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
        vistos = []
        for m in RE_DIR.finditer(limpio):
            frag = re.sub(r"\s+", " ", m.group(0)).strip()
            if frag not in vistos:
                vistos.append(frag)
        print(f"\n  {ruta.name}: {len(vistos)} etiquetas Ubicación/Dirección")
        for h in vistos[:6]:
            print(f"    · {h}")
        # y calles con numero cerca del inicio del contenido visible
        calles = []
        for m in RE_CALLE.finditer(limpio[:20000]):
            frag = m.group(0).strip()
            if frag not in calles and not re.match(r"^(UF|CLP)", frag):
                calles.append(frag)
        if calles:
            print(f"    calles candidatas (primeros 20k chars): {calles[:5]}")

print("\nlisto — con esto se escribe el parser contra dato medido.")
