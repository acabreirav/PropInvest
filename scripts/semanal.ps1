# Corrida semanal de Flujo Cero - pensada para el Programador de tareas de Windows.
#
# Que hace, en orden:
#   1. recolecta venta y arriendo del portal (mantiene la frescura bajo 21 dias)
#   2. recoleccion dirigida de arriendo donde mas unidades esperan comparables
#   3. re-agrega las medianas de arriendo por microzona
#   4. censa la oferta nueva wp-json - detecta bajas de "desde"
#   5. genera el informe con `informe-semanal` y lo envia por correo si hay smtp.json
#
# El informe queda en  <Escritorio>\FlujoCero\informe-AAAA-MM-DD.html (+ .pdf via Edge)
# y el log completo en <Escritorio>\FlujoCero\semanal-AAAA-MM-DD.log
#
# ASCII PURO y salida por PIPELINE, aprendidos a golpes:
#   - powershell.exe 5.1 lee los .ps1 sin BOM como cp1252: un guion largo UTF-8 acaba
#     en un byte que es comilla de cierre y ROMPE el script (25-sep-2026).
#   - Start-Transcript NO captura el stdout de programas externos: tres semanas de
#     logs "limpios" escondieron dos corridas con el informe reventando a mitad de
#     camino (13-sep y 25-sep-2026). Cada comando pasa por ForEach-Object para que su
#     salida entre al pipeline y quede en el transcript, y su codigo de salida se
#     anota; al final se listan los pasos que fallaron.
param([string]$Destino = (Join-Path ([Environment]::GetFolderPath("Desktop")) "FlujoCero"))

$ErrorActionPreference = "Continue"
# La consola de Windows usa cp1252 y cualquier caracter fuera de ese mapa revienta a
# Python con UnicodeEncodeError cuando la salida va redirigida. UTF-8 siempre.
$env:PYTHONUTF8 = "1"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$fecha = Get-Date -Format "yyyy-MM-dd"
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$log = Join-Path $Destino "semanal-$fecha.log"

$script:fallidos = @()
function Paso([string]$Nombre, [scriptblock]$Cuerpo) {
    Write-Output "== $Nombre =="
    & $Cuerpo 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) {
        $script:fallidos += $Nombre
        Write-Output "!! paso '$Nombre' termino con codigo $LASTEXITCODE"
    }
}

Start-Transcript -Path $log -Force
try {
    Paso "1/5 recolectar fase 1" { uv run python -m flujocero.cli recolectar-portal --paginas 4 }
    Paso "1/5 recolectar fase 2" { uv run python -m flujocero.cli recolectar-portal --fase 2 --paginas 4 }
    Paso "1/5 recolectar fase 3" { uv run python -m flujocero.cli recolectar-portal --fase 3 --paginas 4 }

    Paso "2/5 recoleccion dirigida de arriendo" { uv run python -m flujocero.cli recolectar-portal --dirigida 6 }

    Paso "3/5 agregar-arriendo" { uv run python -m flujocero.cli agregar-arriendo }

    foreach ($dominio in @("socovesa.cl", "pilares.cl", "fundamenta.cl", "iarmas.cl",
                           "rvc.cl", "ingevecinmobiliaria.cl")) {
        Paso "4/5 censo wp-json $dominio" { uv run python -m flujocero.cli recolectar-wpjson --dominio $dominio }
    }

    Paso "5/5 informe" { uv run python -m flujocero.cli informe-semanal --carpeta $Destino --top 15 }

    # PDF via Edge headless (viene con Windows; si no esta, se adjunta el HTML)
    $htmlPath = Join-Path $Destino "informe-$fecha.html"
    $pdfPath  = Join-Path $Destino "informe-$fecha.pdf"
    $edge = @("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
              "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge -and (Test-Path $htmlPath)) {
        # 2>&1 fusiona el stderr de Edge: Chromium headless imprime un aviso interno
        # (crbug 40528867) que no es un error - el PDF se escribe igual.
        & $edge --headless=new --disable-gpu "--print-to-pdf=$pdfPath" `
            "file:///$($htmlPath -replace '\\','/')" 2>&1 | Out-Null
        Start-Sleep -Seconds 3
    }
    $adjunto = if (Test-Path $pdfPath) { $pdfPath } else { $htmlPath }

    if (-not (Test-Path $adjunto)) {
        Write-Output "!! ERROR: el informe NO se genero ($adjunto no existe)."
        Write-Output "!! Revisa el paso 5/5 mas arriba - el correo no se envia."
    } else {
        Paso "correo (opcional: requiere secrets/smtp.json)" {
            uv run python scripts/enviar_informe.py --adjunto "$adjunto" --fecha $fecha
        }
        Write-Output "Informe listo: $adjunto"
    }

    if ($script:fallidos.Count -gt 0) {
        Write-Output ""
        Write-Output "!! PASOS CON ERROR ($($script:fallidos.Count)): $($script:fallidos -join ' ; ')"
        Write-Output "!! El detalle de cada uno esta mas arriba en este mismo log."
    } else {
        Write-Output "todos los pasos terminaron OK"
    }
} finally {
    Stop-Transcript
}
