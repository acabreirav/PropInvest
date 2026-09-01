"""API FastAPI del tablero — T-027.

Sirve el JSON que consume `static/index.html`. No calcula nada: eso vive en `servicio.py`.

## Dos reglas de serialización que no son cosméticas

**1. Ningún número de mercado sale sin su `evidence_level`.** El §7.5 lo exige y el §3.2 dice
por qué: un número sin nivel de evidencia es indistinguible de uno inventado. Acá se cumple
con `cifra()`, que envuelve valor y nivel en un solo objeto. Si un endpoint quisiera mandar un
`float` pelado de un dato de mercado, el test `test_ningun_numero_de_mercado_va_sin_evidencia`
lo caza.

**2. Los montos viajan como texto, no como `float`.** El §11 manda `Decimal` en el motor;
serializar a `float` metería error de coma flotante justo en el último paso, después de todo
el cuidado. El tablero formatea el texto y no hace aritmética con él.

## Niveles de evidencia que se emiten

- `V` · vino de una fuente, con URL y fecha. Precio, m², arriendo mediano.
- `D` · cálculo determinístico sobre valores `V`. Todo lo que produce el motor.
- `E` · supuesto de modelo declarado en `params.yml`. Vacancia, opex, inflación.

El motor produce `D` porque sus fórmulas son explícitas y auditables, pero **hereda el peor
nivel de sus entradas**: un cálculo sobre un supuesto `E` no puede ser mejor que `E`. Eso lo
resuelve `nivel_derivado()`.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from flujocero.api.servicio import COLUMNAS_PROCEDENCIA, Fila, Foto, Servicio

ESTATICOS = Path(__file__).resolve().parent / "static"

# Los componentes del modelo financiero que dependen de un supuesto `E` de params.yml. Un
# calculo que los use no puede declararse mejor que `E`, por explicita que sea su formula.
DEPENDE_DE_SUPUESTOS = ("vacancia", "opex", "inflacion", "seguros", "incobrabilidad")


def nivel_derivado(*entradas: str) -> str:
    """El nivel de evidencia de un cálculo es el PEOR de sus entradas.

    `V` + `V` -> `D`: un cálculo explícito sobre datos verificados es derivado.
    `V` + `E` -> `E`: si un supuesto entra en la fórmula, el resultado es un supuesto, por
    muy determinística que sea la aritmética. Redondear esto hacia arriba sería exactamente
    la mentira que el §3.2 prohíbe.
    """
    if "ND" in entradas:
        return "ND"
    if "E" in entradas:
        return "E"
    return "D"


def cifra(valor: Any, nivel: str, unidad: str = "") -> dict[str, Any] | None:
    """Un número con su nivel de evidencia. `None` se mantiene `None` — nunca se imputa.

    Los `Decimal` viajan como texto: convertirlos a `float` acá metería error de coma
    flotante en el último paso, justo después de que el motor los cuidó con `Decimal` (§11).
    """
    if valor is None:
        return None
    return {
        "valor": str(valor) if isinstance(valor, Decimal) else valor,
        "evidence_level": nivel,
        "unidad": unidad,
    }


def _fila_json(f: Fila) -> dict[str, Any]:
    u, ev = f.unidad, f.evaluacion
    # El precio y los m2 vienen de un aviso: `V`. Todo lo que sale del motor es `D`, salvo lo
    # que toca vacancia u opex, que son supuestos `E` de params.yml y arrastran su nivel.
    con_supuestos = nivel_derivado("V", "E")
    d = {
        "posicion": f.posicion,
        "unidad_key": u.unidad_key,
        "microzona_id": u.microzona_id,
        "comuna_id": u.comuna_id,
        "tipologia": u.tipologia,
        "precio_uf": cifra(u.precio_uf, "V", "UF"),
        "m2_utiles": cifra(u.m2_utiles, "V", "m²"),
        "uf_m2": cifra(u.precio_uf / u.m2_utiles, nivel_derivado("V", "V"), "UF/m²"),
        "arriendo_mensual_uf": cifra(u.arriendo_mensual_uf, "V", "UF"),
        "arriendo_n_comparables": u.arriendo_n_comparables,
        "es_vivienda_nueva": u.es_vivienda_nueva,
        "antiguedad_anios": u.antiguedad_anios,
        # --- lo que produce el motor
        "score": cifra(ev.score, con_supuestos, "0-1"),
        "score_desglose": {k: str(v) for k, v in ev.score_desglose.items()},
        # Los componentes del §12 que no variaron en todo el conjunto y por eso no entraron
        # al score. Sin esto la ficha muestra un desglose mas corto y nadie sabe por que:
        # el §7.5 exige que ningun numero aparezca sin decir de donde sale, y "no se midio"
        # es de donde sale la ausencia.
        "score_inertes": list(ev.score_inertes),
        "yield_bruto": cifra(ev.rentabilidad_bruta, nivel_derivado("V", "V"), "%"),
        "cap_rate": cifra(ev.cap_rate, con_supuestos, "%"),
        "dividendo_uf": cifra(ev.dividendo_total_uf, nivel_derivado("V", "E"), "UF/mes"),
        "btcf_mensual_uf": cifra(ev.btcf_mensual_uf, con_supuestos, "UF/mes"),
        "costo_tenencia_mensual_uf": cifra(ev.costo_tenencia_mensual_uf, con_supuestos, "UF/mes"),
        "amortizacion_mensual_uf": cifra(
            ev.amortizacion_mensual_uf, nivel_derivado("V", "E"), "UF/mes"
        ),
        # La metrica insignia. Es `E` y no `D` a proposito: sale de una biseccion sobre el
        # modelo completo, que incluye vacancia, opex e inflacion — los tres supuestos.
        "pie_flujo_cero_real": cifra(ev.pie_flujo_cero_real, con_supuestos, "%"),
        "pie_efectivo": cifra(ev.pie_efectivo, "D", "%"),
        "pie_minimo_exigido": cifra(ev.pie_minimo_exigido, "D", "%"),
        "tir_real_10a": cifra(ev.tir_real.get(10), con_supuestos, "%"),
        "dscr": cifra(ev.dscr, con_supuestos, "x"),
        "arriendo_equilibrio_uf": cifra(ev.arriendo_equilibrio_uf, con_supuestos, "UF/mes"),
        # --- por que el motor le dio o le nego cada beneficio
        "tasa_aplicada": cifra(ev.tasa_aplicada, "V", "%"),
        "subsidio_aplicado": ev.subsidio_aplicado,
        "motivo_sin_subsidio": ev.motivo_sin_subsidio,
        "fogaes_aplicado": ev.fogaes_aplicado,
        "motivo_sin_fogaes": ev.motivo_sin_fogaes,
        "dfl2_aplicado": ev.dfl2_aplicado,
        "motivo_sin_dfl2": ev.motivo_sin_dfl2,
        "procedencia_arriendo": (
            {
                "celda": f.procedencia_arriendo[0],
                "n_comparables": f.procedencia_arriendo[1],
                "mediana_uf": str(f.procedencia_arriendo[2]),
            }
            if f.procedencia_arriendo
            else None
        ),
    }
    if f.evaluacion.arriendo_equilibrio_real_uf is not None:
        # La cifra honesta del equilibrio: resuelta sobre el modelo completo, con el opex
        # creciendo con el arriendo. Solo la ficha la calcula (es una biseccion por unidad);
        # en el ranking masivo la clave no viaja — ausente, no null, para que nadie confunda
        # "no calculado" con un numero.
        d["arriendo_equilibrio_real_uf"] = cifra(
            f.evaluacion.arriendo_equilibrio_real_uf, "E", "UF/mes"
        )
    return d


def _foto_json(fo: Foto, filas: list[Fila]) -> dict[str, Any]:
    return {
        "filas": [_fila_json(f) for f in filas],
        "total_rankeable": len(fo.filas),
        "total_con_precio": fo.total_con_precio,
        "excluidas_por_regla": fo.excluidas_por_regla,
        "descartes_emparejamiento": fo.descartes_emparejamiento,
        "escenario": {
            "pie_pedido": str(fo.pie_pedido),
            "pies_efectivos": [str(x) for x in fo.pies_efectivos],
            "con_subsidio": fo.con_subsidio,
            "con_fogaes": fo.con_fogaes,
        },
        "uf": {"valor_clp": str(fo.valor_uf_clp), "fuente": fo.fuente_uf},
        "componentes_inertes": fo.componentes_inertes,
        "peso_inerte": str(fo.peso_inerte),
        "advertencias": fo.advertencias,
        "capacidades": fo.capacidades,
        "segundos_calculo": round(fo.segundos_calculo, 2),
    }


def crear_app(ruta_db: Path | None = None, servicio: Servicio | None = None) -> FastAPI:
    """La app. `servicio` entra por argumento para que los tests inyecten uno sobre una base
    de prueba, sin variables de entorno ni monkeypatching."""
    app = FastAPI(
        title="Flujo Cero",
        description="Ranking de oportunidades de inversión inmobiliaria, con procedencia.",
        version="1.0.0",
    )
    svc = servicio or Servicio(ruta_db)
    app.state.servicio = svc

    def _pie(pie: float | None) -> Decimal | None:
        if pie is None:
            return None
        if not 0 <= pie < 1:
            raise HTTPException(422, "el pie va entre 0 y 1 (0.2 = 20%)")
        return Decimal(str(pie))

    @app.get("/api/salud")
    def salud() -> dict[str, Any]:
        """Responde sin construir la foto: sirve para saber que el proceso esta vivo
        mientras el primer calculo todavia corre."""
        return {"ok": True, "fotos_en_cache": len(svc._fotos)}

    @app.get("/api/ranking")
    def ranking(
        pie: float | None = Query(None, description="0.2 = 20%. Omitir usa el del perfil"),
        top: int = Query(50, ge=1, le=1000),
        comuna: str | None = None,
        microzona: str | None = None,
        m2_min: float | None = None,
        m2_max: float | None = None,
        pie_cero_max: float | None = Query(
            None, description="solo unidades cuyo pie de flujo cero real no supere esto"
        ),
    ) -> dict[str, Any]:
        fo = svc.foto(_pie(pie))
        filas = fo.filas
        if comuna:
            filas = [f for f in filas if f.unidad.comuna_id == comuna]
        if microzona:
            filas = [f for f in filas if f.unidad.microzona_id == microzona]
        if m2_min is not None:
            filas = [f for f in filas if f.unidad.m2_utiles >= Decimal(str(m2_min))]
        if m2_max is not None:
            filas = [f for f in filas if f.unidad.m2_utiles <= Decimal(str(m2_max))]
        if pie_cero_max is not None:
            tope = Decimal(str(pie_cero_max))
            # Una unidad que NUNCA llega a flujo cero se cae de este filtro, no se cuela por
            # tener `None`: "no llega nunca" es peor que cualquier tope, no mejor.
            filas = [
                f
                for f in filas
                if f.evaluacion.pie_flujo_cero_real is not None
                and f.evaluacion.pie_flujo_cero_real <= tope
            ]
        datos = _foto_json(fo, filas[:top])
        datos["total_filtrado"] = len(filas)
        return datos

    @app.get("/api/unidad/{unidad_key}")
    def unidad(unidad_key: str, pie: float | None = None) -> dict[str, Any]:
        f = svc.fila(unidad_key, _pie(pie))
        if f is None:
            raise HTTPException(404, f"{unidad_key} no está en el ranking")
        d = _fila_json(f)
        # Las SEIS columnas del §3.1, del dato crudo y no de lo que el motor recordo.
        d["procedencia"] = [
            {k: (str(v) if v is not None else None) for k, v in fila.items()}
            for fila in svc.procedencia(unidad_key)
        ]
        d["columnas_procedencia"] = list(COLUMNAS_PROCEDENCIA)
        return d

    @app.get("/api/microzonas")
    def microzonas(pie: float | None = None) -> dict[str, Any]:
        fo = svc.foto(_pie(pie))
        return {
            "microzonas": [
                {
                    **{k: v for k, v in d.items() if not isinstance(v, Decimal)},
                    "uf_m2_mediana": cifra(d["uf_m2_mediana"], nivel_derivado("V", "V"), "UF/m²"),
                    "pie_cero_minimo": cifra(d["pie_cero_minimo"], nivel_derivado("V", "E"), "%"),
                }
                for d in svc.microzonas(_pie(pie))
            ],
            "capacidades": fo.capacidades,
        }

    if ESTATICOS.is_dir():

        @app.get("/")
        def raiz() -> FileResponse:
            return FileResponse(ESTATICOS / "index.html")

        app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    return app


app = crear_app()

__all__ = ["app", "cifra", "crear_app", "nivel_derivado"]
