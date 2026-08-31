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
