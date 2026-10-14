"""El modelo hedónico de arriendo — T-958.

Los tests corren sobre un mercado SINTÉTICO con estructura conocida (β, efectos de
tipología y microzona elegidos a mano, ruido determinista): la única forma de afirmar
que el modelo *recupera* algo es saber qué había que recuperar.
"""

from __future__ import annotations

import math
from decimal import Decimal as D

from flujocero.agg import modelo_arriendo as ma
from flujocero.agg.arriendo import Comparable

RANGOS = [[0, 35], [35, 50], [50, 70], [70, 100], [100, 140]]

# el mercado verdadero: arriendo = exp(MU + BETA·ln(m²) + t_tip + z_mz + ruido)
MU = -0.2
BETA = 0.6
TIPS = {"1D1B": -0.10, "2D1B": 0.0, "2D2B": 0.05, "3D2B": 0.12}
MZS = {
    "a/uno": -0.15,
    "b/dos": -0.05,
    "c/tres": 0.0,
    "d/cuatro": 0.06,
    "e/cinco": 0.10,
    "f/seis": 0.20,
}
M2_TIPICO = {"1D1B": 30, "2D1B": 45, "2D2B": 58, "3D2B": 80}
# ruido determinista, simétrico y chico: el ciclo promedia 0
_RUIDO = (0.04, -0.04, 0.02, -0.02, 0.0)


def _arriendo(mz: str, tip: str, m2: float, i: int) -> D:
    y = MU + BETA * math.log(m2) + TIPS[tip] + MZS[mz] + _RUIDO[i % len(_RUIDO)]
    return D(str(round(math.exp(y), 6)))


def _mercado(n_por_celda: int = 10, saltar: set[tuple[str, str]] | None = None):
    comps = []
    for mz in MZS:
        for tip in TIPS:
            if saltar and (mz, tip) in saltar:
                continue
            base = M2_TIPICO[tip]
            for i in range(n_por_celda):
                m2 = base + (i - n_por_celda / 2) * 1.5  # variación DENTRO de la celda
                comps.append(
                    Comparable(
                        microzona_id=mz,
                        tipologia=tip,
                        m2_utiles=D(str(m2)),
                        arriendo_uf=_arriendo(mz, tip, m2, i),
                    )
                )
    return comps


def test_recupera_la_elasticidad_y_predice_una_celda_observada() -> None:
    modelo = ma.entrenar(_mercado(), RANGOS)
    assert modelo is not None
    assert abs(modelo.beta - BETA) < 0.05
    pred = ma.predecir(modelo, "c/tres", "2D2B", D(58))
    assert pred is not None
    verdad = math.exp(MU + BETA * math.log(58) + TIPS["2D2B"] + MZS["c/tres"])
    assert abs(float(pred.arriendo_uf) / verdad - 1) < 0.03
    assert pred.n_celda == 10


def test_predice_una_celda_NUNCA_VISTA_desde_la_estructura() -> None:
    """El corazón de T-958: (f/seis, 1D1B) no existe en el entrenamiento; el efecto de
    f/seis sale de sus otras tipologías y el de 1D1B de las otras microzonas."""
    modelo = ma.entrenar(_mercado(saltar={("f/seis", "1D1B")}), RANGOS)
    assert modelo is not None
    pred = ma.predecir(modelo, "f/seis", "1D1B", D(30))
    assert pred is not None
    assert pred.n_celda == 0  # extrapolación pura, y lo dice
    verdad = math.exp(MU + BETA * math.log(30) + TIPS["1D1B"] + MZS["f/seis"])
    assert abs(float(pred.arriendo_uf) / verdad - 1) < 0.05


def test_ND_antes_que_extrapolar_lo_nunca_visto() -> None:
    modelo = ma.entrenar(_mercado(), RANGOS)
    assert modelo is not None
    assert ma.predecir(modelo, "zz/nunca-vista", "2D2B", D(58)) is None
    assert ma.predecir(modelo, "c/tres", "9D9B", D(58)) is None
    assert ma.predecir(modelo, "c/tres", "2D2B", D(0)) is None


