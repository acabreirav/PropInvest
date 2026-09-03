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
from decimal import Decimal
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
    # los campos de la FICHA (T-931): con defaults para que los snapshots viejos
    # sigan cargando — comparar_top solo usa unidad_key y precio_uf
    precio_clp: int = 0
    arriendo_clp: int = 0
    n_comparables: int = 0
    tasa_pct: float = 0.0
    con_subsidio: bool = False
    dividendo_clp: int = 0
    flujo_clp: int = 0  # BTCF mensual: >0 sobra plata, <0 se pone de bolsillo
    pie_clp: int = 0
    dfl2: str = "no"  # "sí" / "probable*" (supuesto E, verificar en escritura) / "no"
    drivers: list[str] = field(default_factory=list)  # por qué puntúa alto (§12)


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


# ----------------------------------------------- T-931b · nuevas evaluadas al "desde"


def microzonas_por_geo(conexion: Any, max_dist_m: float = 2500.0) -> dict[str, str]:
    """proyecto_id → microzona_id por el centro de barrio más cercano EN LA MISMA comuna.

    Coordenadas publicadas por la inmobiliaria (Fundamenta y RVC, JSON-LD) o
    geocodificadas vía Nominatim (T-931c, tabla geo_proyecto); la publicada manda.
    La asignación no se persiste: la FK de DuckDB veta el UPDATE de dim_proyecto con
    fact referenciando, y es un derivado barato de recalcular donde se usa. Tope de
    distancia para no asignar un barrio a un proyecto con geo mala: más lejos que
    `max_dist_m`, queda sin microzona (ND) y se cuenta.
    """
    import math

    proyectos = conexion.execute(
        "SELECT p.proyecto_id, p.comuna_id, COALESCE(p.lat, g.lat), COALESCE(p.lon, g.lon) "
        "FROM dim_proyecto p LEFT JOIN geo_proyecto g USING (proyecto_id) "
        "WHERE COALESCE(p.lat, g.lat) IS NOT NULL AND COALESCE(p.lon, g.lon) IS NOT NULL "
        "AND p.comuna_id IS NOT NULL"
    ).fetchall()
    centros = conexion.execute(
        "SELECT microzona_id, comuna_id, centro_lat, centro_lon FROM dim_microzona "
        "WHERE centro_lat IS NOT NULL AND centro_lon IS NOT NULL"
    ).fetchall()
    por_comuna: dict[str, list[tuple[str, float, float]]] = {}
    for mid, cid, la, lo in centros:
        por_comuna.setdefault(cid, []).append((mid, float(la), float(lo)))

    salida: dict[str, str] = {}
    for pid, cid, la, lo in proyectos:
        mejor, mejor_d = None, None
        for mid, cla, clo in por_comuna.get(cid, []):
            dx = (float(lo) - clo) * 111_320.0 * math.cos(math.radians(float(la)))
            dy = (float(la) - cla) * 110_540.0
            d = (dx * dx + dy * dy) ** 0.5
            if mejor_d is None or d < mejor_d:
                mejor, mejor_d = mid, d
        if mejor is not None and mejor_d is not None and mejor_d <= max_dist_m:
            salida[pid] = mejor
    return salida


def _rango_de(m2: float, rangos: list[list[int]]) -> str | None:
    for a, b in rangos:
        if a <= m2 < b:
            return f"{a}-{b}"
    return None


