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


# --------------------------------------------------------------------- verdad del reporte

# Programas externos: PowerShell NO aborta cuando devuelven un codigo distinto de cero.
EXTERNOS = ("git ", "uv ", "pytest", "winget ")


def _lineas_ejecutables(texto: str) -> list[tuple[int, str]]:
    return [
        (i, linea.strip())
        for i, linea in enumerate(texto.splitlines(), 1)
        if linea.strip() and not linea.strip().startswith("#")
    ]


def test_todo_comando_externo_del_script_verifica_su_codigo_de_salida() -> None:
    """EL SEGUNDO FALLO REAL, reportado por el usuario.

    `$ErrorActionPreference = "Stop"` solo gobierna los cmdlets de PowerShell. Un programa
    externo que falla no detiene el script: `git fetch` reventaba, `uv sync` reventaba,
    `pytest` ni se encontraba, y el script igual imprimia "OK tests en verde".

    Un reporte que miente es peor que un error: hace creer que hay un verde donde no lo hay.
    Todo comando externo tiene que pasar por `Correr`, que revisa `$LASTEXITCODE`.
    """
    texto = (SCRIPTS / "setup.ps1").read_text(encoding="utf-8")
    assert "function Correr" in texto, "falta el envoltorio que revisa $LASTEXITCODE"
    assert "$LASTEXITCODE" in texto

    sueltos = []
    for i, linea in _lineas_ejecutables(texto):
        if "Correr " in linea or linea.startswith(("function", "Write-Host", "throw")):
            continue
        for prog in EXTERNOS:
            if linea.startswith(prog):
                # Dos excepciones, ambas con razon:
                # - `git rev-parse` y `git remote` solo LEEN: su fallo no produce un verde falso.
                # - `winget install` devuelve codigo distinto de cero tambien cuando el
                #   programa ya estaba instalado, asi que su codigo de salida no es
                #   confiable. La verificacion real es el `if (-not (Existe git)) { throw }`
                #   de la linea siguiente, que es mas fuerte que mirar el codigo.
                if linea.startswith(("git rev-parse", "git remote", "winget install")):
                    continue
                sueltos.append(f"linea {i}: {linea[:70]}")
    assert not sueltos, "comandos externos sin verificar su codigo de salida:\n" + "\n".join(
        sueltos
    )


def test_winget_se_verifica_por_presencia_y_no_por_codigo_de_salida() -> None:
    """La excepcion anterior no es un agujero: hay que comprobar que la verificacion existe."""
    texto = (SCRIPTS / "setup.ps1").read_text(encoding="utf-8")
    i_winget = texto.index("winget install")
    resto = texto[i_winget : i_winget + 400]
    assert "Existe git" in resto and "throw" in resto, (
        "winget queda sin verificar: falta el chequeo de presencia despues de instalar"
    )


def test_el_script_verifica_que_la_carpeta_sea_este_proyecto() -> None:
    """La causa raiz del fallo: el usuario ya tenia una carpeta con ese nombre, con un
    repositorio git distinto adentro. El script la adopto y siguio como si nada."""
    texto = (SCRIPTS / "setup.ps1").read_text(encoding="utf-8")
    assert "git remote get-url origin" in texto
    assert "pyproject.toml" in texto, "falta comprobar que el clon quedo completo"


def test_el_script_no_verifica_nada_si_faltan_credenciales() -> None:
    """Correr los tests sin .env produce fallos que no dicen nada del sistema."""
    texto = (SCRIPTS / "setup.ps1").read_text(encoding="utf-8")
    i_faltan = texto.index("sin credenciales no tiene sentido verificar")
    i_tests = texto.index('Correr "pytest"')
    assert i_faltan < i_tests, "la salida temprana debe ir ANTES de correr los tests"
