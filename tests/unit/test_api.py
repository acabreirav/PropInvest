"""Tests de la API y la capa de servicio — T-027.

Corren contra una base DuckDB sintética construida acá mismo, no contra la del proyecto: un
test cuyo resultado depende de cuántos avisos se recolectaron ayer no prueba el código, prueba
los datos.

Los valores de esa base son inventados **a propósito y solo existen dentro del test**. No son
dato de mercado ni se acercan a uno: el §3.2 prohíbe que un número inventado salga de acá.
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from flujocero import db  # noqa: E402
from flujocero.api.app import cifra, crear_app, nivel_derivado  # noqa: E402
from flujocero.api.servicio import Servicio  # noqa: E402
from flujocero.sources.base import COLUMNAS_PROCEDENCIA  # noqa: E402

AHORA = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

# Cuatro unidades que emparejan y una que no, para que el conteo de descartes tenga algo que
# contar. Precios y arriendos elegidos para caer dentro de los rangos plausibles del modelo.
UNIDADES = [
    # (key, microzona, tipologia, m2, precio_uf, nueva, antiguedad)
    ("T-001", "san-miguel/gran-avenida", "1D1B", 35.0, 2400.0, False, 8),
    ("T-002", "san-miguel/gran-avenida", "1D1B", 38.0, 2600.0, False, 5),
    ("T-003", "nunoa/irarrazaval", "2D2B", 55.0, 4200.0, False, 12),
    ("T-004", "nunoa/irarrazaval", "2D2B", 58.0, 4500.0, True, 0),
    # Sin celda de arriendo: tiene que caer en `sin_comparables`, no colarse.
    ("T-005", "macul/sin-comparables", "1D1B", 40.0, 2500.0, False, 3),
]

# Las etiquetas de rango tienen que ser las que produce `etiqueta_rango` sobre los rangos de
# `params.yml`. Inventarlas deja el emparejamiento en cero y el test "pasa" sin probar nada.
CELDAS = [
    ("san-miguel/gran-avenida", "1D1B", "35-50", 9.5, 14),
    ("nunoa/irarrazaval", "2D2B", "50-70", 15.0, 11),
]


@pytest.fixture(scope="module")
def base(tmp_path_factory) -> Path:
    """Una base DuckDB con el esquema real y datos sintéticos."""
    ruta = tmp_path_factory.mktemp("api") / "prueba.duckdb"
    con = duckdb.connect(str(ruta))
    db.aplicar_esquema(con)

    for cid, nombre in (("san-miguel", "San Miguel"), ("nunoa", "Ñuñoa"), ("macul", "Macul")):
        con.execute(
            "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?,?,'Metropolitana')",
            (cid, nombre),
        )
    for mz in ("san-miguel/gran-avenida", "nunoa/irarrazaval", "macul/sin-comparables"):
        con.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES (?,?,?)",
            (mz, mz.split("/")[0], mz.split("/")[1]),
        )

    for key, mz, tip, m2, precio, nueva, ant in UNIDADES:
        con.execute(
            # `fact_unidad_venta` NO tiene comuna_id: la comuna se deriva del prefijo de la
            # microzona, que es la unidad de analisis real del §2.4.
            "INSERT INTO fact_unidad_venta (unidad_key, microzona_id, tipologia, "
            "m2_utiles, precio_uf, es_vivienda_nueva, antiguedad_anios, evidence_level, "
            "valid_from, valid_to, source_id, source_url, fetched_at, parser_version, "
            "raw_blob_path, robots_snapshot_sha) "
            "VALUES (?,?,?,?,?,?,?,'V',?,NULL,?,?,?,?,?,?)",
            (
                key,
                mz,
                tip,
                m2,
                precio,
                nueva,
                ant,
                AHORA,
                "fuente_de_prueba",
                f"https://ejemplo.cl/{key}",
                AHORA,
                "prueba/1.0.0",
                f"raw/{key}.json.gz",
                "sha-de-prueba",
            ),
        )
    for mz, tip, rango, mediana, n in CELDAS:
        con.execute(
            "INSERT INTO agg_arriendo_microzona (microzona_id, tipologia, rango_m2, "
            "arriendo_uf_mediana, n) VALUES (?,?,?,?,?)",
            (mz, tip, rango, mediana, n),
        )
    con.close()
    return ruta


@pytest.fixture(scope="module")
def cliente(base: Path) -> TestClient:
    return TestClient(crear_app(servicio=Servicio(base)))


# --------------------------------------------------------------- nivel de evidencia


@pytest.mark.parametrize(
    ("entradas", "esperado"),
    [
        (("V", "V"), "D"),
        (("V", "D"), "D"),
        (("D", "D"), "D"),
        # Un supuesto contamina el resultado por muy explicita que sea la formula.
        (("V", "E"), "E"),
        (("D", "E"), "E"),
        # Un dato ausente gana sobre todo: no se puede derivar de lo que no hay.
        (("V", "ND"), "ND"),
        (("E", "ND"), "ND"),
    ],
)
def test_el_nivel_de_un_calculo_es_el_peor_de_sus_entradas(entradas, esperado) -> None:
    """§3.2 llevado a la serialización. Redondear hacia arriba —declarar `D` un cálculo que
    usa un supuesto `E`— presentaría una estimación como si fuera un dato derivado."""
    assert nivel_derivado(*entradas) == esperado


def test_un_none_no_se_imputa() -> None:
    """§3.2: `ND` es NULL explícito. Rellenarlo con un cero sería el bug grave del contrato."""
    assert cifra(None, "V") is None


def test_los_decimales_viajan_como_texto() -> None:
    """Convertirlos a `float` metería error de coma flotante en el último paso, después de
    que el motor los cuidó con `Decimal` durante todo el cálculo (§11)."""
    c = cifra(Decimal("0.1"), "V", "UF")
    assert c["valor"] == "0.1"
    assert isinstance(c["valor"], str)


# --------------------------------------------------------------- endpoints


def test_salud_responde_sin_construir_la_foto(base: Path) -> None:
    """Tiene que contestar mientras el primer cálculo todavía corre, o no sirve de nada."""
    c = TestClient(crear_app(servicio=Servicio(base)))
    r = c.get("/api/salud")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "fotos_en_cache": 0}


def test_el_ranking_devuelve_las_unidades_que_emparejan(cliente: TestClient) -> None:
    d = cliente.get("/api/ranking?pie=0.3&top=50").json()
    assert d["total_rankeable"] >= 1
    claves = {f["unidad_key"] for f in d["filas"]}
    assert "T-005" not in claves, "una unidad sin comparables no puede rankear (§7.3)"


def test_la_unidad_sin_comparables_se_cuenta_aparte(cliente: TestClient) -> None:
    """Un universo que se achica sin explicación es indistinguible de un filtro roto."""
    d = cliente.get("/api/ranking?pie=0.3").json()
    assert d["descartes_emparejamiento"].get("sin_comparables") == 1


def test_el_ranking_viene_ordenado_por_score(cliente: TestClient) -> None:
    filas = cliente.get("/api/ranking?pie=0.3&top=50").json()["filas"]
    scores = [Decimal(f["score"]["valor"]) for f in filas]
    assert scores == sorted(scores, reverse=True)
    assert [f["posicion"] for f in filas] == list(range(1, len(filas) + 1))


def test_el_filtro_de_comuna_muerde(cliente: TestClient) -> None:
    d = cliente.get("/api/ranking?pie=0.3&comuna=nunoa").json()
    assert d["filas"], "el filtro dejó el ranking vacío: revisa el dato de prueba"
    assert all(f["comuna_id"] == "nunoa" for f in d["filas"])


def test_el_filtro_de_m2_muerde(cliente: TestClient) -> None:
    d = cliente.get("/api/ranking?pie=0.3&m2_min=50").json()
    assert all(Decimal(f["m2_utiles"]["valor"]) >= 50 for f in d["filas"])


def test_el_filtro_de_pie_de_flujo_cero_muerde(cliente: TestClient) -> None:
    """El §7.5 pide explícitamente que el ranking respete el filtro de pie."""
    todas = cliente.get("/api/ranking?pie=0.3&top=100").json()["filas"]
    tope = 0.45
    filtradas = cliente.get(f"/api/ranking?pie=0.3&top=100&pie_cero_max={tope}").json()["filas"]
    assert len(filtradas) <= len(todas)
    for f in filtradas:
        assert f["pie_flujo_cero_real"] is not None
        assert Decimal(f["pie_flujo_cero_real"]["valor"]) <= Decimal(str(tope))


def test_una_unidad_que_nunca_llega_a_flujo_cero_no_pasa_el_filtro(cliente: TestClient) -> None:
    """`None` significa "no llega NUNCA", que es peor que cualquier tope, no mejor.

    Si se colara por ser `None`, el filtro mostraría como alcanzables justo las unidades
    imposibles.
    """
    filtradas = cliente.get("/api/ranking?pie=0.3&top=100&pie_cero_max=0.99").json()["filas"]
    assert all(f["pie_flujo_cero_real"] is not None for f in filtradas)


def test_un_pie_fuera_de_rango_se_rechaza(cliente: TestClient) -> None:
    assert cliente.get("/api/ranking?pie=1.5").status_code == 422
    assert cliente.get("/api/ranking?pie=-0.1").status_code == 422


def test_la_ficha_muestra_las_seis_columnas_de_procedencia(cliente: TestClient) -> None:
    """Gate §7.5, literal: la ficha de unidad muestra las seis columnas de procedencia."""
    key = cliente.get("/api/ranking?pie=0.3").json()["filas"][0]["unidad_key"]
    d = cliente.get(f"/api/unidad/{key}?pie=0.3").json()
    assert d["columnas_procedencia"] == list(COLUMNAS_PROCEDENCIA)
    assert d["procedencia"], "sin filas de procedencia no hay nada que mostrar"
    fila = d["procedencia"][0]
    for col in COLUMNAS_PROCEDENCIA:
        assert fila.get(col), f"{col} vacía en la ficha"


def test_la_ficha_de_una_unidad_que_no_existe_es_404(cliente: TestClient) -> None:
    assert cliente.get("/api/unidad/NO-EXISTE").status_code == 404


def test_las_microzonas_se_ordenan_por_el_pie_mas_bajo(cliente: TestClient) -> None:
    mz = cliente.get("/api/microzonas?pie=0.3").json()["microzonas"]
    pies = [Decimal(m["pie_cero_minimo"]["valor"]) for m in mz if m["pie_cero_minimo"] is not None]
    assert pies == sorted(pies)


# --------------------------------------------------------------- la regla del §7.5


CLAVES_NO_NUMERICAS = {
    "posicion",
    "unidad_key",
    "microzona_id",
    "comuna_id",
    "tipologia",
    "arriendo_n_comparables",
    "antiguedad_anios",
    "es_vivienda_nueva",
    "score_desglose",
    # Nombres de componentes, no cifras de mercado: dicen QUE no se midio, no cuanto.
    "score_inertes",
    "subsidio_aplicado",
    "motivo_sin_subsidio",
    "fogaes_aplicado",
    "motivo_sin_fogaes",
    "dfl2_aplicado",
    "motivo_sin_dfl2",
    "procedencia_arriendo",
    "procedencia",
    "columnas_procedencia",
}


def test_ningun_numero_de_mercado_va_sin_evidencia(cliente: TestClient) -> None:
    """EL GATE DEL §7.5: ningún número aparece sin su `evidence_level`.

    Se verifica sobre la forma real de la respuesta, no sobre una lista de campos escrita a
    mano: cualquier clave nueva que alguien agregue mañana con un número pelado hace fallar
    este test sin que haya que acordarse de actualizarlo.
    """
    d = cliente.get("/api/ranking?pie=0.3&top=50").json()
    assert d["filas"], "sin filas este test no prueba nada"
    for f in d["filas"]:
        for clave, valor in f.items():
            if clave in CLAVES_NO_NUMERICAS:
                continue
            assert isinstance(valor, dict), (
                f"'{clave}' salió como {type(valor).__name__} pelado. Todo número de mercado "
                "va envuelto por `cifra()` con su evidence_level (§7.5)."
            )
            assert valor["evidence_level"] in {"V", "D", "E", "ND"}


def test_la_metrica_insignia_se_declara_estimada_no_derivada(cliente: TestClient) -> None:
    """`pie_flujo_cero_real` sale de una bisección sobre el modelo COMPLETO, que incluye
    vacancia, opex e inflación — los tres supuestos `E` de params.yml.

    Declararlo `D` lo presentaría como un cálculo sobre datos verificados, y no lo es.
    """
    f = cliente.get("/api/ranking?pie=0.3").json()["filas"][0]
    assert f["pie_flujo_cero_real"]["evidence_level"] == "E"
    # El precio, en cambio, sí vino de una fuente.
    assert f["precio_uf"]["evidence_level"] == "V"


# --------------------------------------------------------------- honestidad de la interfaz


def test_declara_que_no_puede_dibujar_el_mapa_y_por_que(cliente: TestClient) -> None:
    """El §7.5 pide un mapa de microzonas y hoy NO se puede: no hay geometría.

    La interfaz tiene que decirlo en vez de dibujar puntos aproximados. Una microzona mal
    ubicada es peor que ninguna, porque el §2.4 dice que la microzona ES la unidad de
    análisis: si está mal puesta, todo el argumento del producto se cae.
    """
    d = cliente.get("/api/ranking?pie=0.3").json()
    assert d["capacidades"]["mapa"] is False
    assert "T-014" in d["capacidades"]["mapa_razon"]
    assert any("geometría" in a for a in d["advertencias"])


def test_avisa_que_un_cuarto_del_score_esta_inerte(cliente: TestClient) -> None:
    """Un score que se presenta como completo cuando un cuarto de su peso no diferencia
    nada miente por omisión."""
    d = cliente.get("/api/ranking?pie=0.3").json()
    assert set(d["componentes_inertes"]) == {"riesgo_microzona", "catalizador"}
    assert any("inerte" in a for a in d["advertencias"])


def test_no_avisa_de_micro_unidades_cuando_no_hay_ninguna(cliente: TestClient) -> None:
    """Con el ranking vacío una versión anterior decía "0 de las 15 primeras son de menos de
    35 m²": una advertencia sobre unidades que no existen."""
    d = cliente.get("/api/ranking?pie=0.3&m2_min=200").json()
    assert not any("menos de 35 m²" in a and a.startswith("0 ") for a in d["advertencias"])


