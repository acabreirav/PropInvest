"""Integración contra respuestas REALES grabadas — CLAUDE.md §7.1.

`tests/integration/` estaba vacío desde el inicio del proyecto, aunque el §7.1 exige que el
`selftest` de cada fuente corra "contra una fixture grabada". Estas seis fichas vienen del
corpus real de mayo-2026, ya anonimizadas, y cubren las seis combinaciones que existen:
{venta, arriendo} × {UF, CLP} × {usada, nueva}.

Nunca tocan la red. Si el portal cambia su HTML mañana, estos tests siguen fijando lo que el
parser prometía hoy, que es justamente para lo que sirven.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from flujocero.sources import portal_legado as pl
from flujocero.sources.base import leer_crudo
from flujocero.sources.portal_legado import _PATRONES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "portal_legado"
ARCHIVOS = sorted(FIXTURES.glob("*.json.gz"))


def test_hay_fixtures_grabadas() -> None:
    assert len(ARCHIVOS) == 6, "una por cada combinacion operacion x moneda x nuevo/usado"


@pytest.mark.parametrize("ruta", ARCHIVOS, ids=lambda p: p.name.replace(".json.gz", ""))
def test_ninguna_fixture_lleva_datos_personales(ruta: Path) -> None:
    """§3.4. Estos archivos van al repositorio: si algo se escapa, se publica."""
    contenido = leer_crudo(ruta).contenido
    for patron, _ in _PATRONES:
        assert not patron.findall(contenido), f"{ruta.name} conserva {patron.pattern!r}"


@pytest.mark.parametrize("ruta", ARCHIVOS, ids=lambda p: p.name.replace(".json.gz", ""))
def test_cada_fixture_parsea_con_su_forma_esperada(ruta: Path) -> None:
    """El nombre del archivo declara qué debe salir. Si el parser cambia de opinión, falla."""
    operacion, moneda, tipo = ruta.name.replace(".json.gz", "").split("_")
    doc = leer_crudo(ruta)
    a = pl.parse_html(
        doc.contenido.decode("utf-8", errors="ignore"),
        doc.url,
        doc.fetched_at,
        str(ruta),
        doc.robots_snapshot_sha,
    )
    assert a is not None, "una ficha real grabada debe parsear"
    assert a.operacion == operacion
    assert a.moneda == moneda.upper()
    assert a.es_vivienda_nueva == {"nueva": True, "usada": False, "nd": None}[tipo]
    assert a.monto > 0
    assert a.comuna_id, "la comuna sale del breadcrumb y es el minimo para ubicar el aviso"


@pytest.mark.parametrize("ruta", ARCHIVOS, ids=lambda p: p.name.replace(".json.gz", ""))
def test_la_procedencia_sobrevive_al_viaje_por_la_zona_cruda(ruta: Path) -> None:
    """§3.1 y §3.6: releer un blob debe devolver las seis columnas intactas."""
    doc = leer_crudo(ruta)
    assert doc.source_id == pl.SOURCE_ID
    assert doc.url.startswith("https://www.portalinmobiliario.com")
    assert doc.fetched_at.year == 2026 and doc.fetched_at.month == 5
    assert doc.fetched_at.tzinfo is not None, "§11: siempre con tzinfo"
    assert doc.robots_snapshot_sha


def test_el_monto_nunca_sale_de_un_rango_pegado() -> None:
    """Regresión del bug que convertía `"35 - 61 m²"` en 3.561 m². Sobre fichas reales:
    ningún m² parseado puede caer fuera del rango físico de un departamento."""
    for ruta in ARCHIVOS:
        doc = leer_crudo(ruta)
        a = pl.parse_html(
            doc.contenido.decode("utf-8", errors="ignore"),
            doc.url,
            doc.fetched_at,
            str(ruta),
            doc.robots_snapshot_sha,
        )
        assert a is not None
        if a.m2_utiles is not None:
            assert Decimal(15) <= a.m2_utiles <= Decimal(400), f"{ruta.name}: {a.m2_utiles} m2"
