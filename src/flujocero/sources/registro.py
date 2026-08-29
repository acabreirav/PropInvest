"""Registro de fuentes: qué colector parsea qué `source_id`, y cómo carga sus filas.

Existe para que `make rebuild --from-raw` pueda recorrer la zona cruda y reconstruir las
tablas analíticas sin saber de antemano qué hay adentro (§3.6). Sin este mapa, reconstruir
exigiría un `if` por fuente repartido por la CLI.

Un `source_id` sin entrada acá NO se reconstruye: se reporta y se deja intacto en la zona
cruda. Nunca se descarta un blob por no saber leerlo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flujocero.sources.base import RawDoc


@dataclass(frozen=True)
class EntradaRegistro:
    """Cómo reconstruir una fuente desde sus blobs crudos."""

    source_id: str
    tabla: str
    parse: Callable[[RawDoc], list[Any]]
    cargar: Callable[[Any, list[Any]], int]
    descripcion: str


def _cmf_indicadores() -> EntradaRegistro:
    from flujocero.sources.cmf_indicadores import CmfIndicadores, cargar_en_duckdb

    # Sin apikey ni user-agent reales: reconstruir no toca la red, solo parsea lo guardado.
    colector = CmfIndicadores(apikey="no-se-usa-al-reconstruir", user_agent="rebuild")
    return EntradaRegistro(
        source_id="cmf_indicadores",
        tabla="dim_tiempo_financiero",
        parse=colector.parse,
        cargar=cargar_en_duckdb,
        descripcion="UF, UTM e IPC desde la CMF",
    )


def _cmf_tasas() -> EntradaRegistro:
    from flujocero.sources.cmf_tasas_hipotecarias import CmfTasasHipotecarias, cargar_en_duckdb

    colector = CmfTasasHipotecarias(user_agent="rebuild")
    return EntradaRegistro(
        source_id="cmf_tasas_hipotecarias",
        tabla="dim_tasa_banco",
        parse=colector.parse,
        cargar=cargar_en_duckdb,
        descripcion="tasas hipotecarias por banco",
    )


def _portal_legado() -> EntradaRegistro:
    from flujocero.sources.portal_legado import SOURCE_ID, PortalLegado, cargar_en_duckdb

    # Reconstruir no vuelve a leer la carpeta del usuario: los documentos ya estan en la zona
    # cruda, anonimizados. `origen` apunta a un directorio inexistente a proposito.
    colector = PortalLegado(origen=Path("/reconstruir-no-lee-el-origen"))
    return EntradaRegistro(
        source_id=SOURCE_ID,
        tabla="fact_unidad_venta + fact_arriendo_comp",
        parse=colector.parse,
        cargar=cargar_en_duckdb,
        descripcion="foto de Portal Inmobiliario de mayo-2026 (legado del usuario)",
    )


# La construcción es perezosa: importar el registro no debe arrastrar todos los colectores.
_CONSTRUCTORES: dict[str, Callable[[], EntradaRegistro]] = {
    "cmf_indicadores": _cmf_indicadores,
    "portal_legado_2026_05": _portal_legado,
    "cmf_tasas_hipotecarias": _cmf_tasas,
}


def entrada(source_id: str) -> EntradaRegistro | None:
    """La entrada de esta fuente, o `None` si no se sabe reconstruirla."""
    constructor = _CONSTRUCTORES.get(source_id)
    return constructor() if constructor else None


def fuentes_conocidas() -> list[str]:
    return sorted(_CONSTRUCTORES)
