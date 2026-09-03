"""El puente manzana → microzona, y el riesgo que por fin se mide — T-014b (2/2).

Las microzonas no tienen poligono; tienen un CENTRO (el del barrio MELI, T-014b 1/2).
Cada manzana censal con centroide se asigna al barrio mas cercano **dentro de su misma
comuna** — una particion de Voronoi. Es una aproximacion y esta DECLARADA como tal en
docs/adr/009: en el borde entre dos barrios la asignacion puede equivocarse, pero las
variables censales varian suave dentro de una comuna, y la alternativa real hoy es
seguir con `riesgo_microzona = 0.5` para todo el mundo — un componente del §12 que lleva
inerte desde el dia uno.

Sobre las manzanas asignadas se agregan los tres insumos, todos `D` sobre datos `V`:

- **desocupacion censal**: viviendas desocupadas / (ocupadas + desocupadas). El proxy de
  vacancia estructural del barrio.
- **profundidad de arriendo**: hogares arrendatarios / hogares. Mas hondo = mas demanda
  de arriendo = menos riesgo de no colocar la unidad.
- **saturacion de oferta**: avisos de arriendo activos hoy / hogares arrendatarios. Es el
  "conteo de avisos activos (proxy de saturacion)" que la B2 del CLAUDE.md §1 pide desde
  el dia uno. Muchos avisos por arrendatario = todos compitiendo por el mismo inquilino.

El `riesgo` final combina los tres con pesos `E` declarados en params.yml
(`riesgo_microzona.*`), cada componente normalizado min-max SOBRE EL ALCANCE: el riesgo
es relativo entre las microzonas donde efectivamente se puede comprar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from flujocero.config import Config

D = Decimal


@dataclass(frozen=True)
class ResultadoPuente:
    manzanas_asignadas: int
    manzanas_sin_centro_de_barrio: int
    microzonas_con_manzanas: int


def _distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular: sobra para ordenar distancias dentro de una comuna (<10 km)."""
    klat = 111_320.0
    klon = klat * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * klat, (lon1 - lon2) * klon)


def asignar_manzanas(conexion: Any, ahora: datetime) -> ResultadoPuente:
    """Reconstruye `map_microzona_manzana` completo (es un derivado).

    Solo manzanas con centroide (las 4 regiones con cartografia) y solo comunas que tienen
    algun barrio con centro. La comuna de la manzana se cruza por slug de su nombre censal
    contra `dim_microzona.comuna_id` — el mismo vocabulario que fabrico las microzonas.
    """
    from flujocero.sources.portal_comun import slug

    centros: dict[str, list[tuple[str, float, float]]] = {}
    for mid, comuna_id, lat, lon in conexion.execute(
        "SELECT microzona_id, comuna_id, centro_lat, centro_lon FROM dim_microzona "
        "WHERE centro_lat IS NOT NULL AND centro_lon IS NOT NULL"
    ).fetchall():
        centros.setdefault(comuna_id, []).append((mid, float(lat), float(lon)))

    manzanas = conexion.execute(
        "SELECT manzent, comuna, lat, lon FROM dim_manzana WHERE lat IS NOT NULL"
    ).fetchall()

    conexion.execute("DELETE FROM map_microzona_manzana")
    asignadas, sin_barrio = 0, 0
    tocadas: set[str] = set()
    lote: list[tuple[str, str, float, datetime]] = []
    for manzent, comuna, lat, lon in manzanas:
        candidatos = centros.get(slug(comuna or ""))
        if not candidatos:
            sin_barrio += 1
            continue
        mid, dist = min(
            ((m, _distancia_m(float(lat), float(lon), clat, clon)) for m, clat, clon in candidatos),
            key=lambda x: x[1],
        )
        lote.append((manzent, mid, dist, ahora))
        tocadas.add(mid)
        asignadas += 1
    if lote:
        conexion.executemany(
            "INSERT INTO map_microzona_manzana (manzent, microzona_id, distancia_m, "
            "calculado_en) VALUES (?, ?, ?, ?)",
            lote,
        )
    return ResultadoPuente(asignadas, sin_barrio, len(tocadas))


