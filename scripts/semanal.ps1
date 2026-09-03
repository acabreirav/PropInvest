# Corrida semanal de Flujo Cero — pensada para el Programador de tareas de Windows.
#
# Qué hace, en orden:
#   1. recolecta venta y arriendo del portal (mantiene la frescura §7.3 bajo 21 días)
#   2. recolección dirigida de arriendo donde más unidades esperan comparables
#   3. re-agrega las medianas de arriendo por microzona
#   4. censa la oferta nueva wp-json (Socovesa + Pilares) — detecta bajas de "desde"
#   5. genera el informe con `informe-semanal`: ranking top de usadas + cambios vs el
#      informe anterior + bajas del "desde" en oferta nueva + delta del mercado usado
#
# El informe queda en  Escritorio\FlujoCero\informe-AAAA-MM-DD.html (+ .pdf via Edge)
# y el log completo en Escritorio\FlujoCero\semanal-AAAA-MM-DD.log
# Si existe secrets/smtp.json (ver secrets/smtp.ejemplo.json), ademas lo envia por
# correo — 100% local, con contraseña de aplicacion de Google, nada sale del PC.
param([string]$Destino = "$env:USERPROFILE\Desktop\FlujoCero")

$ErrorActionPreference = "Continue"
# La consola de Windows usa cp1252 y cualquier caracter fuera de ese mapa (⚠, ², …)
# revienta a Python con UnicodeEncodeError cuando la salida va redirigida — el primer
# PDF real llego con un traceback al medio por esto. UTF-8 en todo Python, siempre.
$env:PYTHONUTF8 = "1"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$fecha = Get-Date -Format "yyyy-MM-dd"
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$log = Join-Path $Destino "semanal-$fecha.log"

Start-Transcript -Path $log -Force
try {
    Write-Output "== 1/5 recolectar-portal (venta + arriendo, las tres fases del alcance) =="
    uv run python -m flujocero.cli recolectar-portal --paginas 4
    uv run python -m flujocero.cli recolectar-portal --fase 2 --paginas 4
    uv run python -m flujocero.cli recolectar-portal --fase 3 --paginas 4

    Write-Output "== 2/5 recoleccion dirigida de arriendo =="
    uv run python -m flujocero.cli recolectar-portal --dirigida 6

    Write-Output "== 3/5 agregar-arriendo =="
    uv run python -m flujocero.cli agregar-arriendo

    Write-Output "== 4/5 censo wp-json de oferta nueva =="
    foreach ($dominio in @("socovesa.cl", "pilares.cl", "fundamenta.cl", "iarmas.cl",
                           "rvc.cl", "ingevecinmobiliaria.cl")) {
        uv run python -m flujocero.cli recolectar-wpjson --dominio $dominio
    }

    Write-Output "== 5/5 informe (documento directo desde la base, no consola pegada) =="
    uv run python -m flujocero.cli informe-semanal --carpeta $Destino --top 15

    # PDF via Edge headless (viene con Windows; si no esta, se adjunta el HTML)
    $htmlPath = Join-Path $Destino "informe-$fecha.html"
    $pdfPath  = Join-Path $Destino "informe-$fecha.pdf"
    $edge = @("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
              "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge -and (Test-Path $htmlPath)) {
        # 2>&1 fusiona el stderr de Edge al stream normal: Chromium headless imprime un
        # aviso interno (crbug 40528867) que PowerShell pintaria como NativeCommandError
        # dentro del transcript, y no es un error — el PDF se escribe igual.
        & $edge --headless=new --disable-gpu "--print-to-pdf=$pdfPath" `
            "file:///$($htmlPath -replace '\\','/')" 2>&1 | Out-Null
        Start-Sleep -Seconds 3
    }
    $adjunto = if (Test-Path $pdfPath) { $pdfPath } else { $htmlPath }

    Write-Output "== correo (opcional: requiere secrets/smtp.json) =="
    uv run python scripts/enviar_informe.py --adjunto "$adjunto" --fecha $fecha

    Write-Output "Informe listo: $adjunto"
} finally {
    Stop-Transcript
}
