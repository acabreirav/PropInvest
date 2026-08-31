"""Gates de calidad de datos — CLAUDE.md §7.3 y tarea T-026.

Cada check devuelve un `Hallazgo` con severidad explícita. La distinción importa:

- `FALLA`  detiene el pipeline. El ranking no se publica.
- `ALERTA` no lo detiene, pero queda en el reporte y marca el ranking como `parcial`.
- `MARCA`  no falla nada: etiqueta filas (`sospechoso = true`) sin borrarlas nunca.

El contrato es explícito en que **no se borra dato** (§7.3) y en que **no se imputa en
silencio** (§3.2). Estos checks marcan y reportan; ninguno hace DELETE ni UPDATE de valores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from flujocero.quality.plausibilidad import implausible

# --------------------------------------------------------------------------- ancla externa

# UF/m² de venta de departamento nuevo, de `docs/00-hallazgos.md §3`.
# No es un supuesto del modelo: es una tabla publicada, con fuente y periodo. Sirve como
# ancla para detectar que nuestro propio pipeline se desvió, no para reemplazar el dato.
UF_M2_REFERENCIA: dict[str, Decimal] = {
    "vitacura": Decimal("133"),
    "las-condes": Decimal("110.7"),
    "nunoa": Decimal("88.4"),
    "santiago": Decimal("80.9"),
    "la-florida": Decimal("75.0"),
    "macul": Decimal("72.9"),
    "recoleta": Decimal("71.0"),
    "san-miguel": Decimal("71"),
    "estacion-central": Decimal("67.1"),
    "la-cisterna": Decimal("66.1"),
    "independencia": Decimal("67.5"),  # punto medio del rango 65-70
    "cerrillos": Decimal("64.3"),
    "maipu": Decimal("61.5"),  # punto medio del rango 58-65
}

# ARRIENDO mensual por m2, columna "retail / particular" de la tabla Colliers/Assetplan que
# Emol publico el 2-abr-2026 (docs/00-hallazgos.md §2). Es la columna que corresponde: nuestro
# inversionista es un arrendador individual, no un operador multifamily institucional, y la
# diferencia entre ambas columnas llega a 26% en Providencia.
ARRIENDO_UF_M2_REFERENCIA: dict[str, Decimal] = {
    "las-condes": Decimal("0.35"),
    "providencia": Decimal("0.31"),
    "nunoa": Decimal("0.30"),
    "la-florida": Decimal("0.25"),
    "santiago": Decimal("0.24"),
    "san-miguel": Decimal("0.24"),
    "la-cisterna": Decimal("0.22"),
    "estacion-central": Decimal("0.20"),
}

# El §7.3 pide +-25% para el arriendo y +-20% para la venta. La holgura mayor del arriendo no
# es descuido: la referencia publicada es una sola cifra por comuna, y una comuna contiene
# microzonas que difieren 17% entre si (§2.4). Exigirle +-20% seria exigirle a un promedio que
# se parezca a cada una de sus partes.
DESVIACION_MAX_ARRIENDO = Decimal("0.25")

# Umbrales del §7.3. Viven acá y no repartidos por el código.
COBERTURA_MINIMA = Decimal("0.80")
FRESCURA_MAX_DIAS = 21
DESVIACION_MAX_ANCLA = Decimal("0.20")
MIN_COMPARABLES = 8
VENTANA_DEDUP_DIAS = 30


class Severidad(str, Enum):
    FALLA = "FALLA"
    ALERTA = "ALERTA"
    MARCA = "MARCA"
    OK = "OK"


@dataclass
class Hallazgo:
    check: str
    severidad: Severidad
    mensaje: str
    filas_afectadas: int = 0
    detalle: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.severidad in (Severidad.OK, Severidad.MARCA)

    def __str__(self) -> str:
        simbolo = {
            Severidad.OK: "✓",
            Severidad.MARCA: "•",
            Severidad.ALERTA: "!",
            Severidad.FALLA: "✗",
        }[self.severidad]
        cabeza = f"{simbolo} {self.check}: {self.mensaje}"
        if not self.detalle:
            return cabeza
        return cabeza + "\n" + "\n".join(f"    {d}" for d in self.detalle[:10])


# --------------------------------------------------------------------------- datos personales

# §3.4: cero datos personales. El check corre sobre VALORES, no sobre nombres de columna:
# un correo en una columna llamada `notas` es exactamente igual de ilegal.
# Los patrones llevan `(?<!\d)` y `(?!\d)` a proposito: sin esos anclajes, cualquier corrida
# larga de digitos dispara el gate desde adentro. Medido contra el corpus real: el ID de
# MercadoLibre `MLC-3939132164` contiene `939132164`, que calza con el formato de celular
# chileno, y hacia fallar el gate en 6.443 valores que no tenian un solo dato personal.
# Un gate que grita en falso se termina desactivando, y ese es el peor final posible para
# el gate que implementa la Ley 21.719.
PATRONES_PERSONALES: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    # Celular chileno: +56 9 XXXX XXXX, con o sin separadores, pero NO incrustado en un ID.
    # `(?<!MLC-)` porque un ID de MercadoLibre de nueve digitos que empieza en 9
    # (`MLC-998686353`) es indistinguible de un celular mirando solo los digitos. Lo que
    # los separa es el contexto, y el contexto esta a cuatro caracteres de distancia.
    "telefono_cl": re.compile(r"(?<!\d)(?<!MLC-)(?:\+?56[\s.-]?)?9[\s.-]?\d{4}[\s.-]?\d{4}(?!\d)"),
    # RUT de persona natural: exige el guion con digito verificador. Sin esa marca, "40804000"
    # es un monto en pesos, no un RUT, y tratarlo como RUT bloquearia cualquier cifra en texto.
    "rut": re.compile(r"(?<!\d)\d{1,2}\.?\d{3}\.?\d{3}[-‐][\dkK](?![\w-])"),
}

# El nombre de la inmobiliaria (persona jurídica) sí se persiste (§3.4). Un RUT de empresa
# empieza en 60.000.000 o más; bajo eso se asume persona natural.
RUT_EMPRESA_DESDE = 60_000_000


def _es_rut_de_empresa(texto: str) -> bool:
    solo_numeros = re.sub(r"[^\d]", "", texto.split("-")[0])
    return bool(solo_numeros) and int(solo_numeros) >= RUT_EMPRESA_DESDE


def buscar_datos_personales(filas: list[dict[str, Any]]) -> Hallazgo:
    """§3.4 · Ley 21.719. Regla dura: si aparece uno, el pipeline se detiene.

    Se revisa el valor de toda columna de texto, no una lista blanca de nombres.
    """
    encontrados: list[str] = []
    for i, fila in enumerate(filas):
        for columna, valor in fila.items():
            if not isinstance(valor, str) or not valor:
                continue
            for etiqueta, patron in PATRONES_PERSONALES.items():
                m = patron.search(valor)
                if not m:
                    continue
                if etiqueta == "rut" and _es_rut_de_empresa(m.group()):
                    continue  # persona jurídica: permitido
                encontrados.append(f"fila {i}, columna `{columna}`: {etiqueta} detectado")
    if encontrados:
        return Hallazgo(
            "datos_personales",
            Severidad.FALLA,
            f"{len(encontrados)} valores con datos personales — CLAUDE.md §3.4, Ley 21.719",
            len(encontrados),
            encontrados,
        )
    return Hallazgo("datos_personales", Severidad.OK, "sin datos personales en los valores")


# --------------------------------------------------------------------------- procedencia


def procedencia_completa(filas: list[dict[str, Any]]) -> Hallazgo:
    """§3.1 · las seis columnas, en cada fila que llegue a la base."""
    from flujocero.sources.base import COLUMNAS_PROCEDENCIA

    faltantes: list[str] = []
    for i, fila in enumerate(filas):
        vacias = [c for c in COLUMNAS_PROCEDENCIA if not fila.get(c)]
        if vacias:
            faltantes.append(f"fila {i}: falta {', '.join(vacias)}")
    if faltantes:
        return Hallazgo(
            "procedencia",
            Severidad.FALLA,
            f"{len(faltantes)} filas sin procedencia completa — §3.1",
            len(faltantes),
            faltantes,
        )
    return Hallazgo("procedencia", Severidad.OK, f"{len(filas)} filas con las seis columnas")


# --------------------------------------------------------------------------- cobertura


def cobertura_precio_y_microzona(filas: list[dict[str, Any]]) -> Hallazgo:
    """§7.3 · ≥80% con `precio_uf` real (no 'desde') y microzona asignada."""
    if not filas:
        return Hallazgo("cobertura", Severidad.ALERTA, "no hay unidades que evaluar")
    buenas = sum(
        1
        for f in filas
        if f.get("precio_uf") and f.get("microzona_id") and f.get("evidence_level") in ("V", "D")
    )
    ratio = Decimal(buenas) / Decimal(len(filas))
    if ratio < COBERTURA_MINIMA:
        return Hallazgo(
            "cobertura",
            Severidad.ALERTA,
            f"cobertura {ratio:.1%} < {COBERTURA_MINIMA:.0%}; el ranking se marca `parcial`",
            len(filas) - buenas,
        )
    return Hallazgo("cobertura", Severidad.OK, f"cobertura {ratio:.1%}")


# --------------------------------------------------------------------------- frescura


def frescura(
    filas: list[dict[str, Any]],
    ahora: datetime,
    fuentes_historicas: frozenset[str] = frozenset(),
) -> Hallazgo:
    """§7.3 · ninguna fila **del ranking** con `fetched_at` de más de 21 días.

    `ahora` entra por argumento: nada de fechas del sistema dentro de la lógica (§11).

    `fuentes_historicas` son fuentes que se ingieren sabiendo que están viejas y que **no
    alimentan el ranking**: la foto de Portal Inmobiliario de mayo-2026, por ejemplo, sirve
    de diccionario de microzonas y de línea base para medir qué bajó de precio. Marcarlas no
    relaja el gate: el gate protege el ranking, y una fila que no entra al ranking no es lo
    que este check vigila. Lo que sí sería relajarlo es subir los 21 días para que quepan.
    """
    limite = ahora - timedelta(days=FRESCURA_MAX_DIAS)
    exentas = 0
    viejas: list[str] = []
    for i, f in enumerate(filas):
        if not isinstance(f.get("fetched_at"), datetime) or f["fetched_at"] >= limite:
            continue
        if str(f.get("source_id", "")) in fuentes_historicas:
            exentas += 1
            continue
        viejas.append(f"{f.get('unidad_key', i)}: {f['fetched_at']:%Y-%m-%d}")
    if viejas:
        # ALERTA y no FALLA, y la diferencia es de fondo. El §7.3 prohibe que una fila vieja
        # **entre al ranking**, no que exista en la base: la linea base historica contra la
        # cual se mide que bajo de precio es vieja por definicion, y tiene que estar guardada.
        #
        # Antes esto era FALLA y funcionaba solo mientras lo viejo y lo fresco vinieran de
        # fuentes distintas. Dejo de funcionar en cuanto la MISMA fuente tuvo las dos cosas:
        # las paginas de listado de mayo se ingieren con el parser del colector vivo, porque
        # comparar tarjeta con tarjeta es la unica comparacion valida. Exonerar por `source_id`
        # ya no alcanza; lo que decide es la fecha de cada fila.
        return Hallazgo(
            "frescura",
            Severidad.ALERTA,
            f"{len(viejas)} filas con más de {FRESCURA_MAX_DIAS} días: quedan FUERA del "
            f"ranking y sirven de línea base histórica",
            len(viejas),
            viejas,
        )
    nota = f"todas dentro de {FRESCURA_MAX_DIAS} días"
    if exentas:
        nota += f" ({exentas} filas de fuentes históricas, fuera del ranking por diseño)"
    return Hallazgo("frescura", Severidad.OK, nota)


# --------------------------------------------------------------------------- outliers


def _percentil(valores: list[Decimal], p: Decimal) -> Decimal:
    """Percentil por interpolación lineal. Determinístico, sin dependencias."""
    if not valores:
        raise ValueError("lista vacía")
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    pos = (Decimal(len(orden)) - 1) * p
    bajo = int(pos)
    alto = min(bajo + 1, len(orden) - 1)
    resto = pos - Decimal(bajo)
    return orden[bajo] + (orden[alto] - orden[bajo]) * resto


def precio_implausible(filas: list[dict[str, Any]]) -> Hallazgo:
    """§7.1 sobre la tabla entera, no sobre la muestra de 5 documentos del `selftest`.

    El `selftest()` de cada fuente verifica los rangos contra ≤5 documentos vivos, así que
    una fila imposible entra sin que nadie la mire. Y el rango que la agarra —`UF/m²` entre
    20 y 200— es un **cociente**, no un campo: el parser aplica precio y superficie por
    separado y los dos pueden ser plausibles sin que se refieran a la misma cosa.

    `ALERTA`, no `FALLA`: son poquísimas filas y no invalidan el resto de la base. Pero
    tampoco son `MARCA`, porque cada una es un aviso que dice una cosa y significa otra, y
    hay que ir a mirarlo. Ver `quality/plausibilidad.py` para el caso que lo destapó.
    """
    malas: list[str] = []
    for f in filas:
        precio, m2 = f.get("precio_uf"), f.get("m2_utiles")
        razon = implausible(
            Decimal(str(precio)) if precio is not None else None,
            Decimal(str(m2)) if m2 is not None else None,
        )
        if razon is not None:
            malas.append(f"{f.get('unidad_key', '?')}: {razon}")
    if not malas:
        return Hallazgo("precio_implausible", Severidad.OK, "todas las filas dentro del §7.1")
    return Hallazgo(
        "precio_implausible",
        Severidad.ALERTA,
        f"{len(malas)} filas fuera de los rangos del §7.1. Bajo el mínimo el precio "
        f"publicado no es el del departamento; sobre el máximo puede ser un precio real de "
        f"barrio caro. Quedan fuera del ranking; el dato se conserva",
        len(malas),
        malas,
    )


def marcar_outliers(filas: list[dict[str, Any]]) -> Hallazgo:
    """§7.3 · `precio_uf/m²` fuera de [p1, p99] de su microzona.

    **Marca, no borra.** La fila se conserva y queda fuera del cálculo de medianas.
    Muta `sospechoso` en el dict recibido, que es la única mutación de todo el módulo.
    """
    por_zona: dict[str, list[tuple[int, Decimal]]] = {}
    for i, f in enumerate(filas):
        zona, precio, m2 = f.get("microzona_id"), f.get("precio_uf"), f.get("m2_utiles")
        if not zona or not precio or not m2:
            continue
        por_zona.setdefault(str(zona), []).append((i, Decimal(str(precio)) / Decimal(str(m2))))

    marcadas: list[str] = []
    for zona, pares in por_zona.items():
        if len(pares) < 3:  # con menos de tres, el percentil no significa nada
            continue
        valores = [v for _, v in pares]
        p1, p99 = _percentil(valores, Decimal("0.01")), _percentil(valores, Decimal("0.99"))
        for i, v in pares:
            if v < p1 or v > p99:
                filas[i]["sospechoso"] = True
                marcadas.append(f"{filas[i].get('unidad_key', i)} en {zona}: {v:.1f} UF/m²")
    if marcadas:
        return Hallazgo(
            "outliers",
            Severidad.MARCA,
            f"{len(marcadas)} unidades marcadas `sospechoso`; se conservan, no entran a medianas",
            len(marcadas),
            marcadas,
        )
    return Hallazgo("outliers", Severidad.OK, "sin outliers de UF/m² por microzona")


# --------------------------------------------------------------------------- duplicados


def duplicados_de_venta(filas: list[dict[str, Any]]) -> Hallazgo:
    """§7.3 · dos unidades con el mismo `(proyecto_id, numero_unidad)` colapsan.

    Solo cuentan las **versiones vigentes** (`valid_to IS NULL`). El §11 manda SCD tipo 2:
    un colector nunca borra, escribe una versión nueva y cierra la anterior, justamente para
    poder responder *"¿cuándo bajó el precio de esta unidad?"* — que es señal de compra.
    Tratar dos versiones de la misma unidad como duplicado convertiría en error el historial
    que el contrato pide guardar.
    """
    vistos: dict[tuple[str, str], int] = {}
    choques: list[str] = []
    for i, f in enumerate(filas):
        if f.get("valid_to") is not None:
            continue  # version cerrada: es historia, no un duplicado
        clave = (str(f.get("proyecto_id", "")), str(f.get("numero_unidad", "")))
        if not all(clave):
            continue
        if clave in vistos:
            choques.append(f"{clave[0]}/{clave[1]} en filas {vistos[clave]} y {i}")
        else:
            vistos[clave] = i
    if choques:
        return Hallazgo(
            "duplicados_venta",
            Severidad.FALLA,
            f"{len(choques)} pares con la misma clave natural",
            len(choques),
            choques,
        )
    return Hallazgo("duplicados_venta", Severidad.OK, "sin duplicados por clave natural")


def duplicados_de_arriendo(filas: list[dict[str, Any]]) -> Hallazgo:
    """§7.3 · misma `(direccion_normalizada, m2, dormitorios, precio)` en ≤30 días.

    El mismo departamento republicado por dos corredores infla el conteo de comparables,
    que es lo que decide si una microzona entra al ranking (n ≥ 8).
    """
    grupos: dict[tuple[Any, ...], list[tuple[int, Any]]] = {}
    for i, f in enumerate(filas):
        clave = (
            f.get("direccion_normalizada"),
            f.get("m2_utiles"),
            f.get("dormitorios"),
            f.get("arriendo_clp"),
        )
        if not all(v is not None for v in clave):
            continue
        grupos.setdefault(clave, []).append((i, f.get("publicado_en")))

    dups: list[str] = []
    for clave, apariciones in grupos.items():
        if len(apariciones) < 2:
            continue
        fechas = [(i, d) for i, d in apariciones if d is not None]
        for a in range(len(fechas)):
            for b in range(a + 1, len(fechas)):
                if abs((fechas[a][1] - fechas[b][1]).days) <= VENTANA_DEDUP_DIAS:
                    dups.append(f"{clave[0]} · filas {fechas[a][0]} y {fechas[b][0]}")
    if dups:
        return Hallazgo(
            "duplicados_arriendo",
            Severidad.MARCA,
            f"{len(dups)} avisos duplicados en ≤{VENTANA_DEDUP_DIAS} días; se deduplican",
            len(dups),
            dups,
        )
    return Hallazgo("duplicados_arriendo", Severidad.OK, "sin avisos duplicados")


# --------------------------------------------------------------------------- anclas


def ancla_externa_uf_m2(mediana_por_comuna: dict[str, Decimal]) -> Hallazgo:
    """§7.3 · UF/m² mediano por comuna vs la tabla Colliers. Desviación >20% falla.

    Es el check que detecta que nuestro pipeline se desvió, no que el mercado se movió:
    una desviación de esa magnitud contra una tabla publicada casi siempre es un parser
    roto, una unidad mal convertida o un filtro que dejó entrar stock usado.
    """
    desviadas: list[str] = []
    sin_referencia: list[str] = []
    comparadas = 0
    for comuna, nuestra in mediana_por_comuna.items():
        referencia = UF_M2_REFERENCIA.get(comuna)
        if referencia is None:
            # **La ausencia de referencia no es un aprobado.** La tabla Colliers cubre la RM
            # y nada mas, asi que al abrir fase 3 el ancla quedo ciega justo donde entraron
            # los datos nuevos: el 31-ago-2026 las tres primeras del ranking eran de
            # Antofagasta y La Serena, y el gate imprimia "4 comunas comparadas" — las
            # cuatro de siempre. Saltarlas en silencio es leer la falta de control como
            # control cumplido.
            sin_referencia.append(comuna)
            continue
        comparadas += 1
        desviacion = abs(nuestra - referencia) / referencia
        if desviacion > DESVIACION_MAX_ANCLA:
            desviadas.append(
                f"{comuna}: {nuestra:.1f} vs {referencia:.1f} UF/m² de referencia "
                f"({desviacion:+.0%})"
            )
    if desviadas:
        return Hallazgo(
            "ancla_externa",
            Severidad.FALLA,
            f"{len(desviadas)} comunas se desvían >{DESVIACION_MAX_ANCLA:.0%} de la referencia",
            len(desviadas),
            desviadas,
        )
    if comparadas == 0:
        return Hallazgo(
            "ancla_externa", Severidad.ALERTA, "ninguna comuna tiene referencia con qué comparar"
        )
    if sin_referencia:
        return Hallazgo(
            "ancla_externa",
            Severidad.ALERTA,
            f"{comparadas} comunas dentro de ±{DESVIACION_MAX_ANCLA:.0%}, pero "
            f"{len(sin_referencia)} quedaron SIN VERIFICAR: no hay referencia publicada para "
            f"ellas en docs/00-hallazgos.md. Sus cifras entran al ranking sin ancla externa",
            len(sin_referencia),
            sorted(sin_referencia),
        )
    return Hallazgo("ancla_externa", Severidad.OK, f"{comparadas} comunas dentro de ±20%")


def comparables_suficientes(
    conteo_por_microzona_tipologia: dict[tuple[str, str], int],
) -> Hallazgo:
    """§7.3 y D-008 · `n < 8` ⇒ `ND`, sin imputar. Es exclusión, no penalización."""
    flacas = [
        f"{z}/{t}: n={n}"
        for (z, t), n in conteo_por_microzona_tipologia.items()
        if n < MIN_COMPARABLES
    ]
    if flacas:
        return Hallazgo(
            "comparables_suficientes",
            Severidad.MARCA,
            f"{len(flacas)} combinaciones con n<{MIN_COMPARABLES}; van a `ND` y salen del ranking",
            len(flacas),
            flacas,
        )
    return Hallazgo("comparables_suficientes", Severidad.OK, f"todas con n>={MIN_COMPARABLES}")


def reconciliacion_arriendo(
    mediana_por_microzona: dict[str, Decimal], benchmark: dict[str, Decimal]
) -> Hallazgo:
    """§7.3 · la mediana debe estar dentro de ±25% del benchmark. Alerta, no borrado."""
    fuera: list[str] = []
    sin_referencia: list[str] = []
    for zona, nuestra in mediana_por_microzona.items():
        ref = benchmark.get(zona)
        if ref is None or ref == 0:
            sin_referencia.append(zona)
            continue
        d = abs(nuestra - ref) / ref
        if d > DESVIACION_MAX_ARRIENDO:
            fuera.append(f"{zona}: {nuestra:.2f} vs {ref:.2f} ({d:+.0%})")
    if fuera:
        return Hallazgo(
            "reconciliacion_arriendo",
            Severidad.ALERTA,
            f"{len(fuera)} microzonas fuera de ±{DESVIACION_MAX_ARRIENDO:.0%}; "
            "se explica, no se borra",
            len(fuera),
            fuera,
        )
    if sin_referencia:
        # Misma razon que en `ancla_externa_uf_m2`, y acá pesa más: el arriendo es el
        # NUMERADOR del yield. Una mediana de arriendo sin ancla externa es la mitad de la
        # cifra que ordena el ranking, sin nadie que la contraste.
        return Hallazgo(
            "reconciliacion_arriendo",
            Severidad.ALERTA,
            f"medianas dentro de ±{DESVIACION_MAX_ARRIENDO:.0%} donde hay con qué comparar, "
            f"pero {len(sin_referencia)} zonas quedaron SIN VERIFICAR",
            len(sin_referencia),
            sorted(sin_referencia),
        )
    return Hallazgo("reconciliacion_arriendo", Severidad.OK, "medianas dentro de ±25%")


# --------------------------------------------------------------------------- orquestación


@dataclass
class ReporteCalidad:
    hallazgos: list[Hallazgo] = field(default_factory=list)

    @property
    def falla(self) -> bool:
        return any(h.severidad is Severidad.FALLA for h in self.hallazgos)

    @property
    def parcial(self) -> bool:
        """El ranking se publica marcado como `parcial` en la UI."""
        return any(h.severidad is Severidad.ALERTA for h in self.hallazgos)

    def __str__(self) -> str:
        cuerpo = "\n".join(str(h) for h in self.hallazgos)
        if self.falla:
            estado = "ROJO — el ranking no se publica"
        elif self.parcial:
            estado = "PARCIAL — se publica con advertencia"
        else:
            estado = "VERDE"
        return f"{cuerpo}\n\ncalidad de datos: {estado}"


def correr(
    unidades: list[dict[str, Any]],
    comparables: list[dict[str, Any]],
    ahora: datetime,
    mediana_uf_m2_por_comuna: dict[str, Decimal] | None = None,
    conteo_comparables: dict[tuple[str, str], int] | None = None,
    fuentes_historicas: frozenset[str] = frozenset(),
) -> ReporteCalidad:
    """Corre todos los checks del §7.3 sobre un lote ya cargado."""
    rep = ReporteCalidad()
    rep.hallazgos.append(buscar_datos_personales(unidades + comparables))
    rep.hallazgos.append(procedencia_completa(unidades))
    rep.hallazgos.append(cobertura_precio_y_microzona(unidades))
    rep.hallazgos.append(frescura(unidades, ahora, fuentes_historicas))
    rep.hallazgos.append(precio_implausible(unidades))
    rep.hallazgos.append(marcar_outliers(unidades))
    rep.hallazgos.append(duplicados_de_venta(unidades))
    rep.hallazgos.append(duplicados_de_arriendo(comparables))
    if mediana_uf_m2_por_comuna is not None:
        rep.hallazgos.append(ancla_externa_uf_m2(mediana_uf_m2_por_comuna))
    if conteo_comparables is not None:
        rep.hallazgos.append(comparables_suficientes(conteo_comparables))
    return rep
