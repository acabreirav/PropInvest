"""Guardias sobre los scripts de instalacion.

Nacieron de un fallo real: `setup.ps1` traia un guion largo dentro de una cadena y
Windows PowerShell 5.1 —que lee los .ps1 en Windows-1252 y no en UTF-8— decodifico ese
caracter como tres bytes basura, uno de los cuales es una comilla. La cadena se cerro
antes de tiempo y el script murio con "Falta la cadena en el terminador" apuntando a una
linea que no tenia nada malo, 70 lineas mas abajo.

Estos tests no prueban logica: impiden que vuelva a pasar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_los_scripts_existen() -> None:
    assert (SCRIPTS / "setup.ps1").is_file()
    assert (SCRIPTS / "setup.sh").is_file()


def test_el_script_de_powershell_es_ascii_puro() -> None:
    """EL FALLO QUE ORIGINO ESTE ARCHIVO.

    PowerShell 5.1 lee los .ps1 en Windows-1252. Un caracter fuera de ASCII se convierte
    en bytes que pueden incluir una comilla y romper el parseo del script entero.
    """
    texto = (SCRIPTS / "setup.ps1").read_text(encoding="utf-8")
    malos = [
        (i, linea, [c for c in linea if ord(c) > 127])
        for i, linea in enumerate(texto.splitlines(), 1)
        if any(ord(c) > 127 for c in linea)
    ]
    assert not malos, "\n".join(
        f"linea {i}: {[hex(ord(c)) for c in cs]} en {linea.strip()[:70]!r}"
        for i, linea, cs in malos
    )


def test_el_script_de_powershell_no_lleva_bom() -> None:
    """Con ASCII puro el BOM sobra, y un BOM mal puesto rompe otros interpretes."""
    assert not (SCRIPTS / "setup.ps1").read_bytes().startswith(b"\xef\xbb\xbf")


def _sin_comentarios_ni_cadenas(texto: str) -> str:
    """Quita comentarios de linea y contenido de cadenas, para contar llaves de verdad."""
    fuera = []
    for linea in texto.splitlines():
        sin_str = re.sub(r'"(?:[^"`]|`.)*"', '""', linea)
        sin_str = re.sub(r"'[^']*'", "''", sin_str)
        fuera.append(sin_str.split("#", 1)[0])
    return "\n".join(fuera)


def test_las_llaves_del_script_de_powershell_estan_balanceadas() -> None:
    limpio = _sin_comentarios_ni_cadenas((SCRIPTS / "setup.ps1").read_text(encoding="utf-8"))
    assert limpio.count("{") == limpio.count("}"), (
        f"{limpio.count('{')} llaves de apertura contra {limpio.count('}')} de cierre"
    )
    assert limpio.count("(") == limpio.count(")")


def test_cada_linea_del_script_de_powershell_cierra_sus_comillas() -> None:
    """Una comilla impar en una linea es exactamente el sintoma del fallo original."""
    impares = []
    for i, linea in enumerate((SCRIPTS / "setup.ps1").read_text(encoding="utf-8").splitlines(), 1):
        if linea.lstrip().startswith("#"):
            continue
        # Se ignoran las comillas escapadas con backtick, que es como PowerShell escapa.
        sin_escapes = re.sub(r"`.", "", linea)
        if sin_escapes.count('"') % 2:
            impares.append(f"linea {i}: {linea.strip()[:70]}")
    assert not impares, "\n".join(impares)


@pytest.mark.parametrize("nombre", ["setup.ps1", "setup.sh"])
def test_los_scripts_no_traen_credenciales(nombre: str) -> None:
    """Estan versionados en GitHub. Un secreto aca es un secreto publicado."""
    texto = (SCRIPTS / nombre).read_text(encoding="utf-8")
    sospechas = [
        r"APP_USR-[\w-]+",  # access token de MercadoLibre
        r"TG-[0-9a-f]{24}",  # refresh token de MercadoLibre
        r"\b[0-9a-f]{40}\b",  # apikey de la CMF
        r"MELI_CLIENT_SECRET=\S",
        r"CMF_APIKEY=\S",
    ]
    for patron in sospechas:
        assert not re.search(patron, texto), f"{nombre} parece traer un secreto: {patron}"


@pytest.mark.parametrize("nombre", ["setup.ps1", "setup.sh"])
def test_los_scripts_apuntan_a_la_rama_correcta(nombre: str) -> None:
    texto = (SCRIPTS / nombre).read_text(encoding="utf-8")
    assert "acabreirav/PropInvest" in texto
    assert "claude/flujo-cero-subsidio-0j4hc6" in texto
