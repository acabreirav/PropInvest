"""Delta de precios entre dos fotos del mercado — T-919. Funciones puras sobre SQL.

El §11 pide SCD tipo 2 con una razón concreta: poder responder *"¿cuándo bajó el precio de
esta unidad?"*, que el contrato declara señal de compra. Este módulo es esa pregunta escrita.

No hay magia: el cargador ya cierra la versión anterior cuando el precio cambia, así que el
historial existe solo con haber corrido el colector dos veces. Lo que falta es leerlo.

**Un aviso desaparece del portal cuando se vende.** Por eso "estaba en mayo y hoy no está" no
es un dato perdido: es la señal más fuerte que produce este cruce, y solo se puede obtener si
alguien guardó la foto vieja. La de mayo-2026 viene del proyecto anterior del usuario y no se
puede volver a tomar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CambioDePrecio:
    unidad_key: str
    microzona_id: str | None
    m2_utiles: float | None
    precio_antes_uf: Decimal
    precio_ahora_uf: Decimal
    visto_antes: datetime
    visto_ahora: datetime

    @property
    def variacion(self) -> Decimal:
        """Fracción. Negativa = bajó."""
        if not self.precio_antes_uf:
            return Decimal(0)
        return (self.precio_ahora_uf - self.precio_antes_uf) / self.precio_antes_uf


@dataclass
class Reporte:
    cambios: list[CambioDePrecio]
    desaparecidas: int
    nuevas: int
    sin_cambio: int
    corte: datetime
    # Unidades viejas en microzonas que la corrida nueva NO toco. No desaparecieron: no se
    # volvieron a mirar. Se cuentan aparte para que nadie las lea como ventas.
    fuera_de_alcance: int = 0
    microzonas_revisadas: int = 0
    # Unidades que la foto vieja tenia dentro del alcance, contra las que la corrida nueva
    # encontro ahi. Si la corrida trajo menos, la paginacion quedo corta y "ya no estan"
    # cuenta unidades que siguen publicadas en una pagina que nadie pidio.
    vistas_antes_en_alcance: int = 0
    vistas_ahora_en_alcance: int = 0

    @property
    def cobertura(self) -> float:
        if not self.vistas_antes_en_alcance:
            return 1.0
        return self.vistas_ahora_en_alcance / self.vistas_antes_en_alcance

    # Cuantas fechas de captura distintas hay antes del corte. Cero significa que todo lo
    # cargado es de una sola foto y que el informe, aunque tenga numeros, no compara nada.
    capturas_previas: int = 0

    @property
    def comparable(self) -> bool:
        return self.capturas_previas > 0

    @property
    def bajaron(self) -> list[CambioDePrecio]:
        return sorted((c for c in self.cambios if c.variacion < 0), key=lambda c: c.variacion)

    @property
    def subieron(self) -> list[CambioDePrecio]:
        return sorted(
            (c for c in self.cambios if c.variacion > 0), key=lambda c: c.variacion, reverse=True
        )

    def _nota_desaparecidas(self) -> str:
        """Un aviso desaparece cuando se vende — pero solo si de verdad se volvio a mirar."""
        if self.cobertura >= 0.9:
            return "(un aviso desaparece al venderse)"
        return (
            f"<- POCO FIABLE: la corrida nueva trajo {self.cobertura:.0%} de las unidades\n"
            f"                      que la foto vieja tenia en esas mismas microzonas. La\n"
            f"                      mayoria de estas sigue publicada en una pagina que no se\n"
            f"                      pidio. Subi --paginas para que el numero signifique algo."
        )

    def __str__(self) -> str:
        if not self.comparable:
            # Sin una foto anterior, "todo es nuevo" es una tautologia, no un hallazgo.
            # Decirlo asi evita que alguien lea 266 oportunidades donde solo hay 266 avisos.
            return (
                f"Delta del mercado, corte {self.corte:%d-%m-%Y}\n"
                f"  NO HAY CON QUE COMPARAR: todo lo cargado es de una sola captura.\n"
                f"  Las {self.nuevas} unidades no son nuevas en el mercado; son simplemente\n"
                f"  todas las que hay. Para que este informe signifique algo hace falta una\n"
                f"  foto anterior: `ingerir-legado` trae la de mayo-2026."
            )
        lineas = [
            f"Delta del mercado, corte {self.corte:%d-%m-%Y}",
            f"  bajaron de precio : {len(self.bajaron)}",
            f"  subieron          : {len(self.subieron)}",
            f"  sin cambio        : {self.sin_cambio}",
            f"  ya no estan       : {self.desaparecidas}   {self._nota_desaparecidas()}",
            f"  nuevas            : {self.nuevas}",
            f"\n  alcance: {self.microzonas_revisadas} microzonas re-revisadas.",
        ]
        if self.fuera_de_alcance:
            lineas.append(
                f"  {self.fuera_de_alcance} unidades de la foto vieja quedaron FUERA de esa\n"
                f"  corrida. No desaparecieron: no se volvieron a mirar. Para incluirlas hay\n"
                f"  que recolectar sus comunas con mas paginas."
            )
        if self.bajaron:
            lineas.append("\n  Las que mas bajaron:")
            for c in self.bajaron[:10]:
                uf_m2 = (
                    f"{c.precio_ahora_uf / Decimal(str(c.m2_utiles)):>5,.0f} UF/m2"
                    if c.m2_utiles
                    else "     sin m2"
                )
                lineas.append(
                    f"    {c.unidad_key:18s} UF {c.precio_antes_uf:>8,.0f} -> "
                    f"{c.precio_ahora_uf:>8,.0f}  {c.variacion:+7.1%}  {uf_m2}  "
                    f"{c.microzona_id or 'sin microzona'}"
                )
        return "\n".join(lineas)


def comparar(conexion: Any, corte: datetime) -> Reporte:
    """Cruza el estado del mercado antes y despues de `corte`, sobre `fact_unidad_venta`.

    **La clasificacion va por fechas, no por `source_id`.** Cuando una unidad sigue publicada
    al mismo precio, el cargador actualiza su procedencia a la captura de hoy: la fila deja de
    "ser del legado" aunque se haya visto por primera vez en mayo. Clasificar por fuente diria
    que esa unidad desaparecio, que es exactamente lo contrario de lo que paso.

    **Y se compara solo dentro del alcance re-revisado.** Una unidad de mayo en una microzona
    que la corrida nueva no toco no "desaparecio": no se volvio a mirar. Contarla como vendida
    inflo el informe del usuario a 2.691 desapariciones cuando solo habia recolectado tres
    comunas y dos paginas de cada una. Un numero que mide el alcance de la corrida disfrazado
    de senal de mercado es peor que no tener el numero.
    """
    # Microzonas que la captura nueva efectivamente toco.
    alcance = {
        f[0]
        for f in conexion.execute(
            "SELECT DISTINCT microzona_id FROM fact_unidad_venta "
            "WHERE fetched_at >= ? AND microzona_id IS NOT NULL",
            (corte,),
        ).fetchall()
    }

    cambios = [
        CambioDePrecio(*fila)
        for fila in conexion.execute(
            """
            -- Una fila por unidad: el cambio NETO desde su version mas antigua hasta la
            -- vigente. Sin el `QUALIFY`, una unidad con dos versiones cerradas aparecia dos
            -- veces en la lista de bajadas, y se lee como dos oportunidades donde hay una.
            SELECT v.unidad_key, n.microzona_id, n.m2_utiles,
                   v.precio_uf, n.precio_uf, v.valid_from, n.valid_from
            FROM fact_unidad_venta v
            JOIN fact_unidad_venta n USING (unidad_key)
            WHERE v.valid_to IS NOT NULL AND n.valid_to IS NULL
              AND n.valid_from >= ?
            QUALIFY row_number() OVER (PARTITION BY v.unidad_key ORDER BY v.valid_from) = 1
            """,
            (corte,),
        ).fetchall()
    ]

    def contar(condicion: str, *extra: Any) -> int:
        return int(
            conexion.execute(
                f"SELECT count(*) FROM fact_unidad_venta WHERE valid_to IS NULL AND {condicion}",
                (corte, corte, *extra),
            ).fetchone()[0]
        )

    dentro = "list_contains(?::VARCHAR[], microzona_id)" if alcance else "FALSE"
    lista = [sorted(alcance)] if alcance else []

    def contar_en_alcance(condicion: str) -> int:
        if not alcance:
            return 0
        return int(
            conexion.execute(
                "SELECT count(*) FROM fact_unidad_venta WHERE valid_to IS NULL "
                f"AND list_contains(?::VARCHAR[], microzona_id) AND {condicion}",
                (sorted(alcance), corte),
            ).fetchone()[0]
        )

    return Reporte(
        cambios=cambios,
        vistas_antes_en_alcance=contar_en_alcance("valid_from < ?"),
        vistas_ahora_en_alcance=contar_en_alcance("fetched_at >= ?"),
        # Estaba antes del corte, en una microzona QUE SI se volvio a revisar, y ninguna
        # captura nueva la toco. Esa es la senal: un aviso desaparece cuando se vende.
        desaparecidas=contar(f"valid_from < ? AND fetched_at < ? AND {dentro}", *lista),
        # Estaba antes y quedo fuera del alcance de la corrida nueva. No dice nada del mercado.
        fuera_de_alcance=contar(f"valid_from < ? AND fetched_at < ? AND NOT ({dentro})", *lista),
        # Aparecio despues del corte **y no tiene historia**. La condicion de la version
        # cerrada no es un detalle: una unidad que bajo de precio tambien tiene su version
        # vigente naciendo hoy, y sin este filtro se contaba dos veces —como cambio de precio
        # y como aviso nuevo—, inflando el universo con unidades que ya estaban.
        nuevas=contar(
            "valid_from >= ? AND fetched_at >= ? AND NOT EXISTS ("
            "  SELECT 1 FROM fact_unidad_venta h"
            "  WHERE h.unidad_key = fact_unidad_venta.unidad_key AND h.valid_to IS NOT NULL)"
        ),
        # Estaba antes y sigue, al mismo precio.
        sin_cambio=contar("valid_from < ? AND fetched_at >= ?"),
        corte=corte,
        capturas_previas=int(
            conexion.execute(
                "SELECT count(DISTINCT valid_from::DATE) FROM fact_unidad_venta "
                "WHERE valid_from < ?",
                (corte,),
            ).fetchone()[0]
        ),
        microzonas_revisadas=len(alcance),
    )
