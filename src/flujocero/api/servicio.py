"""Capa de servicio del dashboard — T-027.

Separa el *qué se muestra* del *cómo se sirve*. La API HTTP de `app.py` no toca DuckDB ni el
motor: le pide a este módulo una foto ya calculada y la serializa.

## El problema de rendimiento, y por qué se resuelve acá y no en la API

El gate §7.5 pide que el tablero cargue en menos de 3 s. Calcular el ranking cuesta **~90 s
sobre mil unidades**, casi todo en la bisección que busca el pie de flujo cero de cada una
(T-923). Servir eso por petición es imposible.

Dos observaciones lo arreglan:

1. **La bisección no depende del pie pedido.** Busca el pie donde el flujo cruza cero, así
   que mover el control del pie no cambia su resultado. Se cachea por unidad.
2. **Sí depende del resto del escenario** — tasa, vacancia, plazo, DFL2. Por eso la caché se
   indexa por la firma del escenario *sin* el pie, y cualquier cambio en lo demás la invalida
   sola en vez de devolver un número viejo.

Resultado: la primera foto cuesta lo que cuesta y queda dicho en `segundos_calculo`; mover el
pie después es una re-evaluación sin bisección, del orden de milisegundos.

## Lo que este módulo NO hace

No inventa geometría. `dim_microzona.geom` está vacío en las 165 microzonas y
`fact_unidad_venta` no guarda coordenadas, así que **no hay mapa que dibujar**. El §7.5 lo
pide y no se puede cumplir todavía; se reporta en `capacidades.mapa` como `False` con su
razón, y el tablero muestra por qué falta en vez de dibujar puntos inventados.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from flujocero.agg import oportunidades as op
from flujocero.alcance import desde_config
from flujocero.config import cargar, con_valor, uf_desde_la_base
from flujocero.finance.escenarios import escenario_base, evaluar_universo
from flujocero.finance.modelo import Evaluacion, Unidad

# Las seis columnas del §3.1. Se importan de `base` en vez de repetirse: una segunda lista
# que se pueda desincronizar de la que usa el gate seria justo lo que el §3.1 quiere evitar.
from flujocero.sources.base import COLUMNAS_PROCEDENCIA

D = Decimal


@dataclass(frozen=True)
class Fila:
    """Una unidad rankeada, con todo lo que la ficha necesita mostrar."""

    unidad: Unidad
    evaluacion: Evaluacion
    posicion: int
    procedencia_arriendo: tuple[str, int, Decimal] | None


@dataclass
class Foto:
    """El estado completo que la API sirve. Inmutable una vez construida."""

    filas: list[Fila] = field(default_factory=list)
    excluidas_por_regla: dict[str, int] = field(default_factory=dict)
    descartes_emparejamiento: dict[str, int] = field(default_factory=dict)
    total_con_precio: int = 0
    componentes_inertes: list[str] = field(default_factory=list)
    peso_inerte: Decimal = D(0)
    pie_pedido: Decimal = D(0)
    pies_efectivos: list[Decimal] = field(default_factory=list)
    con_subsidio: int = 0
    con_fogaes: int = 0
    valor_uf_clp: Decimal = D(0)
    fuente_uf: str = ""
    segundos_calculo: float = 0.0
    capacidades: dict[str, Any] = field(default_factory=dict)
    advertencias: list[str] = field(default_factory=list)


def _capacidades(conexion: Any) -> dict[str, Any]:
    """Qué puede y qué no puede mostrar el tablero HOY, con la razón.

    Existe para que la interfaz no tenga que adivinar ni fingir. Un tablero que dibuja un
    mapa vacío es peor que uno que dice "todavía no hay geometría, falta el Censo".
    """
    con_geom = conexion.execute(
        "SELECT count(*) FROM dim_microzona WHERE geom IS NOT NULL"
    ).fetchone()[0]
    total_mz = conexion.execute("SELECT count(*) FROM dim_microzona").fetchone()[0]
    return {
        "mapa": bool(con_geom),
        "mapa_razon": (
            ""
            if con_geom
            else (
                f"0 de {total_mz} microzonas tienen geometría y los avisos no traen "
                "coordenadas. Se destraba con el Censo 2024 por manzanas del INE (T-014). "
                "No se dibuja un mapa aproximado: una microzona mal ubicada es peor que "
                "ninguna, porque el §2.4 dice que la microzona ES la unidad de análisis."
            )
        ),
        "microzonas": total_mz,
    }


class Servicio:
    """Construye y cachea la foto. Una instancia por proceso.

    No es thread-safe a propósito: uvicorn en un worker corre un event loop, y las funciones
    de ruta llaman a esto de forma síncrona. Si algún día hay varios workers, cada uno tendrá
    su caché y eso está bien — la foto es determinística sobre la misma base.
    """

    def __init__(self, ruta_db: Path | None = None) -> None:
        self.ruta_db = ruta_db
        self._fotos: dict[str, Foto] = {}
        # `unidad_key -> pie de flujo cero`, compartida entre pies porque no depende de el.
        self._pie_cero: dict[str, dict[str, Decimal | None]] = {}

    # ------------------------------------------------------------------ interno

    def _conectar(self) -> Any:
        import duckdb

        from flujocero import db

        return duckdb.connect(str(self.ruta_db or db.crear()), read_only=False)

    @staticmethod
    def _firma_sin_pie(e: Any) -> str:
        """Todo lo que SÍ cambia la bisección. El pie queda fuera a propósito.

        Dos cosas que hay que tener presentes acá, y las dos muerden:

        **`escenario_id` NO entra**, aunque sea el identificador obvio: se construye como
        `pie20`, `pie40`… o sea que *codifica el pie*. Meterlo daría una firma distinta por
        cada pie y anularía la caché entera sin que nada fallara — solo estaría lenta.

        **El plazo y los supuestos no viven en el escenario, viven en los YAML.** Un cambio
        en `params.yml` —el plazo, la vacancia base, el opex, la inflación— cambia el pie de
        flujo cero y no toca ningún campo del escenario. Por eso entra el hash de los dos
        archivos de configuración: sin él, editar un supuesto dejaría la caché sirviendo
        números viejos, que es peor que servirlos lentos.
        """
        import hashlib

        from flujocero.config import RAIZ

        h = hashlib.sha256()
        for nombre in ("params.yml", "inversionista.yml"):
            ruta = RAIZ / "config" / nombre
            if ruta.is_file():
                h.update(ruta.read_bytes())
        campos = (
            e.tasa_anual,
            e.tasa_sin_subsidio,
            e.con_subsidio,
            e.con_fogaes,
            e.dfl2,
            e.vacancia,
        )
        return "|".join(str(x) for x in campos) + "|" + h.hexdigest()[:16]

    # ------------------------------------------------------------------ público

    def foto(self, pie: Decimal | None = None, refrescar: bool = False) -> Foto:
        """La foto para este pie. La primera cuesta la bisección; las siguientes no."""
        clave = str(pie if pie is not None else "perfil")
        if not refrescar and clave in self._fotos:
            return self._fotos[clave]
        f = self._construir(pie)
        self._fotos[clave] = f
        return f

    def fila(self, unidad_key: str, pie: Decimal | None = None) -> Fila | None:
        return next((f for f in self.foto(pie).filas if f.unidad.unidad_key == unidad_key), None)

    def invalidar(self) -> None:
        """Bota todo lo cacheado. Se llama cuando la base cambió bajo nuestros pies."""
        self._fotos.clear()
        self._pie_cero.clear()

    def procedencia(self, unidad_key: str) -> list[dict[str, Any]]:
        """Las seis columnas del §3.1 de esta unidad, tal como están en la base.

        Se leen en la consulta y no desde la foto porque la ficha tiene que mostrar el dato
        crudo: si algún día el emparejamiento pierde una columna por el camino, queremos que
        la ficha lo delate en vez de repetir lo que el motor creyó.
        """
        con = self._conectar()
        try:
            columnas = ", ".join(COLUMNAS_PROCEDENCIA)
            filas = con.execute(
                f"SELECT {columnas}, valid_from, valid_to, evidence_level "  # noqa: S608
                "FROM fact_unidad_venta WHERE unidad_key = ? ORDER BY valid_from DESC",
                (unidad_key,),
            ).fetchall()
        finally:
            con.close()
        nombres = (*COLUMNAS_PROCEDENCIA, "valid_from", "valid_to", "evidence_level")
        return [dict(zip(nombres, f, strict=True)) for f in filas]

    def microzonas(self, pie: Decimal | None = None) -> list[dict[str, Any]]:
        """Resumen por microzona sobre las unidades que SÍ rankean.

        Es lo que reemplaza al mapa mientras no haya geometría: la misma pregunta —dónde
        están las oportunidades— respondida con una tabla en vez de con colores.
        """
        f = self.foto(pie)
        agrupado: dict[str, dict[str, Any]] = {}
        for fila in f.filas:
            mz = fila.unidad.microzona_id
            d = agrupado.setdefault(
                mz,
                {
                    "microzona_id": mz,
                    "comuna_id": fila.unidad.comuna_id,
                    "n": 0,
                    "uf_m2": [],
                    "pie_cero": [],
                    "arriendo_n": fila.unidad.arriendo_n_comparables,
                },
            )
            d["n"] += 1
            d["uf_m2"].append(fila.unidad.precio_uf / fila.unidad.m2_utiles)
            if fila.evaluacion.pie_flujo_cero_real is not None:
                d["pie_cero"].append(fila.evaluacion.pie_flujo_cero_real)
        salida = []
        for d in agrupado.values():
            ufm2 = sorted(d.pop("uf_m2"))
            pies = sorted(d.pop("pie_cero"))
            d["uf_m2_mediana"] = ufm2[len(ufm2) // 2] if ufm2 else None
            d["pie_cero_minimo"] = pies[0] if pies else None
            salida.append(d)
        salida.sort(key=lambda d: (d["pie_cero_minimo"] is None, d["pie_cero_minimo"]))
        return salida

    # ------------------------------------------------------------------ construcción

    def _construir(self, pie: Decimal | None) -> Foto:
        t0 = time.monotonic()
        p, inv = cargar("params"), cargar("inversionista")
        con = self._conectar()
        try:
            real = uf_desde_la_base(con)
            capacidades = _capacidades(con)
            emp = op.emparejar(
                con, p.crudo("ingresos.rangos_m2"), alcance=desde_config(cargar("zonas"))
            )
        finally:
            con.close()

        fuente_uf = "params.yml (no hay serie de UF cargada)"
        if real is not None:
            valor, fuente_uf = real
            p = con_valor(p, "macro.valor_uf_clp", float(valor), fuente_uf)

        e = escenario_base(p, inv)
        if pie is not None:
            e = replace(e, pie_pct=pie, escenario_id=f"pie{int(pie * 100)}")

        firma = self._firma_sin_pie(e)
        cache = self._pie_cero.setdefault(firma, {})
        evals = evaluar_universo(
            emp.unidades, e, p, inv, pie_exacto=True, pie_cero_precalculado=cache
        )
        for u, ev in zip(emp.unidades, evals, strict=True):
            if not ev.excluido:
                cache[u.unidad_key] = ev.pie_flujo_cero_real

        vivos = [(u, ev) for u, ev in zip(emp.unidades, evals, strict=True) if not ev.excluido]
        vivos.sort(key=lambda x: -x[1].score)

        from collections import Counter

        reglas = Counter(
            (ev.motivo_exclusion or "").split(":")[0].split(" UF ")[0].split(" de caja ")[0]
            for ev in evals
            if ev.excluido
        )

        inertes = op.componentes_inertes(emp.unidades)
        advertencias: list[str] = []
        if inertes:
            advertencias.append(
                f"{op.peso_inerte(inertes, p):.0%} del score está inerte: "
                f"{', '.join(inertes)} no tienen fuente todavía (T-014). Reparten el mismo "
                "puntaje a cada unidad y no mueven una sola posición del ranking."
            )
        if not capacidades["mapa"]:
            advertencias.append(capacidades["mapa_razon"])

        cabeza = vivos[:15]
        chicas = [u for u, _ in cabeza if u.m2_utiles < 35]
        # `chicas` tiene que ser un tercio o mas de la cabeza, y la cabeza tiene que existir.
        # Sin el `chicas and`, con el ranking vacio salia "0 de las 15 primeras son de menos
        # de 35 m2": una advertencia sobre unidades que no hay.
        if chicas and len(chicas) * 3 >= len(cabeza):
            advertencias.append(
                f"{len(chicas)} de las {len(cabeza)} primeras son de menos de 35 m². El §13.3 "
                "advierte "
                "que los retornos de dos dígitos del mercado chileno son stock usado chico y "
                "barato: más rotación, más vacancia, gastos comunes más altos por m² y mucha "
                "menos liquidez de salida. El ranking no mide nada de eso (T-924)."
            )

        return Foto(
            filas=[
                Fila(
                    unidad=u,
                    evaluacion=ev,
                    posicion=i + 1,
                    procedencia_arriendo=emp.procedencia_arriendo.get(u.unidad_key),
                )
                for i, (u, ev) in enumerate(vivos)
            ],
            excluidas_por_regla=dict(reglas.most_common()),
            descartes_emparejamiento={k: v for k, v in emp.descartes.items() if v},
            total_con_precio=emp.total,
            componentes_inertes=inertes,
            peso_inerte=op.peso_inerte(inertes, p) if inertes else D(0),
            pie_pedido=e.pie_pct,
            pies_efectivos=sorted({ev.pie_efectivo for _, ev in vivos}),
            con_subsidio=sum(1 for _, ev in vivos if ev.subsidio_aplicado),
            con_fogaes=sum(1 for _, ev in vivos if ev.fogaes_aplicado),
            valor_uf_clp=p.d("macro.valor_uf_clp"),
            fuente_uf=fuente_uf,
            segundos_calculo=time.monotonic() - t0,
            capacidades=capacidades,
            advertencias=advertencias,
        )


__all__ = ["COLUMNAS_PROCEDENCIA", "Fila", "Foto", "Servicio"]
