"""Piezas compartidas por los colectores de Portal Inmobiliario.

Dos colectores leen el mismo portal con las mismas convenciones —números chilenos,
anonimización, slugs de microzona— y ninguno debería depender del otro:

- `portal_legado`: la foto histórica de mayo-2026 que el usuario ya tenía scrapeada.
  `legal_tier: html_prohibido`, autorizada por D-016.
- `portal_busqueda`: el colector vivo, que usa **solo** las rutas `_Desde_` que el
  `robots.txt` permite. `legal_tier: html_permitido`.

Que el segundo importara del primero sería raro y frágil: el histórico se congela y el vivo
sigue. Lo común vive acá.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from decimal import Decimal
from typing import Any

BASE_URL = "https://www.portalinmobiliario.com"

# --------------------------------------------------------------------- anonimizacion (§3.4)

# Lo que de verdad aparece, medido sobre 250 fichas al azar del corpus de mayo-2026:
#   - correos            182/250 (73%)  -- incluye el del PROPIO usuario, que scrapeo logueado
#   - enlaces wa.me      43/250  (17%)  -- el numero del corredor va dentro de la URL
#   - patrones +56       4/250   (2%)
#   - enlaces tel:       0/250
_CORREO = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WHATSAPP = re.compile(rb"(?:wa\.me|api\.whatsapp\.com)[^\"'>\s]*")
_TEL_HREF = re.compile(rb"tel:[^\"'>\s]*")
_MAS56 = re.compile(rb"\+\s?56[\s.\-]?9?[\s.\-]?\d[\d\s.\-]{5,10}\d")

PATRONES = (
    (_CORREO, b"[correo-removido]"),
    (_WHATSAPP, b"[whatsapp-removido]"),
    (_TEL_HREF, b"tel:[removido]"),
    (_MAS56, b"[fono-removido]"),
)

# Un celular chileno de nueve digitos sin marca. Se usa SOLO sobre textos cortos —URLs y
# titulos—, nunca sobre el HTML entero: ahi se comeria IDs y fechas. `(?<!MLC-)` porque un
# ID de MercadoLibre que empieza en 9 es indistinguible de un celular mirando los digitos.
FONO_SUELTO = re.compile(r"(?<!\d)(?<!MLC-)9\d{8}(?!\d)")


def anonimizar(html: bytes) -> tuple[bytes, int]:
    """Borra correos, WhatsApp y teléfonos del HTML. Devuelve `(limpio, cuantos_borro)`.

    Se corre ANTES de escribir a la zona cruda, no después: persistir el dato personal y
    limpiarlo más tarde ya sería haberlo persistido. La Ley 21.719 no distingue entre
    "guardado" y "guardado un rato".

    **Los patrones son deliberadamente estrechos, y esa es la decisión de diseño.** Una
    versión anterior usaba un regex genérico de teléfono chileno de ocho dígitos, y destrozaba
    el dato: `MLC-1859051633_20260504.html` quedaba como
    `MLC-18[fono-removido]_[fono-removido].html`. Un anonimizador que corrompe IDs y fechas
    es peor que no tener uno, porque el daño es silencioso y se descubre tarde.
    """
    limpio, total = html, 0
    for patron, reemplazo in PATRONES:
        limpio, n = patron.subn(reemplazo, limpio)
        total += n
    return limpio, total


def texto_seguro(texto: str) -> str:
    """Anonimiza un texto corto (un título de aviso, por ejemplo).

    El vendedor escribe el título y a veces mete ahí su celular. Ese título viaja al `source_url`
    y a la base, así que no basta con limpiar el HTML.
    """
    limpio = anonimizar(texto.encode("utf-8"))[0].decode("utf-8", errors="ignore")
    return FONO_SUELTO.sub("[fono-removido]", limpio)


def url_segura(url: str, portal_id: str | None) -> str:
    """Recorta la URL a su forma canónica por ID si el slug trae un dato de contacto.

    Caso real del corpus:
    `.../MLC-3872504748-arriendo-dpto-1d-1b-a-3-cuadras-metro-992401813-dueno-_JM`
    Ese número es el celular del propietario. `source_url` es una de las seis columnas de
    procedencia (§3.1), así que la URL se guarda tal cual y el teléfono viaja con ella:
    anonimizar solo el HTML no alcanzaba.

    Se pierde el título; no se pierde la trazabilidad, que es lo que el §3.1 pide. El §3.4
    no admite excepciones ni siquiera en una columna de procedencia.
    """
    sucia = any(p.search(url.encode()) for p, _ in PATRONES) or bool(FONO_SUELTO.search(url))
    if sucia and portal_id:
        return f"{BASE_URL}/{portal_id}"
    return url


# ------------------------------------------------------------------------ numeros chilenos

_NUMERO = re.compile(r"\d[\d.]*(?:,\d+)?")


def a_decimal(texto: str) -> Decimal | None:
    """Número chileno a Decimal. El punto es SIEMPRE separador de miles.

    Es la misma regla que costó un error de mil veces en el colector de la CMF: no se decide
    caso a caso mirando cuántos dígitos hay después del punto. En Chile `3.500` son tres mil
    quinientos, nunca tres coma cinco.

    **Devuelve `None` si el texto trae más de un número.** Los avisos de proyecto publican
    rangos —`"35 - 61 m²"`, `"1 a 2 dormitorios"`— y una versión anterior borraba todo lo que
    no fuera dígito y los pegaba: `"35 - 61"` salía **3561 m²**. Un departamento de 3.561 m²
    no lo detecta nadie mirando un ranking, y contamina la mediana de su microzona para
    siempre. Ante un rango, el §3.2 pide `ND`, no un número inventado.
    """
    numeros = _NUMERO.findall(texto or "")
    if len(numeros) != 1:
        return None
    try:
        return Decimal(numeros[0].replace(".", "").replace(",", "."))
    except Exception:
        return None


def a_entero(texto: str) -> int | None:
    """Un entero, con el mismo criterio que `a_decimal`: un rango es ND."""
    d = a_decimal(texto)
    return int(d) if d is not None else None


# -------------------------------------------------------------------------------- claves


def slug(texto: str) -> str:
    """`'Ñuñoa - Estadio Nacional'` -> `'nunoa-estadio-nacional'`. Estable y sin tildes."""
    sin_tilde = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", sin_tilde.lower())).strip("-")


def tipologia_de(dormitorios: int | None, banos: int | None) -> str | None:
    if dormitorios is None or banos is None:
        return None
    return "studio" if dormitorios == 0 else f"{dormitorios}D{banos}B"


# --------------------------------------------------------------------------------- carga

# Los dos colectores del portal escriben las mismas tablas con la misma semántica. El
# versionado SCD tipo 2 y la idempotencia son delicados y no deben existir dos veces: una
# de las dos copias se corrige y la otra no, y el error queda escondido en la que nadie mira.


def _procedencia(a: Any, source_id: str, parser_version: str) -> tuple[Any, ...]:
    """Las seis columnas del §3.1, siempre en el mismo orden."""
    return (source_id, a.url, a.fetched_at, parser_version, a.raw_blob_path, a.robots_snapshot_sha)


def cargar_avisos(conexion: Any, avisos: list[Any], source_id: str, parser_version: str) -> int:
    """Inserta dimensiones y hechos. Idempotente por clave natural (§3.6).

    Acepta cualquier objeto con la forma de `Aviso`/`Tarjeta`: mismo portal, mismos campos.
    """
    if not avisos:
        return 0

    for cid, nombre in {a.comuna_id: a.comuna_nombre for a in avisos if a.comuna_id}.items():
        conexion.execute(
            "INSERT INTO dim_comuna (comuna_id, nombre, region) VALUES (?, ?, ?) "
            "ON CONFLICT (comuna_id) DO NOTHING",
            (cid, nombre, "Metropolitana"),
        )
    microzonas = {
        a.microzona_id: (a.comuna_id, a.microzona_nombre) for a in avisos if a.microzona_id
    }
    for mid, (cid, nombre) in microzonas.items():
        conexion.execute(
            "INSERT INTO dim_microzona (microzona_id, comuna_id, nombre) VALUES (?, ?, ?) "
            "ON CONFLICT (microzona_id) DO NOTHING",
            (mid, cid, nombre),
        )

    n, omitidas = 0, []
    for a in avisos:
        if a.operacion == "venta" and a.precio_uf is not None:
            n += _cargar_venta(conexion, a, source_id, parser_version)
        elif a.operacion == "venta":
            # Venta publicada en pesos. `fact_unidad_venta.precio_uf` es DECIMAL en UF y el
            # §11 prohibe que esta capa convierta: la UF del dia vive en otra tabla. Se omite
            # la fila y se cuenta aparte, en vez de meter un numero en la columna equivocada.
            omitidas.append(a.portal_id)
        elif a.operacion == "arriendo":
            n += _cargar_arriendo(conexion, a, source_id, parser_version)
    if omitidas:
        logging.getLogger(__name__).info(
            "%d ventas publicadas en pesos omitidas (falta columna precio_clp): %s...",
            len(omitidas),
            omitidas[:3],
        )
    return n


def _cargar_venta(conexion: Any, a: Any, source_id: str, parser_version: str) -> int:
    """Inserta con versionado SCD tipo 2 (§11): nunca se borra, se cierra y se abre.

    El mismo aviso aparece en varias corridas y esas NO son filas duplicadas: son versiones.
    Guardarlas con `valid_from`/`valid_to` es lo que permite responder *"¿cuándo bajó el
    precio de esta unidad?"*, que el contrato declara señal de compra.

    Tres casos, y el orden importa:
      1. no existe                    -> se inserta la primera version
      2. existe con la misma fecha    -> se actualiza en el lugar (§3.6: no duplica)
      3. existe mas antigua y el precio CAMBIO -> se cierra la vieja y se abre una nueva.
         Si el precio no cambio no se abre version: una por corrida sin cambios llenaria la
         tabla de ruido y taparia los cambios reales.
    """
    vigente = conexion.execute(
        "SELECT valid_from, precio_uf, parser_version FROM fact_unidad_venta "
        "WHERE unidad_key = ? AND valid_to IS NULL",
        (a.portal_id,),
    ).fetchone()

    # **El precio depende de la superficie del portal, no solo de la unidad.** Medido sobre
    # 2.689 unidades presentes el mismo dia en la tarjeta del listado y en la ficha de
    # detalle: 48 tenian precios distintos, y una marcaba UF 13.000 en la tarjeta contra
    # UF 15.900 en la ficha — mismo aviso, mismo dia, mismo titulo, 22% de diferencia.
    #
    # Si se versionara entre superficies, cada ingesta inventaria un "cambio de precio" que
    # nunca ocurrio. Una version solo se abre comparando tarjeta con tarjeta o ficha con
    # ficha; entre superficies distintas se completan atributos y nada mas.
    # La asimetria es deliberada: la TARJETA del listado es la superficie canonica del precio,
    # porque es la que el colector vivo va a seguir viendo corrida tras corrida. Una ficha de
    # detalle aporta lo que la tarjeta no trae —antiguedad, gastos comunes— pero su precio es
    # provisional y una tarjeta lo reemplaza. Si mandara la ficha, la linea base quedaria en
    # una superficie que ya nadie vuelve a leer y el delta no cruzaria nunca.
    ES_TARJETA = "portal_busqueda"
    if vigente is not None and vigente[2] != parser_version and ES_TARJETA in parser_version:
        conexion.execute(
            "UPDATE fact_unidad_venta SET precio_uf = ?, parser_version = ?, valid_from = ?, "
            "fetched_at = ?, source_id = ?, source_url = ?, raw_blob_path = ?, "
            "robots_snapshot_sha = ?, microzona_id = coalesce(?, microzona_id) "
            "WHERE unidad_key = ? AND valid_to IS NULL",
            (
                a.precio_uf,
                parser_version,
                min(vigente[0], a.fetched_at),
                a.fetched_at,
                source_id,
                a.url,
                a.raw_blob_path,
                a.robots_snapshot_sha,
                a.microzona_id,
                a.portal_id,
            ),
        )
        return 0

    if vigente is not None and vigente[2] != parser_version:
        conexion.execute(
            "UPDATE fact_unidad_venta SET microzona_id = coalesce(microzona_id, ?), "
            "m2_utiles = coalesce(m2_utiles, ?), dormitorios = coalesce(dormitorios, ?), "
            "banos = coalesce(banos, ?), tipologia = coalesce(tipologia, ?), "
            "antiguedad_anios = coalesce(antiguedad_anios, ?) "
            "WHERE unidad_key = ? AND valid_to IS NULL",
            (
                a.microzona_id,
                float(a.m2_utiles) if a.m2_utiles is not None else None,
                a.dormitorios,
                a.banos,
                a.tipologia,
                getattr(a, "antiguedad_anios", None),
                a.portal_id,
            ),
        )
        return 0

    campos = (
        a.precio_uf,
        float(a.m2_utiles) if a.m2_utiles is not None else None,
        a.dormitorios,
        a.banos,
        a.tipologia,
        getattr(a, "es_vivienda_nueva", None),
        getattr(a, "antiguedad_anios", None),
    )

    if vigente is not None:
        desde, precio_previo, _ = vigente
        if desde == a.fetched_at:
            conexion.execute(
                "UPDATE fact_unidad_venta SET precio_uf = ?, m2_utiles = ?, dormitorios = ?, "
                "banos = ?, tipologia = ?, es_vivienda_nueva = ?, antiguedad_anios = ?, "
                "microzona_id = ?, fetched_at = ?, raw_blob_path = ? "
                "WHERE unidad_key = ? AND valid_to IS NULL",
                (*campos, a.microzona_id, a.fetched_at, a.raw_blob_path, a.portal_id),
            )
            return 0
        if desde > a.fetched_at:
            # Llego una captura MAS VIEJA que la version vigente. No debe reescribir el
            # presente, pero tampoco puede tirarse: es historia, y es justo la que hace
            # posible el delta.
            #
            # Paso de verdad: el usuario recolecto agosto primero y despues ingirio la foto de
            # mayo. Con el `return 0` de antes, toda unidad que aparecia en las dos capturas
            # perdia su version de mayo, y el informe salia con cero cambios de precio y cero
            # confirmadas. El resultado dependia del ORDEN en que se cargaron las fotos, que
            # es exactamente lo que un almacen versionado no puede permitirse.
            return _rellenar_pasado(conexion, a, desde, precio_previo, source_id, parser_version)
        if precio_previo == a.precio_uf:
            # Sigue publicada al mismo precio: no se abre version, pero SI se actualiza la
            # procedencia. Dejarla apuntando al documento viejo diria que la evidencia de
            # esta fila es un blob de mayo, cuando la evidencia es la captura de hoy.
            # `valid_from` conserva cuando se vio por primera vez.
            # `microzona_id` va en las DOS ramas de UPDATE, no solo en el INSERT. Una columna
            # agregada despues queda NULL para siempre en las filas que ya existian si el
            # camino de confirmacion no la escribe: la fila se "actualiza" cada corrida y
            # nunca se llena. Paso de verdad con las 552 filas de la primera corrida real.
            conexion.execute(
                "UPDATE fact_unidad_venta SET fetched_at = ?, microzona_id = ?, source_id = ?, "
                "source_url = ?, parser_version = ?, raw_blob_path = ?, robots_snapshot_sha = ? "
                "WHERE unidad_key = ? AND valid_to IS NULL",
                (
                    a.fetched_at,
                    a.microzona_id,
                    source_id,
                    a.url,
                    parser_version,
                    a.raw_blob_path,
                    a.robots_snapshot_sha,
                    a.portal_id,
                ),
            )
            return 0
        conexion.execute(
            "UPDATE fact_unidad_venta SET valid_to = ? WHERE unidad_key = ? AND valid_to IS NULL",
            (a.fetched_at, a.portal_id),
        )

    conexion.execute(
        """
        INSERT INTO fact_unidad_venta
          (unidad_key, numero_unidad, microzona_id, tipologia, dormitorios, banos, m2_utiles,
           es_vivienda_nueva, antiguedad_anios, precio_uf, disponible, evidence_level,
           valid_from, source_id, source_url, fetched_at, parser_version, raw_blob_path,
           robots_snapshot_sha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            a.portal_id,
            a.portal_id,
            a.microzona_id,
            campos[4],
            campos[2],
            campos[3],
            campos[1],
            campos[5],
            campos[6],
            campos[0],
            True,
            # Un proyecto publica "desde UF X": ese numero no es el precio de esta unidad.
            # Marcarlo `E` no es cosmetico: el §12 excluye del ranking todo precio estimado,
            # asi que la regla que ya existe hace el trabajo sin codigo nuevo.
            "E" if a.es_proyecto else "V",
            a.fetched_at,
            *_procedencia(a, source_id, parser_version),
        ),
    )
    return 1