def calcular_riesgo(conexion: Any, p: Config, ahora: datetime) -> int:
    """Agrega los insumos censales por microzona y escribe `agg_riesgo_microzona`.

    Los NULL censales (conteos enmascarados con '*') se quedan fuera de cada suma: sumar
    sobre lo que se sabe es `D`; tratarlos como cero seria imputar (§3.2).
    """
    filas = conexion.execute(
        """
        SELECT m.microzona_id,
               count(*)                                            AS n_manzanas,
               sum(d.n_viv_desocupadas)                            AS desocupadas,
               sum(d.n_viv_ocupadas)                               AS ocupadas,
               sum(d.n_hog_arrienda_contrato) + sum(d.n_hog_arrienda_sin_contrato)
                                                                   AS arrendatarios,
               sum(d.n_hogares)                                    AS hogares
        FROM map_microzona_manzana m JOIN dim_manzana d USING (manzent)
        GROUP BY m.microzona_id
        """
    ).fetchall()
    avisos = dict(
        conexion.execute(
            "SELECT microzona_id, sum(n) FROM agg_arriendo_microzona GROUP BY microzona_id"
        ).fetchall()
    )

    brutos = []
    for mid, n_mz, desocup, ocup, arrend, hogares in filas:
        total_viv = (desocup or 0) + (ocup or 0)
        desocupacion = (desocup or 0) / total_viv if total_viv else None
        profundidad = (arrend or 0) / hogares if hogares else None
        n_avisos = int(avisos.get(mid) or 0)
        saturacion = n_avisos / arrend if arrend else None
        brutos.append((mid, n_mz, desocupacion, profundidad, arrend, n_avisos, saturacion))

    def _minmax(valores: list[float | None]) -> dict[int, float]:
        conocidos = [(i, v) for i, v in enumerate(valores) if v is not None]
        if not conocidos:
            return {}
        vs = [v for _, v in conocidos]
        lo, hi = min(vs), max(vs)
        if hi == lo:
            return {i: 0.5 for i, _ in conocidos}
        return {i: (v - lo) / (hi - lo) for i, v in conocidos}

    n_desocup = _minmax([b[2] for b in brutos])
    n_prof = _minmax([b[3] for b in brutos])
    n_satur = _minmax([b[6] for b in brutos])
    w_d = float(p.d("riesgo_microzona.peso_desocupacion"))
    w_s = float(p.d("riesgo_microzona.peso_saturacion"))
    w_p = float(p.d("riesgo_microzona.peso_profundidad"))

    conexion.execute("DELETE FROM agg_riesgo_microzona")
    for i, (mid, n_mz, desocupacion, profundidad, arrend, n_avisos, saturacion) in enumerate(
        brutos
    ):
        # Cada componente entra SOLO si se pudo medir; el peso de los ausentes se
        # redistribuye — la misma regla que el score aplica a sus componentes inertes.
        partes: list[tuple[float, float]] = []
        if i in n_desocup:
            partes.append((w_d, n_desocup[i]))
        if i in n_satur:
            partes.append((w_s, n_satur[i]))
        if i in n_prof:
            partes.append((w_p, 1.0 - n_prof[i]))  # mas profundidad = MENOS riesgo
        total_peso = sum(w for w, _ in partes)
        riesgo = sum(w * v for w, v in partes) / total_peso if total_peso else None
        conexion.execute(
            "INSERT INTO agg_riesgo_microzona (microzona_id, n_manzanas, desocupacion, "
            "profundidad_arriendo, hogares_arrendatarios, avisos_arriendo, saturacion, "
            "riesgo, calculado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, n_mz, desocupacion, profundidad, arrend, n_avisos, saturacion, riesgo, ahora),
        )
    return len(brutos)


