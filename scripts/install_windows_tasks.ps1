param(
    [string]$TaskPrefix = "findSecurityNews Feishu",
    [string]$MorningTime = "08:00",
    [string]$EveningTime = "20:00"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$MorningScript = Join-Path $ProjectDir "scripts\feishu_morning.ps1"
$EveningScript = Join-Path $ProjectDir "scripts\feishu_evening.ps1"

function Register-FeishuTask {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string]$At
    )

    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    $Trigger = New-ScheduledTaskTrigger -Daily -At $At
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName $Name `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "findSecurityNews Feishu scheduled security news push" `
        -Force
}

Register-FeishuTask -Name "$TaskPrefix Morning" -ScriptPath $MorningScript -At $MorningTime
Register-FeishuTask -Name "$TaskPrefix Evening" -ScriptPath $EveningScript -At $EveningTime

Write-Host "Installed Windows scheduled tasks:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "$TaskPrefix*" } | Select-Object TaskName, State
