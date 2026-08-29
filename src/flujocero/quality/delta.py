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
            f"  ya no estan       : {self.desaparecidas}   (un aviso desaparece al venderse)",
            f"  nuevas            : {self.nuevas}",
        ]
        if self.bajaron:
            lineas.append("\n  Las que mas bajaron:")
            for c in self.bajaron[:10]:
                lineas.append(
                    f"    {c.unidad_key:18s} UF {c.precio_antes_uf:>8,.0f} -> "
                    f"{c.precio_ahora_uf:>8,.0f}  {c.variacion:+7.1%}   {c.microzona_id or '-'}"
                )
        return "\n".join(lineas)


def comparar(conexion: Any, corte: datetime) -> Reporte:
    """Cruza el estado del mercado antes y después de `corte`, sobre `fact_unidad_venta`.

    **La clasificación va por fechas, no por `source_id`.** Cuando una unidad sigue publicada
    al mismo precio, el cargador actualiza su procedencia a la captura de hoy: la fila deja de
    "ser del legado" aunque se haya visto por primera vez en mayo. Clasificar por fuente diría
    que esa unidad desapareció, que es exactamente lo contrario de lo que pasó.

    Lo que separa los cuatro casos son dos fechas que el SCD tipo 2 ya guarda:
    `valid_from` (cuándo se vio por primera vez a este precio) y `fetched_at` (cuándo se
    confirmó por última vez).
    """
    cambios = [
        CambioDePrecio(*fila)
        for fila in conexion.execute(
            """
            SELECT v.unidad_key, n.microzona_id, n.m2_utiles,
                   v.precio_uf, n.precio_uf, v.valid_from, n.valid_from
            FROM fact_unidad_venta v
            JOIN fact_unidad_venta n USING (unidad_key)
            WHERE v.valid_to IS NOT NULL AND n.valid_to IS NULL
              AND n.valid_from >= ?
            """,
            (corte,),
        ).fetchall()
    ]

    def contar(condicion: str) -> int:
        return int(
            conexion.execute(
                f"SELECT count(*) FROM fact_unidad_venta WHERE valid_to IS NULL AND {condicion}",
                (corte, corte),
            ).fetchone()[0]
        )

    capturas_previas = int(
        conexion.execute(
            "SELECT count(DISTINCT valid_from::DATE) FROM fact_unidad_venta WHERE valid_from < ?",
            (corte,),
        ).fetchone()[0]
    )

    return Reporte(
        cambios=cambios,
        capturas_previas=capturas_previas,
        # Estaba antes del corte y ninguna captura nueva la toco: se cayo del portal.
        desaparecidas=contar("valid_from < ? AND fetched_at < ?"),
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
    )