def _rellenar_pasado(
    conexion: Any,
    a: Any,
    desde_vigente: Any,
    precio_vigente: Any,
    source_id: str,
    parser_version: str,
) -> int:
    """Inserta hacia atras una captura anterior a la version vigente (§11, SCD tipo 2).

    El corpus trae varias capturas del mismo dia a dias distintos —4 y 5 de mayo— y llegan en
    orden arbitrario, asi que hay que mirar **la version que empieza justo despues** de la
    fecha entrante, no solo la vigente:

    - **Mismo precio que ella** -> se retrocede su `valid_from`. Ya estaba a ese precio en la
      fecha vieja: no son dos versiones, es una que empezo antes. Insertar aqui creaba dos
      versiones cerradas superpuestas con el mismo precio, y el informe mostraba la misma
      unidad dos veces en la lista de bajadas.
    - **Precio distinto** -> version cerrada de verdad, `[fecha_vieja, inicio_de_la_siguiente)`.

    Idempotente: si ya existe una version cubriendo ese instante, no hace nada.
    """
    ya_esta = conexion.execute(
        "SELECT count(*) FROM fact_unidad_venta "
        "WHERE unidad_key = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)",
        (a.portal_id, a.fetched_at, a.fetched_at),
    ).fetchone()[0]
    if ya_esta:
        return 0

    # La version mas temprana que empieza despues de esta captura. Puede ser la vigente o una
    # cerrada que otra captura vieja abrio antes.
    siguiente = conexion.execute(
        "SELECT valid_from, precio_uf FROM fact_unidad_venta "
        "WHERE unidad_key = ? AND valid_from > ? ORDER BY valid_from LIMIT 1",
        (a.portal_id, a.fetched_at),
    ).fetchone()
    if siguiente is None:
        return 0
    inicio_siguiente, precio_siguiente = siguiente

    if precio_siguiente == a.precio_uf:
        conexion.execute(
            "UPDATE fact_unidad_venta SET valid_from = ? WHERE unidad_key = ? AND valid_from = ?",
            (a.fetched_at, a.portal_id, inicio_siguiente),
        )
        return 0

    conexion.execute(
        """
        INSERT INTO fact_unidad_venta
          (unidad_key, numero_unidad, microzona_id, tipologia, dormitorios, banos, m2_utiles,
           es_vivienda_nueva, antiguedad_anios, precio_uf, disponible, evidence_level,
           valid_from, valid_to, source_id, source_url, fetched_at, parser_version,
           raw_blob_path, robots_snapshot_sha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            a.portal_id,
            a.portal_id,
            a.microzona_id,
            a.tipologia,
            a.dormitorios,
            a.banos,
            float(a.m2_utiles) if a.m2_utiles is not None else None,
            getattr(a, "es_vivienda_nueva", None),
            getattr(a, "antiguedad_anios", None),
            a.precio_uf,
            True,
            "E" if a.es_proyecto else "V",
            a.fetched_at,
            inicio_siguiente,  # se cierra justo donde empieza la siguiente
            *_procedencia(a, source_id, parser_version),
        ),
    )
    return 1


def _cargar_arriendo(conexion: Any, a: Any, source_id: str, parser_version: str) -> int:
    """Inserta el comparable, o actualiza el que ya estaba. **Devuelve 1 solo si INSERTO.**

    Antes devolvia 1 siempre. El `ON CONFLICT DO UPDATE` hace lo correcto con los datos
    —`comp_id` es clave primaria, no se duplica nada— pero el contador reportaba cada aviso
    confirmado como una fila nueva. Se vio corriendo la misma recoleccion dos veces seguidas:
    la segunda anuncio **1.911 filas nuevas o versionadas** sobre exactamente los mismos
    3.812 avisos.

    El dato nunca estuvo mal; la METRICA que dice si una corrida sirvio de algo estaba
    inflada, y es la que uno mira para decidir si vale la pena volver a recolectar.
    """
    ya_estaba = conexion.execute(
        "SELECT 1 FROM fact_arriendo_comp WHERE comp_id = ?", (a.portal_id,)
    ).fetchone()
    conexion.execute(
        """
        INSERT INTO fact_arriendo_comp
          (comp_id, microzona_id, tipologia, dormitorios, banos, m2_utiles, arriendo_clp,
           arriendo_uf, gastos_comunes_clp, estacionamiento, bodega, activo, evidence_level,
           source_id, source_url, fetched_at, parser_version, raw_blob_path,
           robots_snapshot_sha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (comp_id) DO UPDATE SET
          arriendo_clp = excluded.arriendo_clp, arriendo_uf = excluded.arriendo_uf,
          fetched_at = excluded.fetched_at
        """,
        (
            a.portal_id,
            a.microzona_id,
            a.tipologia,
            a.dormitorios,
            a.banos,
            float(a.m2_utiles) if a.m2_utiles is not None else None,
            a.arriendo_clp,
            a.arriendo_uf,
            getattr(a, "gastos_comunes_clp", None),
            getattr(a, "estacionamientos", 0) > 0,
            getattr(a, "bodegas", 0) > 0,
            True,
            "E" if a.es_proyecto else "V",
            *_procedencia(a, source_id, parser_version),
        ),
    )
    return 0 if ya_estaba else 1
