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
# El informe queda en  Escritorio\FlujoCero\informe-AAAA-MM-DD.txt
# y el log completo en Escritorio\FlujoCero\semanal-AAAA-MM-DD.log
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
    $cuerpo = @()
    $cuerpo += "FLUJO CERO - informe semanal $fecha"
    $cuerpo += "======================================"
    $cuerpo += ""
    $cuerpo += "## Ranking de oportunidades (precio real por unidad, filtros del contrato)"
    $cuerpo += (uv run python -m flujocero.cli oportunidades --top 15 2>&1)
    $cuerpo += ""
    $cuerpo += "## Cambios desde el $corte : bajas de precio (senal de compra),"
    $cuerpo += "## desaparecidos (probablemente vendidos) y avisos nuevos"
    $cuerpo += (uv run python -m flujocero.cli delta --corte $corte 2>&1)
    $cuerpo | Out-File -FilePath $informe -Encoding utf8

    Write-Output "Informe listo: $informe"
} finally {
    Stop-Transcript
}
