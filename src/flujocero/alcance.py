"""Qué comunas y microzonas están DENTRO del alcance — T-938.

Existe porque tres partes del sistema necesitaban esta respuesta y ninguna la tenía, con
consecuencias distintas y una de ellas grave.

## Los tres agujeros que cierra

**1. El §12 tiene una exclusión dura que nunca se aplicaba.** `params.yml` declara
`excluir_microzonas_saturadas: true` y `modelo.py` la implementa contra
`Unidad.microzona_saturada` — pero `oportunidades.emparejar()`, que es el único camino por el
que pasan las unidades reales, **nunca poblaba ese campo**. Quedaba en su default `False` y la
regla no se disparaba jamás. Solo funcionaba en `demo`, sobre unidades inventadas.

El caso concreto que lo destapó: `nunoa/estadio-nacional` está marcada `saturada` en
`zonas.yml` con evidencia Tattersall, y es justo la microzona con más comparables de arriendo
que tenemos (n=124). O sea que la regla que más importaba desactivar estaba desactivada
exactamente donde más datos hay.

**2. La recolección dirigida mandaba corridas a comunas excluidas.** `--dirigida 3` eligió
Ñuñoa, Providencia y Macul por volumen de unidades esperando. **Providencia está en
`excluidas`** —"2D2B en UF 8.921, sobre el tope; yield 3,0-3,5%"— así que un tercio de esa
corrida se gastó recolectando arriendo para unidades que el motor nunca va a rankear.

**3. El diagnóstico de huecos contaba como "desbloqueables" unidades que no lo son.** Una
unidad en una comuna excluida o en una microzona saturada no se desbloquea con comparables
de arriendo: se descarta por regla dura después. Contarla infla el objetivo y desvía el
esfuerzo.

## La regla

`zonas.yml` es la fuente única. Una comuna está dentro si aparece en `fase_1`, `fase_2` o
`fase_3`; está fuera si aparece en `excluidas`. Una comuna que no aparece en ninguna parte
**está fuera**: el alcance es una lista blanca, no una lista negra. Es lo que corresponde
cuando el colector puede traer cualquier comuna del portal y el contrato define un alcance
explícito por fases (§10).

Las microzonas `saturadas` se declaran por su nombre corto bajo su comuna y acá se
convierten al `microzona_id` completo (`nunoa/estadio-nacional`), que es la forma con la que
viajan por el resto del sistema.

Módulo puro: lee un `Config` ya cargado y responde. Sin I/O propio, sin reloj.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FASES = ("fase_1", "fase_2", "fase_3")


@dataclass(frozen=True)
class Alcance:
    """La respuesta a "¿esto entra?", con su razón cuando no entra."""

    comunas: frozenset[str] = field(default_factory=frozenset)
    excluidas: dict[str, str] = field(default_factory=dict)
    saturadas: frozenset[str] = field(default_factory=frozenset)
    fase_de: dict[str, int] = field(default_factory=dict)
    # `comuna -> slug de region que usa el PORTAL en su URL`. Sin esto el colector arma
    # `concepcion-metropolitana`, que no existe: el portal responde 200 con cero resultados
    # y la corrida "funciona" sin traer nada.
    region_de: dict[str, str] = field(default_factory=dict)

    def en_alcance(self, comuna_id: str | None) -> bool:
        """Lista BLANCA: lo que no está declarado en una fase, está fuera.

        Al revés —tratar "no aparece en excluidas" como permitido— cualquier comuna que el
        colector traiga de pasada entraría al ranking sin que nadie lo decidiera.
        """
        return bool(comuna_id) and comuna_id in self.comunas

    def razon_fuera(self, comuna_id: str | None) -> str | None:
        """Por qué esta comuna no entra. `None` si sí entra."""
        if self.en_alcance(comuna_id):
            return None
        if comuna_id in self.excluidas:
            return f"comuna excluida del alcance: {self.excluidas[comuna_id]}"
        return f"comuna {comuna_id!r} no esta declarada en ninguna fase de zonas.yml"

    def saturada(self, microzona_id: str | None) -> bool:
        return bool(microzona_id) and microzona_id in self.saturadas

    def region(self, comuna_id: str) -> str:
        """El slug de region que el portal usa para esta comuna. Default: metropolitana,
        que es donde estaba todo el alcance hasta que entro fase 3."""
        return self.region_de.get(comuna_id, "metropolitana")

    def comunas_de_fase(self, fase: int) -> list[tuple[str, str]]:
        """`[(comuna, region_slug)]` de una fase, que es lo que come el colector."""
        return sorted((c, self.region(c)) for c, f in self.fase_de.items() if f == fase)

    def comuna_de(self, microzona_id: str | None) -> str | None:
        return microzona_id.split("/")[0] if microzona_id else None

    def unidad_rankeable(self, microzona_id: str | None) -> tuple[bool, str | None]:
        """`(entra, razon_si_no)` para una microzona. Es lo que consultan el emparejamiento
        y el diagnóstico de huecos, para que los dos usen exactamente el mismo criterio."""
        if self.saturada(microzona_id):
            return False, f"microzona {microzona_id} marcada como saturada en zonas.yml"
        razon = self.razon_fuera(self.comuna_de(microzona_id))
        return (razon is None), razon


def _comunas_de(entrada: dict[str, Any]) -> list[str]:
    """Las comunas que aporta una entrada de fase.

    Fase 1 y 2 declaran una `comuna` cada una. **Fase 3 declara una `ciudad`**, que es una
    conurbación y no una comuna: "Gran Concepción" son cinco. El portal busca por comuna, así
    que esas entradas traen su lista en `comunas` y la `ciudad` queda como etiqueta.

    Tomar la `ciudad` como si fuera comuna —que es lo que hacía antes— dejaba **fase 3
    inalcanzable**: `gran-concepcion` no existe como comuna en ningún portal, así que el
    alcance la declaraba dentro y ninguna unidad podía calzar con ella jamás.
    """
    if entrada.get("comunas"):
        return [str(c) for c in entrada["comunas"]]
    unica = entrada.get("comuna") or entrada.get("ciudad")
    return [str(unica)] if unica else []


def desde_config(zonas: Any) -> Alcance:
    """Construye el alcance desde `config/zonas.yml` ya cargado."""
    comunas: set[str] = set()
    saturadas: set[str] = set()
    fase_de: dict[str, int] = {}
    region_de: dict[str, str] = {}

    for numero, clave in enumerate(FASES, start=1):
        try:
            entradas = zonas.crudo(clave)
        except Exception:  # noqa: BLE001 — una fase ausente es valida, no un error
            continue
        for entrada in entradas or []:
            propias = _comunas_de(entrada)
            if not propias:
                continue
            slug = str(entrada.get("region_slug") or "metropolitana")
            for nombre in propias:
                comunas.add(nombre)
                fase_de[nombre] = numero
                region_de[nombre] = slug
            for corta in entrada.get("saturadas") or []:
                # En el YAML van por nombre corto bajo su comuna; acá se arman con el
                # `microzona_id` completo, que es la forma con que viajan por el sistema.
                # Con varias comunas la saturada se aplica a todas. Hoy fase 3 no declara
                # ninguna; cuando declare habra que decir a que comuna pertenece.
                for nombre in propias:
                    saturadas.add(f"{nombre}/{corta}")

    excluidas: dict[str, str] = {}
    try:
        for entrada in zonas.crudo("excluidas") or []:
            zona = entrada.get("zona")
            if zona:
                excluidas[zona] = entrada.get("razon", "sin razon registrada")
    except Exception:  # noqa: BLE001 — sin bloque `excluidas` no hay nada que excluir
        pass

    # Una comuna en las dos listas es una contradiccion del YAML, no algo que resolver en
    # silencio: gana la exclusion, que es el lado conservador, y queda visible en el conteo.
    comunas -= set(excluidas)
    return Alcance(
        comunas=frozenset(comunas),
        excluidas=excluidas,
        saturadas=frozenset(saturadas),
        fase_de={k: v for k, v in fase_de.items() if k in comunas},
        region_de={k: v for k, v in region_de.items() if k in comunas},
    )


__all__ = ["FASES", "Alcance", "desde_config"]
