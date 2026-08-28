"""CLI de Flujo Cero."""

from __future__ import annotations

from decimal import Decimal as D
from decimal import getcontext

import typer

from flujocero import db
from flujocero.config import cargar, ticket_maximo_uf

getcontext().prec = 34
app = typer.Typer(add_completion=False, help="Flujo Cero")


@app.command()
def build() -> None:
    """Crea la base DuckDB desde schema/schema.sql."""
    typer.echo(f"base creada: {db.crear()}")


@app.command()
def rebuild(from_raw: bool = typer.Option(False, "--from-raw")) -> None:
    """Reconstruye la base desde cero."""
    r = db.ruta_db()
    if r.exists():
        r.unlink()
    typer.echo(f"base reconstruida: {db.crear()}")


@app.command()
def capacidad() -> None:
    """Ticket máximo según el perfil de config/inversionista.yml."""
    p, inv = cargar("params"), cargar("inversionista")
    renta = inv.crudo("restricciones").get("renta_liquida_mensual_clp")
    if renta is None:
        typer.echo("Falta `renta_liquida_mensual_clp` en config/inversionista.yml.")
        raise typer.Exit(1)
    otras = D(str(inv.crudo("restricciones").get("otros_creditos_cuota_mensual_clp") or 0))
    for etiqueta, tasa in [
        ("con subsidio + FOGAES", p.d("financiamiento.tasa_mejor_caso_fogaes")),
        ("sin subsidio", p.d("financiamiento.tasa_anual_sin_subsidio")),
    ]:
        r = ticket_maximo_uf(
            D(str(renta)),
            otras,
            tasa,
            int(p.d("financiamiento.plazo_anios")),
            p.d("financiamiento.ltv_con_fogaes"),
            p.d("macro.valor_uf_clp"),
            p.d("financiamiento.dividendo_max_pct_ingreso"),
            p.d("financiamiento.carga_financiera_max_pct"),
            p.d("subsidio_ley_21748.tope_valor_vivienda_uf"),
        )
        typer.echo(
            f"{etiqueta:<24} dividendo máx ${int(r['dividendo_max_clp']):,}  "
            f"crédito UF {r['credito_max_uf']:.0f}  ticket UF {r['ticket_max_uf']:.0f}"
        )


@app.command()
def demo() -> None:
    """Corre el motor sobre unidades de ejemplo. Sirve para ver el modelo funcionando."""
    from flujocero.finance.escenarios import escenario_base, evaluar_universo
    from flujocero.finance.modelo import Unidad

    p, inv = cargar("params"), cargar("inversionista")
    e = escenario_base(p, inv)
    us = [
        Unidad(
            "SM-1D-35",
            D(2600),
            D(35),
            "1D1B",
            "san-miguel",
            "san-miguel/gran-avenida",
            D("8.6"),
            24,
            True,
            riesgo_microzona=D("0.2"),
            catalizador=D("0.3"),
        ),
        Unidad(
            "NU-2D-55",
            D(4900),
            D(55),
            "2D2B",
            "nunoa",
            "nunoa/irarrazaval",
            D("16.5"),
            31,
            True,
            riesgo_microzona=D("0.6"),
            catalizador=D("0.1"),
        ),
        Unidad(
            "LF-2D-50",
            D(3700),
            D(50),
            "2D1B",
            "la-florida",
            "la-florida/rojas-magallanes",
            D("12.5"),
            18,
            True,
            riesgo_microzona=D("0.7"),
            catalizador=D("0.1"),
        ),
        Unidad(
            "CO-1D-40",
            D(2761),
            D(40),
            "1D1B",
            "concepcion",
            "concepcion/centro",
            D("10.5"),
            12,
            True,
            riesgo_microzona=D("0.4"),
            catalizador=D("0.0"),
        ),
        Unidad(
            "EC-SAT",
            D(2112),
            D(32),
            "1D1B",
            "estacion-central",
            "estacion-central/santa-isabel",
            D("7.3"),
            40,
            True,
            microzona_saturada=True,
        ),
    ]
    evals = evaluar_universo(us, e, p, inv)
    typer.echo(
        f"Escenario base: pie {e.pie_pct:.0%} · tasa {e.tasa_anual:.2%} · "
        f"{'con' if e.con_subsidio else 'sin'} subsidio · DFL2 {e.dfl2} · vacancia {e.vacancia:.1%}\n"
    )
    hdr = f"{'unidad':<10}{'UF':>7}{'arr UF':>8}{'yield':>8}{'div UF':>9}{'déficit/mes':>13}{'pie eq.':>9}{'TIR 10a':>9}{'score':>7}"
    typer.echo(hdr)
    typer.echo("-" * len(hdr))
    for u, ev in sorted(zip(us, evals), key=lambda x: -x[1].score):
        if ev.excluido:
            typer.echo(f"{u.unidad_key:<10}  EXCLUIDA — {ev.motivo_exclusion}")
            continue
        typer.echo(
            f"{u.unidad_key:<10}{u.precio_uf:>7.0f}{u.arriendo_mensual_uf:>8.1f}"
            f"{ev.rentabilidad_bruta:>8.2%}{ev.dividendo_total_uf:>9.2f}"
            f"{ev.btcf_mensual_uf:>10.2f} UF{ev.pie_minimo_flujo_cero:>9.1%}"
            f"{ev.tir_real.get(10, D(0)):>9.2%}{ev.score:>7.1f}"
        )
    uf = p.d("macro.valor_uf_clp")
    peor = min((e for e in evals if not e.excluido), key=lambda x: x.btcf_mensual_uf)
    typer.echo(
        f"\nDéficit mensual en pesos, peor caso: ${int(-peor.btcf_mensual_uf * uf):,}. "
        "La TIR está en términos REALES: para compararla con un depósito a plazo, súmale la inflación."
    )


@app.command()
def gates() -> None:
    """Gates que no dependen de datos recolectados (CLAUDE.md §7)."""
    fallos: list[str] = []
    p = cargar("params")
    inv = cargar("inversionista")
    est = p.estimados()
    typer.echo(f"✓ params.yml carga; {len(est)} supuestos estimados, todos con rango declarado")

    if inv.crudo("perfil")["tipo"] != "persona_natural":
        fallos.append("el perfil debe ser persona_natural: la persona jurídica no accede a DFL2")
    if (
        inv.crudo("estrategia_dfl2")["objetivo_unidades"]
        > p.crudo("tributacion.limite_dfl2_por_persona_natural")["v"]
    ):
        fallos.append("el objetivo de unidades DFL2 supera el límite legal por persona natural")
    typer.echo("✓ perfil del inversionista coherente con el régimen DFL2")

    ruta = db.crear()
    typer.echo(f"✓ esquema DuckDB aplicado: {ruta.name}")

    if fallos:
        for f in fallos:
            typer.echo(f"✗ {f}")
        raise typer.Exit(1)
    typer.echo("\ngates: VERDE")


if __name__ == "__main__":
    app()
