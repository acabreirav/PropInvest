"""Delta de precios — T-919. El SCD tipo 2 escrito como pregunta."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import duckdb
import pytest

from flujocero import db
from flujocero.quality import delta
from flujocero.sources.portal_comun import cargar_avisos

MAYO = datetime(2026, 5, 4, tzinfo=UTC)
HOY = datetime(2026, 8, 29, tzinfo=UTC)


class Aviso:
    """Lo mínimo que el cargador compartido necesita."""

    def __init__(self, pid: str, precio: str, fecha: datetime, mz: str = "san-miguel/el-llano"):
        self.portal_id, self.operacion, self.url = pid, "venta", f"https://x/{pid}"
        self.fetched_at = fecha
        self.comuna_id, self.comuna_nombre = "san-miguel", "San Miguel"
        self.microzona_id, self.microzona_nombre = mz, "San Miguel - El Llano"
        self.precio_uf = D(precio)
        self.arriendo_clp = self.arriendo_uf = None
        self.m2_utiles, self.dormitorios, self.banos = D(58), 2, 2
        self.tipologia, self.es_proyecto, self.es_vivienda_nueva = "2D2B", False, False
        self.raw_blob_path, self.robots_snapshot_sha = "b", "s"


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    db.aplicar_esquema(c)
    yield c
    c.close()


def test_las_cuatro_categorias_del_cruce(con) -> None:
    cargar_avisos(
        con,
        [Aviso("MLC-1", "4000", MAYO), Aviso("MLC-2", "3500", MAYO), Aviso("MLC-3", "5000", MAYO)],
        "legado",
        "v1",
    )
    cargar_avisos(
        con,
        [Aviso("MLC-1", "3600", HOY), Aviso("MLC-2", "3500", HOY), Aviso("MLC-9", "2800", HOY)],
        "portal_busqueda",
        "v1",
    )
    r = delta.comparar(con, HOY)
    assert len(r.bajaron) == 1 and r.bajaron[0].unidad_key == "MLC-1"
    assert r.sin_cambio == 1
    assert r.desaparecidas == 1, "MLC-3 ya no aparece: un aviso desaparece cuando se vende"
    assert r.nuevas == 1, "solo MLC-9"


def test_la_que_bajo_de_precio_no_se_cuenta_tambien_como_nueva(con) -> None:
    """Su version vigente nace hoy, igual que la de un aviso nuevo. Lo que las separa es que
    la primera tiene una version cerrada detras. Sin ese filtro, el universo se infla con
    unidades que ya estaban."""
    cargar_avisos(con, [Aviso("MLC-1", "4000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3600", HOY)], "portal_busqueda", "v1")
    r = delta.comparar(con, HOY)
    assert r.nuevas == 0
    assert len(r.bajaron) == 1


def test_la_variacion_se_calcula_sobre_el_precio_viejo(con) -> None:
    cargar_avisos(con, [Aviso("MLC-1", "4000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3600", HOY)], "portal_busqueda", "v1")
    assert delta.comparar(con, HOY).bajaron[0].variacion == D("-0.1")


def test_una_que_subio_no_aparece_entre_las_que_bajaron(con) -> None:
    cargar_avisos(con, [Aviso("MLC-1", "3000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3300", HOY)], "portal_busqueda", "v1")
    r = delta.comparar(con, HOY)
    assert not r.bajaron
    assert len(r.subieron) == 1 and r.subieron[0].variacion == D("0.1")


def test_confirmar_una_unidad_actualiza_su_procedencia_pero_no_su_valid_from(con) -> None:
    """Dejar la procedencia apuntando al blob de mayo diria que la evidencia de esta fila es
    un documento viejo, cuando la evidencia es la captura de hoy. `valid_from` conserva
    cuando se vio por primera vez, que es otra pregunta."""
    cargar_avisos(con, [Aviso("MLC-2", "3500", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-2", "3500", HOY)], "portal_busqueda", "v1")
    fila = con.execute(
        "SELECT valid_from, fetched_at, source_id FROM fact_unidad_venta WHERE unidad_key='MLC-2'"
    ).fetchone()
    assert fila[0] == MAYO, "se vio por primera vez en mayo"
    assert fila[1] == HOY, "se confirmo hoy"
    assert fila[2] == "portal_busqueda", "la evidencia vigente es la captura de hoy"
    assert con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0] == 1


def test_la_microzona_viaja_a_la_unidad_de_venta(con) -> None:
    """Sin microzona en `fact_unidad_venta` no hay yield: el arriendo comparable esta indexado
    por microzona y no habria por donde cruzarlos."""
    cargar_avisos(con, [Aviso("MLC-5", "3000", HOY, mz="nunoa/plaza-egana")], "x", "v1")
    assert (
        con.execute("SELECT microzona_id FROM fact_unidad_venta").fetchone()[0]
        == "nunoa/plaza-egana"
    )


def test_con_una_sola_captura_el_informe_dice_que_no_compara_nada(con) -> None:
    """ "Todo es nuevo" con una sola foto es una tautologia, no un hallazgo. Decirlo evita
    que alguien lea 266 oportunidades donde solo hay 266 avisos."""
    cargar_avisos(con, [Aviso("MLC-1", "3000", HOY), Aviso("MLC-2", "4000", HOY)], "x", "v1")
    r = delta.comparar(con, HOY)
    assert not r.comparable
    assert "NO HAY CON QUE COMPARAR" in str(r)
    assert "ingerir-legado" in str(r), "el informe dice como conseguir la foto anterior"


def test_con_dos_capturas_el_informe_si_compara(con) -> None:
    cargar_avisos(con, [Aviso("MLC-1", "4000", MAYO)], "legado", "v1")
    cargar_avisos(con, [Aviso("MLC-1", "3600", HOY)], "portal_busqueda", "v1")
    r = delta.comparar(con, HOY)
    assert r.comparable
    assert "bajaron de precio" in str(r)


def test_confirmar_una_unidad_rellena_una_columna_agregada_despues(con) -> None:
    """Las 552 filas de la primera corrida real quedaron con `microzona_id` en NULL porque la
    columna se agrego despues y el camino de confirmacion no la escribia: la fila se
    "actualizaba" cada corrida y nunca se llenaba."""
    cargar_avisos(con, [Aviso("MLC-7", "3000", MAYO)], "x", "v1")
    con.execute("UPDATE fact_unidad_venta SET microzona_id = NULL")  # simula la fila vieja

    cargar_avisos(con, [Aviso("MLC-7", "3000", HOY)], "x", "v1")  # mismo precio: confirma
    assert (
        con.execute("SELECT microzona_id FROM fact_unidad_venta").fetchone()[0]
        == "san-miguel/el-llano"
    )

    con.execute("UPDATE fact_unidad_venta SET microzona_id = NULL")
    cargar_avisos(con, [Aviso("MLC-7", "3000", HOY)], "x", "v1")  # misma fecha: actualiza
    assert (
        con.execute("SELECT microzona_id FROM fact_unidad_venta").fetchone()[0]
        == "san-miguel/el-llano"
    )


def test_el_orden_en_que_se_cargan_las_fotos_no_cambia_el_resultado(con) -> None:
    """El bug que aparecio en la maquina del usuario: recolecto agosto primero y despues
    ingirio la foto de mayo. La captura vieja se descartaba, asi que toda unidad presente en
    las dos perdia su version de mayo y el informe salia con cero cambios de precio.
    Un almacen versionado no puede dar resultados distintos segun el orden de carga."""
    otra = duckdb.connect(":memory:")
    db.aplicar_esquema(otra)
    try:
        mayo = [Aviso("MLC-1", "4000", MAYO), Aviso("MLC-2", "3500", MAYO)]
        hoy = [Aviso("MLC-1", "3600", HOY), Aviso("MLC-2", "3500", HOY)]

        cargar_avisos(con, mayo, "legado", "v1")
        cargar_avisos(con, hoy, "vivo", "v1")

        cargar_avisos(otra, hoy, "vivo", "v1")  # el orden inverso
        cargar_avisos(otra, mayo, "legado", "v1")

        consulta = (
            "SELECT unidad_key, precio_uf, valid_from, valid_to "
            "FROM fact_unidad_venta ORDER BY unidad_key, valid_from"
        )
        assert con.execute(consulta).fetchall() == otra.execute(consulta).fetchall()

        r = delta.comparar(otra, HOY)
        assert len(r.bajaron) == 1, "MLC-1 bajo, y se ve cargando en cualquier orden"
        assert r.sin_cambio == 1
    finally:
        otra.close()


def test_una_foto_vieja_al_mismo_precio_retrocede_la_version_en_vez_de_duplicarla(con) -> None:
    """Si ya estaba a ese precio en mayo, no hay dos versiones: hay una que empezo antes.
    Crear una version nueva inventaria un cambio de precio que nunca ocurrio."""
    cargar_avisos(con, [Aviso("MLC-2", "3500", HOY)], "vivo", "v1")
    cargar_avisos(con, [Aviso("MLC-2", "3500", MAYO)], "legado", "v1")
    filas = con.execute("SELECT precio_uf, valid_from, valid_to FROM fact_unidad_venta").fetchall()
    assert len(filas) == 1
    assert filas[0][1] == MAYO, "la version vigente empieza en mayo, no hoy"
    assert filas[0][2] is None


def test_lo_que_no_se_volvio_a_mirar_no_cuenta_como_desaparecido(con) -> None:
    """El informe del usuario dijo 2.691 desapariciones cuando solo habia recolectado tres
    comunas y dos paginas de cada una. Un numero que mide el alcance de la corrida disfrazado
    de senal de mercado es peor que no tener el numero."""
    cargar_avisos(
        con,
        [
            Aviso("MLC-1", "4000", MAYO, mz="san-miguel/el-llano"),
            Aviso("MLC-8", "5000", MAYO, mz="las-condes/el-golf"),
        ],
        "legado",
        "v1",
    )
    # La corrida nueva solo toca San Miguel. Las Condes ni se miro.
    cargar_avisos(con, [Aviso("MLC-9", "3000", HOY, mz="san-miguel/el-llano")], "vivo", "v1")

    r = delta.comparar(con, HOY)
    assert r.desaparecidas == 1, "solo MLC-1, que si estaba en una microzona re-revisada"
    assert r.fuera_de_alcance == 1, "MLC-8 no desaparecio: no se volvio a mirar"
    assert "no se volvieron a mirar" in str(r)
    assert r.microzonas_revisadas == 1


def _aviso_superficie(pid: str, precio: str, fecha: datetime) -> Aviso:
    return Aviso(pid, precio, fecha)


def test_tarjeta_y_ficha_del_mismo_dia_no_inventan_un_cambio_de_precio(con) -> None:
    """Medido sobre el corpus real: de 2.689 unidades presentes el mismo dia en las dos
    superficies, 48 traian precios distintos, una con UF 13.000 en la tarjeta contra UF 15.900
    en la ficha —mismo aviso, mismo dia, mismo titulo, 22%—. Versionar entre superficies
    inventaria un cambio que nunca ocurrio."""
    cargar_avisos(con, [_aviso_superficie("MLC-1", "15900", MAYO)], "legado", "portal_legado/1.0.0")
    cargar_avisos(con, [_aviso_superficie("MLC-1", "13000", MAYO)], "vivo", "portal_busqueda/1.0.0")
    filas = con.execute("SELECT precio_uf, parser_version FROM fact_unidad_venta").fetchall()
    assert len(filas) == 1, "una sola fila: no son dos versiones, son dos superficies"


def test_la_tarjeta_es_la_superficie_canonica_del_precio(con) -> None:
    """Es la que el colector vivo va a seguir viendo. Si mandara la ficha, la linea base
    quedaria en una superficie que ya nadie vuelve a leer y el delta no cruzaria nunca."""
    cargar_avisos(con, [_aviso_superficie("MLC-1", "15900", MAYO)], "legado", "portal_legado/1.0.0")
    cargar_avisos(con, [_aviso_superficie("MLC-1", "13000", MAYO)], "vivo", "portal_busqueda/1.0.0")
    precio, parser = con.execute(
        "SELECT precio_uf, parser_version FROM fact_unidad_venta"
    ).fetchone()
    assert precio == D("13000.00") and parser == "portal_busqueda/1.0.0"


def test_la_ficha_completa_atributos_pero_no_pisa_el_precio_de_la_tarjeta(con) -> None:
    cargar_avisos(con, [_aviso_superficie("MLC-1", "13000", MAYO)], "vivo", "portal_busqueda/1.0.0")
    con.execute("UPDATE fact_unidad_venta SET antiguedad_anios = NULL")
    ficha = _aviso_superficie("MLC-1", "15900", MAYO)
    ficha.antiguedad_anios = 12
    cargar_avisos(con, [ficha], "legado", "portal_legado/1.0.0")
    precio, antig = con.execute(
        "SELECT precio_uf, antiguedad_anios FROM fact_unidad_venta"
    ).fetchone()
    assert precio == D("13000.00"), "el precio de la tarjeta manda"
    assert antig == 12, "pero la ficha aporta lo que la tarjeta no trae"


def test_dos_tarjetas_de_fechas_distintas_SI_versionan(con) -> None:
    """El candado es entre superficies, no entre fechas. Tarjeta contra tarjeta es
    exactamente la comparacion que el delta necesita."""
    cargar_avisos(con, [_aviso_superficie("MLC-1", "4000", MAYO)], "vivo", "portal_busqueda/1.0.0")
    cargar_avisos(con, [_aviso_superficie("MLC-1", "3600", HOY)], "vivo", "portal_busqueda/1.0.0")
    assert len(delta.comparar(con, HOY).bajaron) == 1


def test_si_la_corrida_nueva_cubrio_poco_lo_dice_en_vez_de_afirmar_ventas(con) -> None:
    """ "Ya no esta" solo significa "se vendio" si de verdad se volvio a mirar. Con 20 paginas
    contra una foto paginada completa, la mayoria sigue publicada en una pagina que nadie
    pidio, y el numero se lee como ventas que no ocurrieron."""
    viejas = [Aviso(f"MLC-V{i}", "3000", MAYO) for i in range(20)]
    cargar_avisos(con, viejas, "legado", "portal_busqueda/1.0.0")
    # La corrida nueva solo alcanza a ver 2 de las 20.
    cargar_avisos(
        con,
        [Aviso("MLC-V0", "3000", HOY), Aviso("MLC-V1", "3000", HOY)],
        "vivo",
        "portal_busqueda/1.0.0",
    )
    r = delta.comparar(con, HOY)
    assert r.cobertura < D("0.9")
    assert "POCO FIABLE" in str(r)


def test_con_cobertura_completa_el_numero_se_afirma(con) -> None:
    cargar_avisos(
        con,
        [Aviso("MLC-1", "3000", MAYO), Aviso("MLC-2", "4000", MAYO)],
        "legado",
        "portal_busqueda/1.0.0",
    )
    cargar_avisos(
        con,
        [Aviso("MLC-1", "3000", HOY), Aviso("MLC-3", "2500", HOY)],
        "vivo",
        "portal_busqueda/1.0.0",
    )
    r = delta.comparar(con, HOY)
    assert r.cobertura >= 1.0
    assert "un aviso desaparece al venderse" in str(r)
    assert "POCO FIABLE" not in str(r)


def test_el_listado_muestra_UF_por_m2_que_es_lo_que_permite_comparar(con) -> None:
    cargar_avisos(con, [Aviso("MLC-1", "4000", MAYO)], "legado", "portal_busqueda/1.0.0")
    cargar_avisos(con, [Aviso("MLC-1", "3600", HOY)], "vivo", "portal_busqueda/1.0.0")
    salida = str(delta.comparar(con, HOY))
    assert "UF/m2" in salida
    assert "62 UF/m2" in salida, "3600 UF sobre 58 m2"


def test_dos_capturas_viejas_al_mismo_precio_no_crean_versiones_superpuestas(con) -> None:
    """El corpus trae capturas del 4 y del 5 de mayo y llegan en orden arbitrario. Con la
    version anterior, ambas insertaban su propia version cerrada con el mismo precio, y la
    unidad aparecia DOS VECES en la lista de bajadas — se lee como dos oportunidades."""
    mayo4 = datetime(2026, 5, 4, tzinfo=UTC)
    mayo5 = datetime(2026, 5, 5, tzinfo=UTC)
    cargar_avisos(con, [Aviso("MLC-1", "5800", HOY)], "vivo", "portal_busqueda/1.0.0")
    cargar_avisos(con, [Aviso("MLC-1", "6400", mayo5)], "legado", "portal_busqueda/1.0.0")
    cargar_avisos(con, [Aviso("MLC-1", "6400", mayo4)], "legado", "portal_busqueda/1.0.0")

    filas = con.execute(
        "SELECT precio_uf, valid_from, valid_to FROM fact_unidad_venta ORDER BY valid_from"
    ).fetchall()
    assert len(filas) == 2, "una version vieja y una vigente, no tres"
    assert filas[0][1] == mayo4, "la version vieja empieza en la captura mas antigua"
    assert filas[0][0] == D("6400.00")

    r = delta.comparar(con, HOY)
    assert len(r.bajaron) == 1
    assert [c.unidad_key for c in r.bajaron].count("MLC-1") == 1


def test_el_informe_muestra_el_cambio_NETO_una_sola_vez(con) -> None:
    """Una unidad con dos bajadas sucesivas es una oportunidad, no dos."""
    mayo = datetime(2026, 5, 4, tzinfo=UTC)
    junio = datetime(2026, 6, 15, tzinfo=UTC)
    cargar_avisos(con, [Aviso("MLC-1", "6000", mayo)], "x", "portal_busqueda/1.0.0")
    cargar_avisos(con, [Aviso("MLC-1", "5500", junio)], "x", "portal_busqueda/1.0.0")
    cargar_avisos(con, [Aviso("MLC-1", "5000", HOY)], "x", "portal_busqueda/1.0.0")

    r = delta.comparar(con, HOY)
    assert len(r.bajaron) == 1
    c = r.bajaron[0]
    assert c.precio_antes_uf == D("6000.00"), "se compara contra la mas antigua"
    assert c.precio_ahora_uf == D("5000.00")
