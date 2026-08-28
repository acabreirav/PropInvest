# Flujo Cero — instalacion y primera corrida. Windows / PowerShell.
#
# Como correrlo la PRIMERA vez: guarda este archivo en Descargas y ejecuta
#
#   powershell -ExecutionPolicy Bypass -File "$HOME\Downloads\setup.ps1"
#
# Despues de la primera vez, desde la carpeta del proyecto:  .\scripts\setup.ps1
#
# (El repositorio es privado, asi que NO sirve bajarlo con `iwr | iex` desde
#  raw.githubusercontent: esa URL responde 404 sin autenticacion.)
#
# Que hace, en orden:
#   1. verifica git y uv, e instala lo que falte
#   2. clona el repositorio (o lo actualiza si ya existe)
#   3. instala las dependencias de Python
#   4. crea .env si no existe, y avisa que faltan credenciales
#   5. corre los tests y los gates
#
# NO contiene ninguna credencial. El .env se llena aparte, a proposito: este archivo
# esta versionado en GitHub y los secretos nunca entran a un archivo versionado.

$ErrorActionPreference = "Stop"

$Repo   = "https://github.com/acabreirav/PropInvest.git"
$Rama   = "claude/flujo-cero-subsidio-0j4hc6"
$Carpeta = Join-Path $HOME "PropInvest"

function Titulo($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t)     { Write-Host "  OK  $t" -ForegroundColor Green }
function Aviso($t)  { Write-Host "  !!  $t" -ForegroundColor Yellow }
function Existe($c) { $null -ne (Get-Command $c -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------- 1 · herramientas

Titulo "1/5  Herramientas"

if (Existe git) {
  Ok "git ya esta instalado"
} else {
  Aviso "git no esta. Instalando con winget..."
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path","User")
  if (-not (Existe git)) {
    throw "git quedo instalado pero PowerShell no lo ve. Cierra esta ventana, abre una nueva y vuelve a correr el script."
  }
  Ok "git instalado"
}

if (Existe uv) {
  Ok "uv ya esta instalado"
} else {
  Aviso "uv no esta. Instalando..."
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$HOME\.local\bin;$env:Path"
  if (-not (Existe uv)) {
    throw "uv quedo instalado pero PowerShell no lo ve. Cierra esta ventana, abre una nueva y vuelve a correr el script."
  }
  Ok "uv instalado"
}

# ---------------------------------------------------------------- 2 · repositorio

Titulo "2/5  Repositorio"

if (Test-Path (Join-Path $Carpeta ".git")) {
  Set-Location $Carpeta
  Ok "ya existe en $Carpeta — actualizando"
  git fetch origin $Rama
  git checkout $Rama
  git pull origin $Rama
} else {
  Write-Host "  Clonando en $Carpeta"
  Write-Host "  Si es privado, se va a abrir el navegador para que autorices a GitHub." -ForegroundColor DarkGray
  git clone --branch $Rama $Repo $Carpeta
  Set-Location $Carpeta
}
Ok "en la rama $(git rev-parse --abbrev-ref HEAD), commit $(git rev-parse --short HEAD)"

# ---------------------------------------------------------------- 3 · dependencias

Titulo "3/5  Dependencias de Python"
uv sync
Ok "instaladas"

# ---------------------------------------------------------------- 4 · credenciales

Titulo "4/5  Credenciales"

$EnvFile = Join-Path $Carpeta ".env"
if (Test-Path $EnvFile) {
  Ok ".env ya existe (no se toca)"
} else {
  Copy-Item (Join-Path $Carpeta ".env.example") $EnvFile
  Aviso ".env creado desde la plantilla, pero VACIO de credenciales."
  Write-Host "      Pega el bloque que te di en el chat para llenarlo, y vuelve a correr este script." -ForegroundColor Yellow
}

$faltan = @()
foreach ($linea in Get-Content $EnvFile) {
  if ($linea -match '^(MELI_CLIENT_ID|MELI_CLIENT_SECRET|MELI_REFRESH_TOKEN|CMF_APIKEY)=\s*$') {
    $faltan += $Matches[1]
  }
}
if ($faltan.Count -gt 0) {
  Aviso "faltan credenciales en .env: $($faltan -join ', ')"
} else {
  Ok "las cuatro credenciales estan puestas"
}

# ---------------------------------------------------------------- 5 · verificacion

Titulo "5/5  Verificacion"

Write-Host "  Tests..." -ForegroundColor DarkGray
uv run pytest -q
Ok "tests en verde"

Write-Host "  Gates..." -ForegroundColor DarkGray
uv run python -m flujocero.cli gates
Ok "gates en verde"

Write-Host "  Demo del motor financiero:" -ForegroundColor DarkGray
uv run python -m flujocero.cli demo

# ---------------------------------------------------------------- listo

Titulo "Listo"
Write-Host "Carpeta: $Carpeta`n"
if ($faltan.Count -gt 0) {
  Write-Host "SIGUIENTE: llena el .env con las credenciales y vuelve a correr este script." -ForegroundColor Yellow
} else {
  Write-Host "SIGUIENTE: trae el valor de la UF de los ultimos dos anos con" -ForegroundColor Green
  Write-Host ""
  Write-Host "    cd $Carpeta" -ForegroundColor White
  Write-Host "    uv run python -m flujocero.cli ingest --desde 2024-01 --hasta 2026-08" -ForegroundColor White
  Write-Host ""
  Write-Host "Copia toda la salida de ese comando y pegamela en el chat." -ForegroundColor Green
}
