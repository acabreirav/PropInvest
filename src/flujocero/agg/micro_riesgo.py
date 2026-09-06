"""T-924 · ¿Las micro-unidades son de verdad peores? Se mide, no se asume.

El backlog lo exige textual: *"Medir con datos si la vacancia y la rotacion son peores
bajo 35 m2 (no asumirlo)"*. Este modulo produce, por tramo de superficie, los tres
proxies medibles con la base que YA tenemos:

1. **Liquidez de colocacion** (arriendo): edad del aviso activo — cuantos dias lleva
   publicado un arriendo sin arrendarse. Si las chicas se cuelgan mas, se arriendan
   mas lento. Mediana de la edad DECLARADA (ver `_EDAD_DECLARADA`), mas la cota
   inferior por primera vista propia y la fraccion vista fresca (T-924b).
2. **Gastos comunes por m²** (arriendo): el portal publica `gastos_comunes_clp` por
   aviso — dato V, no supuesto. Si el GGCC/m² sube al achicar el depto, el opex real
   de una micro-unidad esta subestimado por el parametro plano de params.yml.
3. **Liquidez de salida** (venta): de la foto de mayo (T-918/919), que % de los avisos
   por tramo ya no se volvio a ver. NO es "% vendido" — la cobertura de paginas
   contamina el nivel — pero la comparacion RELATIVA entre tramos si informa: la
   cobertura no discrimina por m².

La DECISION (sumar un componente de riesgo por tamano, o retirar la advertencia) no
vive aca: mover el score es §8.4, se decide con el humano mirando estos numeros.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

TRAMOS: tuple[tuple[str, float, float], ...] = (
    ("<25", 0.0, 25.0),
    ("25-35", 25.0, 35.0),
    ("35-50", 35.0, 50.0),
    ("50-70", 50.0, 70.0),
    ("70+", 70.0, 10_000.0),
)

_CASE_TRAMO = (
    "CASE "
    + " ".join(
        f"WHEN {col} >= {lo} AND {col} < {hi} THEN '{nombre}'"
        for nombre, lo, hi in TRAMOS
        for col in ("__M2__",)
    )
    + " END"
)


def _caso(col: str) -> str:
    return _CASE_TRAMO.replace("__M2__", col)


@dataclass(frozen=True)
class FilaArriendo:
    tramo: str
    n: int
    # Mediana de edad DECLARADA (dias_en_mercado, o publicado_en -> ultima vista). Un
    # publicado_en igual al dia de su captura no entra: es 0 por construccion, no un
    # dato de edad (verificador 06-sep M-3). Tampoco uno posterior a la primera vista
    # propia: eso es un relisting, no la edad del aviso (M-6). `n_con_fecha` dice
    # cuantas filas sostienen la mediana; None = ND.
    edad_mediana_dias: float | None
    n_con_fecha: int
    uf_m2_mediana: float | None
    ggcc_m2_mediana_clp: float | None
    n_con_ggcc: int
    # T-924b · cota INFERIOR de la edad: dias desde que ESTE sistema vio el aviso por
    # primera vez (`visto_primera_vez`; mejora sola con las semanas de recoleccion).
    edad_cota_inf_mediana_dias: float | None = None
    # Fraccion de avisos que ALGUNA captura vio recien publicados (etiqueta del portal
    # en SU momento — no depende del reloj de la medicion, verificador M-1/M-2). El
    # nivel esta contaminado hacia abajo por capturas del parser <1.1.0, que era ciego
    # a la etiqueta: comparar ENTRE tramos, como todo en este modulo.
    pct_visto_fresco: float | None = None
    n_con_etiqueta: int = 0


@dataclass(frozen=True)
class FilaVenta:
    tramo: str
    n_mayo: int
    pct_no_vistas: float  # % de la foto de mayo que no se volvio a ver (proxy RELATIVO)
    pct_bajaron_precio: float


# Edad declarada de un aviso: dias_en_mercado si el portal lo dijera; si no, la
# distancia publicado_en -> ultima vista, PERO solo cuando publicado_en aporta edad de
# verdad: uno igual al dia de su captura es 0 por construccion (etiqueta "HOY", M-3) y
# uno posterior a la primera vista propia es un relisting, no una publicacion (M-6).
_EDAD_DECLARADA = """
    CASE WHEN dias_en_mercado IS NOT NULL THEN dias_en_mercado
         WHEN publicado_en IS NOT NULL
              AND publicado_en < CAST(fetched_at AS DATE)
              AND publicado_en <= CAST(COALESCE(visto_primera_vez, fetched_at) AS DATE)
         THEN date_diff('day', publicado_en, CAST(fetched_at AS DATE)) END