def nuevas_evaluadas_al_desde(
    conexion: Any, p: Any, inv: Any, rangos: list[list[int]], top: int = 10
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """La oferta nueva pasada por el MISMO motor que las usadas — al precio "desde".

    Es una evaluación HIPOTÉTICA y así se rotula: el "desde" es el piso del modelo, no el
    precio de una unidad, y los m² totales aproximan los útiles. Lo que sí es igual de
    real que en las usadas: el arriendo comparable (mediana de su microzona por geo, regla
    §2.4 — jamás la comuna), la tasa CON subsidio (primera venta) y el DFL2 probable
    (D-018). Todo lo que no se puede evaluar queda contado con su motivo, no desaparece.
    """
    from flujocero.finance.escenarios import escenario_base, evaluar_universo
    from flujocero.finance.modelo import Unidad
    from flujocero.sources.portal_comun import tipologia_de

    mapa = microzonas_por_geo(conexion)
    filas = conexion.execute(
        """
        SELECT v.unidad_key, v.numero_unidad, v.precio_uf, v.m2_totales, v.dormitorios,
               v.banos, p.proyecto_id, p.nombre, p.comuna_id, p.estado
        FROM fact_unidad_venta v
        JOIN dim_proyecto p ON p.proyecto_id = v.proyecto_id
        WHERE coalesce(v.precio_es_desde, FALSE) AND v.valid_to IS NULL
          AND v.precio_uf IS NOT NULL
        """
    ).fetchall()

    descartes = {"sin_geo": 0, "sin_m2": 0, "sin_tipologia": 0, "sin_celda": 0, "excluida": 0}
    unidades: list[Unidad] = []
    contexto: dict[str, dict[str, Any]] = {}
    for clave, modelo, precio, m2, dorm, banos, pid, nombre, comuna, estado in filas:
        microzona = mapa.get(pid)
        if microzona is None:
            descartes["sin_geo"] += 1
            continue
        if m2 is None:
            descartes["sin_m2"] += 1
            continue
        tipologia = tipologia_de(dorm, banos)
        if tipologia is None:
            descartes["sin_tipologia"] += 1
            continue
        rango = _rango_de(float(m2), rangos)
        celda = conexion.execute(
            "SELECT arriendo_uf_mediana, n FROM agg_arriendo_microzona "
            "WHERE microzona_id = ? AND tipologia = ? AND rango_m2 = ? AND n >= 8 "
            "ORDER BY calculado_en DESC LIMIT 1",
            (microzona, tipologia, rango),
        ).fetchone()
        if celda is None:
            descartes["sin_celda"] += 1
            continue
        mediana, n = celda
        unidades.append(
            Unidad(
                unidad_key=clave,
                precio_uf=Decimal(str(precio)),
                # aproximación DECLARADA: la oferta nueva publica m² totales
                m2_utiles=Decimal(str(m2)),
                tipologia=tipologia,
                comuna_id=comuna or "",
                microzona_id=microzona,
                arriendo_mensual_uf=Decimal(str(mediana)),
                arriendo_n_comparables=int(n),
                acogida_dfl2=None,  # D-018 decide: probable si cabe en 140 m²
                es_vivienda_nueva=True,  # primera venta → subsidio y FOGAES aplican
            )
        )
        contexto[clave] = {
            "proyecto": nombre,
            "modelo": modelo,
            "comuna": comuna or "(sin comuna)",
            "microzona": microzona,
            "estado": estado or "",
            "n": int(n),
        }

    if not unidades:
        return [], descartes

    evals = evaluar_universo(unidades, escenario_base(p, inv), p, inv)
    uf = float(p.d("macro.valor_uf_clp"))
    salida: list[dict[str, Any]] = []
    for u, ev in zip(unidades, evals, strict=True):
        if ev.excluido:
            descartes["excluida"] += 1
            continue
        ctx = contexto[u.unidad_key]
        salida.append(
            {
                **ctx,
                "precio_uf": float(u.precio_uf),
                "m2": float(u.m2_utiles),
                "arriendo_clp": int(float(u.arriendo_mensual_uf) * uf),
                "tasa_pct": float(ev.tasa_aplicada),
                "con_subsidio": bool(ev.subsidio_aplicado),
                "flujo_clp": int(float(ev.btcf_mensual_uf) * uf),
                "pie_cero": (
                    "positivo al pie mínimo"
                    if ev.pie_flujo_cero_real == 0
                    else (
                        f"{ev.pie_flujo_cero_real:.0%}"
                        if ev.pie_flujo_cero_real is not None
                        else "nunca"
                    )
                ),
                "score": float(ev.score),
            }
        )
    salida.sort(key=lambda f: -f["score"])
    return salida[:top], descartes


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
    nuevas_evaluadas: list[dict[str, Any]] | None = None,
    descartes_nuevas: dict[str, int] | None = None,
) -> str:
    entrantes = set(cambios.entraron)

    def ficha(i: int, f: FilaTop) -> str:
        """Una oportunidad que se explica sola: qué es, cuánto cuesta, cuánto rinde."""
        marca = " <span class='badge'>▲ nueva en el top</span>" if f.unidad_key in entrantes else ""
        if f.flujo_clp >= 0:
            flujo = f"<b class='pos'>+${_f(f.flujo_clp)}/mes</b> — se paga sola y sobra"
        else:
            flujo = f"<b class='neg'>−${_f(-f.flujo_clp)}/mes</b> de tu bolsillo"
        tasa = (
            f"{f.tasa_pct:.2%} <span class='mini'>con subsidio (primera venta)</span>"
            if f.con_subsidio
            else f"{f.tasa_pct:.2%} <span class='mini'>sin subsidio (usada)</span>"
        )
        drivers = " · ".join(escape(d) for d in f.drivers) or "—"
        return f"""
<div class="ficha">
  <div class="ficha-titulo">#{i} · {escape(f.microzona_id)} · {escape(f.tipologia)} ·
    {f.m2:.0f} m²{marca} <span class="score">score {f.score:.0f}</span></div>
  <div class="ficha-grid">
    <div><span>Precio</span><b>UF {_f(f.precio_uf)}</b> ≈ ${_f(f.precio_clp)}</div>
    <div><span>Arriendo estimado</span><b>${_f(f.arriendo_clp)}/mes</b>
      <span class="mini">mediana de {f.n_comparables} arriendos reales en su microzona</span></div>
    <div><span>Tasa</span><b>{tasa}</b></div>
    <div><span>Dividendo</span><b>${_f(f.dividendo_clp)}/mes</b></div>
    <div><span>Flujo mensual</span>{flujo}</div>
    <div><span>Pie ({f.pie_pct:.0%})</span><b>${_f(f.pie_clp)}</b></div>
    <div><span>Pie para flujo cero</span><b>{f.pie_cero}</b></div>
    <div><span>DFL2</span><b>{escape(f.dfl2)}</b></div>
  </div>
  <div class="mini">Por qué está arriba: {drivers}</div>
</div>"""

    def tabla_top(desde: int) -> str:
        filas = ""
        for i, f in enumerate(top_filas[desde:], desde + 1):
            marca = " ▲" if f.unidad_key in entrantes else ""
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

    def tabla_evaluadas() -> str:
        filas_ev = nuevas_evaluadas or []
        if not filas_ev:
            motivo = ""
            if descartes_nuevas:
                partes_d = [f"{k.replace('_', ' ')}: {v}" for k, v in descartes_nuevas.items() if v]
                motivo = " Motivos: " + ", ".join(partes_d) + "." if partes_d else ""
            return f"<p>Ningún proyecto nuevo se pudo evaluar todavía.{escape(motivo)}</p>"
        cuerpo_ev = ""
        for f in filas_ev:
            flujo = (
                f"<b class='pos'>+${_f(f['flujo_clp'])}</b>"
                if f["flujo_clp"] >= 0
                else f"<b class='neg'>−${_f(-f['flujo_clp'])}</b>"
            )
            tasa = f"{f['tasa_pct']:.2%}" + (" ✓sub" if f["con_subsidio"] else "")
            cuerpo_ev += (
                f"<tr><td>{escape(str(f['proyecto']))}</td><td>{escape(str(f['modelo']))}</td>"
                f"<td>{escape(str(f['microzona']))}</td>"
                f"<td class='n'>UF {_f(f['precio_uf'])}</td><td class='n'>{f['m2']:.0f}</td>"
                f"<td class='n'>${_f(f['arriendo_clp'])} <span class='mini'>(n={f['n']})</span></td>"
                f"<td class='n'>{tasa}</td><td class='n'>{flujo}</td>"
                f"<td class='n'>{escape(str(f['pie_cero']))}</td>"
                f"<td class='n'>{f['score']:.1f}</td></tr>"
            )
        resumen_d = ""
        if descartes_nuevas:
            partes_d = [f"{k.replace('_', ' ')}: {v}" for k, v in descartes_nuevas.items() if v]
            if partes_d:
                resumen_d = (
                    "<p class='nota'>No evaluables (contados, no borrados): "
                    + escape(", ".join(partes_d))
                    + ".</p>"
                )
        return (
            "<table><tr><th>Proyecto</th><th>Modelo</th><th>Microzona</th><th>Desde</th>"
            "<th>m²*</th><th>Arriendo est.</th><th>Tasa</th><th>Flujo/mes</th>"
            f"<th>Pie flujo 0</th><th>Score</th></tr>{cuerpo_ev}</table>{resumen_d}"
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
  .ficha {{ border: 1px solid #ddd; border-left: 4px solid #9C5527; border-radius: 4px;
           padding: 10px 14px; margin: 10px 0; page-break-inside: avoid; }}
  .ficha-titulo {{ font-weight: 700; font-size: 13px; margin-bottom: 8px; }}
  .ficha-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px 14px;
                margin-bottom: 6px; }}
  .ficha-grid div {{ font-size: 11px; }}
  .ficha-grid span:first-child {{ display: block; color: #888; font-size: 9px;
                                 text-transform: uppercase; letter-spacing: .05em; }}
  .mini {{ color: #777; font-size: 9.5px; }}
  .pos {{ color: #2F7A58; }}
  .neg {{ color: #A8442C; }}
  .badge {{ background: #E3EEE6; color: #2F7A58; font-size: 10px; padding: 1px 6px;
           border-radius: 8px; }}
  .score {{ float: right; color: #9C5527; }}
</style></head><body>
<h1>Flujo Cero — informe semanal {fecha}</h1>

<h2>1 · Cambios desde el informe anterior{f" ({cambios.fecha_anterior})" if cambios.fecha_anterior else ""}</h2>
{lista_cambios()}

<h2>2 · Las 5 mejores oportunidades — stock USADO (precio real por unidad)</h2>
{"".join(ficha(i, f) for i, f in enumerate(top_filas[:5], 1))}
<p class='nota'>*DFL2 "probable": el aviso no lo dice, pero la unidad cabe en los 140 m² y se
aplica el supuesto declarado D-018. Los números de TODO el top (fichas y tabla) lo incluyen;
<b>verificar en la escritura antes de ofertar</b> es obligatorio. Recuerda además que la
renta exenta aplica a un máximo de <b>2 viviendas por persona</b> (tienes tus 2 cupos
libres): a partir de la tercera, estos flujos ya no son los tuyos.</p>

<h2>3 · El resto del top</h2>
<table>
<tr><th>#</th><th>Unidad</th><th>Microzona</th><th>Tipo</th><th>m²</th><th>Precio</th>
<th>Yield</th><th>Tenencia/mes</th><th>Pie</th><th>Pie flujo 0</th><th>Score</th></tr>
{tabla_top(5)}
</table>
<p class='nota'>Tenencia/mes = lo que sale de tu bolsillo con el pie del escenario;
"Pie flujo 0" = el pie con el que la unidad se paga sola. Score = suma ponderada del §12.</p>

<h2>4 · Oferta NUEVA: bajas de "precio desde" esta semana (señal de compra)</h2>
{tabla_bajas_nuevas()}

<h2>5 · Oferta NUEVA evaluada al "desde" — HIPOTÉTICO, mismo motor que las usadas</h2>
{tabla_evaluadas()}
<p class='nota'>Rotulado hipotético a propósito: el "desde" es el PISO del modelo (una
unidad real del proyecto puede costar más) y los m²* son totales aproximando útiles.
Lo que sí es real: el arriendo es la mediana de arriendos efectivos de su microzona
(asignada por las coordenadas del proyecto, regla §2.4 — jamás la comuna), la tasa es
la subsidiada cuando corresponde (primera venta, "✓sub") y el DFL2 va por D-018.
Sirve para elegir a quién pedir cotización, no para ofertar.</p>

<h2>6 · Oferta NUEVA: menores "desde" vigentes en comunas del alcance</h2>
<table><tr><th>Proyecto</th><th>Comuna</th><th>Modelo</th><th>Dorm.</th><th>m²</th>
<th>Desde</th><th>Estado</th></tr>{tabla_nuevas(menores_nuevas)}</table>
<p class='nota'>"Desde" = el piso del modelo, no el precio de una unidad: estas filas NO
compiten en el ranking (regla B1); son el radar para pedir cotización dirigida.</p>

<h2>7 · Delta del mercado usado (corte {corte})</h2>
<pre>{escape(delta_texto)}</pre>
{notas_html}
</body></html>
"""
