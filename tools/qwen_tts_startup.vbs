' Silently launches the Qwen3-TTS bridge at Windows logon, with no console window flash.
' Installed into the current user's Startup folder by tools/install_qwen_tts_task.ps1 -
' no administrator rights required, unlike Task Scheduler on this machine.
Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\s3ish\Documents\Workspace\KoalaBattle\tools\start_qwen_tts_windows.ps1""", 0, False
