"""CLI de Flujo Cero."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import getcontext

import typer

from flujocero import db
from flujocero.config import RAIZ, cargar, con_valor, ticket_maximo_uf, uf_desde_la_base

getcontext().prec = 34
app = typer.Typer(add_completion=False, help="Flujo Cero")


@app.command()
def build() -> None:
    """Crea la base DuckDB desde schema/schema.sql."""
    typer.echo(f"base creada: {db.crear()}")


@app.command()
def rebuild(
    from_raw: bool = typer.Option(False, "--from-raw", help="reparsea la zona cruda"),
) -> None:
    """Reconstruye la base. Con `--from-raw`, reparsea todo `data/raw/` (§3.6).

    La zona cruda es la fuente de verdad: si el parseo de una fuente mejora, se corre esto
    y las tablas quedan al dia SIN volver a pedirle nada a nadie. Un blob que no se puede
    reconstruir se reporta y se conserva; nunca se descarta.
    """
    import duckdb

    from flujocero.sources import registro
    from flujocero.sources.base import MetadatoAusente, blobs_crudos, leer_crudo

    r = db.ruta_db()
    if r.exists():
        r.unlink()
    ruta = db.crear()
    typer.echo(f"esquema aplicado: {ruta.name}")

    if not from_raw:
        typer.echo("base vacia. Usa --from-raw para reconstruir desde data/raw/.")
        return

    blobs = [b for b in blobs_crudos() if b.name != "robots.txt.json.gz"]
    if not blobs:
        typer.echo("no hay nada en data/raw/ que reconstruir.")
        return
    typer.echo(f"{len(blobs)} blobs en la zona cruda\n")

    por_fuente: dict[str, list] = {}
    for b in blobs:
        por_fuente.setdefault(b.parts[-5], []).append(b)

    con = duckdb.connect(str(ruta))
    total, sin_meta, desconocidas = 0, [], []
    try:
        for source_id, rutas in sorted(por_fuente.items()):
            ent = registro.entrada(source_id)
            if ent is None:
                desconocidas.append(f"{source_id} ({len(rutas)} blobs)")
                continue
            filas = []
            for ruta_blob in rutas:
                try:
                    filas.extend(ent.parse(leer_crudo(ruta_blob)))
                except MetadatoAusente as exc:
                    sin_meta.append(f"{ruta_blob.name}: {exc}".split(".")[0])
            n = ent.cargar(con, filas) if filas else 0
            total += n
            typer.echo(f"  {source_id:<26} {n:>6} filas -> {ent.tabla}")
    finally:
        con.close()

    typer.echo(f"\n{total} filas reconstruidas desde la zona cruda")
    if desconocidas:
        typer.echo(
            f"\n! sin reconstruir, no hay parser registrado: {', '.join(desconocidas)}"
            f"\n  Los blobs se conservan. Fuentes conocidas: {registro.fuentes_conocidas()}"
        )
    if sin_meta:
        typer.echo(
            f"\n! {len(sin_meta)} blobs sin su .meta.json y por eso sin procedencia "
            "reconstruible.\n  Se recolectaron con una version anterior. Vuelve a "
            "recolectar esa fuente; los blobs viejos NO se borran."
        )


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


def _params_con_uf_real(p):
    """Reemplaza la UF fija de params.yml por la ultima cargada en la base, si la hay.

    El motor es puro y no lee la base (§11): la lectura ocurre aca y el valor entra al
    motor por argumento, con su `evidence` y su fuente.
    """
    import duckdb

    ruta = db.ruta_db()
    if not ruta.exists():
        return p, "params.yml (no hay base cargada)"
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        real = uf_desde_la_base(con)
    finally:
        con.close()
    if real is None:
        return p, "params.yml (no hay serie de UF cargada)"
    valor, fuente = real
    return con_valor(p, "macro.valor_uf_clp", float(valor), fuente), fuente


@app.command()
def demo() -> None:
    """Corre el motor sobre unidades de ejemplo. Sirve para ver el modelo funcionando."""
    from flujocero.finance.escenarios import escenario_base, evaluar_universo
    from flujocero.finance.modelo import Unidad

    p, inv = cargar("params"), cargar("inversionista")
    p, nota_uf = _params_con_uf_real(p)
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
        f"{'con' if e.con_subsidio else 'sin'} subsidio · DFL2 {e.dfl2} · vacancia {e.vacancia:.1%}"
    )
    typer.echo(f"UF ${p.d('macro.valor_uf_clp'):,.0f} — fuente: {nota_uf}\n")
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
    vivos = [e for e in evals if not e.excluido]
    if not vivos:
        typer.echo(
            "\nNinguna unidad sobrevivió a las exclusiones duras. Si todas se cayeron por "
            "déficit de caja, revisa `deficit_mensual_tolerado_clp` en config/inversionista.yml."
        )
        return
    peor = min(vivos, key=lambda x: x.btcf_mensual_uf)
    typer.echo(
        f"\nDéficit mensual en pesos, peor caso: ${int(-peor.btcf_mensual_uf * uf):,}, "
        f"de los cuales ${int(peor.amortizacion_mensual_uf * uf):,} son amortización — "
        f"costo real ${int(-peor.costo_tenencia_mensual_uf * uf):,}."
        "\nLa TIR está en términos REALES: para compararla con un depósito a plazo, "
        "súmale la inflación."
    )


@app.command()
def ingest(
    fuente: str = typer.Option("cmf_indicadores", help="source_id a ejecutar"),
    desde: str = typer.Option("2024-01", help="AAAA-MM"),
    hasta: str = typer.Option("2026-08", help="AAAA-MM"),
) -> None:
    """Ejecuta un colector contra la red y carga el resultado en DuckDB.

    Necesita salida a internet y las credenciales en `.env`. Escribe primero a la zona
    cruda (`data/raw/`) y sólo despues parsea, para que `make rebuild` pueda reconstruir.
    """
    import os

    import duckdb
    from dotenv import load_dotenv

    from flujocero.quality import source_contract
    from flujocero.sources.base import Scope

    if fuente != "cmf_indicadores":
        typer.echo(f"colector '{fuente}' todavia no existe. Disponibles: cmf_indicadores")
        raise typer.Exit(2)

    load_dotenv(RAIZ / ".env")
    from flujocero.sources.cmf_indicadores import ErrorDeFuente, cargar_en_duckdb, desde_entorno

    try:
        colector = desde_entorno(dict(os.environ))
    except ErrorDeFuente as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(2) from exc

    typer.echo(f"colector {colector.id} · series {list(colector.series)} · {desde} → {hasta}")

    from flujocero.quality import bitacora

    # La corrida se abre ANTES de salir a la red: una recoleccion que falla tambien es
    # informacion, y si no queda escrita el detector de parser roto no puede usarla.
    con = duckdb.connect(str(db.ruta_db()))
    db.aplicar_esquema(con)
    corrida = bitacora.abrir(colector.id)
    anterior_pre = bitacora.filas_de_la_ultima_corrida_exitosa(con, colector.id)

    try:
        docs = list(colector.collect(Scope(desde=desde, hasta=hasta)))
    except ErrorDeFuente as exc:
        corrida.notas = f"recoleccion fallida: {exc}"[:400]
        bitacora.cerrar(con, corrida, filas_corrida_anterior=anterior_pre)
        con.close()
        typer.echo(f"✗ {exc}")
        typer.echo(
            "\n  'proxy' o '403'      -> el entorno no tiene salida hacia la CMF;"
            " corre esto desde una maquina con internet abierto."
            "\n  'Server disconnected' -> la API de la CMF corta al azar. Ya se reintenta"
            " 4 veces con espera creciente; vuelve a intentar en un rato."
            "\n  '401' o 'apikey'      -> revisa CMF_APIKEY en el .env."
            "\n\n  `cli probe` prueba peticiones de tamano creciente y dice cual pasa."
            "\n  El intento quedo registrado en la tabla `run_log`."
        )
        raise typer.Exit(1) from exc
    typer.echo(f"✓ {len(docs)} documentos en la zona cruda")
    corrida.docs_recolectados = len(docs)
    # §7.1 · el detector de parser roto compara contra la ULTIMA CORRIDA EXITOSA.
    anterior = anterior_pre
    if anterior:
        typer.echo(f"  corrida anterior exitosa: {anterior} filas")

    try:
        filas = []
        for d in docs:
            try:
                filas.extend(colector.parse(d))
            except Exception as exc:  # noqa: BLE001 — §11: se registra, no se traga
                eid = bitacora.registrar_error(con, colector.id, d.ruta, exc)
                typer.echo(f"! error de parseo registrado ({eid[:8]}) en {d.ruta.name}: {exc}")

        rep = source_contract.verificar(colector, filas)
        if not rep.ok:
            typer.echo(str(rep))
            corrida.notas = "contrato de fuente en rojo"
            raise typer.Exit(1)
        typer.echo(f"✓ contrato de fuente: {len(filas)} filas con procedencia completa")

        st = colector.selftest(muestra_viva=docs[:5], n_filas_corrida_anterior=anterior)
        typer.echo(f"{'✓' if st.ok else '✗'} selftest: {st.checks}")
        for k, v in st.detalle.items():
            typer.echo(f"    {k}: {v}")
        corrida.selftest_ok = st.ok
        if not st.ok:
            corrida.notas = "selftest en rojo"
            raise typer.Exit(1)

        n = cargar_en_duckdb(con, filas)
        corrida.filas_insertadas = n
        por_serie = con.execute(
            "SELECT serie, count(*), min(fecha), max(fecha) "
            "FROM dim_tiempo_financiero GROUP BY serie ORDER BY serie"
        ).fetchall()
        typer.echo(f"✓ {n} filas cargadas en dim_tiempo_financiero")
        for serie, cuenta, mn, mx in por_serie:
            typer.echo(f"    {serie:<12} {cuenta:>6} filas   {mn} → {mx}")
        caida = bitacora.caida_pct(anterior, n)
        if caida is not None:
            typer.echo(f"  variacion vs corrida anterior: {-caida:+.1%}")
    finally:
        # La corrida se registra SIEMPRE, salga bien o mal: una corrida fallida que no
        # queda escrita es una corrida que el detector de parser roto no puede usar.
        bitacora.cerrar(con, corrida, filas_corrida_anterior=anterior)
        con.close()


@app.command()
def probe() -> None:
    """Diagnostico de una fuente: prueba URLs de complejidad creciente y reporta cual pasa.

    Existe porque un `Server disconnected` no dice DONDE esta el limite. En vez de adivinar,
    se mide: hoy, un mes, un ano, y el rango completo. La primera que falle acota el
    problema a un tamano de ventana concreto.
    """
    import os
    import time as _t

    import httpx
    from dotenv import load_dotenv

    from flujocero.sources.base import ocultar_secreto
    from flujocero.sources.cmf_indicadores import BASE

    load_dotenv(RAIZ / ".env")
    apikey = os.environ.get("CMF_APIKEY", "").strip()
    if not apikey:
        typer.echo("✗ falta CMF_APIKEY en .env")
        raise typer.Exit(2)
    ua = os.environ.get("USER_AGENT", "").strip() or "FlujoCero-ResearchBot/1.0"

    pruebas = [
        ("robots.txt", "https://api.cmfchile.cl/robots.txt"),
        ("hoy", f"{BASE}/uf?apikey={apikey}&formato=json"),
        ("1 mes", f"{BASE}/uf/periodo/2026/08/2026/08?apikey={apikey}&formato=json"),
        ("8 meses", f"{BASE}/uf/periodo/2026/01/2026/08?apikey={apikey}&formato=json"),
        ("1 ano", f"{BASE}/uf/periodo/2025/01/2025/12?apikey={apikey}&formato=json"),
        ("32 meses", f"{BASE}/uf/periodo/2024/01/2026/08?apikey={apikey}&formato=json"),
    ]
    typer.echo(f"user-agent: {ua}\n")
    typer.echo(f"{'prueba':<12}{'resultado':<30}{'bytes':>8}  registros")
    typer.echo("-" * 68)
    with httpx.Client(timeout=45.0, follow_redirects=True) as c:
        for i, (etiqueta, url) in enumerate(pruebas):
            if i:
                _t.sleep(0.5)
            try:
                r = c.get(url, headers={"User-Agent": ua})
                n = ""
                if r.status_code == 200 and "json" in url:
                    try:
                        d = r.json()
                        clave = next(iter(d)) if isinstance(d, dict) else "?"
                        n = f"{len(d[clave])} en {clave}" if isinstance(d, dict) else "?"
                    except (ValueError, KeyError, TypeError):
                        n = "respuesta no es el JSON esperado"
                estado = f"HTTP {r.status_code}"
                typer.echo(f"{etiqueta:<12}{estado:<30}{len(r.content):>8}  {n}")
            except httpx.HTTPError as exc:
                typer.echo(f"{etiqueta:<12}{type(exc).__name__ + ': ' + str(exc)[:26]:<30}{'—':>8}")
    typer.echo(
        "\nLa primera prueba que falle acota el limite. Si 'hoy' pasa y '32 meses' no,"
        "\nel problema es el tamano de la ventana y el troceado por ano ya lo resuelve."
    )
    typer.echo(f"\n(URL de ejemplo, sin la clave: {ocultar_secreto(pruebas[-1][1])})")


@app.command()
def medir_meli() -> None:
    """T-011 · mide las cuatro brechas del §G de docs/01-fuentes.md contra la API real.

    Necesita red y las credenciales de MercadoLibre en `.env`. NO recolecta datos: solo
    responde preguntas que hoy son supuestos, para no comprometer arquitectura a ciegas.

    OJO: renueva el token y **reescribe `MELI_REFRESH_TOKEN` en el .env**. El refresh token
    de MercadoLibre es de un solo uso.
    """
    import os

    from dotenv import load_dotenv

    from flujocero.sources.meli import ErrorDeFuente as ErrorMeli
    from flujocero.sources.meli import TokenInvalido
    from flujocero.sources.meli import desde_entorno as meli_desde_entorno

    ruta_env = RAIZ / ".env"
    load_dotenv(ruta_env)
    try:
        cliente = meli_desde_entorno(dict(os.environ), ruta_env)
    except TokenInvalido as exc:
        typer.echo(f"✗ {exc}")
        typer.echo(
            "\n  Pideme un link de autorizacion nuevo en el chat y repetimos el paso del"
            "\n  navegador. Son dos minutos."
        )
        raise typer.Exit(2) from exc
    except ErrorMeli as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(2) from exc

    typer.echo("✓ token renovado y MELI_REFRESH_TOKEN actualizado en .env\n")
    try:
        rep = cliente.medir()
    finally:
        cliente.cerrar()
    typer.echo(str(rep))
    typer.echo("\nPegame esta salida completa en el chat: con ella cierro T-011 y escribo el ADR.")


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

    # §7.3 sobre lo que haya cargado. Sin datos aun, verifica que los checks corren.
    import duckdb

    from flujocero.quality import checks as qc

    con = duckdb.connect(str(ruta))
    try:
        unidades = (
            [
                dict(zip([d[0] for d in con.description], fila, strict=True))
                for fila in con.execute("SELECT * FROM fact_unidad_venta").fetchall()
            ]
            if con.execute("SELECT count(*) FROM fact_unidad_venta").fetchone()[0]
            else []
        )
        comps = (
            [
                dict(zip([d[0] for d in con.description], fila, strict=True))
                for fila in con.execute("SELECT * FROM fact_arriendo_comp").fetchall()
            ]
            if con.execute("SELECT count(*) FROM fact_arriendo_comp").fetchone()[0]
            else []
        )
    finally:
        con.close()

    if unidades or comps:
        rep = qc.correr(unidades, comps, datetime.now(UTC))
        typer.echo(str(rep))
        if rep.falla:
            fallos.append("los gates de calidad de datos del §7.3 estan en rojo")
    else:
        typer.echo(
            f"• calidad de datos: sin filas que revisar todavia "
            f"({len(qc.PATRONES_PERSONALES)} patrones de datos personales armados)"
        )

    if fallos:
        for f in fallos:
            typer.echo(f"✗ {f}")
        raise typer.Exit(1)
    typer.echo("\ngates: VERDE")


if __name__ == "__main__":
    app()