def test_reporta_lo_pedido_y_lo_aplicado_por_separado(cliente: TestClient) -> None:
    """Confundirlos miente sobre la plata: el escenario pide 10% de pie con subsidio, pero a
    un usado el motor le niega los dos y le exige 20%."""
    d = cliente.get("/api/ranking?pie=0.1").json()
    e = d["escenario"]
    assert e["pie_pedido"] == "0.1"
    assert "pies_efectivos" in e
    assert isinstance(e["con_subsidio"], int)


# --------------------------------------------------------------- rendimiento


def test_la_segunda_llamada_al_mismo_pie_sale_de_la_cache(base: Path) -> None:
    import time

    svc = Servicio(base)
    c = TestClient(crear_app(servicio=svc))
    c.get("/api/ranking?pie=0.3")
    t0 = time.monotonic()
    c.get("/api/ranking?pie=0.3&top=10")
    assert time.monotonic() - t0 < 0.5


def test_cambiar_el_pie_reusa_la_biseccion(base: Path) -> None:
    """La bisección busca el pie donde el flujo cruza cero, así que NO depende del pie
    pedido. Sin esta caché, mover el control rehace 90 s de cálculo para llegar al mismo
    número."""
    svc = Servicio(base)
    svc.foto(Decimal("0.3"))
    firma = next(iter(svc._pie_cero))
    cacheados = dict(svc._pie_cero[firma])
    assert cacheados, "la primera foto no dejó nada en la caché"

    svc.foto(Decimal("0.5"))
    # Mismo escenario salvo el pie: la firma tiene que ser LA MISMA, o la caché no sirve.
    assert list(svc._pie_cero) == [firma]
    for key, valor in cacheados.items():
        assert svc._pie_cero[firma][key] == valor, f"{key} se recalculó y dio distinto"


