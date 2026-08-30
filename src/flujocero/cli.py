"""CLI de Flujo Cero."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import getcontext
from typing import Any

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
    _ahorro = inv.crudo("restricciones").get("ahorro_disponible_pie_clp")
    ahorro = D(str(_ahorro)) if _ahorro is not None else None
    # Las tres combinaciones que importan. El LTV va con cada una: sin FOGAES el banco no
    # presta el 90%, asi que el ticket no lo limita solo el dividendo sino tambien el pie.
    # Las tasas del par con/sin subsidio son del MISMO banco y el MISMO dia (T-914).
    con_sub = p.d("financiamiento.tasa_mejor_caso_fogaes")
    sin_sub = p.d("financiamiento.tasa_mejor_sin_subsidio")
    ltv_con = p.d("financiamiento.ltv_con_fogaes")
    ltv_sin = p.d("financiamiento.ltv_sin_fogaes")
    # Los tres casos que EXISTEN, ya sin condicionales: confirmado el 29-ago-2026 que el
    # FOGAES tradicional cubre solo primera venta, asi que "usado con FOGAES" no es un caso.
    for etiqueta, tasa, ltv in [
        ("nuevo, subsidio+FOGAES", con_sub, ltv_con),
        ("nuevo, cupo agotado", sin_sub, ltv_con),
        ("usado (sin ninguno)", sin_sub, ltv_sin),
    ]:
        r = ticket_maximo_uf(
            D(str(renta)),
            otras,
            tasa,
            int(p.d("financiamiento.plazo_anios")),
            ltv,
            p.d("macro.valor_uf_clp"),
            p.d("financiamiento.dividendo_max_pct_ingreso"),
            p.d("financiamiento.carga_financiera_max_pct"),
            p.d("subsidio_ley_21748.tope_valor_vivienda_uf"),
        )
        # Un ticket mas alto con menos LTV es aritmetica correcta y consejo falso si el pie
        # no esta en la cuenta: sale de tu bolsillo, no del banco.
        pie_clp = r["ticket_max_uf"] * (D(1) - ltv) * p.d("macro.valor_uf_clp")
        alcanza = ahorro is None or pie_clp <= ahorro
        marca = "" if alcanza else "  <- el pie NO alcanza"
        typer.echo(
            f"{etiqueta:<24} tasa {tasa:.2%}  pie min {1 - ltv:.0%}  "
            f"crédito UF {r['credito_max_uf']:.0f}  ticket UF {r['ticket_max_uf']:.0f}  "
            f"pie ${int(pie_clp):,}{marca}"
        )
    typer.echo(
        f"\n  dividendo máximo ${int(r['dividendo_max_clp']):,}/mes en los tres casos: "
        "lo fija la renta, no el producto."
    )
    if ahorro is not None:
        typer.echo(f"  ahorro disponible para el pie: ${int(ahorro):,}")


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


def _ingerir_gael(con: Any, ahora: Any, raiz_cruda: Any = None) -> bool:
    """T-908 · segunda fuente de UF y UTM. Devuelve True si cargo o confirmo algun valor.

    Rellena huecos y **nunca pisa** una fila que ya exista: eso lo garantiza
    `gael_indicadores.cargar_en_duckdb`, no este comando. Aca solo se imprime lo que paso,
    incluidas las discrepancias entre fuentes, que son un hallazgo y no un detalle.
    """
    import os

    from flujocero.sources import gael_indicadores as gael
    from flujocero.sources.base import Scope

    colector = gael.desde_entorno(dict(os.environ), raiz_cruda=raiz_cruda)
    typer.echo(f"\n→ fallback {colector.id}: pidiendo el valor VIGENTE de {list(colector.series)}")
    typer.echo(
        "  (Gael no sirve series historicas: cubre 'hoy la CMF no responde', no el backfill)"
    )
    try:
        docs = list(colector.collect(Scope(ahora=ahora)))
    except gael.CupoExcedido as exc:
        typer.echo(f"  ✗ {exc}")
        return False
    except gael.ErrorDeFuente as exc:
        typer.echo(f"  ✗ el fallback tampoco respondio: {exc}")
        return False

    filas = []
    for d in docs:
        try:
            filas.extend(colector.parse(d))
        except (gael.ErrorDeFuente, ValueError) as exc:
            # §11: no se traga, se reporta. `ValueError` entra porque la validacion de
            # pydantic levanta `ValidationError`, que hereda de ahi: sin este caso, una
            # fila mal formada reventaba el fallback con un traceback en vez de un mensaje.
            # Es el caso ESPERADO si la forma real de Gael difiere de la documentada, por
            # eso el mensaje apunta al blob crudo, que ya quedo escrito (§3.6).
            typer.echo(f"  ! {d.ruta.name}: {type(exc).__name__}: {exc}")
    if not filas:
        typer.echo(
            "  ✗ el fallback no produjo ninguna fila. El blob crudo quedo en data/raw/"
            "gael_indicadores/ — mandamelo y ajusto el parser a la forma real."
        )
        return False

    st = colector.selftest(muestra_viva=docs[:5])
    typer.echo(f"  {'✓' if st.ok else '✗'} selftest: {st.checks}")
    if not st.ok:
        for k, v in st.detalle.items():
            typer.echo(f"      {k}: {v}")
        return False

    rep = gael.cargar_en_duckdb(con, filas)
    typer.echo(f"  ✓ {rep}")
    for d in rep.discrepancias:
        typer.echo(f"    ⚠ DISCREPANCIA ENTRE FUENTES OFICIALES: {d}")
    if rep.discrepancias:
        typer.echo(
            "    No se resolvio sola a proposito: dos fuentes oficiales que no coinciden es"
            "\n    un hallazgo de calidad de datos. La fila que ya estaba NO se toco."
        )
    return rep.insertadas > 0 or rep.ya_estaban > 0


@app.command()
def ingest(
    fuente: str = typer.Option("cmf_indicadores", help="source_id a ejecutar"),
    desde: str = typer.Option("2024-01", help="AAAA-MM"),
    hasta: str = typer.Option("2026-08", help="AAAA-MM"),
    sin_fallback: bool = typer.Option(
        False, "--sin-fallback", help="no intentar Gael Cloud si la CMF no responde"
    ),
) -> None:
    """Ejecuta un colector contra la red y carga el resultado en DuckDB.

    Necesita salida a internet y las credenciales en `.env`. Escribe primero a la zona
    cruda (`data/raw/`) y sólo despues parsea, para que `make rebuild` pueda reconstruir.

    Si la CMF no responde —corta al azar, esta medido— cae a Gael Cloud para el valor
    VIGENTE de la UF y la UTM. Ese fallback rellena huecos y nunca pisa lo que ya existe.
    """
    import os

    import duckdb
    from dotenv import load_dotenv

    from flujocero.quality import source_contract
    from flujocero.sources.base import Scope

    conocidas = ("cmf_indicadores", "gael_indicadores")
    if fuente not in conocidas:
        typer.echo(f"colector '{fuente}' todavia no existe. Disponibles: {', '.join(conocidas)}")
        raise typer.Exit(2)

    load_dotenv(RAIZ / ".env")

    if fuente == "gael_indicadores":
        con = duckdb.connect(str(db.ruta_db()))
        db.aplicar_esquema(con)
        try:
            ok = _ingerir_gael(con, datetime.now(UTC))
        finally:
            con.close()
        raise typer.Exit(0 if ok else 1)
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
        typer.echo(f"✗ {exc}")
        # T-908 · la CMF corta al azar. Antes de rendirse, la segunda fuente. Se intenta
        # con la conexion todavia abierta porque el fallback tambien escribe en DuckDB.
        rescatado = False
        try:
            if not sin_fallback:
                rescatado = _ingerir_gael(con, datetime.now(UTC))
        finally:
            # La conexion se cierra pase lo que pase: un fallback que revienta no puede
            # dejar la base tomada, porque el siguiente comando no podria ni abrirla.
            con.close()
        if rescatado:
            typer.echo(
                "\n  El valor VIGENTE quedo cubierto por Gael, pero el periodo "
                f"{desde}..{hasta} NO se descargo: para el historico hace falta la CMF."
                "\n  Vuelve a correr este mismo comando en un rato."
            )
            raise typer.Exit(1) from exc
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
def ingerir_legado(
    busqueda: str = typer.Option(
        "", help="carpeta `search` — paginas de LISTADO. Es la linea base del delta."
    ),
    origen: str = typer.Option(
        "", help="carpeta `listings` — fichas de detalle. OPCIONAL y cara: 3,2 GB."
    ),
    limite: int = typer.Option(0, help="0 = todos. Solo aplica a --origen."),
) -> None:
    """T-918 · ingiere la foto de mayo-2026 del proyecto anterior (docs/adr/004).

    No toca la red. Anonimiza ANTES de escribir (§3.4) y declara `fetched_at` de mayo, no de
    hoy, asi que el gate de frescura los deja fuera del ranking — que es lo correcto.

    **Empeza por `--busqueda`.** Son 130 paginas, menos de un minuto, y son el 100% de lo que
    el delta necesita: la misma superficie que lee el colector vivo. `--origen` son 6.229
    fichas de 3,2 GB que solo suman antiguedad y gastos comunes, y cuyo precio vive en otra
    superficie del portal, asi que no sirven de linea base.
    """
    from pathlib import Path as _Path

    import duckdb

    from flujocero.quality import bitacora
    from flujocero.sources import portal_busqueda as pb
    from flujocero.sources.base import leer_crudo
    from flujocero.sources.portal_legado import PortalLegado
    from flujocero.sources.portal_legado import cargar_en_duckdb as cargar_fichas

    if not origen and not busqueda:
        typer.echo("✗ pasa al menos --busqueda (la linea base del delta) o --origen (fichas).")
        raise typer.Exit(2)

    def avance(etiqueta: str, cada: int):
        def _(hechos: int, total: int) -> None:
            if hechos % cada == 0 or hechos == total:
                typer.echo(f"    {etiqueta}: {hechos}/{total} ({hechos / total:.0%})")

        return _

    con = duckdb.connect(str(db.crear()))
    try:
        if busqueda:
            carpeta = _Path(busqueda).expanduser()
            if not carpeta.is_dir():
                typer.echo(f"✗ no existe la carpeta {carpeta}")
                raise typer.Exit(2)
            typer.echo("  Paginas de listado — la linea base correcta para el delta:")
            docs = pb.ingerir_guardadas(carpeta, progreso=avance("listados", 25))
            colector = pb.PortalBusqueda("FlujoCero-ResearchBot/1.0")
            tarjetas = [t for d in docs for t in colector.parse(d)]
            n = pb.cargar_en_duckdb(con, tarjetas)
            typer.echo(f"✓ {len(docs)} paginas, {len(tarjetas)} tarjetas, {n} filas")

        if origen:
            carpeta = _Path(origen).expanduser()
            if not carpeta.is_dir():
                typer.echo(f"✗ no existe la carpeta {carpeta}")
                raise typer.Exit(2)
            typer.echo("\n  Fichas de detalle — solo aportan antiguedad y gastos comunes:")
            col = PortalLegado(origen=carpeta)
            typer.echo(f"    {len(col.archivos())} archivos en el origen")
            corrida = bitacora.abrir(col.id)
            docs_f = col.collect(limite=limite or None, progreso=avance("zona cruda", 250))
            corrida.docs_recolectados = len(docs_f)
            avisos = []
            for i, d in enumerate(docs_f, 1):
                avisos += col.parse(leer_crudo(d.ruta))
                if i % 500 == 0 or i == len(docs_f):
                    typer.echo(f"    parseando: {i}/{len(docs_f)} ({i / len(docs_f):.0%})")
            corrida.filas_insertadas = cargar_fichas(con, avisos)
            rep = col.selftest(muestra=min(600, len(col.archivos())))
            corrida.selftest_ok = rep.ok
            corrida.notas = rep.detalle.get("cobertura", "")
            bitacora.cerrar(con, corrida)
            typer.echo(f"✓ {len(avisos)} avisos, {corrida.filas_insertadas} filas")
            typer.echo(f"{'✓' if rep.ok else '✗'} selftest: {rep.detalle.get('cobertura')}")

        for tabla in ("dim_comuna", "dim_microzona", "fact_unidad_venta", "fact_arriendo_comp"):
            total = con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
            typer.echo(f"    {tabla:22s} {total:6d}")
    finally:
        con.close()

    typer.echo("\n  Son datos de mayo-2026: el gate de frescura los deja fuera del ranking.")


@app.command()
def recolectar_portal(
    comunas: str = typer.Option("", help="separadas por coma. Vacio = las de config/zonas.yml"),
    operaciones: str = typer.Option("venta,arriendo"),
    paginas: int = typer.Option(3, help="paginas por comuna y operacion (48 avisos c/u)"),
    tipo: str = typer.Option("usadas", help="usadas | nuevas | proyectos | '' para todo"),
) -> None:
    """T-920 · recolecta Portal Inmobiliario por la ruta que el robots.txt PERMITE.

    Solo listados `_Desde_`; nunca fichas `/MLC-`. User-Agent honesto, sin sesion y sin
    disfraz de navegador: lo que el scraper anterior arriesgaba no era una IP, era tu cuenta
    de MercadoLibre. Si el portal responde 403 a un cliente honesto, se detiene y lo dice.

    Pausa de 3 a 5 segundos entre paginas. Con los valores por defecto son ~10 minutos.
    """
    import os

    import duckdb
    from dotenv import load_dotenv

    from flujocero.quality import bitacora
    from flujocero.sources import portal_busqueda as pb

    load_dotenv(RAIZ / ".env")
    ua = os.environ.get("USER_AGENT", "").strip()
    if not ua:
        typer.echo("✗ falta USER_AGENT en el .env. Es la identidad con la que nos presentamos.")
        raise typer.Exit(2)

    lista = [c.strip() for c in comunas.split(",") if c.strip()] or [
        z["comuna"] for z in cargar("zonas").crudo("fase_1")
    ]
    ops = tuple(o.strip() for o in operaciones.split(",") if o.strip())
    typer.echo(f"  comunas: {', '.join(lista)}\n  operaciones: {', '.join(ops)}")

    col = pb.PortalBusqueda(user_agent=ua)
    veredicto = col.robots_ok()
    typer.echo(f"{'✓' if veredicto.allowed else '✗'} robots.txt: {veredicto.motivo}")
    if not veredicto.allowed:
        raise typer.Exit(2)

    con = duckdb.connect(str(db.crear()))
    corrida = bitacora.abrir(col.id)
    try:
        anterior = bitacora.filas_de_la_ultima_corrida_exitosa(con, col.id)
        docs = col.collect(lista, ops, max_paginas=paginas, tipo=tipo or None)
        corrida.docs_recolectados = len(docs)
        tarjetas = [t for d in docs for t in col.parse(d)]
        typer.echo(f"✓ {len(docs)} paginas, {len(tarjetas)} avisos")

        corrida.filas_insertadas = pb.cargar_en_duckdb(con, tarjetas)
        rep = col.selftest(docs, filas_corrida_anterior=anterior)
        corrida.selftest_ok = rep.ok
        corrida.notas = rep.detalle.get("cobertura", "")
        typer.echo(f"✓ {corrida.filas_insertadas} filas nuevas o versionadas")
        typer.echo(f"{'✓' if rep.ok else '✗'} selftest: {rep.detalle.get('cobertura')}")
        if not rep.ok:
            for k, v in rep.detalle.items():
                if k not in ("cobertura", "proyectos"):
                    typer.echo(f"    {k}: {v}")
    except pb.Bloqueado as exc:
        corrida.notas = str(exc)
        typer.echo(f"✗ {exc}")
        raise typer.Exit(3) from exc
    finally:
        bitacora.cerrar(con, corrida, filas_corrida_anterior=None)
        con.close()
        col.cerrar()


@app.command()
def delta(
    corte: str = typer.Option(
        "", help="fecha ISO del corte. Vacio = la fecha de la ultima recoleccion"
    ),
) -> None:
    """T-919 · que cambio de precio, que desaparecio y que es nuevo desde el corte.

    Un aviso desaparece del portal cuando se vende, asi que "estaba antes y hoy no esta" es
    la senal mas fuerte de este cruce. Y una unidad que baja de precio es, segun el §11 del
    contrato, senal de compra.

    No necesita nada especial: el colector ya versiona con SCD tipo 2. Esto solo lo lee.
    """
    from datetime import date as _date

    import duckdb

    from flujocero.quality import delta as dl

    con = duckdb.connect(str(db.crear()))
    try:
        if corte:
            momento = datetime.fromisoformat(corte).replace(tzinfo=UTC)
        else:
            fila = con.execute("SELECT max(fetched_at) FROM fact_unidad_venta").fetchone()
            if fila is None or fila[0] is None:
                typer.echo("No hay datos cargados todavia. Corre `recolectar-portal` primero.")
                raise typer.Exit(1)
            # El corte es el DIA de la ultima captura: dentro de una misma corrida las filas
            # llevan la misma marca, y comparar contra el instante exacto dejaria fuera todo.
            momento = datetime.combine(
                _date.fromisoformat(str(fila[0])[:10]), datetime.min.time(), tzinfo=UTC
            )
        typer.echo(str(dl.comparar(con, momento)))
    finally:
        con.close()


@app.command()
def agregar_arriendo() -> None:
    """T-023 · calcula la mediana de arriendo por microzona × tipología × rango de m².

    Es el numerador de todo: el yield bruto sale de `arriendo_mediano × 12 / precio`.

    Cada aviso en pesos se convierte con la UF de SU día, no con la de hoy: usar la de hoy
    mezclaría el movimiento de la UF con el del mercado, que es lo que el §3.3 manda separar.
    Si falta la UF de ese día, la fila no se convierte y no se usa.
    """
    import duckdb

    from flujocero.agg import arriendo as agg

    p = cargar("params")
    rangos = p.crudo("ingresos.rangos_m2")
    con = duckdb.connect(str(db.crear()))
    try:
        # Se informa ANTES de agregar: "4.099 descartados" sin decir el estado de la serie
        # obliga a adivinar si falta el insumo o si el codigo esta roto.
        estado = agg.estado_serie(con)
        typer.echo(f"  {estado}")
        comparables, descartes = agg.comparables_desde_duckdb(con)
        total = sum(descartes.values()) + len(comparables)
        typer.echo(f"  {total} comparables activos · {len(comparables)} utilizables")
        for motivo, n in descartes.items():
            if n:
                typer.echo(f"    descartados por {motivo}: {n}")
        if descartes["sin_uf_del_dia"] and not estado.n:
            typer.echo(
                "\n✗ La serie de UF esta VACIA, por eso no se convirtio ningun arriendo en\n"
                "  pesos. `rebuild --from-raw` la reconstruye solo si los blobs de la CMF\n"
                "  estan en data/raw/cmf_indicadores/. Si no estan:\n"
                "    uv run python -m flujocero.cli ingest --fuente cmf_indicadores"
            )
        if not comparables:
            raise typer.Exit(1)

        agregados = agg.agregar(comparables, rangos)
        n = agg.cargar_en_duckdb(con, agregados, datetime.now(UTC))
        buenos = [a for a in agregados if a.suficiente]
        typer.echo(f"✓ {n} celdas (microzona × tipología × rango)")
        typer.echo(f"✓ {len(buenos)} con n ≥ {agg.MIN_COMPARABLES}: son las que pueden rankear")

        # §7.3, la reconciliacion externa. Estaba escrita y nadie la llamaba: es la
        # validacion mas fuerte que tiene el pipeline, porque compara una mediana calculada
        # desde miles de avisos crudos contra una tabla que publico un tercero. Si las dos
        # coinciden, es muy improbable que esten mal de la misma forma.
        from flujocero.quality import checks as qc

        por_comuna: dict[str, list] = {}
        for a in buenos:
            por_comuna.setdefault(a.microzona_id.split("/")[0], []).append(a.uf_m2_mediana)
        medianas = {c: agg.percentil(v, D("0.5")) for c, v in por_comuna.items()}
        hallazgo = qc.reconciliacion_arriendo(medianas, qc.ARRIENDO_UF_M2_REFERENCIA)
        typer.echo(f"\n  {hallazgo}")
        for comuna, nuestra in sorted(medianas.items()):
            ref = qc.ARRIENDO_UF_M2_REFERENCIA.get(comuna)
            if ref:
                typer.echo(
                    f"    {comuna:20s} nuestro {nuestra:.3f}  publicado {ref:.2f}  "
                    f"({(nuestra - ref) / ref:+.0%})"
                )

        typer.echo("\n  Las más profundas:")
        for a in sorted(buenos, key=lambda x: -x.n)[:10]:
            typer.echo(
                f"    {a.microzona_id:38s} {a.tipologia:6s} {a.rango_m2:>7s} m²  "
                f"n={a.n:3d}  mediana UF {a.mediana:6.2f}  "
                f"{a.uf_m2_mediana:.3f} UF/m²  dispersión {a.dispersion:.0%}"
            )
    finally:
        con.close()


@app.command()
def oportunidades(
    top: int = typer.Option(15, help="cuántas mostrar"),
    pie: float = typer.Option(0.0, help="pie deseado. 0 = el del perfil"),
) -> None:
    """T-029 · cruza cada unidad en venta con el arriendo de su microzona y rankea.

    Es el eslabón que faltaba: hasta ahora el motor solo había corrido sobre departamentos
    inventados. El emparejamiento usa la clave `(microzona, tipología, rango_m2)` del §2.4,
    la misma con la que se agregó el arriendo. **No hay caída a comuna**: si una unidad no
    tiene su celda con 8 comparables, no se rankea. Prestarle la mediana de la comuna sería
    justo lo que el §2.4 prohíbe.
    """
    import duckdb

    from flujocero.agg import oportunidades as op
    from flujocero.finance.escenarios import escenario_base, evaluar_universo

    p, inv = cargar("params"), cargar("inversionista")
    con = duckdb.connect(str(db.crear()))
    try:
        r = op.emparejar(con, p.crudo("ingresos.rangos_m2"))
    finally:
        con.close()

    typer.echo(f"  {r.total} unidades con precio verificado · {len(r.unidades)} rankeables")
    for motivo, n in r.descartes.items():
        if n:
            typer.echo(f"    fuera por {motivo}: {n}")
    if not r.unidades:
        typer.echo(
            "\n✗ Ninguna unidad tiene su celda de arriendo con 8 comparables.\n"
            "  Corré `agregar-arriendo` primero, y si ya lo hiciste, recolectá más páginas\n"
            "  de arriendo en esas comunas."
        )
        raise typer.Exit(1)

    e = escenario_base(p, inv)
    if pie:
        e = replace(e, pie_pct=D(str(pie)), escenario_id=f"pie{int(pie * 100)}")
    evals = evaluar_universo(r.unidades, e, p, inv)

    # Antes del ranking: qué parte del score está viva. Un score que se presenta como
    # completo cuando un cuarto de su peso está inerte miente por omisión.
    inertes = op.componentes_inertes(r.unidades)
    if inertes:
        muerto = op.peso_inerte(inertes, p)
        typer.echo(
            f"\n  ⚠ {muerto:.0%} del score está INERTE: {', '.join(inertes)} no tienen fuente\n"
            f"    todavía (falta el Censo 2024 y las distancias a Metro, T-014). Reparten el\n"
            f"    mismo puntaje a cada unidad y no mueven una sola posición del ranking."
        )

    vivos = [(u, ev) for u, ev in zip(r.unidades, evals, strict=True) if not ev.excluido]
    vivos.sort(key=lambda x: -x[1].score)

    # Agrupado por REGLA, no por unidad. "26 excluidas" obliga a adivinar si el filtro esta
    # haciendo su trabajo o comiendose el universo; "19 sobre el tope de UF 6.000" se lee solo.
    from collections import Counter

    reglas = Counter(
        (ev.motivo_exclusion or "").split(":")[0].split(" UF ")[0].split(" de caja ")[0]
        for ev in evals
        if ev.excluido
    )
    if reglas:
        typer.echo(f"\n  {len(evals) - len(vivos)} excluidas por regla dura:")
        for regla, n in reglas.most_common():
            typer.echo(f"    {n:4d}  {regla}")
    typer.echo(f"\n  {len(vivos)} llegan al ranking")
    if not vivos:
        typer.echo(
            "    Ninguna sobrevivio. Las reglas duras son del §12 y del perfil: mira arriba\n"
            "    cual es la que muerde. Si es el tope de deficit, esta en\n"
            "    `config/inversionista.yml:restricciones.deficit_mensual_tolerado_clp`."
        )
        raise typer.Exit(0)

    uf = p.d("macro.valor_uf_clp")
    # Lo PEDIDO y lo APLICADO son cosas distintas, y confundirlas es grave: el escenario pide
    # 10% de pie con subsidio, pero a un usado el motor le niega los dos y le exige 20%. Un
    # encabezado que anuncia "pie 10%" sobre numeros calculados al 20% miente sobre la plata
    # que hay que poner.
    con_sub = sum(1 for _, ev in vivos if ev.subsidio_aplicado)
    con_fog = sum(1 for _, ev in vivos if ev.fogaes_aplicado)
    pies = {ev.pie_efectivo for _, ev in vivos}
    typer.echo(
        f"\n  Escenario PEDIDO: pie {e.pie_pct:.0%} · {'con' if e.con_subsidio else 'sin'} subsidio"
    )
    typer.echo(
        f"  Lo que el motor APLICO: {con_sub} de {len(vivos)} con subsidio · "
        f"{con_fog} con FOGAES · pie efectivo {' y '.join(f'{x:.0%}' for x in sorted(pies))}"
    )
    if con_sub < len(vivos):
        typer.echo(
            "    El subsidio y el FOGAES exigen primera venta. Un usado paga la tasa completa\n"
            "    y 20% de pie, y los numeros de abajo ya lo reflejan."
        )
    typer.echo("")
    typer.echo(
        f"    {'unidad':16s} {'UF':>7s} {'m2':>5s} {'UF/m2':>6s} {'yield':>6s} {'cap':>6s} "
        f"{'tenencia/mes':>13s} {'pie':>4s} {'pie 0':>6s}  microzona"
    )
    for u, ev in vivos[:top]:
        tenencia = ev.costo_tenencia_mensual_uf * uf
        # El pie de flujo cero REAL, no la forma cerrada: esa subestima 24-30 puntos porque
        # ignora vacancia, incobrabilidad, erosion intra-anual y seguros.
        pie_cero = (
            f"{ev.pie_flujo_cero_real:.0%}" if ev.pie_flujo_cero_real is not None else "nunca"
        )
        typer.echo(
            f"    {u.unidad_key:16s} {u.precio_uf:>7,.0f} {u.m2_utiles:>5.0f} "
            f"{u.precio_uf / u.m2_utiles:>6.1f} "
            f"{ev.rentabilidad_bruta:>6.2%} {ev.cap_rate:>6.2%} "
            f"{'$' + format(int(tenencia), ','):>13s} {ev.pie_efectivo:>4.0%} "
            f"{pie_cero:>6s}  {u.microzona_id}"
        )

    # El §13.3 advierte exactamente de esto: los yields de dos digitos del ranking chileno son
    # stock usado chico y barato. Alto yield bruto no es lo mismo que buena inversion: una
    # unidad de 25 m2 tiene mas rotacion, mas vacancia, gastos comunes mas altos por m2 y
    # mucha menos liquidez de salida. El ranking no lo sabe; el usuario tiene que saberlo.
    chicas = [u for u, _ in vivos[:top] if u.m2_utiles < D(35)]
    if len(chicas) >= top // 3:
        mediana_m2 = sorted(u.m2_utiles for u, _ in vivos[:top])[len(vivos[:top]) // 2]
        typer.echo(
            f"\n  ⚠ {len(chicas)} de las {top} primeras son de menos de 35 m² "
            f"(mediana {mediana_m2:.0f} m²).\n"
            "    Es esperable: a menor tamaño, mayor yield bruto. Pero el §13.3 advierte que\n"
            "    los retornos de dos dígitos del mercado chileno son stock usado chico, y el\n"
            "    ranking no mide rotación, vacancia real ni liquidez de salida. Verificá\n"
            "    estado y gastos comunes antes de emocionarte con las primeras filas."
        )

    typer.echo("\n  De dónde salió el arriendo de las tres primeras:")
    for u, _ in vivos[:3]:
        celda, n, arr = r.procedencia_arriendo[u.unidad_key]
        typer.echo(f"    {u.unidad_key}: UF {arr:.2f}/mes · mediana de {n} avisos en {celda}")


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
    objetivo = inv.crudo("estrategia_dfl2")["objetivo_unidades"]
    limite = p.crudo("tributacion.limite_dfl2_por_persona_natural")["v"]
    # `None` = el inversionista no declaro un objetivo. No es lo mismo que declarar el tope:
    # dar por hecho que quiere el maximo legal es inventarle una intencion.
    if objetivo is not None and objetivo > limite:
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
        # Las fuentes marcadas `historica: true` en fuentes.yml se ingieren sabiendo que
        # estan viejas y NO alimentan el ranking. El gate de frescura las exime; no las
        # ignora: las cuenta aparte y lo dice.
        historicas = frozenset(
            f["id"] for f in cargar("fuentes").crudo("fuentes") if f.get("historica")
        )
        rep = qc.correr(unidades, comps, datetime.now(UTC), fuentes_historicas=historicas)
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


@app.command()
def faltantes(
    top: int = typer.Option(15, help="cuantas celdas mostrar"),
    comuna: str = typer.Option("", help="filtrar a una comuna"),
) -> None:
    """Que recolectar para desbloquear mas unidades, ordenado por cuantas desbloquea cada aviso.

    El cuello de botella del proyecto NO son los avisos de venta: hay miles con precio
    verificado. Es que su celda de arriendo no llega a los 8 comparables del §7.3, y sin eso
    la unidad no se rankea. Este comando dice DONDE recolectar para que el esfuerzo pague.
    """
    import duckdb

    from flujocero.agg import faltantes as fa

    p = cargar("params")
    con = duckdb.connect(str(db.crear()))
    try:
        dg = fa.diagnosticar(con, p.crudo("ingresos.rangos_m2"))
    finally:
        con.close()

    if not dg.huecos:
        typer.echo("No hay celdas bloqueadas: todas las unidades con precio ya rankean.")
        return

    pct = dg.unidades_rankeables_hoy / dg.unidades_con_precio if dg.unidades_con_precio else 0
    typer.echo(
        f"\n  {dg.unidades_con_precio} unidades con precio verificado · "
        f"{dg.unidades_rankeables_hoy} rankean hoy ({pct:.0%})"
    )
    typer.echo(
        f"  {dg.desbloqueables} esperan comparables de arriendo. "
        f"Conseguir {dg.avisos_necesarios} avisos las desbloquea TODAS."
    )

    huecos = [h for h in dg.huecos if not comuna or h.comuna_id == comuna]
    typer.echo(f"\n  Las {min(top, len(huecos))} celdas que mas rinden:\n")
    typer.echo(f"  {'celda':<48} {'unids':>6} {'tiene':>6} {'faltan':>7} {'x aviso':>8}")
    typer.echo(f"  {'-' * 48} {'-' * 6} {'-' * 6} {'-' * 7} {'-' * 8}")
    for h in huecos[:top]:
        celda = f"{h.microzona_id} · {h.tipologia} · {h.rango_m2} m2"
        typer.echo(
            f"  {celda:<48} {h.unidades_bloqueadas:>6} {h.comparables_actuales:>6} "
            f"{h.faltan:>7} {float(h.palanca):>8.1f}"
        )

    typer.echo("\n  Por comuna, para planear la corrida:\n")
    for c, (unidades, avisos) in list(dg.por_comuna().items())[:10]:
        typer.echo(f"    {c:<28} {unidades:>5} unidades esperan  ·  faltan {avisos:>4} avisos")

    typer.echo(
        "\n  El umbral de 8 comparables es del §7.3 y NO se baja: una mediana de tres avisos"
        "\n  es ruido con cara de dato. La respuesta correcta es conseguirlos."
        "\n\n  Siguiente paso: recolecta ARRIENDO en las comunas de arriba y vuelve a correr"
        "\n  `agregar-arriendo` y `oportunidades`."
    )


@app.command()
def explorar(
    url: str = typer.Argument(..., help="URL a explorar"),
    seguir: int = typer.Option(0, help="si es un sitemap, cuantas URLs hijas traer tambien"),
    render: bool = typer.Option(False, "--render", help="usar navegador (paginas con JS)"),
) -> None:
    """Captura documentos crudos de una fuente nueva SIN escribir todavia su parser.

    Existe por disciplina de metodo: un parser de HTML escrito a ciegas contra una fuente que
    nunca vimos es adivinanza con cara de codigo. Este comando verifica robots, baja unos
    pocos documentos a la zona cruda con procedencia completa (§3.6), y describe su FORMA —
    no su contenido— para que el parser se escriba sobre bytes reales.

    Es el paso `fuente-scout` del §8 antes del paso `colector`.
    """
    import os

    import httpx
    from dotenv import load_dotenv

    from flujocero.sources import robots_check
    from flujocero.sources.base import escribir_crudo

    load_dotenv(RAIZ / ".env")
    ua = os.environ.get("USER_AGENT", "").strip() or "FlujoCero-ResearchBot/1.0"
    ahora = datetime.now(UTC)

    typer.echo(f"user-agent: {ua}\n")
    veredicto = robots_check.verificar(url, ua, source_id="_explorar")
    marca = "PERMITE" if veredicto.allowed else "PROHIBE"
    typer.echo(f"robots.txt {marca}: {veredicto.motivo}")
    if veredicto.crawl_delay_s:
        typer.echo(f"  Crawl-delay declarado: {veredicto.crawl_delay_s}s (se respeta)")
    if not veredicto.allowed:
        typer.echo(
            "\n  No se descarga nada. El §3.5 es regla dura: un `html_prohibido` necesita"
            "\n  aprobacion humana explicita registrada en docs/05-decisiones.md."
        )
        raise typer.Exit(1)

    demora = float(veredicto.crawl_delay_s or 1.0)
    objetivos = [url]
    cliente = httpx.Client(timeout=30.0, follow_redirects=True)
    capturados: list[tuple[str, bytes, str]] = []
    try:
        while objetivos:
            destino = objetivos.pop(0)
            if destino != url:
                v = robots_check.verificar(destino, ua, source_id="_explorar")
                if not v.allowed:
                    typer.echo(f"  - {destino}: PROHIBIDA por robots, se salta")
                    continue
                time.sleep(demora)
            if render:
                cuerpo, tipo = _render(destino, ua)
            else:
                r = cliente.get(destino, headers={"User-Agent": ua})
                if r.status_code != 200:
                    typer.echo(f"  ! {destino} respondio {r.status_code}")
                    continue
                cuerpo, tipo = r.content, r.headers.get("content-type", "")
            capturados.append((destino, cuerpo, tipo))
            escribir_crudo(
                source_id="_explorar",
                url=destino,
                contenido=cuerpo,
                momento=ahora,
                robots_snapshot_sha=veredicto.snapshot_sha,
                nombre=destino.replace("https://", "").replace("/", "_")[:80],
                parser_version="explorar/1.0.0",
            )
            hijas = _urls_de_sitemap(cuerpo)
            if hijas and seguir and len(capturados) == 1:
                typer.echo(f"\n  es un sitemap con {len(hijas)} URLs; se traen {seguir}")
                objetivos.extend(hijas[:seguir])
    finally:
        cliente.close()

    typer.echo(f"\n  {len(capturados)} documentos en data/raw/_explorar/\n")
    for destino, cuerpo, tipo in capturados:
        typer.echo(f"  {destino}")
        typer.echo(f"    {len(cuerpo):>9,} bytes · {tipo}")
        for linea in _forma(cuerpo):
            typer.echo(f"    {linea}")
    typer.echo(
        "\n  Mandame estos archivos y escribo el parser sobre bytes reales."
        "\n  Estan en: data/raw/_explorar/"
    )


def _render(url: str, ua: str) -> tuple[bytes, str]:
    """Trae la pagina con un navegador. Solo para fuentes que lo justifiquen en su ADR (§5)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(user_agent=ua)
        pag.goto(url, wait_until="networkidle", timeout=45_000)
        html = pag.content()
        nav.close()
    return html.encode("utf-8"), "text/html (renderizado)"


