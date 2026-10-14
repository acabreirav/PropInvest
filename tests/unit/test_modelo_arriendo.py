"""El modelo hedónico de arriendo — T-958.

Los tests corren sobre un mercado SINTÉTICO con estructura conocida (β, efectos de
tipología y microzona elegidos a mano, ruido determinista): la única forma de afirmar
que el modelo *recupera* algo es saber qué había que recuperar.

Las tolerancias no son 0 a propósito: el encogimiento `n/(n+k)` (verificador T-958 H1)
arrastra los efectos hacia el mercado promedio, así que con n chico el modelo queda
DELIBERADAMENTE entre la estructura verdadera y la media — conservador por diseño.
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
    # todas las tipologías comparten el β verdadero: las propias deben parecerse
    for tp, b in modelo.beta_tipologia.items():
        assert abs(b - BETA) < 0.08, tp
    pred = ma.predecir(modelo, "c/tres", "2D2B", D(58))
    assert pred is not None
    verdad = math.exp(MU + BETA * math.log(58) + TIPS["2D2B"] + MZS["c/tres"])
    assert abs(float(pred.arriendo_uf) / verdad - 1) < 0.03
    assert pred.n_grupo == 10


def test_predice_una_celda_NUNCA_VISTA_desde_la_estructura() -> None:
    """El corazón de T-958: (f/seis, 1D1B) no existe en el entrenamiento; el efecto de
    f/seis sale de sus otras tipologías y el de 1D1B de las otras microzonas. La
    desviación tolerada incluye el sesgo CONSERVADOR del encogimiento (con n_mz=30,
    ~21% del efecto verdadero se arrastra hacia el mercado promedio)."""
    modelo = ma.entrenar(_mercado(saltar={("f/seis", "1D1B")}), RANGOS)
    assert modelo is not None
    pred = ma.predecir(modelo, "f/seis", "1D1B", D(30))
    assert pred is not None
    assert pred.n_grupo == 0  # extrapolación pura, y lo dice
    verdad = math.exp(MU + BETA * math.log(30) + TIPS["1D1B"] + MZS["f/seis"])
    assert abs(float(pred.arriendo_uf) / verdad - 1) < 0.07
    # y el error va hacia ABAJO (f/seis es la mz cara: encoger subestima, no infla)
    assert float(pred.arriendo_uf) < verdad


def test_ND_antes_que_extrapolar_lo_nunca_visto() -> None:
    modelo = ma.entrenar(_mercado(), RANGOS)
    assert modelo is not None
    assert ma.predecir(modelo, "zz/nunca-vista", "2D2B", D(58)) is None
    assert ma.predecir(modelo, "c/tres", "9D9B", D(58)) is None
    assert ma.predecir(modelo, "c/tres", "2D2B", D(0)) is None


def test_ND_con_soporte_bajo_el_umbral_del_7_3() -> None:
    """Verificador H1: una microzona sostenida por menos avisos que una celda rankeable
    (n<8, §7.3) no tiene "estructura" — tiene comparables insuficientes disfrazados.
    Antes, UN aviso un 30% caro fijaba el arriendo de toda su microzona."""
    comps = _mercado()
    # una microzona con UN solo aviso, 30% sobre su valor verdadero
    comps.append(Comparable("x/rala", "2D1B", D(45), _arriendo("c/tres", "2D1B", 45, 0) * D("1.3")))
    modelo = ma.entrenar(comps, RANGOS)
    assert modelo is not None
    for tip in TIPS:
        assert ma.predecir(modelo, "x/rala", tip, D(45)) is None
    # y con 7 avisos (uno bajo el umbral) sigue siendo ND
    comps7 = _mercado()
    for i in range(7):
        comps7.append(
            Comparable("x/rala", "2D1B", D(str(44 + i)), _arriendo("c/tres", "2D1B", 44 + i, i))
        )
    modelo7 = ma.entrenar(comps7, RANGOS)
    assert modelo7 is not None
    assert ma.predecir(modelo7, "x/rala", "2D1B", D(45)) is None


def test_el_encogimiento_amortigua_a_la_microzona_apenas_predecible() -> None:
    """Verificador H1, la otra mitad: con n_mz=8 (apenas sobre el umbral) y avisos un
    30% caros, el efecto encogido absorbe la MITAD del sesgo, no entero."""
    comps = _mercado()
    for i in range(8):
        comps.append(
            Comparable(
                "x/rala", "2D1B", D(str(44 + i)), _arriendo("c/tres", "2D1B", 44 + i, i) * D("1.3")
            )
        )
    modelo = ma.entrenar(comps, RANGOS, k_encogimiento=8.0)
    assert modelo is not None
    pred = ma.predecir(modelo, "x/rala", "1D1B", D(30))  # OTRA tipología: usa solo z_mz
    assert pred is not None
    verdad_limpia = math.exp(MU + BETA * math.log(30) + TIPS["1D1B"] + MZS["c/tres"])
    exceso = float(pred.arriendo_uf) / verdad_limpia - 1
    # sin encogimiento el exceso sería ~30%; con n/(n+k)=0.5 queda cerca de la mitad
    assert 0.05 < exceso < 0.20


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


def test_un_puente_de_un_aviso_no_une_dos_mercados() -> None:
    """Verificador H6: una celda de n=1 no es una arista del grafo — el ruido de ese
    único aviso se transferiría entre componentes enteras."""
    comps = _mercado()
    # la isla: 10 LOFT + UN aviso 2D2B que la "conectaría" con el resto
    for i in range(10):
        m2 = 100 + i
        comps.append(
            Comparable(
                "isla/sola",
                "LOFT",
                D(str(m2)),
                D(str(round(math.exp(0.5 + 0.6 * math.log(m2)), 6))),
            )
        )
    comps.append(Comparable("isla/sola", "2D2B", D(58), D("20")))
    modelo = ma.entrenar(comps, RANGOS)
    assert modelo is not None
    # sigue desconectada: el puente de un aviso no cuenta
    assert ma.predecir(modelo, "isla/sola", "1D1B", D(30)) is None
    assert ma.predecir(modelo, "c/tres", "LOFT", D(105)) is None


def test_la_temporada_se_excluye_POR_VENTANA_no_por_grupo() -> None:
    """Verificador H4: a nivel de grupo, los m² limpios del mismo grupo diluían la
    contaminación (la misma dilución que D-022 H6 prohibió). El guardia corre por
    ventana de m², aviso por aviso: caen los del segmento contaminado, quedan los
    del segmento limpio del MISMO grupo."""
    comps = _mercado()
    # en a/uno 1D1B (m² 22.5-36): 8 gemelos sin marca de 29-32.5 m², 50% caros, y 12
    # amoblados marcados de ~30 m² — el segmento de 30 m² está tomado por la temporada
    for i in range(8):
        comps.append(
            Comparable(
                "a/uno", "1D1B", D(str(29 + i * 0.5)), _arriendo("a/uno", "1D1B", 29, i) * D("1.5")
            )
        )
    amoblados = {("a/uno", "1D1B"): [D(str(29 + i * 0.2)) for i in range(12)]}
    con_guardia = ma.entrenar(comps, RANGOS, amoblados, tope_temporada=D("0.30"))
    sin_guardia = ma.entrenar(comps, RANGOS)
    assert con_guardia is not None and sin_guardia is not None
    # el guardia excluyó avisos (los del segmento de ~30 m², gemelos incluidos)
    assert con_guardia.obs_temporada_excluidas > 0
    assert con_guardia.n_obs < sin_guardia.n_obs
    # y el efecto de la microzona NO queda envenenado: la predicción de OTRA tipología
    # de a/uno con guardia queda más cerca de la verdad que sin él
    verdad = math.exp(MU + BETA * math.log(45) + TIPS["2D1B"] + MZS["a/uno"])
    con_g = float(ma.predecir(con_guardia, "a/uno", "2D1B", D(45)).arriendo_uf)
    sin_g = float(ma.predecir(sin_guardia, "a/uno", "2D1B", D(45)).arriendo_uf)
    assert abs(con_g / verdad - 1) < abs(sin_g / verdad - 1)


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
    assert float(pred.p75_uf / pred.arriendo_uf) < 1.08


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
    propio ni se lo cree entero. Con k enorme, todo efecto se encoge y la predicción
    cae hacia el mercado promedio (más conservadora aún)."""
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
    assert aditivo < p8 < propio
    assert pk < p8  # más k = menos dato propio y efectos más encogidos


