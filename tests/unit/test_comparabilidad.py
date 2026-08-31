"""Un arriendo amoblado no es comparable con uno pelado — T-047.

Los once títulos son los reales de `antofagasta/la-chimba · 1D1B · 35-50 m²`, la celda que
puso a `MLC-4427322266` primera en el ranking del 31-ago-2026 con yield 11,48%.
"""

from __future__ import annotations

import pytest

from flujocero.quality.comparabilidad import dudoso, marca, no_comparable

# Los 11 avisos reales de la celda, con su arriendo.
LA_CHIMBA = [
    (470_000, "arriendo-departamento-calle-oficina-lastenia-antofagasta"),
    (620_000, "amplio-departamento-semi-amoblado-con-hermosa-vista"),
    (630_000, "se-arrienda-departamento-en-edificio-las-aguilas"),
    (650_000, "se-arrienda-depto-amoblado-en-el-sector-norte-de-antofagasta"),
    (650_000, "arrienda-departamento-amoblado-edificio-alerce-antofagasta"),
    (660_000, "departamento-amoblado-1d-1e-areas-comunes-premium-gc-incl"),
    (660_000, "arrienda-departamento-amoblado-sector-norte-antofagasta"),
    (660_000, "departamento-de-1-dormotorio-en-ultimo-piso"),
    (670_000, "departamento-en-arriendo-de-1-dorm-en-antofagasta"),
    (680_000, "arriendo-dpto-1d-1b-equipado-con-buen-gusto"),
    (690_000, "departamento-full-amoblado-1d1b1e-en-edificio-las-aguilas"),
]


def _mediana(v: list[int]) -> int:
    v = sorted(v)
    return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) // 2


def test_el_hallazgo_no_es_que_la_mediana_estuviera_inflada() -> None:
    """**Ese no es el problema, y decirlo importa.**

    Sacando los seis amoblados declarados la mediana no se mueve: sigue en $660.000. Los
    amoblados de Antofagasta no cobran mucho más que el resto. Si el hallazgo se contara
    como "la mediana estaba inflada", sería falso y se caería a la primera revisión.
    """
    limpios = [m for m, t in LA_CHIMBA if not no_comparable(t)]
    assert _mediana([m for m, _ in LA_CHIMBA]) == 660_000
    assert _mediana(limpios) == 660_000


def test_el_hallazgo_es_que_la_celda_no_deberia_rankear() -> None:
    """Seis de once declaran amoblado. Sin ellos quedan menos de los 8 del §7.3: la celda
    llegaba al umbral contando productos que no son el mismo producto."""
    limpios = [m for m, t in LA_CHIMBA if not no_comparable(t)]
    assert len(LA_CHIMBA) == 11 >= 8, "en el papel alcanzaba"
    assert len(limpios) == 5 < 8, "en el fondo no"


@pytest.mark.parametrize(
    "titulo",
    [
        "depto-amoblado-en-el-sector-norte",
        "amplio-departamento-semi-amoblado-con-hermosa-vista",
        "departamento-full-amoblado-1d1b1e",
        "departamento-arriendo-1-dorm-nunoa-amueblado",
        "arriendo-por-dia-centro",
        "depto-corta-estadia-vina",
    ],
)
def test_declaraciones_inequivocas(titulo) -> None:
    assert no_comparable(titulo)


@pytest.mark.parametrize(
    "titulo",
    [
        "se-arrienda-departamento-en-edificio-las-aguilas",
        "departamento-de-1-dormotorio-en-ultimo-piso",
        "arriendo-departamento-calle-oficina-lastenia-antofagasta",
        "lindo-depto-1d1b-est-nunoa",
    ],
)
def test_no_bota_avisos_normales(titulo) -> None:
    assert not no_comparable(titulo)


def test_equipado_se_marca_pero_no_se_excluye() -> None:
    """En Chile "cocina equipada" es estándar en un arriendo pelado. Excluir por esa palabra
    perdería dato bueno; se marca para que un humano lo mire."""
    t = "arriendo-dpto-1d-1b-equipado-con-buen-gusto"
    assert not no_comparable(t)
    assert dudoso(t)
    assert marca(t) == "? "


def test_un_amoblado_con_gc_incluido_se_excluye_igual() -> None:
    """La señal dura gana sobre la dudosa: no se marca `?` algo que ya sale por `✗`."""
    t = "departamento-amoblado-1d-1e-areas-comunes-premium-gc-incl"
    assert no_comparable(t) and not dudoso(t)
    assert marca(t) == "✗ "


def test_sin_titulo_no_se_excluye() -> None:
    """La ausencia de dato no es evidencia. §3.2: un `ND` no se rellena con una suposición."""
    assert not no_comparable(None) and not no_comparable("")


# ------------------------- el filtro que el portal no aplico (T-049)

from flujocero.quality.comparabilidad import busquedas_que_devuelven_lo_mismo  # noqa: E402


def test_las_cinco_comunas_del_gran_concepcion() -> None:
    """El caso real. `probar-comunas --fase 3` dijo **8/8, 48 tarjetas cada una** y las cinco
    comunas del Gran Concepción habían devuelto exactamente los mismos 48 avisos. Contar
    resultados no podía notarlo: el número era el correcto."""
    mismos = frozenset(f"MLC-{i}" for i in range(48))
    ids = {
        "concepcion": mismos,
        "talcahuano": mismos,
        "hualpen": mismos,
        "san-pedro-de-la-paz": mismos,
        "chiguayante": mismos,
        "antofagasta": frozenset(f"MLC-A{i}" for i in range(48)),
        "la-serena": frozenset(f"MLC-L{i}" for i in range(48)),
    }
    pares = busquedas_que_devuelven_lo_mismo(ids)
    afectadas = {a for a, _, _, _ in pares} | {b for _, b, _, _ in pares}
    assert afectadas == {
        "concepcion",
        "talcahuano",
        "hualpen",
        "san-pedro-de-la-paz",
        "chiguayante",
    }
    assert len(pares) == 10, "los diez pares de las cinco comunas, y ninguno mas"


def test_comunas_de_verdad_distintas_no_disparan() -> None:
    """La contraprueba. Un aviso mal geolocalizado no puede convertir el check en ruido."""
    ids = {
        "san-miguel": frozenset(f"MLC-{i}" for i in range(48)),
        "la-florida": frozenset([*[f"MLC-F{i}" for i in range(47)], "MLC-0"]),  # 1 compartido
    }
    assert busquedas_que_devuelven_lo_mismo(ids) == []


def test_una_busqueda_vacia_no_es_un_duplicado() -> None:
    """Cero resultados ya lo agarra el conteo, y es otro diagnóstico: comuna sin oferta o
    slug malo, no filtro ignorado. Mezclarlos mandaría a arreglar lo que no está roto."""
    ids = {"a": frozenset(), "b": frozenset(), "c": frozenset(["MLC-1"])}
    assert busquedas_que_devuelven_lo_mismo(ids) == []


def test_el_solape_parcial_cuenta_desde_la_mitad() -> None:
    """El umbral es del menor de los dos, no del total: una comuna chica contenida entera
    dentro de una grande es el caso que hay que agarrar."""
    grande = frozenset(f"MLC-{i}" for i in range(100))
    chica = frozenset(f"MLC-{i}" for i in range(10))  # contenida entera
    assert busquedas_que_devuelven_lo_mismo({"grande": grande, "chica": chica}) == [
        ("chica", "grande", 10, 10)
    ]