def calcular_catalizador(conexion: Any, p: Config, ahora: datetime) -> dict[str, int]:
    """El catalizador del §12 por microzona: distancia a la estacion ELEGIBLE mas cercana.

    Elegible = operativa, o en construccion cuya linea tenga fecha creible dentro del
    horizonte en `config/metro.yml`. Una estacion en construccion sin linea declarada en
    OSM o sin fecha curada NO cataliza: se cuenta, no se le inventa fecha (§3.2).

    La conversion distancia -> 0..1 es lineal con dos umbrales E declarados en params
    (`catalizador.*`): pleno hasta `dist_plena_m`, cero desde `dist_max_m`. Las estaciones
    en construccion valen `factor_en_construccion` de lo que valdria una operativa.

    Escribe sobre `agg_riesgo_microzona` (upsert): la fila puede existir del riesgo o
    nacer aca — una microzona con centro y sin manzanas igual tiene distancia al Metro.
    Con `dim_estacion_metro` vacia no se escribe nada: catalizador NULL = sin medir,
    que el emparejamiento cuenta como defecto. Cero seria "medimos y no hay Metro cerca",
    y eso es otra afirmacion.
    """
    from flujocero.config import cargar as cargar_config

    filas = conexion.execute(
        "SELECT estacion_id, linea, estado, lat, lon, anio_apertura FROM dim_estacion_metro"
    ).fetchall()
    if not filas:
        return {"microzonas": 0, "construccion_sin_fecha": 0, "elegibles": 0}

    fechas = {
        str(e["linea"]).lower(): e["fecha_apertura"]
        for e in (cargar_config("metro").crudo("lineas_en_construccion") or [])
    }
    horizonte_anios = int(p.d("catalizador.horizonte_fecha_anios"))
    plena = float(p.d("catalizador.dist_plena_m"))
    maxima = float(p.d("catalizador.dist_max_m"))
    factor_constr = float(p.d("catalizador.factor_en_construccion"))

    elegibles: list[tuple[float, float, float]] = []  # (lat, lon, factor)
    construccion_sin_fecha = 0
    for _eid, linea, estado, lat, lon, anio_apertura in filas:
        if estado == "operativa":
            elegibles.append((float(lat), float(lon), 1.0))
            continue
        fecha = fechas.get((linea or "").lower())
        if fecha is None:
            construccion_sin_fecha += 1
            continue
        # DOBLE llave para lo no operativo: la fecha curada del YAML manda, pero el nodo
        # ademas debe declarar su propia apertura dentro del horizonte. Sin eso, los
        # miembros de la relation "Propuesta de Extension Linea 7" (sin fecha, pura
        # propuesta) heredarian la fecha 2028 de la L7 real y catalizarian un plan.
        anios = (fecha - ahora.date()).days / 365.25
        nodo_ok = anio_apertura is not None and int(anio_apertura) <= ahora.year + horizonte_anios
        if 0 <= anios <= horizonte_anios and nodo_ok:
            elegibles.append((float(lat), float(lon), factor_constr))
        else:
            construccion_sin_fecha += 1

    centros = conexion.execute(
        "SELECT microzona_id, centro_lat, centro_lon FROM dim_microzona "
        "WHERE centro_lat IS NOT NULL"
    ).fetchall()
    n = 0
    for mid, clat, clon in centros:
        mejor = 0.0
        mejor_dist = None
        for elat, elon, factor in elegibles:
            d = _distancia_m(float(clat), float(clon), elat, elon)
            if mejor_dist is None or d < mejor_dist:
                mejor_dist = d
            if d <= plena:
                puntaje = factor
            elif d >= maxima:
                puntaje = 0.0
            else:
                puntaje = factor * (maxima - d) / (maxima - plena)
            mejor = max(mejor, puntaje)
        existe = conexion.execute(
            "SELECT 1 FROM agg_riesgo_microzona WHERE microzona_id = ?", (mid,)
        ).fetchone()
        if existe:
            conexion.execute(
                "UPDATE agg_riesgo_microzona SET dist_metro_m = ?, catalizador = ?, "
                "calculado_en = ? WHERE microzona_id = ?",
                (mejor_dist, mejor, ahora, mid),
            )
        else:
            conexion.execute(
                "INSERT INTO agg_riesgo_microzona (microzona_id, dist_metro_m, catalizador, "
                "calculado_en) VALUES (?, ?, ?, ?)",
                (mid, mejor_dist, mejor, ahora),
            )
        n += 1
    return {
        "microzonas": n,
        "construccion_sin_fecha": construccion_sin_fecha,
        "elegibles": len(elegibles),
    }