def test_beta_por_tipologia_no_infla_al_3D_chico() -> None:
    """Verificador H2 (repro3): con elasticidades DISTINTAS por tipología, un β único
    se sesga hacia la de los chicos (más varianza en log) e infla al 3D2B de 60 m² en
    una microzona cuyos 3D rondan los 80. El β por tipología lo corrige."""
    comps = []
    betas = {"1D1B": 0.2, "3D2B": 0.9}
    for mz, z in MZS.items():
        for tip, b in betas.items():
            base = M2_TIPICO[tip]
            for i in range(10):
                m2 = base + (i - 5) * (3.0 if tip == "3D2B" else 1.5)
                y = MU + b * math.log(m2) + TIPS[tip] + z + _RUIDO[i % 5]
                comps.append(Comparable(mz, tip, D(str(m2)), D(str(round(math.exp(y), 6)))))
    modelo = ma.entrenar(comps, RANGOS)
    assert modelo is not None
    assert abs(modelo.beta_tipologia["3D2B"] - 0.9) < 0.1
    assert abs(modelo.beta_tipologia["1D1B"] - 0.2) < 0.1
    # el 3D2B de 60 m² (lejos del típico 80) ya no hereda la elasticidad de los chicos
    pred = ma.predecir(modelo, "c/tres", "3D2B", D(60))
    assert pred is not None
    verdad = math.exp(MU + 0.9 * math.log(60) + TIPS["3D2B"] + MZS["c/tres"])
    assert abs(float(pred.arriendo_uf) / verdad - 1) < 0.06


