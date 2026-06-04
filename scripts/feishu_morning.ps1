param(
    [string]$Date = "",
    [int]$CollectLimit = 30,
    [int]$PushLimit = 20
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "run_feishu.ps1") `
    -Window morning `
    -Date $Date `
    -CollectLimit $CollectLimit `
    -PushLimit $PushLimit
