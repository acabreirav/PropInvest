"""El rango UF/m² del §7.1, aplicado a la tabla y no solo a una muestra — T-042.

## Por qué existe

El §7.1 declara tres rangos de plausibilidad, no dos:

    precio_uf entre 500 y 60.000 · m² entre 15 y 400 · **UF/m² entre 20 y 200**

Los dos primeros ya se aplicaban al parsear (`portal_busqueda.plausible`). El tercero
—que es un **cociente**, no un campo— no lo aplicaba nadie. Y es el único que agarra la fila
en la que precio y superficie son cada uno plausibles pero **no se refieren a la misma cosa**.

## El caso que lo destapó

`MLC-1939505225`, primera del ranking del 31-ago-2026 con **yield 17,58%** y `pie 0%` para
flujo cero, muy por encima de la segunda (7,90%). Su título:

    vendo-promesa-con-descuento-de-6-millones

No es la venta de un departamento. Es la **cesión de una promesa de compraventa**: alguien
compró en verde, pagó el pie, y vende su posición en el contrato. Los UF 850 son lo que pide
por la cesión — el comprador además hereda el saldo con la inmobiliaria. UF 850 sobre un
2D2B de 60 m² da **14,2 UF/m²** cuando su microzona mediana está en 59.

Precio plausible (>500). Superficie plausible (60). Cociente imposible.

Es el error del §13.3 en ropa nueva: *"tomar rankings de rentabilidad al pie de la letra"*.
Un ranking por yield ordena por precio bajo, así que **toda fila cuyo precio signifique otra
cosa flota sola hasta el primer lugar**. No es un outlier entre muchos: es el número que el
usuario iba a mirar primero.

## Por qué el detector de outliers del §7.3 no lo agarró, y por qué no bastaba

Dos razones independientes:

1. `checks.marcar_outliers` lee las filas a diccionarios, muta `sospechoso` en el
   diccionario y **nadie lo escribe de vuelta a la base**. El gate anuncia "161 unidades
   marcadas" en cada corrida y la columna sigue en `false` para las 161. (Se arregla aparte;
   queda en el backlog como T-043 porque cambia las medianas de arriendo y eso se mide.)
2. Aunque se persistiera, no serviría acá. Con `[p1, p99]` y n chico el percentil cae casi
   sobre el extremo, así que **el mínimo y el máximo de cada microzona quedan marcados
   siempre**, sean anómalos o no. Eso está bien para lo que el §7.3 pide —sacarlos del
   cálculo de una mediana— y sería pésimo para el ranking: descartaría automáticamente la
   unidad más barata de cada barrio, que es justo la candidata a mejor oportunidad.

Un rango absoluto no tiene ese problema: no depende de cuántas filas haya al lado.

## Por qué no se filtra por palabra en el título

De 9 avisos de "cesión de promesa" en la base, **8 publican el precio del departamento**
(69 a 172 UF/m², de mercado) y solo uno publica el de la cesión. Un filtro por la palabra
`promesa` botaría 8 unidades legítimas para agarrar 1, y sería una heurística de texto
disfrazada de regla. El cociente distingue lo que la palabra no distingue.

## Qué hace y qué NO hace

**Marca y excluye del ranking. No borra, no corrige, no imputa** (§3.2). La fila sigue en
`fact_unidad_venta` con su procedencia intacta, y el conteo aparece en el desglose de
descartes con su nombre propio, para que se vea cuántas son.

Tampoco se aplica al parsear. Ahí `plausible()` descarta la fila entera antes de escribirla,
y una fila descartada no se puede mirar después: el aviso de la promesa dejaría de existir y
nunca sabríamos cuántos hay. Se conserva y se excluye, que es lo que el §7.3 pide del dato
sospechoso.

Módulo puro: sin I/O, sin reloj.
"""

from __future__ import annotations

from decimal import Decimal

# §7.1, textual. No son supuestos de modelo —no van a `params.yml`— sino los límites de lo
# que puede ser un departamento: fuera de acá el número significa otra cosa.
UF_M2_MIN = Decimal(20)
UF_M2_MAX = Decimal(200)
PRECIO_UF_MIN = Decimal(500)
PRECIO_UF_MAX = Decimal(60_000)
M2_MIN = Decimal(15)
M2_MAX = Decimal(400)


def implausible(precio_uf: Decimal | None, m2_utiles: Decimal | None) -> str | None:
    """La razón por la que esta fila no puede ser un departamento. `None` si sí puede.

    Devuelve texto y no un booleano a propósito: cuando una unidad queda fuera del ranking,
    lo primero que uno pregunta es por qué, y la respuesta tiene que viajar con el descarte.

    Con `precio_uf` o `m2_utiles` en `None` devuelve `None`: la ausencia de dato no es
    implausibilidad, y ya la agarran los descartes `sin_m2` / cobertura del §7.3.
    """
    if precio_uf is None or m2_utiles is None:
        return None
    if not (PRECIO_UF_MIN <= precio_uf <= PRECIO_UF_MAX):
        return f"precio UF {precio_uf:,.0f} fuera de [{PRECIO_UF_MIN:,.0f}, {PRECIO_UF_MAX:,.0f}]"
    if not (M2_MIN <= m2_utiles <= M2_MAX):
        return f"{m2_utiles:,.0f} m² fuera de [{M2_MIN:,.0f}, {M2_MAX:,.0f}]"
    if m2_utiles <= 0:
        return "superficie no positiva"
    razon = precio_uf / m2_utiles
    if razon < UF_M2_MIN:
        return (
            f"{razon:.1f} UF/m² bajo el mínimo del §7.1 ({UF_M2_MIN}): el precio publicado no "
            f"es el del departamento — revisar si el aviso vende una promesa o una cesión"
        )
    if razon > UF_M2_MAX:
        return f"{razon:.1f} UF/m² sobre el máximo del §7.1 ({UF_M2_MAX})"
    return None


__all__ = [
    "M2_MAX",
    "M2_MIN",
    "PRECIO_UF_MAX",
    "PRECIO_UF_MIN",
    "UF_M2_MAX",
    "UF_M2_MIN",
    "implausible",
]
