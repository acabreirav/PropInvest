"""Modelo hedónico de arriendo — T-958: estimar celdas RALAS desde la estructura del mercado.

El emparejamiento (D-020/D-024) es honesto a costa de cobertura: una celda
`(microzona, tipología, m² similares)` sin n≥8 comparables queda en ND, y el diagnóstico
de huecos (T-935) mostró que ahí espera buena parte del universo. Observación del usuario
(14-oct-2026): una celda rala puede ser *poca oferta con demanda honda* — menos competencia,
menor vacancia — y hoy el sistema no puede ni mirarla.

Este módulo estima el arriendo de esas celdas **desde las otras**, con un modelo hedónico
aditivo en logaritmos:

    log(arriendo_uf) = μ + β·log(m²) + efecto_tipología + efecto_microzona + ajuste_celda + ε

- **β** (elasticidad del tamaño) se estima SOLO con variación *dentro* de cada celda
  (estimador de efectos fijos): comparar un 1D de 30 m² en Ñuñoa contra un 3D de 90 m² en
  La Serena no dice nada del tamaño — dice que son otro producto en otro mercado.
- Los efectos de tipología y microzona salen de un ajuste aditivo de dos vías sobre las
  medias por celda (mínimos cuadrados por medias alternadas, determinista).
- **ajuste_celda**: lo que la celda observada se desvía del modelo aditivo, ENCOGIDO por
  `n/(n+k)` — una celda con pocos comparables aporta poco de sí misma y hereda la
  estructura; una densa se parece a su propia mediana.
- La predicción es `exp(·)`: bajo residuos simétricos en log, estima la **mediana** del
  arriendo — la misma magnitud que usa el emparejamiento — y el intervalo reportado son
  los cuantiles EMPÍRICOS de los residuos (sin supuesto de normalidad).

Reglas de contrato que este módulo respeta a propósito:

- **§3.2 — ningún número nace de la nada**: se entrena solo con los comparables LIMPIOS
  (los mismos que `comparables_desde_duckdb` entrega: frescos, sin amoblados, sin
  sospechosos, relistings colapsados, gemelos fuera). Una (microzona, tipología) donde el
  guardia de temporada D-022 dispararía a nivel de grupo queda FUERA del entrenamiento:
  un efecto de microzona envenenado contaminaría cada predicción de esa zona.
- **ND antes que extrapolar**: no se predice una microzona o tipología nunca vista, ni un
  par (microzona, tipología) cuyos nodos caen en componentes desconectadas del grafo
  bipartito de entrenamiento — ahí los efectos no son comparables entre sí y la suma
  sería un número sin significado.
- **El modelo JAMÁS alimenta el ranking** (§12): sus salidas son evidencia `E`
  (supuesto de modelo con parámetros declarados en `config/params.yml`), viven en una
  sección aparte del informe rotulada como tal, y esa sección solo se publica si el
  backtest leave-one-cell-out PASA sobre la base del día (gate en tiempo de ejecución,
  no una promesa).

Puro: sin I/O, sin reloj, sin aleatoriedad. La aritmética interna es float (regresión en
espacio log, no un monto); los montos de salida vuelven como Decimal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from flujocero.agg.arriendo import Comparable, etiqueta_rango

D = Decimal

# Mínimos ESTRUCTURALES (sin dimensión de mercado — misma regla que DESCENTRADO_MAX:
# viven en el código, no en params.yml). Bajo esto, β y los efectos son ruido con
# forma de coeficiente y el modelo entero es ND.
MIN_OBS_ENTRENAMIENTO = 100
MIN_CELDAS_ENTRENAMIENTO = 12
# Convergencia del ajuste de dos vías por medias alternadas. Determinista: mismo input,
# mismas iteraciones, mismo output.
_ITER_MAX = 300
_TOL = 1e-12


@dataclass(frozen=True)
class Prediccion:
    """Un arriendo MODELADO, con su intervalo empírico y cuánto dato real lo sostiene."""

    arriendo_uf: Decimal  # mediana modelada
    p25_uf: Decimal  # exp(ŷ + q25 de los residuos de entrenamiento)
    p75_uf: Decimal
    n_celda: int  # comparables reales en la celda exacta (0 = extrapolación pura)
    n_microzona: int  # observaciones que sostienen el efecto de SU microzona
    n_tipologia: int


@dataclass
class ModeloHedonico:
    """El modelo entrenado. Solo estado: predecir() es quien lo usa."""

    beta: float
    mu: float
    efecto_tipologia: dict[str, float]
    efecto_microzona: dict[str, float]
    ajuste_celda: dict[tuple[str, str], float]
    n_celda: dict[tuple[str, str], int]
    n_tipologia: dict[str, int]
    n_microzona: dict[str, int]
    # cuantiles EMPÍRICOS de los residuos del modelo aditivo (sin el ajuste de celda):
    # el intervalo honesto para una celda rala, donde el ajuste propio es ~0
    q25: float
    q75: float
    n_obs: int
    n_celdas: int
    grupos_temporada_excluidos: int
    # componente conexa de cada nodo del grafo bipartito microzona↔tipología: dos nodos
    # en componentes distintas no comparten ninguna celda observada (ni por transición)
    # y sus efectos NO son comparables — predecir cruzándolos sería inventar.
    componente: dict[str, int] = field(default_factory=dict)


def _percentil_f(valores: list[float], p: float) -> float:
    """El mismo percentil interpolado de `arriendo.percentil`, en float."""
    if not valores:
        return 0.0
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    pos = (len(orden) - 1) * p
    bajo = int(pos)
    alto = min(bajo + 1, len(orden) - 1)
    return orden[bajo] + (orden[alto] - orden[bajo]) * (pos - bajo)


def _observaciones(
    comparables: list[Comparable],
    rangos: list[list[int]],
    amoblados: dict[tuple[str, str], list[Decimal]] | None = None,
    tope_temporada: Decimal | None = None,
) -> tuple[list[tuple[str, str, float, float]], int]:
    """`(mz, tip, log m², log arriendo)` de los comparables entrenables + grupos excluidos.

    Mismos filtros de población que el emparejamiento: fuera de los rangos del §12
    (>140 m²) no se entrena, y un grupo (mz, tip) donde la fracción de avisos marcados
    amoblado/temporada alcanza el umbral D-022 **a nivel de grupo** se excluye entero —
    sus "pelados" son sospechosos por asociación y entrenarían un efecto de microzona
    contaminado que luego se propagaría a toda predicción de esa zona.
    """
    por_grupo: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for c in comparables:
        if c.arriendo_uf <= 0 or c.m2_utiles <= 0:
            continue
        if etiqueta_rango(c.m2_utiles, rangos) is None:
            continue
        por_grupo.setdefault((c.microzona_id, c.tipologia), []).append(
            (math.log(float(c.m2_utiles)), math.log(float(c.arriendo_uf)))
        )
    excluidos = 0
    obs: list[tuple[str, str, float, float]] = []
    for clave in sorted(por_grupo):
        grupo = por_grupo[clave]
        if amoblados is not None and tope_temporada is not None:
            n_amo = len(amoblados.get(clave, []))
            if n_amo >= 2 and D(n_amo) / (n_amo + len(grupo)) >= tope_temporada:
                excluidos += 1
                continue
        mz, tip = clave
        obs.extend((mz, tip, x, y) for x, y in grupo)
    return obs, excluidos


def _componentes(celdas: list[tuple[str, str]]) -> dict[str, int]:
    """Componentes conexas del grafo bipartito `mz:` ↔ `tip:` (union-find chico)."""
    padre: dict[str, str] = {}

    def raiz(a: str) -> str:
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    for mz, tip in celdas:
        for nodo in (f"mz:{mz}", f"tip:{tip}"):
            padre.setdefault(nodo, nodo)
        ra, rb = raiz(f"mz:{mz}"), raiz(f"tip:{tip}")
        if ra != rb:
            padre[max(ra, rb)] = min(ra, rb)  # determinista: gana el menor lexicográfico
    etiquetas: dict[str, int] = {}
    salida: dict[str, int] = {}
    for nodo in sorted(padre):
        r = raiz(nodo)
        salida[nodo] = etiquetas.setdefault(r, len(etiquetas))
    return salida


def entrenar(
    comparables: list[Comparable],
    rangos: list[list[int]],
    amoblados: dict[tuple[str, str], list[Decimal]] | None = None,
    tope_temporada: Decimal | None = None,
    k_encogimiento: float = 8.0,
) -> ModeloHedonico | None:
    """Ajusta el modelo sobre los comparables limpios. `None` = no hay con qué (ND, §3.2).

    `k_encogimiento` es el `E` `modelo_arriendo.encogimiento_celda_k` de params.yml:
    el promedio propio de la celda pesa `n/(n+k)` — con k=8, una celda en el umbral
    del §7.3 (n=8) pesa exactamente la mitad.
    """
    obs, excluidos = _observaciones(comparables, rangos, amoblados, tope_temporada)
    # estadísticos por celda: n, Σx, Σy, Σxx, Σxy — todo lo demás sale de aquí
    stats: dict[tuple[str, str], list[float]] = {}
    for mz, tip, x, y in obs:
        s = stats.setdefault((mz, tip), [0.0, 0.0, 0.0, 0.0, 0.0])
        s[0] += 1
        s[1] += x
        s[2] += y
        s[3] += x * x
        s[4] += x * y
    if len(obs) < MIN_OBS_ENTRENAMIENTO or len(stats) < MIN_CELDAS_ENTRENAMIENTO:
        return None

    # β por variación DENTRO de celda (efectos fijos): solo celdas con n≥2 aportan.
    sxx = sxy = 0.0
    for n, sx, sy, sxx_c, sxy_c in stats.values():
        if n >= 2:
            sxx += sxx_c - sx * sx / n
            sxy += sxy_c - sx * sy / n
    if sxx <= 1e-9:
        # sin variación de tamaño dentro de las celdas no hay elasticidad estimable
        return None
    beta = sxy / sxx

    # Ajuste aditivo de dos vías sobre las medias por celda, ponderado por n.
    # r̄_celda = media de (y − β·x) en la celda; se busca μ + t_tip + z_mz.
    celdas = sorted(stats)
    media_r = {c: (stats[c][2] - beta * stats[c][1]) / stats[c][0] for c in celdas}
    n_c = {c: stats[c][0] for c in celdas}
    total = sum(n_c.values())
    mu = sum(media_r[c] * n_c[c] for c in celdas) / total
    tips = sorted({tip for _, tip in celdas})
    mzs = sorted({mz for mz, _ in celdas})
    t = dict.fromkeys(tips, 0.0)
    z = dict.fromkeys(mzs, 0.0)
    por_tip = {tp: [c for c in celdas if c[1] == tp] for tp in tips}
    por_mz = {m: [c for c in celdas if c[0] == m] for m in mzs}
    for _ in range(_ITER_MAX):
        delta = 0.0
        for tp in tips:
            cs = por_tip[tp]
            nuevo = sum((media_r[c] - mu - z[c[0]]) * n_c[c] for c in cs) / sum(n_c[c] for c in cs)
            delta = max(delta, abs(nuevo - t[tp]))
            t[tp] = nuevo
        # identificación: los efectos promedian 0 (ponderado); el nivel vive en μ
        ancla = sum(t[tip] * n for (_, tip), n in n_c.items()) / total
        mu += ancla
        for tp in tips:
            t[tp] -= ancla
        for m in mzs:
            cs = por_mz[m]
            nuevo = sum((media_r[c] - mu - t[c[1]]) * n_c[c] for c in cs) / sum(n_c[c] for c in cs)
            delta = max(delta, abs(nuevo - z[m]))
            z[m] = nuevo
        ancla = sum(z[mz] * n for (mz, _), n in n_c.items()) / total
        mu += ancla
        for m in mzs:
            z[m] -= ancla
        if delta < _TOL:
            break

    # Residuos del modelo ADITIVO (sin ajuste de celda): el intervalo honesto para una
    # celda rala. Y el ajuste encogido de cada celda observada, para las densas.
    residuos: list[float] = []
    suma_e: dict[tuple[str, str], float] = dict.fromkeys(celdas, 0.0)
    for mz, tip, x, y in obs:
        e = y - beta * x - mu - t[tip] - z[mz]
        residuos.append(e)
        suma_e[(mz, tip)] += e
    ajuste = {c: (n_c[c] / (n_c[c] + k_encogimiento)) * (suma_e[c] / n_c[c]) for c in celdas}

    n_tip = {tp: int(sum(n_c[c] for c in por_tip[tp])) for tp in tips}
    n_mz = {m: int(sum(n_c[c] for c in por_mz[m])) for m in mzs}
    return ModeloHedonico(
        beta=beta,
        mu=mu,
        efecto_tipologia=t,
        efecto_microzona=z,
        ajuste_celda=ajuste,
        n_celda={c: int(n) for c, n in n_c.items()},
        n_tipologia=n_tip,
        n_microzona=n_mz,
        q25=_percentil_f(residuos, 0.25),
        q75=_percentil_f(residuos, 0.75),
        n_obs=len(obs),
        n_celdas=len(celdas),
        grupos_temporada_excluidos=excluidos,
        componente=_componentes(celdas),
    )


def predecir(modelo: ModeloHedonico, mz: str, tip: str, m2: Decimal) -> Prediccion | None:
    """La mediana modelada para `(mz, tip, m2)`, o `None` cuando sería inventar.

    `None` si la microzona o la tipología no se vieron en el entrenamiento, o si cayeron
    en componentes desconectadas (sus efectos no son comparables entre sí). ND antes que
    extrapolar (§3.2).
    """
    if m2 <= 0 or tip not in modelo.efecto_tipologia or mz not in modelo.efecto_microzona:
        return None
    if modelo.componente.get(f"mz:{mz}") != modelo.componente.get(f"tip:{tip}"):
        return None
    y = (
        modelo.mu
        + modelo.beta * math.log(float(m2))
        + modelo.efecto_tipologia[tip]
        + modelo.efecto_microzona[mz]
        + modelo.ajuste_celda.get((mz, tip), 0.0)
    )
    return Prediccion(
        arriendo_uf=D(str(round(math.exp(y), 4))),
        p25_uf=D(str(round(math.exp(y + modelo.q25), 4))),
        p75_uf=D(str(round(math.exp(y + modelo.q75), 4))),
        n_celda=modelo.n_celda.get((mz, tip), 0),
        n_microzona=modelo.n_microzona.get(mz, 0),
        n_tipologia=modelo.n_tipologia.get(tip, 0),
    )


# ------------------------------------------------------------- backtest leave-one-cell-out


@dataclass(frozen=True)
class ErrorCelda:
    microzona_id: str
    tipologia: str
    n: int
    mediana_real_uf: float
    mediana_modelo_uf: float

    @property
    def comuna(self) -> str:
        return self.microzona_id.split("/")[0]

    @property
    def error(self) -> float:
        """(modelo − real) / real. Positivo = el modelo SOBREestima — el lado que infla."""
        return (self.mediana_modelo_uf - self.mediana_real_uf) / self.mediana_real_uf


@dataclass
class ResultadoBacktest:
    """El examen del modelo: predecir celdas DENSAS sin verlas y medirse contra su mediana."""

    errores: list[ErrorCelda] = field(default_factory=list)
    no_predecibles: int = 0  # celdas densas que, sin sí mismas, quedan sin mz/tip estimable
    sin_modelo: int = 0  # reentrenos que no juntaron el mínimo estructural
    celdas_densas: int = 0

    @property
    def error_abs_mediano(self) -> float:
        return _percentil_f([abs(e.error) for e in self.errores], 0.5)

    @property
    def error_abs_p75(self) -> float:
        return _percentil_f([abs(e.error) for e in self.errores], 0.75)

    def por_grupo(self, llave: str) -> dict[str, tuple[int, float]]:
        """`comuna` o `tipologia` → (n celdas, mediana de |error|)."""
        grupos: dict[str, list[float]] = {}
        for e in self.errores:
            grupos.setdefault(getattr(e, llave), []).append(abs(e.error))
        return {g: (len(v), _percentil_f(v, 0.5)) for g, v in sorted(grupos.items())}

    def pasa(self, error_mediano_max: float, error_p75_max: float, min_celdas: int) -> bool:
        """El gate: con pocas celdas evaluadas NO pasa — un backtest chico no prueba nada."""
        return (
            len(self.errores) >= min_celdas
            and self.error_abs_mediano <= error_mediano_max
            and self.error_abs_p75 <= error_p75_max
        )


def backtest_loco(
    comparables: list[Comparable],
    rangos: list[list[int]],
    amoblados: dict[tuple[str, str], list[Decimal]] | None = None,
    tope_temporada: Decimal | None = None,
    k_encogimiento: float = 8.0,
    min_celda: int = 8,
) -> ResultadoBacktest:
    """Leave-one-cell-out sobre las celdas densas (n≥`min_celda`, las que el ranking usa).

    Para cada celda densa se REENTRENA el modelo sin ninguno de sus comparables y se
    predice la mediana de la celda en su m² mediano. El error contra la mediana real es
    exactamente el error que el modelo cometería en una celda rala cuya verdad no vemos
    — con el sesgo de que las densas son los mercados más líquidos; el intervalo p25/p75
    de `predecir` carga el resto de la incertidumbre.

    Nada se filtra del reporte: una celda no predecible o un reentreno sin mínimo se
    cuenta, no desaparece.
    """
    obs, _ = _observaciones(comparables, rangos, amoblados, tope_temporada)
    por_celda: dict[tuple[str, str], list[Comparable]] = {}
    for c in comparables:
        por_celda.setdefault((c.microzona_id, c.tipologia), []).append(c)
    # la población entrenable de la celda (post-filtros de _observaciones) decide "densa":
    # una celda que D-022 excluye del entrenamiento tampoco sirve de examen.
    conteo_obs: dict[tuple[str, str], int] = {}
    for mz, tip, _, _ in obs:
        conteo_obs[(mz, tip)] = conteo_obs.get((mz, tip), 0) + 1
    densas = sorted(c for c, n in conteo_obs.items() if n >= min_celda)

    r = ResultadoBacktest(celdas_densas=len(densas))
    for celda in densas:
        mz, tip = celda
        resto = [c for c in comparables if (c.microzona_id, c.tipologia) != celda]
        modelo = entrenar(resto, rangos, amoblados, tope_temporada, k_encogimiento)
        if modelo is None:
            r.sin_modelo += 1
            continue
        propios = [
            c
            for c in por_celda[celda]
            if c.arriendo_uf > 0 and c.m2_utiles > 0 and etiqueta_rango(c.m2_utiles, rangos)
        ]
        m2_med = _percentil_f([float(c.m2_utiles) for c in propios], 0.5)
        real = _percentil_f([float(c.arriendo_uf) for c in propios], 0.5)
        pred = predecir(modelo, mz, tip, D(str(m2_med)))
        if pred is None or real <= 0:
            r.no_predecibles += 1
            continue
        r.errores.append(
            ErrorCelda(
                microzona_id=mz,
                tipologia=tip,
                n=len(propios),
                mediana_real_uf=real,
                mediana_modelo_uf=float(pred.arriendo_uf),
            )
        )
    return r
