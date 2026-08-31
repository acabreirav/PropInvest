"""CLI de Flujo Cero."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from decimal import getcontext
from typing import Any

import typer

from flujocero import db
from flujocero.alcance import desde_config
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
    fase: int = typer.Option(
        0, help="recolecta todas las comunas de una fase del alcance (§10). 3 = fuera de la RM"
    ),
    operaciones: str = typer.Option("venta,arriendo"),
    paginas: int = typer.Option(3, help="paginas por comuna y operacion (48 avisos c/u)"),
    tipo: str = typer.Option("usadas", help="usadas | nuevas | proyectos | '' para todo"),
    dirigida: int = typer.Option(
        0,
        "--dirigida",
        help="recolecta ARRIENDO en las N comunas con mas unidades esperando (ver `faltantes`)",
    ),
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

    antes = None
    if dirigida:
        # El cuello de botella medido no son los avisos de venta: es que la celda de arriendo
        # de la unidad no llega a los 8 comparables del §7.3. Recolectar "mas arriendo" a
        # ciegas reparte el esfuerzo entre celdas que ya sirven; esto lo manda donde paga.
        # El diagnostico YA respeta el alcance del §10, asi que la prioridad no puede volver
        # a caer en una comuna excluida. Pasó en la corrida del 30-ago: `--dirigida 3` eligio
        # Nunoa, Providencia y Macul por volumen, y Providencia esta en `excluidas` — un
        # tercio de la corrida se gasto recolectando arriendo para unidades que el motor
        # nunca iba a rankear. El filtro vive en el diagnostico y no aca a proposito: asi
        # `cli faltantes` y `--dirigida` no pueden divergir.
        antes = _diagnostico()
        prioridad = list(antes.por_comuna())[:dirigida]
        if not prioridad:
            typer.echo("No hay comunas con unidades esperando: nada que dirigir.")
            raise typer.Exit(0)
        alc = desde_config(cargar("zonas"))
        intrusas = [c for c in prioridad if not alc.en_alcance(c)]
        if intrusas:
            # Defensa en profundidad: si algun dia el diagnostico deja pasar una, la corrida
            # se detiene en vez de gastar 20 minutos recolectando para nada.
            typer.echo(f"✗ el diagnostico propuso comunas fuera del alcance: {intrusas}")
            raise typer.Exit(2)
        lista, ops = prioridad, ("arriendo",)
        typer.echo("  RECOLECCION DIRIGIDA (`--dirigida`): solo arriendo, solo donde falta\n")
        for c in prioridad:
            unidades, avisos = antes.por_comuna()[c]
            typer.echo(f"    {c:<24} {unidades:>5} unidades esperan · faltan {avisos:>4} avisos")
        typer.echo("")
    elif fase:
        # Fase 3 vive fuera de la Region Metropolitana, asi que cada comuna viaja con su
        # slug de region: sin eso la URL apunta a `concepcion-metropolitana`, que no existe,
        # y el portal responde 200 con cero resultados sin dar error.
        alc = desde_config(cargar("zonas"))
        lista = alc.comunas_de_fase(fase)
        if not lista:
            typer.echo(f"La fase {fase} no declara comunas en config/zonas.yml.")
            raise typer.Exit(1)
        ops = tuple(o.strip() for o in operaciones.split(",") if o.strip())
        typer.echo(f"  FASE {fase}: {len(lista)} comunas fuera de la RM")
        typer.echo("  Si nunca corriste `probar-comunas --fase %d`, hacelo primero: un slug" % fase)
        typer.echo("  de region malo devuelve 200 con cero avisos y no da error.\n")
    else:
        lista = [c.strip() for c in comunas.split(",") if c.strip()] or [
            z["comuna"] for z in cargar("zonas").crudo("fase_1")
        ]
        ops = tuple(o.strip() for o in operaciones.split(",") if o.strip())
    etiquetas = [c if isinstance(c, str) else f"{c[0]} ({c[1]})" for c in lista]
    typer.echo(f"  comunas: {', '.join(etiquetas)}\n  operaciones: {', '.join(ops)}")

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

        # **El selftest corre ANTES de cargar.** Estaba al reves: se insertaba y despues se
        # verificaba, asi que el detector de parser roto del §7.1 —"el conteo no cayo >30%
        # vs la ultima corrida exitosa"— se enteraba con los datos ya adentro. El §7.1 pone
        # el selftest para que un colector roto NO contamine; verificar despues de escribir
        # convierte el gate en un informe de danos.
        # Antes que nada: ¿el portal aplico el filtro de comuna? Si dos comunas devolvieron
        # los mismos avisos, esto no recolecto N comunas — recolecto una N veces, y al
        # cargarla la primera se lleva las filas mientras el resto queda en cero. Paso con
        # las cinco del Gran Concepcion (T-049) y ninguna senal lo delataba: paginas
        # completas, HTTP 200, 48 tarjetas cada una.
        from flujocero.quality.comparabilidad import busquedas_que_devuelven_lo_mismo

        por_busqueda: dict[str, set[str]] = {}
        for d in docs:
            if "/arriendo/" in d.url:
                continue
            clave = pb.comuna_de_la_url(d.url) or d.url
            por_busqueda.setdefault(clave, set()).update(t.portal_id for t in col.parse(d))
        repetidas = busquedas_que_devuelven_lo_mismo(
            {k: frozenset(v) for k, v in por_busqueda.items()}
        )
        if repetidas:
            corrida.notas = "el portal no aplico el filtro de comuna"
            typer.echo("\n✗ Comunas distintas devolvieron LOS MISMOS avisos:")
            for a_, b_, comunes, menor in repetidas[:10]:
                typer.echo(f"    {a_} y {b_}: {comunes} en comun de {menor}")
            typer.echo(
                "\n  Un departamento esta en una sola comuna, asi que el portal ignoro el"
                "\n  filtro. No se cargo nada: al cargar, la primera comuna se lleva las"
                "\n  filas y el resto queda en cero sin que nada avise."
                "\n  El `region_slug` de config/zonas.yml es el sospechoso; verificalo con"
                "\n  `cli probar-comunas`. Los blobs QUEDAN en data/raw/."
            )
            raise typer.Exit(5)

        rep = col.selftest(docs, filas_corrida_anterior=anterior)
        corrida.selftest_ok = rep.ok
        corrida.notas = rep.detalle.get("cobertura", "")
        typer.echo(f"{'✓' if rep.ok else '✗'} selftest: {rep.detalle.get('cobertura')}")
        if not rep.ok:
            for k, v in rep.detalle.items():
                if k not in ("cobertura", "proyectos"):
                    typer.echo(f"    {k}: {v}")
            typer.echo(
                "\n✗ No se cargo nada. El selftest del §7.1 esta en rojo, y cargar igual"
                "\n  mete al ranking dato de un parser que ya sabemos que fallo."
                "\n  Los blobs crudos QUEDAN en data/raw/: si el arreglo es del parser, se"
                "\n  recuperan con `rebuild --from-raw` sin volver a pedirle nada al portal."
            )
            raise typer.Exit(4)

        corrida.filas_insertadas = pb.cargar_en_duckdb(con, tarjetas)
        typer.echo(f"✓ {corrida.filas_insertadas} filas nuevas o versionadas")
    except pb.Bloqueado as exc:
        corrida.notas = str(exc)
        typer.echo(f"✗ {exc}")
        raise typer.Exit(3) from exc
    finally:
        bitacora.cerrar(con, corrida, filas_corrida_anterior=None)
        con.close()
        col.cerrar()

    if antes is not None:
        _rendimiento_de_la_corrida(antes)


def _diagnostico():
    """El diagnostico de huecos sobre la base actual. Se abre y cierra la conexion aca."""
    import duckdb

    from flujocero.agg import faltantes as fa

    con = duckdb.connect(str(db.crear()))
    try:
        return fa.diagnosticar(
            con,
            cargar("params").crudo("ingresos.rangos_m2"),
            alcance=desde_config(cargar("zonas")),
            ahora=datetime.now(UTC),
        )
    finally:
        con.close()


def _rendimiento_de_la_corrida(antes) -> None:
    """Cuantas unidades desbloqueo esta corrida. Es la unica medida honesta de si sirvio.

    Sin esto, "traje 340 avisos" es una metrica de esfuerzo, no de resultado: los 340 pueden
    haber caido todos en celdas que ya tenian sus 8 comparables. Lo que importa es cuantas
    unidades pasaron de no evaluables a evaluables.

    Ojo: hay que correr `agregar-arriendo` ANTES de que esto tenga algo que medir. Los avisos
    recien recolectados no cuentan hasta que la agregacion los convierte en comparables.
    """
    typer.echo("\n  Recalculando la agregacion de arriendo para medir el rendimiento...")
    agregar_arriendo()
    despues = _diagnostico()
    ganadas = despues.unidades_rankeables_hoy - antes.unidades_rankeables_hoy
    typer.echo(
        f"\n  RENDIMIENTO DE LA CORRIDA"
        f"\n    rankeables antes:   {antes.unidades_rankeables_hoy}"
        f"\n    rankeables ahora:   {despues.unidades_rankeables_hoy}"
        f"\n    unidades DESBLOQUEADAS: {ganadas:+d}"
        f"\n    todavia esperan:    {despues.desbloqueables}"
    )
    if ganadas <= 0:
        typer.echo(
            "\n  Cero desbloqueadas. No es necesariamente una corrida perdida: los avisos"
            "\n  pueden haber caido en celdas que aun no llegan a 8. Corre `faltantes` para"
            "\n  ver si las celdas objetivo se acercaron al umbral o si no llego nada de ellas."
        )


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
        comparables, descartes = agg.comparables_desde_duckdb(con, datetime.now(UTC))
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

        # Una celda puede tener 124 comparables y no servirle a NADIE: si su microzona esta
        # saturada o su comuna esta fuera del alcance del §10, ninguna unidad de ahi va a
        # rankear nunca. `nunoa/estadio-nacional` es el caso: es la celda mas profunda que
        # tenemos (n=124) y esta marcada saturada. Presentarla como "nuestro mejor dato"
        # —y peor, seguir recolectando ahi— es gastar esfuerzo en un callejon sin salida.
        alc = desde_config(cargar("zonas"))
        utiles, inertes = [], []
        for a in buenos:
            (utiles if alc.unidad_rankeable(a.microzona_id)[0] else inertes).append(a)
        typer.echo(f"✓ {len(buenos)} con n ≥ {agg.MIN_COMPARABLES}")
        typer.echo(f"✓ {len(utiles)} de esas SIRVEN para rankear")
        if inertes:
            avisos_perdidos = sum(a.n for a in inertes)
            typer.echo(
                f"  ⚠ {len(inertes)} celdas con {avisos_perdidos} comparables NO le sirven a"
                "\n    ninguna unidad: su microzona está saturada o su comuna está fuera del"
                "\n    alcance (§10). El dato se conserva, pero recolectar ahí no rinde."
            )
            for a in sorted(inertes, key=lambda x: -x.n)[:3]:
                razon = alc.unidad_rankeable(a.microzona_id)[1] or ""
                typer.echo(f"      {a.microzona_id:34s} n={a.n:3d}  {razon[:52]}")

        # §7.3, la reconciliacion externa. Estaba escrita y nadie la llamaba: es la
        # validacion mas fuerte que tiene el pipeline, porque compara una mediana calculada
        # desde miles de avisos crudos contra una tabla que publico un tercero. Si las dos
        # coinciden, es muy improbable que esten mal de la misma forma.
        from flujocero.quality import checks as qc

        # Solo comunas EN ALCANCE: la alerta venia disparando por las-condes (+49%) y
        # providencia (+29%), que son justamente las dos que el §10 excluye. Una alerta que
        # salta por datos que no rankeamos entrena a ignorarla, que es lo peor que le puede
        # pasar a una alerta.
        por_comuna: dict[str, list] = {}
        for a in utiles:
            por_comuna.setdefault(a.microzona_id.split("/")[0], []).append(a.uf_m2_mediana)
        medianas = {c: agg.percentil(v, D("0.5")) for c, v in por_comuna.items()}
        comparables_con_ref = set(medianas) & set(qc.ARRIENDO_UF_M2_REFERENCIA)
        if not comparables_con_ref:
            # Un chequeo sin datos NO es un chequeo aprobado. Sin esta guarda, con cero
            # comunas en alcance el gate imprimia "✓ medianas dentro de ±25%", que se lee
            # como validado cuando en realidad no se comparo nada. Es la validacion externa
            # mas fuerte del pipeline: presentarla como verde en falso es peor que omitirla.
            typer.echo(
                "\n  ⚠ reconciliacion_arriendo NO SE PUDO CORRER: ninguna comuna en alcance"
                "\n    tiene celdas suficientes para comparar contra la tabla de referencia."
            )
        else:
            hallazgo = qc.reconciliacion_arriendo(medianas, qc.ARRIENDO_UF_M2_REFERENCIA)
            typer.echo(f"\n  {hallazgo}  ({len(comparables_con_ref)} comunas comparadas)")
        for comuna, nuestra in sorted(medianas.items()):
            ref = qc.ARRIENDO_UF_M2_REFERENCIA.get(comuna)
            if ref:
                typer.echo(
                    f"    {comuna:20s} nuestro {nuestra:.3f}  publicado {ref:.2f}  "
                    f"({(nuestra - ref) / ref:+.0%})"
                )

        typer.echo("\n  Las más profundas de las que SIRVEN:")
        for a in sorted(utiles, key=lambda x: -x.n)[:10]:
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
    from flujocero.quality.checks import FRESCURA_MAX_DIAS

    p, inv = cargar("params"), cargar("inversionista")
    con = duckdb.connect(str(db.crear()))
    try:
        r = op.emparejar(
            con,
            p.crudo("ingresos.rangos_m2"),
            alcance=desde_config(cargar("zonas")),
            ahora=datetime.now(UTC),
        )
    finally:
        con.close()

    typer.echo(f"  {r.total} unidades con precio verificado · {len(r.unidades)} rankeables")
    for motivo, n in r.descartes.items():
        if n:
            typer.echo(f"    fuera por {motivo}: {n}")
    if r.implausibles:
        # Se listan una por una, no se cuentan nomas. Son pocas y cada una es un aviso que
        # dice una cosa y significa otra: la primera que aparecio pedia UF 850 por un 2D2B
        # de 60 m2 —14,2 UF/m2— porque vendia una PROMESA, no el departamento, y con eso
        # encabezaba el ranking con 17,58% de yield contra 7,90% de la segunda.
        typer.echo(
            "\n  ⚠ El §7.1 declara UF/m² entre 20 y 200. Estas filas caen fuera: bajo el\n"
            "    mínimo, el precio publicado no es el del departamento. Se conservan en la\n"
            "    base con su procedencia; quedan fuera del ranking:"
        )
        for key, razon in r.implausibles[:10]:
            typer.echo(f"      {key:18} {razon}")
    if not r.unidades:
        # El mensaje nombra la causa que DOMINA, no una causa plausible. Cuando el corpus
        # entero era de mayo, "corré agregar-arriendo" mandaba a arreglar lo que no estaba
        # roto: faltaba recolectar precios de hoy, no agregar arriendos viejos.
        peor = max(r.descartes.items(), key=lambda kv: kv[1], default=("", 0))
        if peor[0] == "desactualizada":
            typer.echo(
                f"\n✗ Las {peor[1]} unidades tienen precio de hace más de "
                f"{FRESCURA_MAX_DIAS} días.\n"
                "  El §7.3 las deja fuera del ranking: un precio de hace meses no es una\n"
                "  oportunidad peor, es una que no sabemos si existe. Siguen en la base como\n"
                "  línea base para medir qué bajó de precio.\n"
                "    uv run python -m flujocero.cli recolectar-portal --paginas 8"
            )
        else:
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
        dv = r.desvio_m2.get(u.unidad_key)
        nota = ""
        if dv is not None and abs(dv) >= D("0.15"):
            nota = f"  ⚠ la unidad es {dv:+.0%} vs el depto típico de esa celda"
        typer.echo(f"    {u.unidad_key}: UF {arr:.2f}/mes · mediana de {n} avisos en {celda}{nota}")

    # T-941 · Una banda de m2 NO es homogenea, y el sesgo cae justo en las primeras filas.
    # Medido el 30-ago-2026 sobre 1D1B en la banda `0-35`: el 60% de los comparables mide
    # 31-35 m2 y la mediana de la banda es $350.000, mientras que los de 22-26 rentan
    # $300.000. A un depto de 22 m2 se le acredita +17% de arriendo, y el arriendo es el
    # numerador del yield: el mismo +17% se traslada entero al yield y lo sube en el ranking.
    UMBRAL_DESVIO = D("0.15")
    sesgadas = [
        (u, ev, r.desvio_m2[u.unidad_key])
        for u, ev in vivos[:20]
        if u.unidad_key in r.desvio_m2 and r.desvio_m2[u.unidad_key] <= -UMBRAL_DESVIO
    ]
    if sesgadas:
        typer.echo(
            f"\n  ⚠ {len(sesgadas)} de las 20 primeras son MÁS CHICAS que el depto típico"
            "\n    de su celda de arriendo, así que su arriendo está SOBREestimado y su"
            "\n    yield también. El rango de m² se trata como homogéneo y no lo es:"
        )
        for u, _ev, dv in sesgadas[:6]:
            celda, n, _arr = r.procedencia_arriendo[u.unidad_key]
            typer.echo(
                f"      {u.unidad_key}  {u.m2_utiles:>5.0f} m²  {dv:+.0%} vs su celda "
                f"({n} comparables)"
            )
        bandas_tocadas = sorted(
            {
                r.procedencia_arriendo[u.unidad_key][0].split("·")[-1].strip()
                for u, _ev, _dv in sesgadas
            }
        )
        typer.echo(
            "\n    NO se corrige el arriendo: inventar un ajuste sería imputar (§3.2)."
            f"\n    El sesgo que queda vive en {', '.join(bandas_tocadas)}."
            "\n    Ya se angostó `0-35` en D-018 y eso sacó 6 de las 9 que estaban sesgadas;"
            "\n    partir otra banda tiene el mismo canje —menos sesgo, menos celdas— y se"
            "\n    mide con `cli bandas --propuesta <cortes>` antes de decidir (§8.4)."
            "\n    La solución de fondo es otra: comparables con superficie exacta por unidad,"
            "\n    no medianas de banda."
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
        # **El ancla externa del §7.3 nunca habia corrido.** `correr()` la acepta desde
        # siempre y `cli gates` no le pasaba el argumento, asi que el gate que el contrato
        # declara como FALLA —"desviacion >20% contra la tabla Colliers"— no se evaluo jamas.
        #
        # Y se conecta comparando lo comparable: la tabla es de departamento **NUEVO** y hoy
        # el 100% de la base es usado. Medirlos con la misma vara es el error del amoblado
        # del lado de la venta. El ancla mira el stock nuevo; el usado va aparte, como
        # medicion informativa que no aprueba ni reprueba.
        por_comuna_nuevo: dict[str, list[D]] = {}
        por_comuna_usado: dict[str, list[D]] = {}
        for u in unidades:
            mz, precio, m2 = u.get("microzona_id"), u.get("precio_uf"), u.get("m2_utiles")
            if not mz or not precio or not m2:
                continue
            destino = por_comuna_nuevo if u.get("es_vivienda_nueva") else por_comuna_usado
            destino.setdefault(str(mz).split("/")[0], []).append(D(str(precio)) / D(str(m2)))

        def _medianas(d: dict[str, list[D]]) -> dict[str, D]:
            return {c: sorted(v)[len(v) // 2] for c, v in d.items() if v}

        rep = qc.correr(
            unidades,
            comps,
            datetime.now(UTC),
            mediana_uf_m2_por_comuna=_medianas(por_comuna_nuevo),
            mediana_usado_por_comuna=_medianas(por_comuna_usado),
            fuentes_historicas=historicas,
        )
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
    alc = desde_config(cargar("zonas"))
    con = duckdb.connect(str(db.crear()))
    try:
        dg = fa.diagnosticar(
            con, p.crudo("ingresos.rangos_m2"), alcance=alc, ahora=datetime.now(UTC)
        )
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

    # El desglose por comuna respeta `--comuna` igual que la tabla de arriba. Antes no, y
    # eso confundia de la peor manera: `--comuna concepcion` devolvia "0 celdas" y ACTO
    # SEGUIDO listaba nunoa, antofagasta y talcahuano, que se lee como si fueran de
    # Concepcion. La respuesta correcta a esa consulta era "Concepcion no tiene ninguna
    # unidad en la base", y quedaba tapada por un listado de otras comunas.
    por_comuna = [(c, v) for c, v in dg.por_comuna().items() if not comuna or c == comuna]
    if comuna and not por_comuna:
        typer.echo(
            f"\n  {comuna} no tiene ninguna unidad esperando comparables.\n"
            "  Puede ser que ya rankeen todas, o que no haya ninguna en la base.\n"
            f"    uv run python -m flujocero.cli embudo --comuna {comuna}"
        )
        return
    typer.echo("\n  Por comuna, para planear la corrida:\n")
    for c, (unidades, avisos) in por_comuna[:10]:
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


AYUDA_NAVEGADOR = (
    "falta el navegador de Playwright. Se descarga una vez:\n\n"
    "    uv run playwright install chromium\n\n"
    "  (son ~150 MB; `make setup` tambien lo hace)"
)


def navegador_ausente(exc: Exception) -> typer.BadParameter | None:
    """Traduce "no esta el binario" a un comando. `None` si el error es otro.

    Es puro para poder testearlo sin instalar ni desinstalar un navegador. Playwright busca
    un build EXACTO —`chromium_headless_shell-1234`— asi que este error aparece tanto en una
    maquina recien clonada como en una donde el paquete se actualizo y el binario no.
    """
    texto = str(exc)
    if "Executable doesn't exist" in texto or "playwright install" in texto:
        return typer.BadParameter(AYUDA_NAVEGADOR)
    return None


def _render(url: str, ua: str) -> tuple[bytes, str]:
    """Trae la pagina con un navegador. Solo para fuentes que lo justifiquen en su ADR (§5).

    El navegador se descarga aparte de las dependencias de Python, asi que en una maquina
    recien clonada esto falla. Antes reventaba con un traceback de 60 lineas terminado en un
    cartel en ingles; ahora dice el comando. Un error de instalacion que exige leer un
    traceback para saber que hacer es un error mal reportado.
    """
    from playwright.sync_api import Error as ErrorPlaywright
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch()
        except ErrorPlaywright as exc:
            amable = navegador_ausente(exc)
            if amable is not None:
                raise amable from exc
            raise
        try:
            pag = nav.new_page(user_agent=ua)
            pag.goto(url, wait_until="networkidle", timeout=45_000)
            html = pag.content()
        finally:
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


@app.command()
def bandas(
    propuesta: str = typer.Option("0,25,35,50,70,100,140", help="cortes en m2, separados por coma"),
) -> None:
    """T-941 · cuanto cuesta angostar las bandas de m2, y cuanto sesgo saca.

    El problema: una banda de m2 se trata como si fuera homogenea y no lo es. Medido sobre
    1D1B en la banda `0-35`, el 60% de los comparables mide 31-35 m2 y la mediana de la banda
    es $350.000, mientras que los de 22-26 rentan $300.000. A un depto de 22 m2 se le acredita
    **+17% de arriendo**, que es el numerador del yield: el mismo +17% se traslada entero al
    yield y lo sube en el ranking. Las primeras filas del top son justo unidades de 18-23 m2.

    Angostar arregla el sesgo y **cuesta comparables**: cada banda nueva parte la muestra, y
    una celda que caiga bajo los 8 del §7.3 deja de rankear a todas sus unidades. Este
    comando mide las dos cosas sobre los datos reales para que la decision sea informada.

    No cambia nada: solo mide. El §8.4 dice que un supuesto que mueve el ranking mas de un
    10% se decide con el humano, y este lo mueve.
    """
    import duckdb

    from flujocero.agg import arriendo as ag

    cortes = [int(x.strip()) for x in propuesta.split(",") if x.strip()]
    if len(cortes) < 2 or cortes != sorted(cortes):
        typer.echo("✗ los cortes tienen que ir en orden ascendente y ser al menos dos.")
        raise typer.Exit(2)
    nuevos = [[a, b] for a, b in zip(cortes, cortes[1:], strict=False)]
    actuales = cargar("params").crudo("ingresos.rangos_m2")

    con = duckdb.connect(str(db.crear()))
    try:
        # Devuelve `(comparables, descartes)`; aca solo interesan los comparables.
        comps, _descartes = ag.comparables_desde_duckdb(con, datetime.now(UTC))
    finally:
        con.close()
    if not comps:
        typer.echo("No hay comparables cargados. Corré `agregar-arriendo` primero.")
        raise typer.Exit(1)

    m2_min = min(c.m2_utiles for c in comps)
    typer.echo(f"\n  {len(comps)} comparables de arriendo · el más chico mide {m2_min:.0f} m²\n")
    guardadas: dict[str, list] = {}
    for etiqueta, rangos in (("ACTUAL  ", actuales), ("PROPUESTA", nuevos)):
        ags = ag.agregar(comps, rangos)
        utiles = [a for a in ags if a.n >= ag.MIN_COMPARABLES]
        guardadas[etiqueta.strip()] = utiles
        # Cuantas veces mas grande es el techo de la banda que su piso: el factor de
        # heterogeneidad. En una banda de 2x, dos unidades del mismo grupo pueden diferir al
        # doble de superficie y compartir mediana de arriendo.
        # La primera banda empieza en 0, asi que su piso REAL es el m2 mas chico observado.
        # Dividir por cero —o por 1, que era el parche— daba un "35x" que no medía nada.
        factores = [D(str(b)) / max(D(str(a)), m2_min) for a, b in [tuple(x) for x in rangos]]
        typer.echo(
            f"  {etiqueta}  {len(rangos)} bandas · {len(ags)} celdas · "
            f"{len(utiles)} con n>=8 · la banda más heterogénea mezcla hasta "
            f"{max(factores):.1f}x de superficie"
        )
        typer.echo(f"             cortes: {[r[0] for r in rangos] + [rangos[-1][1]]}")

    ags_act, ags_new = guardadas["ACTUAL"], guardadas["PROPUESTA"]
    delta = len(ags_new) - len(ags_act)
    typer.echo(f"\n  Celdas que pueden rankear: {len(ags_act)} → {len(ags_new)} ({delta:+d})")
    if delta < 0:
        typer.echo(
            "\n  Angostar SACA celdas: al partir la muestra, algunas caen bajo los 8"
            "\n  comparables del §7.3 y dejan de rankear a todas sus unidades. El umbral"
            "\n  NO se baja para compensar: una mediana de tres avisos es ruido con cara"
            "\n  de dato. Se compensa recolectando (`recolectar-portal --dirigida`)."
        )
    else:
        typer.echo("\n  Angostar no cuesta celdas con los datos de hoy.")

    typer.echo(
        "\n  Si decidís cambiarlas, van en `config/params.yml:ingresos.rangos_m2`."
        "\n  Es un cambio de supuesto: queda registrado en docs/05-decisiones.md."
    )
    # Las CELDAS no son la unidad de decision: importa cuantas UNIDADES dejan de rankear y
    # cuantas quedan comparadas contra un depto de su tamano. Una celda perdida con 2
    # unidades y otra con 80 pesan distinto, y contar celdas las trata igual.
    _unidades_afectadas(ags_act, ags_new, actuales, nuevos)


def _unidades_afectadas(ags_act, ags_new, actuales, nuevos) -> None:
    """Cuantas unidades de venta pierden su celda y cuantas quedan bien emparejadas.

    Es el numero con el que se decide. `cli bandas` contaba CELDAS, y una celda con 2
    unidades pesa igual que una con 80 si se cuentan celdas.
    """
    import duckdb

    from flujocero.agg.arriendo import etiqueta_rango
    from flujocero.agg.faltantes import CONSULTA

    vivas_act = {(a.microzona_id, a.tipologia, a.rango_m2) for a in ags_act}
    vivas_new = {(a.microzona_id, a.tipologia, a.rango_m2) for a in ags_new}
    m2_tipico = {(a.microzona_id, a.tipologia, a.rango_m2): a.m2_mediana for a in ags_new}

    alc = desde_config(cargar("zonas"))
    con = duckdb.connect(str(db.crear()))
    try:
        filas = con.execute(CONSULTA).fetchall()
    finally:
        con.close()

    pierden = ganan = bien_emparejadas = 0
    for mz, tip, m2 in filas:
        if not alc.unidad_rankeable(mz)[0]:
            continue
        val = D(str(m2))
        ra, rn = etiqueta_rango(val, actuales), etiqueta_rango(val, nuevos)
        antes = ra is not None and (mz, tip, ra) in vivas_act
        despues = rn is not None and (mz, tip, rn) in vivas_new
        if antes and not despues:
            pierden += 1
        elif despues and not antes:
            ganan += 1
        elif antes and despues:
            tipico = m2_tipico.get((mz, tip, rn))
            if tipico and abs(val - tipico) / tipico < D("0.15"):
                bien_emparejadas += 1

    typer.echo(
        "\n  En UNIDADES, que es lo que importa para decidir:"
        f"\n    dejan de rankear:                                    {pierden}"
        f"\n    empiezan a rankear:                                  {ganan}"
        f"\n    quedan comparadas contra un depto de su tamaño (±15%): {bien_emparejadas}"
    )


@app.command()
def probar_comunas(
    fase: int = typer.Option(3, help="que fase del alcance probar"),
) -> None:
    """Verifica que los slugs de comuna y region de una fase EXISTEN en el portal.

    Existe porque un slug de region equivocado **no da error**. El portal responde 200 con
    cero resultados y una corrida de veinte minutos "funciona" sin traer nada. `zonas.yml`
    los declara marcados como SIN VERIFICAR justamente para que nadie recolecte antes de
    pasar por aca.

    Pide UNA pagina por comuna, respetando robots y la pausa entre peticiones. Reporta
    cuantas tarjetas trajo cada una: cero tarjetas con HTTP 200 es la senal de slug malo.
    """
    import os

    from dotenv import load_dotenv

    from flujocero.sources import portal_busqueda as pb

    load_dotenv(RAIZ / ".env")
    ua = os.environ.get("USER_AGENT", "").strip()
    if not ua:
        typer.echo("✗ falta USER_AGENT en el .env. Es la identidad con la que nos presentamos.")
        raise typer.Exit(2)

    alc = desde_config(cargar("zonas"))
    objetivos = alc.comunas_de_fase(fase)
    if not objetivos:
        typer.echo(f"La fase {fase} no declara comunas en config/zonas.yml.")
        raise typer.Exit(1)

    col = pb.PortalBusqueda(user_agent=ua)
    veredicto = col.robots_ok()
    typer.echo(f"{'✓' if veredicto.allowed else '✗'} robots.txt: {veredicto.motivo}")
    if not veredicto.allowed:
        raise typer.Exit(2)

    typer.echo(f"\n  Probando {len(objetivos)} comunas de la fase {fase}:\n")
    buenas, malas = [], []
    # Los `MLC-` que devolvio cada comuna. **Contar tarjetas no basta**, y esa fue la leccion
    # cara de fase 3: este comando dijo "8/8, 48 tarjetas cada una" y las cinco comunas del
    # Gran Concepcion habian devuelto EXACTAMENTE los mismos 48 avisos. El portal ignoro el
    # filtro de comuna y sirvio la misma pagina; el conteo no podia notarlo porque contaba
    # el numero correcto. Se recolecto una comuna cinco veces creyendo que eran cinco.
    ids_por_comuna: dict[str, frozenset[str]] = {}
    try:
        for i, (comuna, region) in enumerate(objetivos):
            url = pb.url_busqueda("venta", comuna, 1, "usadas", region_slug=region)
            if i:
                col._dormir()
            r = col._pedir(url)
            if r.status_code != 200:
                typer.echo(f"    ✗ {comuna:24s} {region:14s} HTTP {r.status_code}")
                malas.append((comuna, region, f"HTTP {r.status_code}"))
                continue
            doc = pb.RawDoc(
                source_id=col.id,
                url=url,
                fetched_at=datetime.now(UTC),
                ruta=RAIZ / "sin-guardar",
                contenido=r.content,
                robots_snapshot_sha=veredicto.snapshot_sha,
            )
            tarjetas = col.parse(doc)
            n = len(tarjetas)
            ids_por_comuna[comuna] = frozenset(t.portal_id for t in tarjetas)
            marca = "✓" if n else "✗"
            typer.echo(f"    {marca} {comuna:24s} {region:14s} {n:3d} tarjetas")
            (buenas if n else malas).append((comuna, region, f"{n} tarjetas"))
    finally:
        col.cerrar()

    # Dos comunas distintas no pueden devolver el mismo aviso: un departamento esta en una
    # sola. Si comparten avisos, el filtro no se aplico y la corrida recolectaria lo mismo
    # varias veces. Se compara antes de dar los slugs por buenos.
    from flujocero.quality.comparabilidad import busquedas_que_devuelven_lo_mismo

    repetidas = [
        f"{a} y {b}: {comunes} avisos en comun de {menor}"
        for a, b, comunes, menor in busquedas_que_devuelven_lo_mismo(ids_por_comuna)
    ]

    typer.echo(f"\n  {len(buenas)} comunas responden con avisos · {len(malas)} no")
    if repetidas:
        typer.echo(
            "\n  ✗ Hay comunas que devuelven LOS MISMOS avisos. Un departamento esta en una"
            "\n    sola comuna, asi que el portal no aplico el filtro: recolectar asi trae"
            "\n    una comuna repetida N veces, y al cargar la primera se lleva las filas"
            "\n    mientras el resto queda en cero.\n"
        )
        for linea in repetidas[:10]:
            typer.echo(f"      {linea}")
        typer.echo(
            "\n    El `region_slug` es el sospechoso. Cambialo en `config/zonas.yml` y volve"
            f"\n    a correr esto.  Regiones que el colector reconoce: {', '.join(pb.REGIONES)}"
        )
        raise typer.Exit(1)
    if malas:
        typer.echo(
            "\n  Cero tarjetas con HTTP 200 casi siempre es el SLUG DE REGION mal puesto,"
            "\n  no una comuna sin oferta. Los slugs viven en `config/zonas.yml` como"
            "\n  `region_slug` y estan marcados SIN VERIFICAR hasta que este comando pase."
            f"\n  Regiones que el colector reconoce hoy: {', '.join(pb.REGIONES)}"
        )
        raise typer.Exit(1)
    typer.echo(
        "\n  Todos los slugs son buenos. Saca el comentario `SIN VERIFICAR` de zonas.yml"
        f"\n  y ya se puede recolectar:  cli recolectar-portal --fase {fase}"
    )


@app.command()
def comparables(
    microzona: str = typer.Argument(..., help="ej. antofagasta/la-chimba"),
    tipologia: str = typer.Option("", help="ej. 1D1B. Vacio = todas"),
    rango: str = typer.Option("", help="ej. 35-50. Vacio = todos"),
) -> None:
    """Los avisos DETRAS de una mediana de arriendo, con su URL para ir a mirarlos.

    Una mediana de arriendo es la mitad de todo yield del sistema y hasta ahora era una
    caja cerrada: el ranking decia "mediana de 11 avisos" y no habia forma de ver cuales.
    Las seis columnas de procedencia del §3.1 existen justamente para esto, pero guardadas
    sin manera de leerlas no sirven de nada.

    Lo destapo el ranking del 31-ago-2026: `antofagasta/la-chimba · 1D1B · 35-50 m²` da
    **UF 16,15/mes con n=11** — mas que un 2D2B de La Serena (14,68) y que uno de San Miguel
    (12,21). Puede ser real: el §10 predice cap rate 4,5% para Antofagasta, el mas alto del
    pais, y una ciudad minera tiene arriendos altos de verdad. Pero la tabla de referencia
    externa **no cubre Antofagasta**, asi que no hay con que contrastarlo. Cuando el ancla
    externa no llega, el unico control que queda es mirar los avisos.
    """
    import duckdb

    con = duckdb.connect(str(db.crear()))
    try:
        condiciones = ["microzona_id = ?", "activo", "arriendo_clp IS NOT NULL"]
        args: list[object] = [microzona]
        if tipologia:
            condiciones.append("tipologia = ?")
            args.append(tipologia)
        filas = con.execute(
            "SELECT comp_id, tipologia, m2_utiles, arriendo_clp, arriendo_uf, fetched_at, "
            f"source_url FROM fact_arriendo_comp WHERE {' AND '.join(condiciones)} "
            "ORDER BY arriendo_clp",
            args,
        ).fetchall()
    finally:
        con.close()

    if rango:
        lo, hi = (int(x) for x in rango.split("-"))
        filas = [f for f in filas if f[2] is not None and lo <= f[2] < hi]

    if not filas:
        typer.echo(f"  Sin comparables activos en {microzona} con ese filtro.")
        raise typer.Exit(1)

    from flujocero.quality.checks import FRESCURA_MAX_DIAS
    from flujocero.quality.comparabilidad import dudoso, no_comparable

    # **La mediana tiene que salir de la MISMA poblacion que usa el ranking.** Este comando
    # nacio para auditar el numero que el ranking muestra, y sin este filtro auditaba otro:
    # sobre `santiago/san-diego 1D1B 25-35` decia $330.000 sobre 23 avisos mientras el
    # ranking usaba $355.000 sobre 12. Los 11 de diferencia eran de mayo, que el §7.3 saca de
    # la agregacion. Dos numeros para la misma celda es exactamente lo que este proyecto
    # viene cazando toda la semana — y esta vez lo habia puesto yo.
    limite = datetime.now(UTC) - timedelta(days=FRESCURA_MAX_DIAS)

    def entra(f: Any) -> bool:
        return not no_comparable(f[6]) and f[5] is not None and f[5] >= limite

    def senal(f: Any) -> str:
        if no_comparable(f[6]):
            return "✗ "
        if f[5] is None or f[5] < limite:
            return "· "
        return "? " if dudoso(f[6]) else "  "

    montos = sorted(f[3] for f in filas if entra(f))
    amoblados = sum(1 for f in filas if no_comparable(f[6]))
    viejos = sum(1 for f in filas if not no_comparable(f[6]) and (f[5] is None or f[5] < limite))
    cabecera = (
        f"  {len(filas)} avisos · {amoblados} amoblados · {viejos} de más de "
        f"{FRESCURA_MAX_DIAS} días · "
    )
    if montos:
        mediana = (
            montos[len(montos) // 2]
            if len(montos) % 2
            else (montos[len(montos) // 2 - 1] + montos[len(montos) // 2]) // 2
        )
        typer.echo(f"{cabecera}{len(montos)} alimentan la mediana de ${mediana:,.0f}/mes\n")
    else:
        # Sin comparables vigentes NO hay mediana, y no se calcula una con los viejos: seria
        # exactamente el numero que el ranking no usa. La celda no rankea y hay que decirlo.
        typer.echo(
            f"{cabecera}ninguno alimenta la mediana.\n\n"
            "  ✗ Esta celda NO produce arriendo para el ranking: todo lo que tiene está\n"
            "    amoblado o vencido. Los avisos se listan igual porque son historia."
        )
    typer.echo(f"    {'arriendo':>12s} {'m2':>5s} {'$/m2':>7s} {'tipo':6s} {'visto':10s} aviso")
    for fila in filas:
        _cid, tip, m2, clp, _uf, visto, url = fila
        # `arriendo_clp` es DECIMAL y `m2_utiles` FLOAT: dividirlos directo revienta.
        por_m2 = f"{float(clp) / m2:>7,.0f}" if m2 else "      —"
        typer.echo(
            f"  {senal(fila)}${clp:>11,.0f} {m2 or 0:>5.0f} {por_m2} {tip or '?':6s} "
            f"{visto:%Y-%m-%d} {url}"
        )
    typer.echo(
        "\n  ✗ = amoblado o estadia corta: otro producto.   · = de más de "
        f"{FRESCURA_MAX_DIAS} días: el §7.3 lo saca del ranking, se conserva como historia."
        "\n  ? = merece una mirada (cocina equipada, gastos comunes incluidos)."
        f"\n  La mediana sale de los {len(montos)} marcados con espacio, "
        f"no de los {len(filas)} avisos."
    )
    if len(montos) < 8:
        # El umbral del §7.3 existe para que la mediana no sea ruido. Once avisos de tres
        # productos distintos son ruido con mejor presentacion que tres avisos de uno.
        typer.echo(
            f"\n  ⚠ Con {len(montos)} comparables limpios esta celda NO alcanza los 8 del §7.3."
            "\n    Llegaba a 8 contando productos que no son el mismo producto."
        )
    if any(dudoso(f[6]) for f in filas):
        typer.echo(
            '\n  Los marcados `?` SI entran a la mediana: en Chile "cocina equipada" es'
            "\n  estandar en un arriendo pelado, y excluirlos por esa palabra perderia dato"
            "\n  bueno. Se marcan para que los mires, no para decidir por ti."
        )


@app.command()
def embudo(
    comuna: str = typer.Option("", help="una comuna, o vacio para todas"),
    fase: int = typer.Option(0, help="solo las comunas de una fase del alcance (§10)"),
    detalle: bool = typer.Option(False, help="muestra un aviso de ejemplo por comuna"),
) -> None:
    """Que le paso a las unidades de cada comuna, paso por paso hasta el ranking.

    Nace de una pregunta concreta que no se podia contestar: **Gran Concepcion respondio 48
    tarjetas por comuna en `probar-comunas`, se recolecto, y no aparecio ni una sola unidad
    suya en el ranking.** ¿Se cayeron por viejas, por microzona, por falta de comparables, o
    nunca llegaron a la base? Cada respuesta lleva a una accion distinta y adivinar cual es
    sale caro: una corrida de recoleccion son veinte minutos apuntando al lugar equivocado.

    Lo cuenta **el mismo recorrido que arma el ranking** (`emparejar`), no una consulta
    paralela. Es deliberado: este proyecto ya pago varias veces el precio de tener dos
    implementaciones del mismo criterio, una de las cuales se queda atras en silencio.
    """
    import duckdb

    from flujocero.agg import oportunidades as op

    alc = desde_config(cargar("zonas"))
    con = duckdb.connect(str(db.crear()))
    try:
        r = op.emparejar(
            con, cargar("params").crudo("ingresos.rangos_m2"), alcance=alc, ahora=datetime.now(UTC)
        )
    finally:
        con.close()

    quiere = {c for c, _ in alc.comunas_de_fase(fase)} if fase else None
    if comuna:
        quiere = {comuna}

    filas = {c: m for c, m in r.por_comuna.items() if quiere is None or c in quiere}

    # El silencio es una respuesta, y hay que decirla con todas las letras: una comuna que no
    # aparece en el embudo NO tiene ninguna unidad en `fact_unidad_venta`. No es que se
    # cayeron en algun filtro; nunca llegaron. Eso apunta al colector de VENTA, y es la unica
    # rama que ninguna cantidad de recoleccion de ARRIENDO arregla. Se dice ANTES de la
    # tabla porque una comuna ausente no tiene fila donde mirarse.
    ausentes = sorted(quiere - set(filas)) if quiere else []
    if ausentes:
        typer.echo(
            f"\n  ⚠ CERO unidades en la base: {', '.join(ausentes)}\n"
            "    No se cayeron en un filtro: no hay ninguna fila. Es el colector de VENTA,\n"
            "    no la falta de comparables de arriendo.\n"
            "      uv run python -m flujocero.cli recolectar-portal --comunas "
            f"{','.join(ausentes)} --operaciones venta --paginas 8"
        )
        if not filas:
            raise typer.Exit(1)

    motivos = ["rankea", *[m for m in r.descartes if m != "rankea"]]
    presentes = [m for m in motivos if any(f.get(m) for f in filas.values())]
    typer.echo(f"\n  {'comuna':24s}" + "".join(f"{m[:11]:>13s}" for m in presentes))
    typer.echo("  " + "-" * (24 + 13 * len(presentes)))
    for c, m in sorted(filas.items(), key=lambda kv: -sum(kv[1].values())):
        typer.echo(f"  {c:24s}" + "".join(f"{m.get(k, 0) or '':>13}" for k in presentes))
    if detalle:
        # La etiqueta de comuna sale de la URL de BUSQUEDA, no del texto del aviso. Cuando
        # una comuna aparece con unidades que uno no esperaba —o desaparece una que si—, lo
        # que hay que ver es la URL: dice que filtro aplico el portal cuando se recolecto.
        # Sin esto, "chiguayante tiene 103 unidades" es una afirmacion que no se puede
        # auditar, y una etiqueta equivocada manda la recoleccion a la comuna equivocada.
        from pathlib import Path

        con = duckdb.connect(str(db.crear()))
        try:
            typer.echo("\n  De donde salio cada comuna, para poder auditar la etiqueta:\n")
            for c in sorted(filas):
                fila = con.execute(
                    "SELECT count(*), min(raw_blob_path), max(raw_blob_path), "
                    "count(precio_clp), min(m2_utiles), median(m2_utiles), max(m2_utiles) "
                    "FROM fact_unidad_venta WHERE valid_to IS NULL AND microzona_id LIKE ?",
                    (f"{c}/%",),
                ).fetchone()
                if not fila or not fila[0]:
                    continue
                n, blob_min, blob_max, en_pesos, m2_min, m2_med, m2_max = fila
                typer.echo(
                    f"    {c:22} {n:>5} unidades · {en_pesos} con precio en pesos · "
                    f"m² min {m2_min or 0:.0f} / mediana {m2_med or 0:.0f} / max {m2_max or 0:.0f}"
                )
                # El nombre del blob es `{operacion}_{comuna}_p{NN}`: dice con QUE FILTRO se
                # pidio la pagina. Si no coincide con la comuna de la fila, la etiqueta esta
                # mal puesta y toda la recoleccion dirigida apunta al lugar equivocado.
                typer.echo(f"      blobs: {Path(blob_min).name} … {Path(blob_max).name}")
        finally:
            con.close()

    typer.echo(
        "\n  `rankea` es la unica columna que produce oportunidades. El resto son salidas,\n"
        "  y cada una tiene su arreglo: `desactualizada` se arregla recolectando VENTA de\n"
        "  nuevo; `sin_comparables`, recolectando ARRIENDO; `fuera_de_alcance` y\n"
        "  `microzona_saturada` son decisiones de `config/zonas.yml`, no problemas de dato."
    )


@app.command()
def crudo(
    fuente: str = typer.Option("", help="un source_id, o vacio para todas"),
    contiene: str = typer.Option("", help="filtra por parte del nombre, ej. 'venta_conce'"),
) -> None:
    """Que hay en `data/raw/`, agrupado por dia. La zona cruda es la fuente de verdad (§3.6).

    Sirve para separar dos preguntas que se confunden todo el tiempo y llevan a acciones
    opuestas: **¿el colector no trajo esto, o lo trajo y se perdio al cargar?** Si el blob
    existe, el problema esta en el parser o en la carga y se arregla con `rebuild --from-raw`,
    sin pedirle nada al portal. Si no existe, hay que volver a recolectar.

    Se agrega por dia porque una recoleccion es un dia: ver "30-ago: 40 blobs de venta, 4
    comunas" contra "8 comunas" contesta la pregunta de un vistazo.
    """
    import json
    from collections import Counter

    from flujocero.sources.base import blobs_crudos

    blobs = [b for b in blobs_crudos(fuente or None) if b.name != "robots.txt.json.gz"]
    if contiene:
        blobs = [b for b in blobs if contiene in b.name]
    if not blobs:
        typer.echo("  No hay blobs que calcen con ese filtro en data/raw/.")
        raise typer.Exit(1)

    # `.../{source_id}/{yyyy}/{mm}/{dd}/nombre.json.gz` — el §3.6 fija esa forma.
    por_dia: Counter[tuple[str, str]] = Counter()
    nombres: dict[tuple[str, str], set[str]] = {}
    for b in blobs:
        clave = (b.parts[-5], f"{b.parts[-4]}-{b.parts[-3]}-{b.parts[-2]}")
        por_dia[clave] += 1
        # El nombre es `{operacion}_{comuna}_pNN`: se agrupa sin la pagina para contar
        # cuantas comunas distintas se recolectaron ese dia, que es lo que uno quiere saber.
        nombres.setdefault(clave, set()).add("_".join(b.name.split("_")[:2]))

    typer.echo(f"\n  {len(blobs)} blobs\n")
    for (fte, dia), n in sorted(por_dia.items()):
        distintos = sorted(nombres[(fte, dia)])
        typer.echo(f"  {dia}  {fte:<22} {n:>4} blobs · {len(distintos)} busquedas distintas")
        for d in distintos:
            typer.echo(f"      {d}")

    # **Dos busquedas distintas que devuelven el MISMO documento.** El `.meta.json` guarda el
    # sha del contenido desde siempre y nadie lo miraba. Si `venta_concepcion_p01` y
    # `venta_talcahuano_p01` tienen el mismo sha, el portal ignoro el filtro de comuna y
    # sirvio la misma pagina: la corrida "funciono" —200, 48 tarjetas por pagina— y no
    # recolecto ocho comunas, recolecto una ocho veces.
    #
    # Al cargarlas, todas traen los mismos `MLC-`, asi que la primera se lleva las filas y
    # las otras siete quedan en CERO. Eso es exactamente lo que se vio en fase 3, y por que
    # cambiaba de comuna entre corridas: gana la que se carga primero.
    por_sha: dict[str, list[str]] = {}
    for b in blobs:
        meta = b.with_name(b.name.replace(".json.gz", ".meta.json"))
        if not meta.is_file():
            continue
        sha = json.loads(meta.read_text(encoding="utf-8")).get("sha_contenido")
        if sha:
            por_sha.setdefault(sha, []).append(b.name)
    colisiones = [
        ns
        for ns in por_sha.values()
        if len({"_".join(n.split("_")[:2]) for n in ns}) > 1  # busquedas DISTINTAS
    ]
    if colisiones:
        typer.echo(
            f"\n  ✗ {len(colisiones)} documentos identicos servidos a busquedas DISTINTAS."
            "\n    El portal ignoro el filtro: no se recolectaron N comunas, se recolecto"
            "\n    una N veces. Al cargar, la primera se lleva las filas y el resto queda en"
            "\n    cero — no porque falten datos, sino porque son los mismos.\n"
        )
        for ns in colisiones[:8]:
            typer.echo(f"      {' = '.join(sorted(ns))}")
        raise typer.Exit(1)


@app.command()
def autopsia(
    contiene: str = typer.Argument(..., help="parte del nombre del blob, ej. 'venta_concepcion'"),
    max_blobs: int = typer.Option(5, help="cuantos blobs abrir"),
) -> None:
    """Abre blobs crudos y cuenta que sobrevive a cada paso del parseo.

    `cli crudo` contesta si el blob existe. Esto contesta la otra mitad: **existe, se leyo, y
    aun asi no llego ninguna fila — ¿donde se cayo?** Las ocho comunas de fase 3 estan en
    disco con cinco paginas cada una, el rebuild las parseo, y cuatro no dejaron una sola
    unidad. Entre "el portal no lo tiene" y "nuestro parser no lo entiende" hay una diferencia
    que ninguna cantidad de recoleccion arregla si es la segunda.

    No toca la base: solo lee la zona cruda y parsea. Correrlo es gratis y no cambia nada.
    """
    from flujocero.sources.base import blobs_crudos, leer_crudo
    from flujocero.sources.portal_busqueda import parse_busqueda

    blobs = [b for b in blobs_crudos("portal_busqueda") if contiene in b.name][:max_blobs]
    if not blobs:
        typer.echo(f"  Ningun blob de portal_busqueda con {contiene!r} en el nombre.")
        typer.echo("  `cli crudo` lista lo que si hay.")
        raise typer.Exit(1)

    # Se llama `parse_busqueda` directo y no el colector: parsear es una funcion pura sobre
    # bytes que ya estan en disco, y construir el colector pediria un user-agent para una
    # operacion que no toca la red.
    def parsear(doc):
        return parse_busqueda(
            doc.contenido.decode("utf-8", errors="ignore"),
            doc.url,
            "arriendo" if "/arriendo/" in doc.url else "venta",
            doc.fetched_at,
            str(doc.ruta),
            doc.robots_snapshot_sha,
        )

    typer.echo(f"\n  {len(blobs)} blobs\n")
    typer.echo(
        f"  {'blob':<34} {'KB':>6} {'tarj':>5} {'UF':>4} {'CLP':>4} "
        f"{'mzona':>6} {'tipo':>5} {'m2':>4}"
    )
    totales = dict.fromkeys(("tarjetas", "uf", "clp", "mzona", "tipo", "m2"), 0)
    for b in blobs:
        doc = leer_crudo(b)
        ts = parsear(doc)
        fila = {
            "tarjetas": len(ts),
            "uf": sum(1 for t in ts if t.moneda == "UF"),
            "clp": sum(1 for t in ts if t.moneda == "CLP"),
            "mzona": sum(1 for t in ts if t.microzona_id),
            "tipo": sum(1 for t in ts if t.tipologia),
            "m2": sum(1 for t in ts if t.m2_utiles),
        }
        for k, v in fila.items():
            totales[k] += v
        typer.echo(
            f"  {b.name[:34]:<34} {len(doc.contenido) / 1024:>6.0f} "
            + " ".join(
                f"{fila[k]:>{w}}"
                for k, w in (
                    ("tarjetas", 5),
                    ("uf", 4),
                    ("clp", 4),
                    ("mzona", 6),
                    ("tipo", 5),
                    ("m2", 4),
                )
            )
        )

    t = totales["tarjetas"]
    typer.echo(f"\n  {t} tarjetas en total")
    if not t:
        typer.echo(
            "\n  ✗ CERO tarjetas. El blob existe pero el parser no encuentra avisos adentro."
            "\n    Recolectar de nuevo NO lo arregla: hay que mirar el HTML guardado."
        )
        raise typer.Exit(1)
    for clave, texto in (
        ("mzona", "sin microzona -> no se pueden cruzar con arriendo (§2.4)"),
        ("tipo", "sin tipologia  -> no entran a ninguna celda"),
        ("m2", "sin m2         -> no entran a ninguna banda"),
    ):
        faltan = t - totales[clave]
        if faltan:
            typer.echo(f"  ⚠ {faltan} de {t} ({faltan / t:.0%}) {texto}")
    typer.echo(
        "\n  Una tarjeta necesita microzona Y tipologia Y m2 para rankear. "
        "El limite lo pone la columna mas flaca."
    )


if __name__ == "__main__":
    app()
