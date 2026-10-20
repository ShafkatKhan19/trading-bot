# auto_update.ps1 — Sync N:\trading-bot with Muse's latest code on GitHub.
# Runs daily at 09:25 ET via the TradingBotAutoUpdate scheduled task,
# ten minutes before the bot's 09:35 run. Runtime state (books, .env,
# logs) is gitignored and never touched by this sync.
$ErrorActionPreference = "Continue"
Set-Location "N:\trading-bot"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$log = "logs\auto_update.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
git fetch origin YOYOYO 2>&1 | Out-Null
$local = git rev-parse HEAD
$remote = git rev-parse origin/YOYOYO
if ($local -ne $remote) {
    # Safety net: keep any local-only state reachable on a backup branch.
    git branch "backup-autoupdate-$(Get-Date -Format yyyyMMddHHmmss)" 2>&1 | Out-Null
    git reset --hard origin/YOYOYO 2>&1 | Out-Null
    Add-Content $log "$stamp updated $local -> $remote"
} else {
    Add-Content $log "$stamp already up to date"
}
