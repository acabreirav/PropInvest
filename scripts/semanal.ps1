# Corrida semanal de Flujo Cero — pensada para el Programador de tareas de Windows.
#
# Qué hace, en orden:
#   1. recolecta venta y arriendo del portal (mantiene la frescura §7.3 bajo 21 días)
#   2. recolección dirigida de arriendo donde más unidades esperan comparables
#   3. re-agrega las medianas de arriendo por microzona
#   4. censa la oferta nueva wp-json (Socovesa + Pilares) — detecta bajas de "desde"
#   5. escribe el informe en el Escritorio: ranking top 15 + cambios de la semana
#      (bajas de precio, avisos desaparecidos = vendidos, avisos nuevos)
#
# El informe queda en  Escritorio\FlujoCero\informe-AAAA-MM-DD.txt (+ .pdf via Edge)
# y el log completo en Escritorio\FlujoCero\semanal-AAAA-MM-DD.log
# Si existe secrets/smtp.json (ver secrets/smtp.ejemplo.json), ademas lo envia por
# correo — 100% local, con contraseña de aplicacion de Google, nada sale del PC.
param([string]$Destino = "$env:USERPROFILE\Desktop\FlujoCero")

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$fecha = Get-Date -Format "yyyy-MM-dd"
$corte = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$log = Join-Path $Destino "semanal-$fecha.log"
$informe = Join-Path $Destino "informe-$fecha.txt"

Start-Transcript -Path $log -Force
try {
    Write-Output "== 1/5 recolectar-portal (venta + arriendo, alcance de zonas.yml) =="
    uv run python -m flujocero.cli recolectar-portal --paginas 4

    Write-Output "== 2/5 recoleccion dirigida de arriendo =="
    uv run python -m flujocero.cli recolectar-portal --dirigida 6

    Write-Output "== 3/5 agregar-arriendo =="
    uv run python -m flujocero.cli agregar-arriendo

    Write-Output "== 4/5 censo wp-json de oferta nueva =="
    uv run python -m flujocero.cli recolectar-wpjson --dominio socovesa.cl
    uv run python -m flujocero.cli recolectar-wpjson --dominio pilares.cl

    Write-Output "== 5/5 informe =="
    $ranking = (uv run python -m flujocero.cli oportunidades --top 15 2>&1) -join "`n"
    $cambios = (uv run python -m flujocero.cli delta --corte $corte 2>&1) -join "`n"

    $cuerpo = @()
    $cuerpo += "FLUJO CERO - informe semanal $fecha"
    $cuerpo += "======================================"
    $cuerpo += ""
    $cuerpo += "## Ranking de oportunidades (precio real por unidad, filtros del contrato)"
    $cuerpo += $ranking
    $cuerpo += ""
    $cuerpo += "## Cambios desde el $corte : bajas de precio (senal de compra),"
    $cuerpo += "## desaparecidos (probablemente vendidos) y avisos nuevos"
    $cuerpo += $cambios
    $cuerpo | Out-File -FilePath $informe -Encoding utf8

    # PDF via Edge headless (viene con Windows; si no esta, se adjunta el .txt)
    function Esc([string]$t) { $t.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;') }
    $htmlPath = Join-Path $Destino "informe-$fecha.html"
    $pdfPath  = Join-Path $Destino "informe-$fecha.pdf"
    $html = @"
<!doctype html><html><head><meta charset="utf-8"><title>Flujo Cero $fecha</title>
<style>
  body { font-family: Segoe UI, sans-serif; margin: 28px; color: #222; }
  h1 { font-size: 20px; border-bottom: 3px solid #9C5527; padding-bottom: 8px; }
  h2 { font-size: 14px; margin-top: 28px; color: #9C5527; }
  pre { font-family: Consolas, monospace; font-size: 10px; white-space: pre-wrap; }
</style></head><body>
<h1>Flujo Cero &mdash; informe semanal $fecha</h1>
<h2>Ranking de oportunidades (precio real por unidad)</h2>
<pre>$(Esc $ranking)</pre>
<h2>Cambios desde el $corte: bajas de precio, desaparecidos, nuevos</h2>
<pre>$(Esc $cambios)</pre>
</body></html>
"@
    $html | Out-File -FilePath $htmlPath -Encoding utf8
    $edge = @("$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
              "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe") |
            Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($edge) {
        & $edge --headless=new --disable-gpu "--print-to-pdf=$pdfPath" `
            "file:///$($htmlPath -replace '\\','/')" 2>$null | Out-Null
        Start-Sleep -Seconds 3
    }
    $adjunto = if (Test-Path $pdfPath) { $pdfPath } else { $informe }

    Write-Output "== correo (opcional: requiere secrets/smtp.json) =="
    uv run python scripts/enviar_informe.py --adjunto "$adjunto" --fecha $fecha

    Write-Output "Informe listo: $informe"
} finally {
    Stop-Transcript
}
