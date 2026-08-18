# Launches the Windows/CUDA Qwen3-TTS bridge (qwen_tts_server_windows.py) without a console
# window and with output captured to a log file. Registered as a scheduled task by
# tools/install_qwen_tts_task.ps1 so it starts automatically at logon and survives crashes -
# see docs/TTS.md for the manual/one-off way to run it instead.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root '.venv-qwen-tts\Scripts\pythonw.exe'
$script = Join-Path $root 'qwen_tts_server_windows.py'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir 'qwen-tts-bridge.out.log'
$errLog = Join-Path $logDir 'qwen-tts-bridge.err.log'

if (-not (Test-Path $pythonw)) {
    throw "venv not found at $pythonw - run: python -m venv tools/.venv-qwen-tts, then install tools/requirements-qwen-tts-windows.txt"
}

# -PassThru + exiting with the child's code lets Task Scheduler see a crash as a task failure,
# which is what makes its restart-on-failure setting actually retry.
$process = Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $root `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog -WindowStyle Hidden -Wait -PassThru
exit $process.ExitCode
