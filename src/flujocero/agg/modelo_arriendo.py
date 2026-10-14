"""Modelo hedónico de arriendo — T-958: estimar celdas RALAS desde la estructura del mercado.

El emparejamiento (D-020/D-024) es honesto a costa de cobertura: una celda
`(microzona, tipología, m² similares)` sin n≥8 comparables queda en ND, y el diagnóstico
de huecos (T-935) mostró que ahí espera buena parte del universo. Observación del usuario
(14-oct-2026): una celda rala puede ser *poca oferta con demanda honda* — menos competencia,
menor vacancia — y hoy el sistema no puede ni mirarla.

Este módulo estima el arriendo de esas celdas **desde las otras**, con un modelo hedónico
aditivo en logaritmos:

    log(arriendo_uf) = μ + β_tip·log(m²) + efecto_tipología + efecto_microzona
                       + ajuste_celda + ε

- **β** (elasticidad del tamaño) se estima SOLO con variación *dentro* de cada celda
  (estimador de efectos fijos), y **por tipología** cuando la tipología junta variación
  suficiente (verificador T-958 H2: un β único se sesga hacia la elasticidad de los
  chicos, cuya varianza en log es mayor, e infla a los 3D chicos). Sin variación propia,
  respaldo al β global.
- Los efectos de tipología y microzona salen de un ajuste aditivo de dos vías sobre las
  medias por celda (mínimos cuadrados por medias alternadas, determinista) y luego se
  **encogen por `n/(n+k)`** (verificador H1: sin encoger, una microzona con una sola
  celda observada absorbía entero el residuo de esa celda y el `k` no actuaba).
- **ajuste_celda**: lo que el grupo (mz, tip) observado se desvía del modelo aditivo ya
  encogido, a su vez encogido por `n/(n+k)`.
- La predicción es `exp(·)`: bajo residuos simétricos en log, estima la **mediana** del
  arriendo — la misma magnitud que usa el emparejamiento. El intervalo que el módulo
  entrega son los cuantiles EMPÍRICOS de sus residuos de entrenamiento; el informe lo
  ENSANCHA además con los errores fuera de muestra del backtest del día (verificador
  H3: el residuo en muestra subestima la duda donde menos dato hay).

Reglas de contrato que este módulo respeta a propósito:

- **§3.2 — ningún número nace de la nada**: se entrena solo con los comparables LIMPIOS
  (los mismos que `comparables_desde_duckdb` entrega: frescos, sin amoblados, sin
  sospechosos, relistings colapsados, gemelos fuera). Y el guardia de temporada D-022 se
  aplica **por ventana de m², aviso por aviso** — igual que en `emparejar` — no por
  grupo entero: a nivel de grupo la contaminación se diluía con los m² no contaminados
  del mismo grupo (verificador H4), que es exactamente la dilución que D-022 H6 prohibió.
- **ND antes que extrapolar**: no se predice una microzona o tipología nunca vista, ni
  una con menos de `MIN_SOPORTE` observaciones (verificador H1: "estructura" sostenida
  por 1-7 avisos es comparables insuficientes disfrazados — el mismo umbral 8 del §7.3),
  ni pares en componentes desconectadas del grafo bipartito de entrenamiento, donde las
  aristas exigen celdas con n≥2 (verificador H6: un puente de UN aviso conecta dos
  mercados que no se miden entre sí). Un ajuste de dos vías que no converge es ND, no
  un número a medio cocinar.
- **El modelo JAMÁS alimenta el ranking** (§12): sus salidas son evidencia `E`
  (supuesto de modelo con parámetros declarados en `config/params.yml`), viven en una
  sección aparte del informe rotulada como tal, y esa sección solo se publica si el
  backtest leave-one-cell-out PASA sobre la base del día (gate en tiempo de ejecución,
  no una promesa). El backtest incluye la variante `mz_minima` —la microzona adelgazada
  al soporte mínimo— para que el examen cubra a la población rala que la sección
  publica, no solo a las celdas cómodas (verificador H2).

Puro: sin I/O, sin reloj, sin aleatoriedad. La aritmética interna es float (regresión en
espacio log, no un monto); los montos de salida vuelven como Decimal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from flujocero.agg.arriendo import MIN_COMPARABLES, Comparable, etiqueta_rango

D = Decimal

# Mínimos ESTRUCTURALES (sin dimensión de mercado — misma regla que DESCENTRADO_MAX:
# viven en el código, no en params.yml). Bajo esto, β y los efectos son ruido con
# forma de coeficiente y el modelo entero es ND.
MIN_OBS_ENTRENAMIENTO = 100
MIN_CELDAS_ENTRENAMIENTO = 12
# soporte mínimo para PREDECIR una microzona o tipología: el mismo 8 del §7.3 — un
# "efecto" sostenido por menos avisos que una celda rankeable no es estructura
MIN_SOPORTE = MIN_COMPARABLES
# observaciones demeaned mínimas para que una tipología use SU β y no el global
MIN_OBS_ELASTICIDAD_TIP = 30
# ventana D-022 del numerador de temporada: la misma ±20% (mín ±3) del emparejamiento
_VENTANA_TEMPORADA = D("0.20")
_VENTANA_TEMPORADA_MIN = D(3)
# Convergencia del ajuste de dos vías por medias alternadas. Determinista; si no
# converge, el modelo es ND (verificador H6: salir del bucle sin señal entregaba
# efectos a medio cocinar cuando dos componentes se unían por un puente débil).
_ITER_MAX = 500
_TOL = 1e-9


@dataclass(frozen=True)
class Prediccion:
    """Un arriendo MODELADO, con su intervalo empírico y cuánto dato real lo sostiene."""

    arriendo_uf: Decimal  # mediana modelada
    p25_uf: Decimal  # exp(ŷ + q25 de los residuos de entrenamiento)
    p75_uf: Decimal
    n_grupo: int  # avisos reales del grupo (mz, tip), en TODO el rango de m²
    n_microzona: int  # observaciones que sostienen el efecto de SU microzona
    n_tipologia: int


@dataclass
class ModeloHedonico:
    """El modelo entrenado. Solo estado: predecir() es quien lo usa."""

    beta: float  # elasticidad global (respaldo)
    beta_tipologia: dict[str, float]  # la propia, donde hay variación suficiente
    mu: float
    efecto_tipologia: dict[str, float]  # ya ENCOGIDOS por n/(n+k)
    efecto_microzona: dict[str, float]
    ajuste_celda: dict[tuple[str, str], float]
    n_celda: dict[tuple[str, str], int]
    n_tipologia: dict[str, int]
    n_microzona: dict[str, int]
    # cuantiles EMPÍRICOS de los residuos del modelo aditivo encogido (sin el ajuste de
    # celda): el piso del intervalo para una celda rala. El informe lo ensancha con los
    # errores fuera de muestra del backtest del día.
    q25: float
    q75: float
    n_obs: int
    n_celdas: int
    obs_temporada_excluidas: int
    iteraciones: int
    # componente conexa de cada nodo del grafo bipartito microzona↔tipología; las
    # aristas son celdas con n>=2 (un puente de un aviso no une mercados)
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
    """`(mz, tip, log m², log arriendo)` entrenables + avisos excluidos por temporada.

    Mismos filtros de población que el emparejamiento: fuera de los rangos del §12
    (>140 m²) no se entrena. Y el guardia D-022 se evalúa POR VENTANA de m² (±20%,
    mín ±3, la misma del núcleo del emparejamiento), aviso por aviso: un comparable
    cuyo vecindario de tamaño está contaminado por amoblados queda fuera, aunque el
    resto de su grupo esté limpio. A nivel de grupo la contaminación se diluía
    (verificador H4) y el efecto de microzona entrenaba envenenado.
    """
    por_grupo: dict[tuple[str, str], list[Decimal]] = {}
    for c in comparables:
        if c.arriendo_uf <= 0 or c.m2_utiles <= 0:
            continue
        if etiqueta_rango(c.m2_utiles, rangos) is None:
            continue
        por_grupo.setdefault((c.microzona_id, c.tipologia), []).append(c.m2_utiles)

    excluidos = 0
    obs: list[tuple[str, str, float, float]] = []
    for c in sorted(
        (c for c in comparables if (c.microzona_id, c.tipologia) in por_grupo),
        key=lambda c: (c.microzona_id, c.tipologia, c.m2_utiles, c.arriendo_uf),
    ):
        if c.arriendo_uf <= 0 or c.m2_utiles <= 0:
            continue
        if etiqueta_rango(c.m2_utiles, rangos) is None:
            continue
        clave = (c.microzona_id, c.tipologia)
        if amoblados is not None and tope_temporada is not None:
            ventana = max(_VENTANA_TEMPORADA_MIN, c.m2_utiles * _VENTANA_TEMPORADA)
            n_amo = sum(1 for ma in amoblados.get(clave, []) if abs(ma - c.m2_utiles) <= ventana)
            if n_amo >= 2:
                pool = sum(1 for m2v in por_grupo[clave] if abs(m2v - c.m2_utiles) <= ventana)
                if D(n_amo) / (n_amo + pool) >= tope_temporada:
                    excluidos += 1
                    continue
        obs.append(
            (
                c.microzona_id,
                c.tipologia,
                math.log(float(c.m2_utiles)),
                math.log(float(c.arriendo_uf)),
            )
        )
    return obs, excluidos


def _componentes(
    celdas: list[tuple[str, str]], n_celda: dict[tuple[str, str], float]
) -> dict[str, int]:
    """Componentes conexas del grafo bipartito `mz:` ↔ `tip:` (union-find chico).

    Solo las celdas con n>=2 son aristas: un grupo de UN aviso no une dos mercados
    (verificador H6 — el puente débil transfería el ruido de ese aviso entre
    componentes enteras). Los nodos de celdas n=1 existen igual, pero pueden quedar
    en su propia componente, donde `predecir` los tratará con la regla de siempre.
    """
    padre: dict[str, str] = {}

    def raiz(a: str) -> str:
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    for mz, tip in celdas:
        for nodo in (f"mz:{mz}", f"tip:{tip}"):
            padre.setdefault(nodo, nodo)
        if n_celda.get((mz, tip), 0) < 2:
            continue
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

    `k_encogimiento` es el `E` `modelo_arriendo.encogimiento_celda_k` de params.yml y
    encoge TRES cosas por `n/(n+k)`: el efecto de cada microzona, el de cada tipología
    y el ajuste propio de cada celda. Con k=8, un efecto sostenido por n=8 avisos (el
    umbral del §7.3) pesa exactamente la mitad.
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
    # Global como respaldo, y POR TIPOLOGÍA donde la tipología junta variación propia
    # suficiente — un β único se sesga hacia la elasticidad de los chicos (más varianza
    # en log) e infla a las unidades chicas de las tipologías grandes (verificador H2).
    celdas = sorted(stats)
    tips = sorted({tip for _, tip in celdas})
    sxx_tip = dict.fromkeys(tips, 0.0)
    sxy_tip = dict.fromkeys(tips, 0.0)
    n_dem_tip = dict.fromkeys(tips, 0)
    for (mz, tip), (n, sx, sy, sxx_c, sxy_c) in stats.items():
        if n >= 2:
            sxx_tip[tip] += sxx_c - sx * sx / n
            sxy_tip[tip] += sxy_c - sx * sy / n
            n_dem_tip[tip] += int(n)
    sxx = sum(sxx_tip.values())
    sxy = sum(sxy_tip.values())
    if sxx <= 1e-9:
        # sin variación de tamaño dentro de las celdas no hay elasticidad estimable
        return None
    beta = sxy / sxx
    beta_tip = {
        tp: (
            sxy_tip[tp] / sxx_tip[tp]
            if n_dem_tip[tp] >= MIN_OBS_ELASTICIDAD_TIP and sxx_tip[tp] > 1e-9
            else beta
        )
        for tp in tips
    }

    # Ajuste aditivo de dos vías sobre las medias por celda, ponderado por n.
    # r̄_celda = media de (y − β_tip·x) en la celda; se busca μ + t_tip + z_mz.
    media_r = {
        (mz, tip): (stats[(mz, tip)][2] - beta_tip[tip] * stats[(mz, tip)][1]) / stats[(mz, tip)][0]
        for mz, tip in celdas
    }
    n_c = {c: stats[c][0] for c in celdas}
    total = sum(n_c.values())
    mu = sum(media_r[c] * n_c[c] for c in celdas) / total
    mzs = sorted({mz for mz, _ in celdas})
    t = dict.fromkeys(tips, 0.0)
    z = dict.fromkeys(mzs, 0.0)
    por_tip = {tp: [c for c in celdas if c[1] == tp] for tp in tips}
    por_mz = {m: [c for c in celdas if c[0] == m] for m in mzs}
    convergio = False
    iteraciones = 0
    for iteraciones in range(1, _ITER_MAX + 1):
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
            convergio = True
            break
    if not convergio:
        # ND antes que un número a medio cocinar (verificador H6): si las medias
        # alternadas no se asientan, los efectos dependen de dónde se cortó el bucle.
        return None

    # ENCOGIMIENTO de los efectos (verificador H1): un z_mz estimado con pocos avisos
    # se arrastra hacia 0 (el mercado promedio). Sin esto, una microzona de una sola
    # celda absorbía entero el residuo de esa celda y el k no actuaba jamás.
    n_tip = {tp: int(sum(n_c[c] for c in por_tip[tp])) for tp in tips}
    n_mz = {m: int(sum(n_c[c] for c in por_mz[m])) for m in mzs}
    t = {tp: v * (n_tip[tp] / (n_tip[tp] + k_encogimiento)) for tp, v in t.items()}
    z = {m: v * (n_mz[m] / (n_mz[m] + k_encogimiento)) for m, v in z.items()}

    # Residuos del modelo aditivo ENCOGIDO (sin ajuste de celda): el piso del intervalo
    # para una celda rala. Y el ajuste encogido de cada celda observada, para las densas.
    residuos: list[float] = []
    suma_e: dict[tuple[str, str], float] = dict.fromkeys(celdas, 0.0)
    for mz, tip, x, y in obs:
        e = y - beta_tip[tip] * x - mu - t[tip] - z[mz]
        residuos.append(e)
        suma_e[(mz, tip)] += e
    ajuste = {c: (n_c[c] / (n_c[c] + k_encogimiento)) * (suma_e[c] / n_c[c]) for c in celdas}

    return ModeloHedonico(
        beta=beta,
        beta_tipologia=beta_tip,
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
        obs_temporada_excluidas=excluidos,
        iteraciones=iteraciones,
        componente=_componentes(celdas, n_c),
    )


def predecir(modelo: ModeloHedonico, mz: str, tip: str, m2: Decimal) -> Prediccion | None:
    """La mediana modelada para `(mz, tip, m2)`, o `None` cuando sería inventar.

    `None` si la microzona o la tipología no se vieron en el entrenamiento, si alguna
    tiene menos de `MIN_SOPORTE` observaciones (un "efecto" sostenido por menos avisos
    que una celda rankeable del §7.3 es comparables insuficientes disfrazados —
    verificador H1), o si cayeron en componentes desconectadas (sus efectos no son
    comparables entre sí). ND antes que extrapolar (§3.2).
    """
    if m2 <= 0 or tip not in modelo.efecto_tipologia or mz not in modelo.efecto_microzona:
        return None
    if modelo.n_microzona.get(mz, 0) < MIN_SOPORTE or modelo.n_tipologia.get(tip, 0) < MIN_SOPORTE:
        return None
    if modelo.componente.get(f"mz:{mz}") != modelo.componente.get(f"tip:{tip}"):
        return None
    y = (
        modelo.mu
        + modelo.beta_tipologia.get(tip, modelo.beta) * math.log(float(m2))
        + modelo.efecto_tipologia[tip]
        + modelo.efecto_microzona[mz]
        + modelo.ajuste_celda.get((mz, tip), 0.0)
    )
    return Prediccion(
        arriendo_uf=D(str(round(math.exp(y), 4))),
        p25_uf=D(str(round(math.exp(y + modelo.q25), 4))),
        p75_uf=D(str(round(math.exp(y + modelo.q75), 4))),
        n_grupo=modelo.n_celda.get((mz, tip), 0),
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
    # "loco" = celda retenida; "mz_minima" = además la microzona adelgazada al soporte
    # mínimo — el examen de la población RALA que la sección 6 publica (verificador H2)
    variante: str = "loco"

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
    no_predecibles: int = 0  # celdas densas que, sin sí mismas, quedan sin soporte
    sin_modelo: int = 0  # reentrenos que no juntaron el mínimo estructural
    celdas_densas: int = 0

    @property
    def error_abs_mediano(self) -> float:
        return _percentil_f([abs(e.error) for e in self.errores], 0.5)

    @property
    def error_abs_p75(self) -> float:
        return _percentil_f([abs(e.error) for e in self.errores], 0.75)

    def cuantiles_error(self, p25: float = 0.25, p75: float = 0.75) -> tuple[float, float]:
        """Cuantiles del error CON SIGNO: el insumo fuera de muestra del intervalo."""
        firmados = [e.error for e in self.errores]
        return _percentil_f(firmados, p25), _percentil_f(firmados, p75)

    def por_grupo(self, llave: str) -> dict[str, tuple[int, float]]:
        """`comuna`, `tipologia` o `variante` → (n celdas, mediana de |error|)."""
        grupos: dict[str, list[float]] = {}
        for e in self.errores:
            grupos.setdefault(getattr(e, llave), []).append(abs(e.error))
        return {g: (len(v), _percentil_f(v, 0.5)) for g, v in sorted(grupos.items())}

    def pasa(self, error_mediano_max: float, error_p75_max: float, min_celdas: int) -> bool:
        """El gate: con pocas celdas evaluadas NO pasa — un backtest chico no prueba nada.

        Los errores de TODAS las variantes cuentan juntos: la sección publica celdas
        ralas, así que la variante `mz_minima` no es opcional para el veredicto.
        """
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
    con_mz_minima: bool = True,
) -> ResultadoBacktest:
    """Leave-one-cell-out sobre las celdas densas (n≥`min_celda`, las que el ranking usa).

    Para cada celda densa, DOS exámenes:
    - `loco`: se reentrena sin ninguno de sus comparables y se predice la mediana de la
      celda en su m² mediano — el error que el modelo cometería en una celda rala cuya
      verdad no vemos, con la microzona bien poblada.
    - `mz_minima` (verificador H2): además se adelgaza la microzona de la celda a sus
      `MIN_SOPORTE` observaciones restantes (elegidas determinísticamente) — el examen
      de la microzona APENAS predecible, que es la población rala real de la sección 6.

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

    def _elegible(c: Comparable) -> bool:
        return (
            c.arriendo_uf > 0
            and c.m2_utiles > 0
            and etiqueta_rango(c.m2_utiles, rangos) is not None
        )

    r = ResultadoBacktest(celdas_densas=len(densas))
    for celda in densas:
        mz, tip = celda
        propios = [c for c in por_celda[celda] if _elegible(c)]
        m2_med = _percentil_f([float(c.m2_utiles) for c in propios], 0.5)
        real = _percentil_f([float(c.arriendo_uf) for c in propios], 0.5)
        if real <= 0:
            r.no_predecibles += 1
            continue

        variantes: list[tuple[str, list[Comparable]]] = []
        resto = [c for c in comparables if (c.microzona_id, c.tipologia) != celda]
        variantes.append(("loco", resto))
        if con_mz_minima:
            # la misma microzona, adelgazada a MIN_SOPORTE obs elegibles (deterministas)
            de_la_mz = sorted(
                (c for c in resto if c.microzona_id == mz and _elegible(c)),
                key=lambda c: (c.tipologia, c.m2_utiles, c.arriendo_uf),
            )
            if len(de_la_mz) > MIN_SOPORTE:
                quedan = set(id(c) for c in de_la_mz[:MIN_SOPORTE])
                variantes.append(
                    (
                        "mz_minima",
                        [c for c in resto if c.microzona_id != mz or id(c) in quedan],
                    )
                )

        for nombre, pool in variantes:
            modelo = entrenar(pool, rangos, amoblados, tope_temporada, k_encogimiento)
            if modelo is None:
                r.sin_modelo += 1
                continue
            pred = predecir(modelo, mz, tip, D(str(m2_med)))
            if pred is None:
                r.no_predecibles += 1
                continue
            r.errores.append(
                ErrorCelda(
                    microzona_id=mz,
                    tipologia=tip,
                    n=len(propios),
                    mediana_real_uf=real,
                    mediana_modelo_uf=float(pred.arriendo_uf),
                    variante=nombre,
                )
            )
    return r