# ------------------------------------------------------------- backtest leave-one-cell-out


def test_backtest_en_mercado_regular_el_error_es_chico() -> None:
    bt = ma.backtest_loco(_mercado(), RANGOS)
    assert bt.celdas_densas == 24
    # cada celda rinde dos exámenes: loco + mz_minima (la microzona adelgazada a 8)
    por_variante = bt.por_grupo("variante")
    assert set(por_variante) == {"loco", "mz_minima"}
    assert por_variante["loco"][0] == 24
    assert bt.error_abs_mediano < 0.05
    assert bt.pasa(0.10, 0.15, min_celdas=20)
    # la variante rala es MENOS precisa que la cómoda, nunca al revés por construcción
    assert por_variante["mz_minima"][1] >= por_variante["loco"][1]
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
    assert rota  # al menos el examen loco
    for e in rota:
        assert e.error < -0.30  # el modelo queda MUY por debajo de la celda inflada


def test_el_encogimiento_k_SI_mueve_el_backtest() -> None:
    """Verificador H2: antes el k no tocaba el backtest (la celda retenida no tenía
    ajuste propio) y el E era inmedible. Con el encogimiento de efectos, k cambia las
    predicciones fuera de muestra — la sensibilidad declarada en params se puede medir."""
    comps = _mercado()
    e4 = {
        (e.microzona_id, e.tipologia, e.variante): e.mediana_modelo_uf
        for e in ma.backtest_loco(comps, RANGOS, k_encogimiento=4.0).errores
    }
    e16 = {
        (e.microzona_id, e.tipologia, e.variante): e.mediana_modelo_uf
        for e in ma.backtest_loco(comps, RANGOS, k_encogimiento=16.0).errores
    }
    assert any(e4[c] != e16[c] for c in e4 if c in e16)


def test_el_gate_exige_un_minimo_de_examenes() -> None:
    bt = ma.backtest_loco(_mercado(), RANGOS, con_mz_minima=False)
    assert not bt.pasa(0.10, 0.15, min_celdas=40)  # 24 exámenes < 40: no prueba nada


def test_defaults_del_codigo_calzan_con_params_yml() -> None:
    from flujocero.config import cargar

    p = cargar("params")
    # los E declarados existen y con rango (§3.2); el k por defecto del código no
    # gobierna el informe — el informe SIEMPRE pasa el de params
    assert p.d("modelo_arriendo.encogimiento_celda_k") == D(8)
    assert D("0") < p.d("modelo_arriendo.error_mediano_max") < p.d("modelo_arriendo.error_p75_max")
    assert p.d("modelo_arriendo.min_celdas_backtest") >= 20
    # y el soporte mínimo del modelo ES el umbral del §7.3, no otro número
    from flujocero.agg.arriendo import MIN_COMPARABLES

    assert ma.MIN_SOPORTE == MIN_COMPARABLES


def test_una_elasticidad_implausible_cae_al_respaldo_global() -> None:
    """Medido en la corrida real (14-oct-2026): 4D3B dio beta=1,067 con ~30 obs — una
    elasticidad >1 (el arriendo subiria MAS que proporcional) es ruido con forma de
    coeficiente. Fuera de (0, 1], la tipologia usa el beta global."""
    comps = _mercado()
    # una tipologia rara cuya variacion interna dicta beta ~1.4 (ruido/segmento raro)
    for j, mz in enumerate(MZS):
        for i in range(6):
            m2 = 90 + i * 4
            y = MU + 1.4 * math.log(m2) + 0.1 + 0.01 * j
            comps.append(Comparable(mz, "4D3B", D(str(m2)), D(str(round(math.exp(y), 6)))))
    modelo = ma.entrenar(comps, RANGOS)
    assert modelo is not None
    # junto >=30 obs demeaned, pero su beta propio es implausible: respaldo al global
    assert modelo.beta_tipologia["4D3B"] == modelo.beta
    assert 0 < modelo.beta <= 1
