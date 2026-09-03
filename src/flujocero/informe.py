"""El informe semanal — T-930: un documento para leer, no consola pegada.

Nace del primer PDF real que llegó por correo (02-sep-2026): el ranking no aparecía
porque `oportunidades` reventó con UnicodeEncodeError en la consola cp1252 de Windows,
y el "informe" era la salida de dos comandos pegada con un traceback al medio.

Este módulo genera el informe DIRECTO desde la base, en HTML y texto:
  1. TOP de oportunidades USADAS (precio real por unidad, el ranking del §12), con los
     CAMBIOS contra el informe anterior: qué entró al top, qué salió, qué bajó de precio.
     El top de cada corrida queda en `data/informes/top-AAAA-MM-DD.json` para comparar.
  2. Oferta NUEVA (precio "desde" por modelo, fuera del ranking por regla): las BAJAS de
     la semana (la señal de inmobiliaria apurada, directo del SCD) y los menores "desde"
     en las comunas del alcance.
  3. El delta del mercado usado (quality/delta): bajas, desaparecidas (≈vendidas), nuevas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


@dataclass
class FilaTop:
    unidad_key: str
    microzona_id: str
    tipologia: str
    m2: float
    precio_uf: float
    yield_bruto: float
    tenencia_clp: int
    pie_pct: float
    pie_cero: str
    score: float


@dataclass
class CambiosTop:
    entraron: list[str] = field(default_factory=list)
    salieron: list[str] = field(default_factory=list)
    bajas_precio: list[tuple[str, float, float]] = field(default_factory=list)  # key, antes, ahora
    fecha_anterior: str | None = None


def _carpeta_snapshots(raiz: Path) -> Path:
    carpeta = raiz / "data" / "informes"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def comparar_top(carpeta: Path, hoy: str, top_actual: list[FilaTop]) -> CambiosTop:
    """Compara el top de hoy con el snapshot más reciente anterior y guarda el de hoy.

    Sin snapshot previo no hay comparación (primera corrida): se dice, no se inventa.
    """
    cambios = CambiosTop()
    previos = sorted(p for p in carpeta.glob("top-*.json") if p.stem != f"top-{hoy}")
    if previos:
        anterior = json.loads(previos[-1].read_text(encoding="utf-8"))
        cambios.fecha_anterior = previos[-1].stem.removeprefix("top-")
        claves_antes = {f["unidad_key"]: f for f in anterior}
        claves_ahora = {f.unidad_key: f for f in top_actual}
        cambios.entraron = [k for k in claves_ahora if k not in claves_antes]
        cambios.salieron = [k for k in claves_antes if k not in claves_ahora]
        for k, fila in claves_ahora.items():
            antes = claves_antes.get(k)
            if antes and fila.precio_uf < float(antes["precio_uf"]):
                cambios.bajas_precio.append((k, float(antes["precio_uf"]), fila.precio_uf))
    (carpeta / f"top-{hoy}.json").write_text(
        json.dumps([f.__dict__ for f in top_actual], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return cambios


def bajas_oferta_nueva(conexion: Any, corte: datetime) -> list[dict[str, Any]]:
    """Bajas del "precio desde" en la oferta nueva: la versión cerrada esta semana cuya
    sucesora (misma unidad, valid_from = valid_to de la cerrada) tiene menor precio."""
    filas = conexion.execute(
        """
        SELECT v.unidad_key, p.nombre, p.comuna_id, v.numero_unidad,
               v.precio_uf AS antes, n.precio_uf AS ahora
        FROM fact_unidad_venta v
        JOIN fact_unidad_venta n
          ON n.unidad_key = v.unidad_key AND n.valid_from = v.valid_to
        LEFT JOIN dim_proyecto p ON p.proyecto_id = v.proyecto_id
        WHERE coalesce(v.precio_es_desde, FALSE) AND v.valid_to >= ?
          AND n.precio_uf < v.precio_uf
        ORDER BY (v.precio_uf - n.precio_uf) / v.precio_uf DESC
        """,
        (corte,),
    ).fetchall()
    return [
        {
            "proyecto": nombre or clave,
            "comuna": comuna or "(sin comuna)",
            "modelo": modelo,
            "antes": float(antes),
            "ahora": float(ahora),
            "variacion": float((ahora - antes) / antes),
        }
        for clave, nombre, comuna, modelo, antes, ahora in filas
    ]


def menores_desde_en_alcance(
    conexion: Any, comunas: frozenset[str], top: int = 12
) -> list[dict[str, Any]]:
    """Los menores "precio desde" vigentes de la oferta nueva en las comunas del §10."""
    marcadores = ", ".join("?" for _ in comunas) or "''"
    filas = conexion.execute(
        f"""
        SELECT p.nombre, p.comuna_id, v.numero_unidad, v.dormitorios, v.m2_totales,
               v.precio_uf, p.estado
        FROM fact_unidad_venta v
        JOIN dim_proyecto p ON p.proyecto_id = v.proyecto_id
        WHERE coalesce(v.precio_es_desde, FALSE) AND v.valid_to IS NULL
          AND v.precio_uf IS NOT NULL AND p.comuna_id IN ({marcadores})
        ORDER BY v.precio_uf
        LIMIT ?
        """,  # noqa: S608 - los marcadores son placeholders, no datos
        (*sorted(comunas), top),
    ).fetchall()
    return [
        {
            "proyecto": n,
            "comuna": c,
            "modelo": m,
            "dormitorios": d,
            "m2": float(m2) if m2 is not None else None,
            "precio_uf": float(uf),
            "estado": e,
        }
        for n, c, m, d, m2, uf, e in filas
    ]


# ------------------------------------------------------------------------------- render


def _f(n: float) -> str:
    """Formato chileno de miles: 3.390."""
    return f"{n:,.0f}".replace(",", ".")


def render_html(
    fecha: str,
    corte: str,
    top_filas: list[FilaTop],
    cambios: CambiosTop,
    bajas_nuevas: list[dict[str, Any]],
    menores_nuevas: list[dict[str, Any]],
    delta_texto: str,
    notas: list[str],
) -> str:
    def tabla_top() -> str:
        filas = ""
        entrantes = set(cambios.entraron)
        for i, f in enumerate(top_filas, 1):
            marca = " ▲ nuevo en el top" if f.unidad_key in entrantes else ""
            filas += (
                f"<tr><td>{i}</td><td>{escape(f.unidad_key)}{marca}</td>"
                f"<td>{escape(f.microzona_id)}</td><td>{escape(f.tipologia)}</td>"
                f"<td class='n'>{f.m2:.0f}</td><td class='n'>UF {_f(f.precio_uf)}</td>"
                f"<td class='n'>{f.yield_bruto:.1%}</td>"
                f"<td class='n'>${_f(f.tenencia_clp)}</td>"
                f"<td class='n'>{f.pie_pct:.0%}</td><td class='n'>{f.pie_cero}</td>"
                f"<td class='n'>{f.score:.1f}</td></tr>"
            )
        return filas

    def lista_cambios() -> str:
        if cambios.fecha_anterior is None:
            return "<p>Primera corrida con snapshot: la próxima semana se comparan cambios.</p>"
        partes = []
        if cambios.bajas_precio:
            items = "".join(
                f"<li><b>{escape(k)}</b>: UF {_f(a)} → UF {_f(h)} ({(h - a) / a:+.1%})</li>"
                for k, a, h in cambios.bajas_precio
            )
            partes.append(f"<p><b>Bajaron de precio dentro del top:</b></p><ul>{items}</ul>")
        if cambios.entraron:
            partes.append(
                "<p><b>Entraron al top:</b> " + ", ".join(map(escape, cambios.entraron)) + "</p>"
            )
        if cambios.salieron:
            partes.append(
                "<p><b>Salieron del top</b> (¿vendidas? revisar): "
                + ", ".join(map(escape, cambios.salieron))
                + "</p>"
            )
        if not partes:
            partes.append(f"<p>Sin cambios en el top desde el {cambios.fecha_anterior}.</p>")
        return "".join(partes)

    def tabla_nuevas(filas: list[dict[str, Any]]) -> str:
        out = ""
        for f in filas:
            m2 = f"{f['m2']:.0f}" if f.get("m2") else "—"
            dorm = f["dormitorios"] if f.get("dormitorios") is not None else "—"
            out += (
                f"<tr><td>{escape(str(f['proyecto']))}</td><td>{escape(str(f['comuna']))}</td>"
                f"<td>{escape(str(f['modelo']))}</td><td class='n'>{dorm}</td>"
                f"<td class='n'>{m2}</td><td class='n'>UF {_f(f['precio_uf'])}</td>"
                f"<td>{escape(str(f.get('estado') or ''))}</td></tr>"
            )
        return out

    def tabla_bajas_nuevas() -> str:
        if not bajas_nuevas:
            return "<p>Sin bajas de precio en la oferta nueva esta semana.</p>"
        filas = "".join(
            f"<tr><td>{escape(str(b['proyecto']))}</td><td>{escape(str(b['comuna']))}</td>"
            f"<td>{escape(str(b['modelo']))}</td><td class='n'>UF {_f(b['antes'])}</td>"
            f"<td class='n'>UF {_f(b['ahora'])}</td><td class='n'>{b['variacion']:+.1%}</td></tr>"
            for b in bajas_nuevas
        )
        return (
            "<table><tr><th>Proyecto</th><th>Comuna</th><th>Modelo</th>"
            f"<th>Antes</th><th>Ahora</th><th>Var.</th></tr>{filas}</table>"
        )

    notas_html = "".join(f"<p class='nota'>{escape(n)}</p>" for n in notas)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Flujo Cero {fecha}</title>
<style>
  body {{ font-family: Segoe UI, sans-serif; margin: 28px; color: #222; font-size: 12px; }}
  h1 {{ font-size: 20px; border-bottom: 3px solid #9C5527; padding-bottom: 8px; }}
  h2 {{ font-size: 14px; margin-top: 26px; color: #9C5527; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 10.5px; }}
  th {{ text-align: left; border-bottom: 2px solid #999; padding: 3px 6px; }}
  td {{ border-bottom: 1px solid #ddd; padding: 3px 6px; }}
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .nota {{ color: #666; font-size: 10px; }}
  pre {{ font-family: Consolas, monospace; font-size: 10px; white-space: pre-wrap; }}
</style></head><body>
<h1>Flujo Cero — informe semanal {fecha}</h1>

<h2>1 · Cambios desde el informe anterior{f" ({cambios.fecha_anterior})" if cambios.fecha_anterior else ""}</h2>
{lista_cambios()}

<h2>2 · Top oportunidades — stock USADO (precio real por unidad)</h2>
<table>
<tr><th>#</th><th>Unidad</th><th>Microzona</th><th>Tipo</th><th>m²</th><th>Precio</th>
<th>Yield</th><th>Tenencia/mes</th><th>Pie</th><th>Pie flujo 0</th><th>Score</th></tr>
{tabla_top()}
</table>
<p class='nota'>Tenencia/mes = lo que sale de tu bolsillo con el pie del escenario;
"Pie flujo 0" = el pie con el que la unidad se paga sola. Score = suma ponderada del §12.</p>

<h2>3 · Oferta NUEVA: bajas de "precio desde" esta semana (señal de compra)</h2>
{tabla_bajas_nuevas()}

<h2>4 · Oferta NUEVA: menores "desde" vigentes en comunas del alcance</h2>
<table><tr><th>Proyecto</th><th>Comuna</th><th>Modelo</th><th>Dorm.</th><th>m²</th>
<th>Desde</th><th>Estado</th></tr>{tabla_nuevas(menores_nuevas)}</table>
<p class='nota'>"Desde" = el piso del modelo, no el precio de una unidad: estas filas NO
compiten en el ranking (regla B1); son el radar para pedir cotización dirigida.</p>

<h2>5 · Delta del mercado usado (corte {corte})</h2>
<pre>{escape(delta_texto)}</pre>
{notas_html}
</body></html>
"""