def test_componentes_desconectadas_no_se_cruzan() -> None:
    """Una microzona-isla cuya única tipología no aparece en ninguna otra microzona:
    sus efectos no son comparables con el resto y cruzarlos sería inventar."""
    comps = _mercado()
    for i in range(10):
        m2 = 100 + i
        comps.append(
            Comparable(
                microzona_id="isla/sola",
                tipologia="LOFT",
                m2_utiles=D(str(m2)),
                arriendo_uf=D(str(round(math.exp(0.5 + 0.6 * math.log(m2)), 6))),
            )
        )
    modelo = ma.entrenar(comps, RANGOS)
    assert modelo is not None
    # dentro de la isla se puede; cruzando la frontera, ND
    assert ma.predecir(modelo, "isla/sola", "LOFT", D(105)) is not None
    assert ma.predecir(modelo, "isla/sola", "2D2B", D(58)) is None
    assert ma.predecir(modelo, "c/tres", "LOFT", D(105)) is None


def test_un_grupo_de_temporada_queda_fuera_del_entrenamiento() -> None:
    """D-022 a nivel de grupo: una (mz, tip) contaminada entrenaría un efecto de
    microzona envenenado que luego se propaga a toda predicción de esa zona."""
    comps = _mercado()
    amoblados = {("a/uno", "1D1B"): [D(30), D(31), D(32), D(33), D(34)]}
    modelo = ma.entrenar(comps, RANGOS, amoblados, tope_temporada=D("0.30"))
    assert modelo is not None
    assert modelo.grupos_temporada_excluidos == 1
    assert ("a/uno", "1D1B") not in modelo.n_celda
    # la microzona sigue estimable desde sus OTRAS tipologías
    assert ma.predecir(modelo, "a/uno", "1D1B", D(30)) is not None


def test_bajo_el_minimo_estructural_el_modelo_es_ND() -> None:
    assert ma.entrenar(_mercado(n_por_celda=2), RANGOS) is None  # 48 obs < 100


def test_sobre_140_m2_no_entrena() -> None:
    comps = _mercado()
    gigantes = [
        Comparable("c/tres", "3D2B", D(150), D(60)),
        Comparable("c/tres", "3D2B", D(180), D(70)),
    ]
    modelo = ma.entrenar(comps + gigantes, RANGOS)
    assert modelo is not None
    assert modelo.n_obs == len(comps)


def test_el_intervalo_envuelve_al_central_y_refleja_el_ruido() -> None:
    modelo = ma.entrenar(_mercado(), RANGOS)
    assert modelo is not None
    pred = ma.predecir(modelo, "b/dos", "2D1B", D(45))
    assert pred is not None
    assert pred.p25_uf < pred.arriendo_uf < pred.p75_uf
    # ruido de ±4%: el intervalo empírico tiene que vivir en ese orden de magnitud
    assert (
        0.99 < float(pred.p25_uf / pred.arriendo_uf) * 1.06
        and float(pred.p75_uf / pred.arriendo_uf) < 1.06
    )


def test_determinista_mismo_input_mismo_modelo() -> None:
    m1 = ma.entrenar(_mercado(), RANGOS)
    m2 = ma.entrenar(_mercado(), RANGOS)
    assert m1 is not None and m2 is not None
    assert m1.beta == m2.beta and m1.mu == m2.mu
    assert m1.efecto_microzona == m2.efecto_microzona
    assert m1.ajuste_celda == m2.ajuste_celda


