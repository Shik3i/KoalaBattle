# Makes the Windows Qwen3-TTS bridge start automatically at logon - no manual "run this
# script" step every session. Tries a proper scheduled task first (it can restart itself if
# it crashes); if Task Scheduler refuses without admin rights, as it does on some machines
# even for a task that only ever runs as your own already-logged-on account, falls back to a
# silent launcher shortcut in your per-user Startup folder, which never needs elevation.
#
# Run once, from a normal PowerShell prompt (admin not required either way):
#   powershell -ExecutionPolicy Bypass -File tools/install_qwen_tts_task.ps1
#
# To remove: Unregister-ScheduledTask -TaskName 'KoalaBattle Qwen3-TTS Bridge' -Confirm:$false
# or delete qwen_tts_startup.vbs from shell:startup, whichever this installed.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root 'start_qwen_tts_windows.ps1'
$taskName = 'KoalaBattle Qwen3-TTS Bridge'

function Install-ViaTaskScheduler {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description 'Starts the local Qwen3-TTS voice-clone bridge for KoalaBattle (tools/qwen_tts_server_windows.py) on logon and restarts it if it crashes.' `
        | Out-Null
    Write-Host "Registered scheduled task '$taskName'. It will start at your next logon."
    Start-ScheduledTask -TaskName $taskName
}

function Install-ViaStartupFolder {
    $startupDir = [Environment]::GetFolderPath('Startup')
    $startupScript = (Get-Content -LiteralPath (Join-Path $root 'qwen_tts_startup.vbs') -Raw).Replace(
        '__KOALABATTLE_ROOT__',
        $root
    )
    Set-Content -LiteralPath (Join-Path $startupDir 'qwen_tts_startup.vbs') `
        -Value $startupScript -Encoding Unicode
    Write-Host "Task Scheduler requires admin rights on this machine; installed a Startup-folder"
    Write-Host "launcher instead: $startupDir\qwen_tts_startup.vbs"
    Write-Host "It will start silently at your next logon (no auto-restart on crash, unlike a real task)."
    Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$startupDir\qwen_tts_startup.vbs`""
}

try {
    Install-ViaTaskScheduler
} catch {
    Install-ViaStartupFolder
}
