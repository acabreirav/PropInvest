"""El rango UF/m² del §7.1 — T-042. La cesión de promesa que encabezó el ranking.

El caso real: `MLC-1939505225`, primera del ranking del 31-ago-2026 con yield 17,58% contra
7,90% de la segunda. Título: *vendo promesa con descuento de 6 millones*. UF 850 por un 2D2B
de 60 m² = 14,2 UF/m². No vendía el departamento: vendía su posición en una promesa de
compraventa.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from flujocero.quality.plausibilidad import implausible


def test_la_cesion_de_promesa_que_encabezo_el_ranking() -> None:
    razon = implausible(D(850), D(60))
    assert razon is not None
    assert "14.2 UF/m²" in razon
    assert "promesa" in razon, "el descarte tiene que decir QUÉ mirar, no solo que está fuera"


def test_precio_y_m2_plausibles_por_separado_no_bastan() -> None:
    """Es todo el punto del módulo: los dos rangos que ya existían dejaban pasar la fila."""
    from flujocero.sources.portal_busqueda import RANGO_M2, RANGOS

    lo, hi = RANGOS[("venta", "UF")]
    assert lo <= D(850) <= hi, "el precio pasa el rango que el parser ya aplicaba"
    assert RANGO_M2[0] <= D(60) <= RANGO_M2[1], "la superficie también"
    assert implausible(D(850), D(60)) is not None, "y aun así la fila es imposible"


@pytest.mark.parametrize(
    ("precio", "m2"),
    [
        (D(1350), D(39)),  # 34,6 UF/m² — la #2 real del ranking
        (D(2100), D(55)),  # 38,2 — san-miguel/lo-vial
        (D(4200), D(138)),  # 30,4 — el piso del stock real que tenemos
        (D(15326), D(89)),  # 172,2 — una cesión de promesa CON el precio del depto
        (D(13500), D(67.5)),  # 200,0 exacto — el borde es inclusivo
        (D(1200), D(60)),  # 20,0 exacto — el otro borde
    ],
)
def test_no_bota_unidades_reales(precio, m2) -> None:
    """La contraprueba que importa. Un filtro que además saca unidades legítimas cuesta más
    de lo que arregla: en un ranking por yield, las baratas son justo las candidatas."""
    assert implausible(precio, m2) is None


def test_las_nueve_promesas_no_se_botan_por_la_palabra() -> None:
    """De 9 avisos de cesión de promesa en la base, **8 publican el precio del departamento**
    (69 a 172 UF/m²). Un filtro por la palabra `promesa` botaría 8 legítimas para agarrar 1."""
    con_precio_de_depto = [
        (D(3206), D(46)),
        (D(2490), D(35)),
        (D(3729), D(47)),
        (D(4881), D(53)),
        (D(4740), D(48)),
        (D(2700), D(20)),
        (D(3100), D(21)),
        (D(15326), D(89)),
    ]
    assert all(implausible(p, m) is None for p, m in con_precio_de_depto)
    assert implausible(D(850), D(60)) is not None, "solo la que publica el precio de la cesión"


def test_dato_ausente_no_es_implausible() -> None:
    """Un `None` es `ND` (§3.2), no una fila imposible. Lo agarran `sin_m2` y cobertura."""
    assert implausible(None, D(60)) is None
    assert implausible(D(850), None) is None


def test_los_otros_dos_rangos_del_71_tambien() -> None:
    assert implausible(D(400), D(20)) is not None  # precio bajo el mínimo
    assert implausible(D(70_000), D(400)) is not None  # precio sobre el máximo
    assert implausible(D(1000), D(10)) is not None  # 10 m² no es una vivienda
    assert implausible(D(30_000), D(500)) is not None  # 500 m² tampoco es un depto
