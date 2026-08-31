"""Un arriendo amoblado no es comparable con uno pelado — T-047.

## El caso que lo destapó

`antofagasta/la-chimba · 1D1B · 35-50 m²` daba **UF 16,15/mes con n=11**, más que un 2D2B de
La Serena y que uno de San Miguel. Con eso, `MLC-4427322266` encabezó el ranking del
31-ago-2026 con **yield 11,48%** —contra 7,63% del segundo— y flujo mensual positivo.

Se abrieron los 11 avisos con `cli comparables`. **Siete declaran "amoblado", "semi
amoblado" o "equipado" en su propio título.** Uno además dice `gc incl`.

## Lo que el hallazgo NO es

No es que la mediana estuviera inflada. Sacando los siete, la mediana pasa de $660.000 a
$645.000: **2%**. Los amoblados de Antofagasta no cobran mucho más que el resto.

## Lo que sí es, y es peor

**La celda solo llega a los 8 comparables del §7.3 contando productos que no son el mismo
producto.** Sin ellos quedan 4, y con 4 no se rankea nada. La regla dura del §7.3 —*"sin
comparables de arriendo suficientes (n < 8)"*— estaba satisfecha en el papel y vacía en el
fondo: el umbral existe para que la mediana no sea ruido, y once avisos de tres productos
distintos son ruido con mejor presentación que tres avisos de uno.

Y no es una rareza de Antofagasta. Un arriendo amoblado es **otro negocio**: lo toma un
trabajador de faena o un turista, dura meses en vez de años, y el arrendador repone muebles.
Este inversionista compra para arrendar pelado a 30 años. Las ciudades donde ese otro negocio
es grande —Antofagasta por la minería, La Serena por la playa— son exactamente las que fase 3
acaba de meter arriba del ranking.

## Por qué acá sí se filtra por palabra y en la cesión de promesa no

Es la distinción importante. En la promesa, la palabra era un **proxy**: 8 de 9 avisos que
decían "promesa" publicaban el precio del departamento, así que la palabra no identificaba el
problema. Acá la palabra **es el hecho**: un aviso que dice "amoblado" está declarando qué
producto vende. No se está infiriendo nada sobre él; se le está creyendo.

## La asimetría, que hay que decir en voz alta

Que un aviso **no** diga "amoblado" no prueba que esté pelado. Esta corrección saca los
amoblados declarados y deja adentro los no declarados, así que **corrige en una sola
dirección**: después de aplicarla la mediana sigue pudiendo estar sesgada hacia arriba, solo
que menos. No se compensa con un ajuste inventado — eso sería imputar (§3.2).

`equipado` queda **fuera** de la lista dura a propósito: en Chile "cocina equipada" es
estándar en un arriendo pelado. Se marca para que un humano lo mire, no se excluye solo.

Módulo puro: recibe texto, devuelve un veredicto. Sin I/O, sin reloj.
"""

from __future__ import annotations

import re

# Declaraciones inequívocas de que el producto no es un arriendo pelado a largo plazo.
# `amoblad` cubre amoblado/amoblada/amoblados; `semi amoblado` cae dentro de la misma raíz.
NO_COMPARABLE = re.compile(
    r"amoblad|amueblad|corta[\s-]estad[ií]a|por[\s-]d[ií]a|airbnb|temporada|"
    r"turistic|tur[ií]stic|diario",
    re.I,
)

# Señales que NO bastan para excluir pero merecen una mirada humana. `equipado` casi siempre
# es "cocina equipada" en un arriendo pelado; `gc incl` mete los gastos comunes dentro del
# arriendo, y el modelo los resta aparte — contarlos dos veces subestima el flujo.
DUDOSO = re.compile(r"equipad|gc[\s-]incl|gastos[\s-]comunes[\s-]inclu", re.I)


def no_comparable(texto: str | None) -> bool:
    """El aviso declara que vende otro producto: amoblado o estadía corta.

    Se le cree al aviso. No se infiere nada sobre los que no lo dicen — ver la asimetría
    en el docstring del módulo.
    """
    return bool(texto) and bool(NO_COMPARABLE.search(texto or ""))


def dudoso(texto: str | None) -> bool:
    """Merece una mirada, no una exclusión automática."""
    return bool(texto) and bool(DUDOSO.search(texto or "")) and not no_comparable(texto)


def marca(texto: str | None) -> str:
    """Dos caracteres para poner al lado del aviso en `cli comparables`."""
    if no_comparable(texto):
        return "✗ "
    return "? " if dudoso(texto) else "  "


__all__ = ["DUDOSO", "NO_COMPARABLE", "dudoso", "marca", "no_comparable"]


# --------------------------------------------------- el filtro que el portal no aplico


def busquedas_que_devuelven_lo_mismo(
    ids_por_busqueda: dict[str, frozenset[str]], umbral: float = 0.5
) -> list[tuple[str, str, int, int]]:
    """Pares de busquedas cuyos resultados se solapan demasiado para ser cosas distintas.

    **Contar resultados no basta.** Esa fue la leccion cara de fase 3: `probar-comunas` dijo
    *"8/8, 48 tarjetas cada una"* y las cinco comunas del Gran Concepcion habian devuelto
    **exactamente los mismos 48 avisos**. El portal ignoro el filtro de comuna y sirvio la
    misma pagina cinco veces. El conteo no podia notarlo, porque el numero era el correcto.

    Al cargar, todas traen los mismos `MLC-`: la primera se lleva las filas y las otras
    cuatro quedan en CERO — no por falta de datos, sino porque son los mismos datos. Y cual
    gana depende del orden de carga, asi que la comuna "que existe" cambia entre corridas.

    Un departamento esta en una sola comuna. Dos comunas distintas no pueden compartir un
    aviso, asi que **cualquier** solape es sospechoso; el umbral por defecto exige la mitad
    para no disparar por un aviso mal geolocalizado, que si pasa.

    Devuelve `(busqueda_a, busqueda_b, comunes, minimo_de_los_dos)`, ordenado.
    """
    salida: list[tuple[str, str, int, int]] = []
    claves = sorted(ids_por_busqueda)
    for i, a in enumerate(claves):
        for b in claves[i + 1 :]:
            ia, ib = ids_por_busqueda[a], ids_por_busqueda[b]
            if not ia or not ib:
                continue
            comunes = len(ia & ib)
            menor = min(len(ia), len(ib))
            if comunes >= menor * umbral:
                salida.append((a, b, comunes, menor))
    return salida
