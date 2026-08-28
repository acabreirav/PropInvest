"""Tests de los gates de calidad de datos — T-026, CLAUDE.md §7.3."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from flujocero.quality import checks as q

AHORA = datetime(2026, 8, 28, tzinfo=UTC)

PROC: dict[str, Any] = {
    "source_id": "meli_venta",
    "source_url": "https://api.mercadolibre.com/items/MLC1",
    "fetched_at": AHORA,
    "parser_version": "meli_venta/1.0.0",
    "raw_blob_path": "data/raw/meli_venta/2026/08/28/x.json.gz",
    "robots_snapshot_sha": "abc123",
}


def unidad(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "unidad_key": "U1",
        "proyecto_id": "P1",
        "numero_unidad": "101",
        "precio_uf": D("2600"),
        "m2_utiles": 35.0,
        "microzona_id": "san-miguel/gran-avenida",
        "evidence_level": "V",
        **PROC,
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------- datos personales


@pytest.mark.parametrize(
    "valor",
    [
        "consultar a juan.perez@corretaje.cl",
        "WhatsApp +56 9 8765 4321",
        "fono 987654321",
        "RUT 12.345.678-9",
        "contacto: 12345678-K",
    ],
)
def test_detecta_datos_personales_en_cualquier_columna(valor: str) -> None:
    """§3.4: el check mira VALORES. Una columna inocente con un correo adentro es ilegal igual."""
    h = q.buscar_datos_personales([unidad(orientacion=valor)])
    assert h.severidad is q.Severidad.FALLA
    assert not h.ok


def test_el_rut_de_una_empresa_si_se_permite() -> None:
    """§3.4 persiste el nombre de la inmobiliaria: es persona jurídica, no natural."""
    h = q.buscar_datos_personales([unidad(orientacion="Inmobiliaria Socovesa 90.222.000-3")])
    assert h.severidad is q.Severidad.OK


def test_una_unidad_limpia_pasa() -> None:
    h = q.buscar_datos_personales([unidad(orientacion="norponiente")])
    assert h.severidad is q.Severidad.OK


def test_el_check_no_se_deja_enganar_por_el_nombre_de_la_columna() -> None:
    """El criterio de aceptación de T-026 es explícito: regex sobre valores, no sobre nombres."""
    h = q.buscar_datos_personales([{"un_campo_cualquiera": "escribe a hola@ejemplo.cl"}])
    assert h.severidad is q.Severidad.FALLA
    assert "un_campo_cualquiera" in h.detalle[0]


# --------------------------------------------------------------------- procedencia


def test_falta_una_columna_de_procedencia_y_falla() -> None:
    u = unidad()
    u["raw_blob_path"] = ""
    h = q.procedencia_completa([u])
    assert h.severidad is q.Severidad.FALLA
    assert "raw_blob_path" in h.detalle[0]


# --------------------------------------------------------------------- cobertura


def test_cobertura_bajo_80_por_ciento_marca_el_ranking_parcial() -> None:
    filas = [unidad()] * 7 + [unidad(precio_uf=None)] * 3
    h = q.cobertura_precio_y_microzona(filas)
    assert h.severidad is q.Severidad.ALERTA
    assert "parcial" in h.mensaje


def test_un_precio_estimado_no_cuenta_como_cobertura() -> None:
    """§12: un precio con `evidence_level: E` excluye del ranking."""
    h = q.cobertura_precio_y_microzona([unidad(evidence_level="E")] * 10)
    assert h.severidad is q.Severidad.ALERTA


def test_cobertura_suficiente_pasa() -> None:
    h = q.cobertura_precio_y_microzona([unidad()] * 9 + [unidad(microzona_id=None)])
    assert h.severidad is q.Severidad.OK


# --------------------------------------------------------------------- frescura


def test_una_fila_de_mas_de_21_dias_falla() -> None:
    vieja = unidad(fetched_at=AHORA - timedelta(days=22))
    h = q.frescura([vieja], AHORA)
    assert h.severidad is q.Severidad.FALLA


def test_exactamente_21_dias_todavia_pasa() -> None:
    h = q.frescura([unidad(fetched_at=AHORA - timedelta(days=21))], AHORA)
    assert h.severidad is q.Severidad.OK


# --------------------------------------------------------------------- outliers


def test_marca_el_outlier_pero_no_lo_borra() -> None:
    """§7.3: se marca `sospechoso` y se conserva. Nunca se borra dato."""
    normales = [unidad(unidad_key=f"U{i}", precio_uf=D(2600), m2_utiles=35.0) for i in range(20)]
    raro = unidad(unidad_key="RARO", precio_uf=D(9000), m2_utiles=35.0)
    filas = [*normales, raro]
    h = q.marcar_outliers(filas)
    assert h.severidad is q.Severidad.MARCA
    assert h.ok, "marcar no debe detener el pipeline"
    assert len(filas) == 21, "no se borró ninguna fila"
    assert filas[-1]["sospechoso"] is True
    assert all("sospechoso" not in f or not f["sospechoso"] for f in filas[:20])


def test_con_menos_de_tres_unidades_no_se_calcula_percentil() -> None:
    filas = [unidad(precio_uf=D(2600)), unidad(precio_uf=D(90000))]
    h = q.marcar_outliers(filas)
    assert h.severidad is q.Severidad.OK


def test_el_percentil_interpola() -> None:
    vals = [D(1), D(2), D(3), D(4)]
    assert q._percentil(vals, D("0.5")) == D("2.5")
    assert q._percentil(vals, D(0)) == D(1)
    assert q._percentil(vals, D(1)) == D(4)


# --------------------------------------------------------------------- duplicados


def test_dos_unidades_con_la_misma_clave_natural_fallan() -> None:
    h = q.duplicados_de_venta([unidad(), unidad()])
    assert h.severidad is q.Severidad.FALLA


def test_unidades_distintas_del_mismo_proyecto_no_son_duplicado() -> None:
    h = q.duplicados_de_venta([unidad(numero_unidad="101"), unidad(numero_unidad="102")])
    assert h.severidad is q.Severidad.OK


def comp(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "direccion_normalizada": "gran avenida 1234",
        "m2_utiles": 35.0,
        "dormitorios": 1,
        "arriendo_clp": 350000,
        "publicado_en": date(2026, 8, 1),
    }
    base.update(kw)
    return base


def test_el_mismo_aviso_republicado_en_30_dias_se_deduplica() -> None:
    """Dos corredores publicando el mismo depto inflarían el conteo que decide n>=8."""
    h = q.duplicados_de_arriendo([comp(), comp(publicado_en=date(2026, 8, 20))])
    assert h.severidad is q.Severidad.MARCA
    assert h.filas_afectadas == 1


def test_el_mismo_aviso_a_mas_de_30_dias_es_otro_arriendo() -> None:
    h = q.duplicados_de_arriendo([comp(), comp(publicado_en=date(2026, 10, 1))])
    assert h.severidad is q.Severidad.OK


# --------------------------------------------------------------------- anclas


def test_una_desviacion_mayor_al_20_por_ciento_falla_el_gate() -> None:
    """Contra la tabla Colliers de docs/00-hallazgos.md §3."""
    h = q.ancla_externa_uf_m2({"san-miguel": D("110")})  # referencia 71
    assert h.severidad is q.Severidad.FALLA
    assert "san-miguel" in h.detalle[0]


def test_una_desviacion_dentro_del_20_por_ciento_pasa() -> None:
    h = q.ancla_externa_uf_m2({"san-miguel": D("78"), "nunoa": D("85")})
    assert h.severidad is q.Severidad.OK


def test_una_comuna_sin_referencia_no_inventa_una() -> None:
    """§3.2: no se compara contra un número que no existe."""
    h = q.ancla_externa_uf_m2({"concepcion": D("55")})
    assert h.severidad is q.Severidad.ALERTA


def test_menos_de_ocho_comparables_van_a_nd() -> None:
    """D-008: n<8 ⇒ ND, sin imputar."""
    h = q.comparables_suficientes({("san-miguel/gran-avenida", "1D1B"): 5})
    assert h.severidad is q.Severidad.MARCA
    assert "ND" in h.mensaje


def test_reconciliacion_de_arriendo_alerta_pero_no_borra() -> None:
    h = q.reconciliacion_arriendo({"z1": D("10")}, {"z1": D("5")})
    assert h.severidad is q.Severidad.ALERTA
    assert "no se borra" in h.mensaje


# --------------------------------------------------------------------- orquestación


def lote(n: int, **kw: Any) -> list[dict[str, Any]]:
    """n unidades distintas entre si: mismo proyecto, numeros de unidad correlativos."""
    return [unidad(unidad_key=f"U{i}", numero_unidad=str(100 + i), **kw) for i in range(n)]


def test_el_reporte_completo_distingue_rojo_de_parcial() -> None:
    limpio = q.correr(lote(10), [comp()], AHORA)
    assert not limpio.falla and not limpio.parcial, str(limpio)

    parcial = q.correr(
        lote(5)
        + lote(5)[:0]
        + [
            unidad(unidad_key=f"V{i}", numero_unidad=str(200 + i), precio_uf=None) for i in range(5)
        ],
        [comp()],
        AHORA,
    )
    assert not parcial.falla and parcial.parcial
    assert "PARCIAL" in str(parcial)

    rojo = q.correr(lote(10, orientacion="fono@corredor.cl"), [comp()], AHORA)
    assert rojo.falla
    assert "ROJO" in str(rojo)


def test_diez_unidades_identicas_son_un_duplicado_no_un_lote_valido() -> None:
    """Lo que hizo caer el test anterior: la clave natural es (proyecto_id, numero_unidad)."""
    rep = q.correr([unidad()] * 10, [comp()], AHORA)
    assert rep.falla
    assert any(h.check == "duplicados_venta" for h in rep.hallazgos if not h.ok)
