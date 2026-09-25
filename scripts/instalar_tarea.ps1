# Registra (o re-registra) la tarea programada "FlujoCero semanal" en Windows.
#
# Existe porque la corrida del domingo NUNCA quedo instalada de forma reproducible:
# semanal.ps1 decia "pensada para el Programador de tareas" pero el repo no traia el
# comando que la registra — y ningun domingo corrio nada (descubierto 25-sep-2026).
#
# Que registra:
#   - domingo 20:00, cada semana
#   - StartWhenAvailable: si el PC estaba apagado/dormido a las 20:00, corre apenas
#     vuelva a estar disponible — el modo de falla mas probable de un notebook
#   - WakeToRun: intenta despertar el equipo si esta suspendido
#   - corre solo con el usuario logueado (no pide contraseña); el transcript queda
#     igual en Escritorio\FlujoCero\semanal-AAAA-MM-DD.log
#
# Uso (PowerShell normal, no necesita admin):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\instalar_tarea.ps1
# Verificar despues:
#   Get-ScheduledTaskInfo -TaskName "FlujoCero semanal"

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\semanal.ps1"
if (-not (Test-Path $script)) { throw "no encuentro $script — corre esto desde el repo" }

$nombre = "FlujoCero semanal"
$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repo
$gatillo = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 20:00
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

if (Get-ScheduledTask -TaskName $nombre -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $nombre -Confirm:$false
    Write-Output "tarea anterior '$nombre' reemplazada"
}
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $gatillo `
    -Settings $ajustes -Description "Flujo Cero: recoleccion + informe semanal + correo" | Out-Null

Write-Output "tarea '$nombre' registrada: domingos 20:00 (o al encender el PC si estaba apagado)"
Write-Output ""
Write-Output "estado actual:"
Get-ScheduledTaskInfo -TaskName $nombre | Format-List LastRunTime, LastTaskResult, NextRunTime
Write-Output "para probarla AHORA sin esperar al domingo:"
Write-Output "  Start-ScheduledTask -TaskName '$nombre'"