"""


def medir_arriendo(conexion: Any, ahora: datetime | None = None) -> list[FilaArriendo]:
    """Colocacion y GGCC por tramo, sobre avisos activos, no amoblados (el MISMO filtro
    del §7.3: `no_comparable` sobre la URL — la columna `amoblado` nunca se puebla y
    filtrar solo por ella era un no-op, verificador 06-sep m-7) ni sospechosos.

    A diferencia del ranking, aca NO corre el gate de frescura de 21 dias: la
    comparacion entre tramos usa todo el historico activo a proposito — mas historia,
    mas n — y el nivel absoluto se lee con ese caveat, igual que en `medir_venta`.

    Con `ahora` ademas calcula la cota inferior de edad de T-924b; sin el
    (compatibilidad y tests viejos) esa columna queda en ND, nunca en un cero."""
    from flujocero.quality.comparabilidad import NO_COMPARABLE

    cota_sql = (
        f"""median(date_diff('day',
                   CAST(COALESCE(visto_primera_vez, fetched_at) AS DATE),
                   DATE '{ahora:%Y-%m-%d}'))"""
        if ahora is not None
        else "NULL"
    )
    filas = conexion.execute(
        f"""
        SELECT {_caso("m2_utiles")} AS tramo,
               count(*) AS n,
               median({_EDAD_DECLARADA}),
               count({_EDAD_DECLARADA}),
               median(arriendo_uf / m2_utiles),
               median(CASE WHEN gastos_comunes_clp > 0
                           THEN gastos_comunes_clp / m2_utiles END),
               count(CASE WHEN gastos_comunes_clp > 0 THEN 1 END),
               {cota_sql},
               avg(CASE WHEN publicado_desde IS NOT NULL THEN 1.0 ELSE 0.0 END),
               count(publicado_desde)
        FROM fact_arriendo_comp
        WHERE activo AND NOT COALESCE(amoblado, FALSE) AND NOT COALESCE(sospechoso, FALSE)
          AND NOT regexp_matches(lower(COALESCE(source_url, '')), ?)
          AND m2_utiles IS NOT NULL AND m2_utiles > 0
        GROUP BY 1
        """,
        (NO_COMPARABLE.pattern,),
    ).fetchall()
    orden = {nombre: i for i, (nombre, _, _) in enumerate(TRAMOS)}
    salida = [
        FilaArriendo(
            tramo=t,
            n=int(n),
            edad_mediana_dias=float(edad) if edad is not None else None,
            n_con_fecha=int(n_fecha),
            uf_m2_mediana=float(ufm2) if ufm2 is not None else None,
            ggcc_m2_mediana_clp=float(ggcc) if ggcc is not None else None,
            n_con_ggcc=int(n_ggcc),
            edad_cota_inf_mediana_dias=float(cota) if cota is not None else None,
            pct_visto_fresco=float(pct) if pct is not None else None,
            n_con_etiqueta=int(n_eti),
        )
        for t, n, edad, n_fecha, ufm2, ggcc, n_ggcc, cota, pct, n_eti in filas
        if t is not None
    ]
    return sorted(salida, key=lambda f: orden[f.tramo])


def medir_venta(conexion: Any, ahora: datetime) -> list[FilaVenta]:
    """Liquidez de salida por tramo: la foto de mayo contra lo re-visto despues.

    'No vista' = la unidad no aparece en ninguna captura de los ultimos 14 dias. El NIVEL
    esta contaminado por cobertura de paginas (el propio `cli delta` lo advierte); la
    comparacion ENTRE tramos es lo que informa."""
    corte_mayo = "2026-06-01"
    corte_reciente = (ahora - timedelta(days=14)).strftime("%Y-%m-%d")
    filas = conexion.execute(
        f"""
        WITH por_unidad AS (
            SELECT unidad_key,
                   {_caso("COALESCE(m2_utiles, m2_totales)")} AS tramo,
                   min(valid_from)  AS primera,
                   max(fetched_at)  AS ultima_vista,
                   arg_min(precio_uf, valid_from) AS precio_inicial,
                   arg_max(precio_uf, valid_from) AS precio_final
            FROM fact_unidad_venta
            WHERE COALESCE(m2_utiles, m2_totales) > 0 AND precio_uf IS NOT NULL
            GROUP BY 1, 2
        )
        SELECT tramo,
               count(*) AS n_mayo,
               avg(CASE WHEN ultima_vista < TIMESTAMP '{corte_reciente}' THEN 1.0 ELSE 0.0 END),
               avg(CASE WHEN precio_final < precio_inicial THEN 1.0 ELSE 0.0 END)
        FROM por_unidad
        WHERE primera < TIMESTAMP '{corte_mayo}' AND tramo IS NOT NULL
        GROUP BY 1
        """
    ).fetchall()
    orden = {nombre: i for i, (nombre, _, _) in enumerate(TRAMOS)}
    salida = [
        FilaVenta(
            tramo=t,
            n_mayo=int(n),
            pct_no_vistas=float(pnv),
            pct_bajaron_precio=float(pb),
        )
        for t, n, pnv, pb in filas
    ]
    return sorted(salida, key=lambda f: orden[f.tramo])
