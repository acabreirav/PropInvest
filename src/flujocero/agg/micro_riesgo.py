"""T-924 · ¿Las micro-unidades son de verdad peores? Se mide, no se asume.

El backlog lo exige textual: *"Medir con datos si la vacancia y la rotacion son peores
bajo 35 m2 (no asumirlo)"*. Este modulo produce, por tramo de superficie, los tres
proxies medibles con la base que YA tenemos:

1. **Liquidez de colocacion** (arriendo): edad del aviso activo — cuantos dias lleva
   publicado un arriendo sin arrendarse. Si las chicas se cuelgan mas, se arriendan
   mas lento. `COALESCE(dias_en_mercado, fetched_at - publicado_en)`, mediana por tramo.
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
    edad_mediana_dias: float | None  # None = ningun aviso del tramo declara fecha (ND)
    uf_m2_mediana: float | None
    ggcc_m2_mediana_clp: float | None
    n_con_ggcc: int
    # T-924b · dos medidas nuevas, cada una con su naturaleza a la vista:
    # cota INFERIOR de la edad (dias desde que ESTE sistema vio el aviso por primera
    # vez — `visto_primera_vez`; mejora sola con las semanas de recoleccion), y cota
    # inferior de la fraccion recien publicada (avisos cuya etiqueta del portal declara
    # publicacion en los ultimos 7 dias; la ausencia de etiqueta es ND, no "viejo").
    edad_cota_inf_mediana_dias: float | None = None
    pct_recien_publicado: float | None = None
    n_con_etiqueta: int = 0


@dataclass(frozen=True)
class FilaVenta:
    tramo: str
    n_mayo: int
    pct_no_vistas: float  # % de la foto de mayo que no se volvio a ver (proxy RELATIVO)
    pct_bajaron_precio: float


def medir_arriendo(conexion: Any, ahora: datetime | None = None) -> list[FilaArriendo]:
    """Colocacion y GGCC por tramo, sobre avisos activos no amoblados ni sospechosos
    (los mismos filtros que la agregacion del §7.3 — medir con otra vara diria otra cosa).

    Con `ahora` ademas calcula las dos cotas de T-924b; sin el (compatibilidad y tests
    viejos) esas columnas quedan en ND, nunca en un cero inventado."""
    con_cotas = ahora is not None
    cotas_sql = (
        f"""
               median(date_diff('day',
                      CAST(COALESCE(visto_primera_vez, fetched_at) AS DATE),
                      DATE '{ahora:%Y-%m-%d}')),
               avg(CASE WHEN publicado_desde >= DATE '{ahora:%Y-%m-%d}' - 7
                        THEN 1.0 ELSE 0.0 END),
               count(publicado_desde)
        """
        if con_cotas
        else "NULL, NULL, 0"
    )
    filas = conexion.execute(
        f"""
        SELECT {_caso("m2_utiles")} AS tramo,
               count(*) AS n,
               median(COALESCE(dias_en_mercado,
                               date_diff('day', publicado_en, CAST(fetched_at AS DATE)))),
               median(arriendo_uf / m2_utiles),
               median(CASE WHEN gastos_comunes_clp > 0
                           THEN gastos_comunes_clp / m2_utiles END),
               count(CASE WHEN gastos_comunes_clp > 0 THEN 1 END),
               {cotas_sql}
        FROM fact_arriendo_comp
        WHERE activo AND NOT COALESCE(amoblado, FALSE) AND NOT COALESCE(sospechoso, FALSE)
          AND m2_utiles IS NOT NULL AND m2_utiles > 0
        GROUP BY 1
        """
    ).fetchall()
    orden = {nombre: i for i, (nombre, _, _) in enumerate(TRAMOS)}
    salida = [
        FilaArriendo(
            tramo=t,
            n=int(n),
            edad_mediana_dias=float(edad) if edad is not None else None,
            uf_m2_mediana=float(ufm2) if ufm2 is not None else None,
            ggcc_m2_mediana_clp=float(ggcc) if ggcc is not None else None,
            n_con_ggcc=int(n_ggcc),
            edad_cota_inf_mediana_dias=float(cota) if cota is not None else None,
            # cota INFERIOR: un aviso sin etiqueta cuenta 0 aunque pudiera ser fresco.
            # `n_con_etiqueta` al lado dice cuanta declaracion sostiene el numero.
            pct_recien_publicado=float(pct) if pct is not None else None,
            n_con_etiqueta=int(n_eti),
        )
        for t, n, edad, ufm2, ggcc, n_ggcc, cota, pct, n_eti in filas
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