def test_el_encogimiento_arrastra_hacia_la_celda_cuando_hay_dato_propio() -> None:
    """Una celda que renta +20% sobre lo que su estructura predice: con n=10 y k=8 la
    predicción queda ENTRE el modelo aditivo y la mediana propia — ni ignora el dato
    propio ni se lo cree entero. Con k enorme, vuelve casi al aditivo."""
    comps = _mercado(saltar={("d/cuatro", "2D2B")})
    premium = 0.20
    for i in range(10):
        m2 = 58 + (i - 5) * 1.5
        y = MU + BETA * math.log(m2) + TIPS["2D2B"] + MZS["d/cuatro"] + premium
        comps.append(Comparable("d/cuatro", "2D2B", D(str(m2)), D(str(round(math.exp(y), 6)))))
    aditivo = math.exp(MU + BETA * math.log(58) + TIPS["2D2B"] + MZS["d/cuatro"])
    propio = aditivo * math.exp(premium)

    con_k8 = ma.entrenar(comps, RANGOS, k_encogimiento=8.0)
    con_k = ma.entrenar(comps, RANGOS, k_encogimiento=10_000.0)
    assert con_k8 is not None and con_k is not None
    p8 = float(ma.predecir(con_k8, "d/cuatro", "2D2B", D(58)).arriendo_uf)
    pk = float(ma.predecir(con_k, "d/cuatro", "2D2B", D(58)).arriendo_uf)
    # el premium propio es parte del ajuste: la celda contamina un poco los efectos
    # globales, así que la cota es holgada pero el ORDEN es estricto
    assert aditivo * 1.02 < p8 < propio
    assert pk < p8  # más k = menos celda propia, más estructura


# ------------------------------------------------------------- backtest leave-one-cell-out


def test_backtest_en_mercado_regular_el_error_es_chico() -> None:
    bt = ma.backtest_loco(_mercado(), RANGOS)
    assert bt.celdas_densas == 24
    assert len(bt.errores) == 24
    assert bt.error_abs_mediano < 0.03
    assert bt.pasa(0.10, 0.15, min_celdas=20)
    # y el agrupador funciona: 6 comunas, 4 tipologías
    assert len(bt.por_grupo("comuna")) == 6
    assert len(bt.por_grupo("tipologia")) == 4


def test_backtest_no_esconde_una_celda_que_rompe_la_estructura() -> None:
    """Una celda al DOBLE de lo que su estructura predice: el leave-one-cell-out tiene
    que mostrar ese error, no absorberlo — es exactamente el caso donde el modelo
    mentiría en una celda rala."""
    comps = _mercado(saltar={("e/cinco", "3D2B")})
    for i in range(10):
        m2 = 80 + (i - 5) * 1.5
        y = MU + BETA * math.log(m2) + TIPS["3D2B"] + MZS["e/cinco"] + math.log(2)
        comps.append(Comparable("e/cinco", "3D2B", D(str(m2)), D(str(round(math.exp(y), 6)))))
    bt = ma.backtest_loco(comps, RANGOS)
    rota = [e for e in bt.errores if e.microzona_id == "e/cinco" and e.tipologia == "3D2B"]
    assert len(rota) == 1
    assert rota[0].error < -0.30  # el modelo queda MUY por debajo de la celda inflada


def test_el_gate_exige_un_minimo_de_celdas() -> None:
    bt = ma.backtest_loco(_mercado(), RANGOS)
    assert not bt.pasa(0.10, 0.15, min_celdas=40)  # 24 celdas < 40: no prueba nada


def test_defaults_del_codigo_calzan_con_params_yml() -> None:
    from flujocero.config import cargar

    p = cargar("params")
    # los E declarados existen y con rango (§3.2); el k por defecto del código no
    # gobierna el informe — el informe SIEMPRE pasa el de params
    assert p.d("modelo_arriendo.encogimiento_celda_k") == D(8)
    assert D("0") < p.d("modelo_arriendo.error_mediano_max") < p.d("modelo_arriendo.error_p75_max")
    assert p.d("modelo_arriendo.min_celdas_backtest") >= 20