def _urls_de_sitemap(cuerpo: bytes) -> list[str]:
    """Las URLs de un sitemap XML, o vacio si no lo es. No usa un parser XML a proposito:
    un sitemap malformado tiene que devolver lo que se pueda, no reventar la exploracion."""
    import re

    texto = cuerpo[:5_000_000].decode("utf-8", errors="replace")
    if "<urlset" not in texto and "<sitemapindex" not in texto:
        return []
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", texto)


def _forma(cuerpo: bytes) -> list[str]:
    """Describe la FORMA del documento, no su contenido.

    Lo que un parser necesita saber antes de escribirse: si trae JSON-LD (que es dato
    estructurado y evita parsear HTML), cuantos bloques, si es un sitemap y de que tamano.
    """
    import json
    import re

    texto = cuerpo[:2_000_000].decode("utf-8", errors="replace")
    lineas: list[str] = []

    locs = _urls_de_sitemap(cuerpo)
    if locs:
        lineas.append(f"sitemap con {len(locs)} <loc>; primera: {locs[0]}")
        return lineas

    if texto.lstrip()[:1] in "{[":
        try:
            datos = json.loads(texto)
            claves = sorted(datos)[:12] if isinstance(datos, dict) else f"lista de {len(datos)}"
            lineas.append(f"JSON · {claves}")
            return lineas
        except ValueError:
            pass

    # JSON-LD es el mejor regalo que puede dar una pagina: dato estructurado, sin parsear HTML.
    ld = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        texto,
        re.S | re.I,
    )
    if ld:
        tipos = []
        for bloque in ld:
            try:
                d = json.loads(bloque)
            except ValueError:
                tipos.append("(no parsea)")
                continue
            for item in d if isinstance(d, list) else [d]:
                if isinstance(item, dict):
                    tipos.append(str(item.get("@type", "?")))
        lineas.append(f"JSON-LD: {len(ld)} bloques · @type {tipos}")
    else:
        lineas.append("sin JSON-LD")

    for etiqueta, patron in (
        ("__NEXT_DATA__", r"__NEXT_DATA__"),
        ("window.__NUXT__", r"window\.__NUXT__"),
        ("data-page (Inertia)", r"data-page="),
    ):
        if re.search(patron, texto):
            lineas.append(f"trae {etiqueta}: hay estado de la app embebido, mejor que el HTML")

    precios = re.findall(r"\$\s?[\d.]{6,}", texto)[:3]
    if precios:
        lineas.append(f"montos en pesos visibles, ej: {precios}")
    if re.search(r"\bUF\s?[\d.,]+", texto):
        lineas.append("hay montos en UF")
    return lineas


if __name__ == "__main__":
    app()
