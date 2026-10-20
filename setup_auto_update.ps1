# setup_auto_update.ps1 — ONE-TIME setup, run once by the owner.
# Registers a daily 09:25 ET task that syncs this repo with Muse's code
# on GitHub before the bot's 09:35 run, then syncs once immediately.
# After this, the owner never has to install an update by hand again.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File N:\trading-bot\auto_update.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 09:25
Register-ScheduledTask -TaskName "TradingBotAutoUpdate" -Action $action -Trigger $trigger -Force
Write-Host "Auto-update task registered for 09:25 daily. Syncing once now..."
& "N:\trading-bot\auto_update.ps1"
Write-Host "Done. This PC now pulls Muse's updates on its own."
