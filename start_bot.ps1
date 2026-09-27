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

# 2026-09-27: the intraday paper_runner.py was retired after failing its
# out-of-sample test; daily_runner.py (SPY index book + paper RSI(2) forward
# test) replaces it. See RESULTS_2026-09-27_daily.md.
while ($true) {
    if (-not (Test-ScriptRunning "daily_runner.py")) {
        # Via cmd so output APPENDS — Start-Process redirection truncates the file on
        # every relaunch, which would erase the traceback of the crash that caused it.
        Start-Process -FilePath "cmd.exe" -WindowStyle Hidden -ArgumentList `
            "/c `"`"$pythonExe`" daily_runner.py >> `"$PSScriptRoot\logs\daily_runner_console.log`" 2>&1`""
    }

    if (-not (Test-ScriptRunning "web_dashboard.py")) {
        Start-Process -FilePath $pythonExe -ArgumentList "web_dashboard.py" -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\dashboard_stdout.log") `
            -RedirectStandardError  (Join-Path $PSScriptRoot "logs\dashboard_stderr.log")
    }

    Start-Sleep -Seconds 30
}
