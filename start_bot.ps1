# ============================================================
#  start_bot.ps1 — Watchdog for the trading bot.
#  Run at user logon via a registered Scheduled Task. Loops
#  forever, relaunching paper_runner.py / web_dashboard.py
#  whenever either process is found dead, so they survive
#  silent crashes without manual restarts.
# ============================================================

Set-Location -Path $PSScriptRoot

$pythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

function Test-ScriptRunning($scriptName) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*$scriptName*" }
    return $procs.Count -gt 0
}

while ($true) {
    if (-not (Test-ScriptRunning "paper_runner.py")) {
        Start-Process -FilePath $pythonExe -ArgumentList "paper_runner.py" -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\paper_runner_stdout.log") `
            -RedirectStandardError  (Join-Path $PSScriptRoot "logs\paper_runner_stderr.log")
    }

    if (-not (Test-ScriptRunning "web_dashboard.py")) {
        Start-Process -FilePath $pythonExe -ArgumentList "web_dashboard.py" -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\dashboard_stdout.log") `
            -RedirectStandardError  (Join-Path $PSScriptRoot "logs\dashboard_stderr.log")
    }

    Start-Sleep -Seconds 30
}