def test_la_firma_de_cache_ignora_el_pie_pero_no_los_supuestos(base: Path) -> None:
    """Si `escenario_id` entrara en la firma, cada pie tendría su propia caché y esta no
    serviría de nada — sin que fallara nada, solo estaría lenta."""
    from dataclasses import replace

    from flujocero.config import cargar
    from flujocero.finance.escenarios import escenario_base

    p, inv = cargar("params"), cargar("inversionista")
    e = escenario_base(p, inv)
    otro_pie = replace(e, pie_pct=Decimal("0.55"), escenario_id="pie55")
    assert Servicio._firma_sin_pie(e) == Servicio._firma_sin_pie(otro_pie)

    otra_vacancia = replace(e, vacancia=e.vacancia + Decimal("0.05"))
    assert Servicio._firma_sin_pie(e) != Servicio._firma_sin_pie(otra_vacancia)


# --------------------------------------------------------------- estáticos


def test_sirve_el_tablero_en_la_raiz(cliente: TestClient) -> None:
    r = cliente.get("/")
    assert r.status_code == 200
    assert b"Flujo Cero" in r.content


def test_el_tablero_no_depende_de_ningun_cdn(cliente: TestClient) -> None:
    """El gate E2E corre en un contenedor sin salida a internet, y un tablero de decisión
    financiera que se rompe cuando falla un CDN ajeno es peor que uno que no se rompe."""
    html = cliente.get("/").text
    for patron in ("cdn.", "unpkg", "jsdelivr", "googleapis", "//cdnjs"):
        assert patron not in html, f"el tablero carga algo externo: {patron}"
